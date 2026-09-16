"""paper.read 结构层：PDF → PaperStructure（deterministic，**不调 LLM**）。

论文 → ``PaperStructure``（meta + sections + figures/tables，References 及其后截断），
供 `paper.read` 的两种模式共用：

- ``original``（原文听读）：拿 sections 的段落文字做听觉清洗后合成（本模块只给结构）；
- ``explain``（讲解，v1 保留未交付）：拿 sections 做选段喂 LLM。

v1 全部是确定性规则（无模型、无网络、可单测）：

1. **阅读顺序**：PyMuPDF block 先按「双栏检测」排序（中缝带无 block + 左右各有 ≥3 块
   → 判定双栏），避免跨栏串行；
2. **去页眉 / 页脚 / 页码**：页边界高度带（上 8% / 下 8%）内的短块 + ``^\\d{1,4}$``
   行 + 跨页重复文本剔除；
3. **章节识别**：``SECTION_PATTERNS`` 表 + 编号正则 + 字号/加粗启发，保留原 heading，
   拿不准 → ``other``；识别不到任何标题时退化为单节 ``full``（整篇一段）；
4. **References 硬截断**：命中 references/bibliography 标题即停止（``references_dropped``）；
5. **Figure / Table caption**：只识别 + 记页码（original 不念，explain 可用）。

底层不新增依赖：PyMuPDF 走共享 `mac_edge.plugins.pdf_render`（与 `pdf.to_images` /
`display.pdf` / `pdf.reader` 同源）。读 PDF 与「纯结构组装」分离：``extract_structure``
读文件，``structure_from_pages`` 只吃 ``PageBlocks``（单测用合成 block，不需要 PDF）。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from mac_edge.plugins.pdf_render import PdfRenderError, _fitz

log = logging.getLogger("mac_edge.paper_structure")

# 页边界高度带比例（上/下）：带内的短块按页眉页脚处理。
_MARGIN_BAND = 0.08
# 页眉页脚带内「短块」阈值：超过这个长度就当作正文（避免误删首行正文）。
_MARGIN_MAX_CHARS = 60
# 双栏判定：中缝带宽度比例 + 每列最少块数。
_GUTTER_BAND = 0.06
_MIN_COLUMN_BLOCKS = 3
# 标题判定的字号放大倍数（相对本页中位字号）与最大长度。
_HEADING_SIZE_RATIO = 1.08
_MAX_HEADING_CHARS = 90
_MAX_HEADING_WORDS = 14

_SECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("abstract", re.compile(r"^(abstract|summary|摘要)\b", re.I)),
    ("introduction", re.compile(r"^(introduction|background|motivation|引言|绪论)\b", re.I)),
    (
        "related_work",
        re.compile(
            r"^(related\s+works?|prior\s+work|literature\s+review|相关工作|研究现状)\b", re.I
        ),
    ),
    (
        "method",
        re.compile(
            r"^(methods?|methodology|approach|our\s+approach|proposed\s+(method|approach|model)"
            r"|system\s+design|framework|architecture|model|方法|模型|算法设计)\b",
            re.I,
        ),
    ),
    (
        "experiment",
        re.compile(
            r"^(experiments?|experimental\s+(setup|settings|details)|evaluation|"
            r"implementation\s+details|数据集|实验)\b",
            re.I,
        ),
    ),
    (
        "results",
        re.compile(r"^(results?|results?\s+and\s+discussion|findings|结果)\b", re.I),
    ),
    ("discussion", re.compile(r"^(discussions?|讨论)\b", re.I)),
    (
        "conclusion",
        re.compile(
            r"^(conclusions?|concluding\s+remarks|conclusion\s+and\s+future\s+work|"
            r"summary\s+and\s+conclusions?|结论|总结)\b",
            re.I,
        ),
    ),
    (
        "references",
        re.compile(r"^(references?|bibliography|参考文献|引用文献)\b", re.I),
    ),
    ("acknowledg", re.compile(r"^(acknowledge?ments?|致谢)\b", re.I)),
    ("appendix", re.compile(r"^(appendi(x|ces)|附录)\b", re.I)),
)

# 编号标题：`3 Method` / `3.2 Method` / `IV. EXPERIMENT` / `四、方法`
_NUMBERED_RE = re.compile(
    r"^((?:\d+(?:\.\d+){0,3})|(?:[IVXLC]+)|(?:[一二三四五六七八九十]+))[.)、]?\s+(?P<rest>\S.*)$"
)

# Figure / Table caption（识别用，不念）：`Figure 3:` / `Fig. 3.` / `TABLE II.`
# 必须带分隔符（`: . — -`）——「Table 3 lists the results on 8 datasets」是正文，不是 caption。
_CAPTION_RE = re.compile(
    r"^(fig(?:ure)?s?\.?|tab(?:le)?s?\.?)\s*([0-9]+|[IVXLC]+)\s*[:.\u2014\u2013-]",
    re.I,
)
_CAPTION_KIND_RE = re.compile(r"^(fig(?:ure)?s?\.?|tab(?:le)?s?\.?)", re.I)

_PAGE_NUM_RE = re.compile(r"^\d{1,4}$")
_WS_RE = re.compile(r"[ \t\u3000]+")
_DEHYPHEN_RE = re.compile(r"(\w)-\s*\n\s*(\w)")


class PaperStructureError(Exception):
    """结构层明确中文失败（缺依赖 / 打不开 / 加密 / 无页 / 抽不到结构）。"""


@dataclass
class Block:
    """页面上的一个文字块（PyMuPDF block 的最小投影，便于单测构造）。"""

    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    size: float = 0.0
    bold: bool = False

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2.0


@dataclass
class PageBlocks:
    """一页的块集合（page 为 1-based 页码）。"""

    page: int
    width: float
    height: float
    blocks: list[Block] = field(default_factory=list)


@dataclass
class Section:
    """一个章节：类型 + 原 heading + 段落 + 页范围。"""

    type: str
    heading: str
    paragraphs: list[str] = field(default_factory=list)
    start_page: int = 1
    end_page: int = 1

    @property
    def chars(self) -> int:
        return sum(len(p) for p in self.paragraphs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "heading": self.heading,
            "chars": self.chars,
            "paragraphs": len(self.paragraphs),
            "page_start": self.start_page,
            "page_end": self.end_page,
        }


@dataclass
class Caption:
    """Figure / Table caption（只记位置，original 不念）。"""

    kind: str  # figure | table
    caption: str
    page: int

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "caption": self.caption, "page": self.page}


@dataclass
class PaperStructure:
    """论文结构（两种阅读模式共用的中间表示）。"""

    title: str | None
    pages: int
    sections: list[Section] = field(default_factory=list)
    captions: list[Caption] = field(default_factory=list)
    references_dropped: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def chars(self) -> int:
        return sum(s.chars for s in self.sections)

    def figures(self) -> list[Caption]:
        return [c for c in self.captions if c.kind == "figure"]

    def tables(self) -> list[Caption]:
        return [c for c in self.captions if c.kind == "table"]

    def to_meta(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "pages": self.pages,
            "sections": len(self.sections),
            "chars": self.chars,
            "figures": len(self.figures()),
            "tables": len(self.tables()),
            "references_dropped": self.references_dropped,
            "warnings": list(self.warnings),
        }


def _norm_text(raw: str) -> str:
    """块内文字规整：统一换行 → 断词修复 → 行拼接（块内换行只是排版折行）。"""
    text = str(raw or "").replace("\r\n", "\n").replace("\r", "\n")
    text = _DEHYPHEN_RE.sub(r"\1\2", text)
    lines = [_WS_RE.sub(" ", line).strip() for line in text.split("\n")]
    return " ".join(line for line in lines if line).strip()


def _classify_heading(text: str) -> tuple[str, str, bool] | None:
    """判断一行是不是章节标题 → ``(section_type, heading, strong)``，否则 None。

    ``strong``：命中已知章节名或编号标题（不受字号启发约束）；否则只有字号明显更大
    或加粗才当标题（保守，拿不准不做）。
    """
    raw = _norm_text(text)
    if not raw or len(raw) > _MAX_HEADING_CHARS:
        return None
    if "。" in raw or len(raw.split()) > _MAX_HEADING_WORDS:
        return None
    body = raw.rstrip(" .:：;；,-")
    if not body:
        return None
    numbered = _NUMBERED_RE.match(body)
    if numbered is not None and len(numbered.group("rest")) > 70:
        numbered = None
    candidate = numbered.group("rest") if numbered is not None else body
    if numbered is None:
        # 非编号行：句子（「… . …」）不当标题
        if ". " in raw:
            return None
    for stype, pattern in _SECTION_PATTERNS:
        if pattern.match(candidate):
            return stype, body, True
    if numbered is not None:
        return "other", body, True
    letters = [ch for ch in body if ch.isalpha()]
    if letters and body == body.upper() and len(body) <= 70:
        return "other", body, False
    return None


def _caption_kind(text: str) -> str | None:
    """Figure / Table caption 判定（不念，只记位置）。"""
    raw = _norm_text(text)
    head = _CAPTION_KIND_RE.match(raw)
    if head is None or not _CAPTION_RE.match(raw):
        return None
    return "figure" if head.group(1).lower().startswith("fig") else "table"


def _in_margin(block: Block, height: float) -> bool:
    h = float(height or 0.0)
    if h <= 0:
        return False
    return block.y1 <= _MARGIN_BAND * h or block.y0 >= (1.0 - _MARGIN_BAND) * h


def _strip_margins(pages: Sequence[PageBlocks]) -> list[PageBlocks]:
    """去页眉 / 页脚 / 页码：带内短块、``^\\d{1,4}$``、跨页重复文本。"""
    counts: dict[str, int] = {}
    for pg in pages:
        for block in pg.blocks:
            text = _norm_text(block.text)
            if text and _in_margin(block, pg.height):
                counts[text] = counts.get(text, 0) + 1
    out: list[PageBlocks] = []
    for pg in pages:
        kept: list[Block] = []
        for block in pg.blocks:
            text = _norm_text(block.text)
            if not text:
                continue
            if _in_margin(block, pg.height) and (
                _PAGE_NUM_RE.match(text)
                or counts.get(text, 0) >= 2
                or len(text) <= _MARGIN_MAX_CHARS
            ):
                continue
            kept.append(
                Block(
                    text=text,
                    x0=block.x0,
                    y0=block.y0,
                    x1=block.x1,
                    y1=block.y1,
                    size=block.size,
                    bold=block.bold,
                )
            )
        out.append(PageBlocks(page=pg.page, width=pg.width, height=pg.height, blocks=kept))
    return out


def _sort_blocks(blocks: Sequence[Block], *, width: float) -> list[Block]:
    """阅读顺序排序：双栏（左栏整列 → 右栏整列），否则按 (y, x) 单栏序。"""
    items = [b for b in blocks if _norm_text(b.text)]
    if not items:
        return []
    mid = float(width or 0.0) / 2.0
    two_column = False
    if mid > 0:
        left = [b for b in items if b.cx < mid]
        right = [b for b in items if b.cx >= mid]
        gutter = [b for b in items if abs(b.cx - mid) <= _GUTTER_BAND * float(width)]
        two_column = (
            len(left) >= _MIN_COLUMN_BLOCKS
            and len(right) >= _MIN_COLUMN_BLOCKS
            and len(gutter) <= max(1, int(0.2 * len(items)))
        )
    if two_column:
        left.sort(key=lambda b: (b.y0, b.x0))
        right.sort(key=lambda b: (b.y0, b.x0))
        return left + right
    return sorted(items, key=lambda b: (b.y0, b.x0))


def _median_size(blocks: Sequence[Block]) -> float:
    sizes = sorted(float(b.size) for b in blocks if b.size > 0)
    if not sizes:
        return 0.0
    return sizes[len(sizes) // 2]


def _detect_title(pages: Sequence[PageBlocks]) -> str | None:
    """首页阅读顺序第一个块 → 论文标题（字号不比本页中位大的就放弃）。"""
    if not pages:
        return None
    first = pages[0]
    blocks = _sort_blocks(first.blocks, width=first.width)
    if not blocks:
        return None
    median = _median_size(blocks)
    head = blocks[0]
    if median and head.size < median * 1.05:
        return None
    text = _norm_text(head.text)
    if len(text) < 8 or len(text) > 200:
        return None
    return text



def structure_from_pages(
    pages: Sequence[PageBlocks],
    *,
    title: str | None = None,
    total_pages: int | None = None,
    detect_title: bool = True,
    warnings: Iterable[str] | None = None,
) -> PaperStructure:
    """把各页文字块组装成 PaperStructure（纯函数，单测直接喂合成 block）。"""
    cleaned = _strip_margins(pages)
    page_count = int(total_pages) if total_pages else max((p.page for p in pages), default=0)
    resolved_title = _norm_text(title) if title else None
    if resolved_title is None and detect_title:
        resolved_title = _detect_title(cleaned)

    sections: list[Section] = []
    captions: list[Caption] = []
    references_dropped = False
    current: Section | None = None
    stop = False
    title_consumed = False

    for pg in cleaned:
        if stop:
            break
        blocks = _sort_blocks(pg.blocks, width=pg.width)
        median = _median_size(blocks)
        for block in blocks:
            text = block.text
            if not text:
                continue
            kind = _caption_kind(text)
            if kind is not None:
                captions.append(Caption(kind=kind, caption=text, page=pg.page))
                continue
            hit = _classify_heading(text)
            if (
                hit is not None
                and not hit[2]
                and not block.bold
                and median
                and block.size < median * _HEADING_SIZE_RATIO
            ):
                hit = None
            if hit is not None:
                stype, heading, _strong = hit
                if stype == "references":
                    references_dropped = True
                    stop = True
                    break
                current = Section(
                    type=stype, heading=heading, start_page=pg.page, end_page=pg.page
                )
                sections.append(current)
                continue
            if current is None:
                if resolved_title and not title_consumed and text == resolved_title:
                    # 标题已作为 script 的 prefix（「论文标题：…」）朗读，正文里不再重复
                    title_consumed = True
                    continue
                current = Section(type="front", heading="", start_page=pg.page, end_page=pg.page)
                sections.append(current)
            current.paragraphs.append(text)
            current.end_page = pg.page

    if not sections:
        flat = [
            block.text
            for pg in cleaned
            for block in _sort_blocks(pg.blocks, width=pg.width)
            if block.text and _caption_kind(block.text) is None
        ]
        if flat:
            sections = [
                Section(
                    type="full",
                    heading="",
                    paragraphs=flat,
                    start_page=1,
                    end_page=page_count or 1,
                )
            ]
            log.info("paper_structure: 未识别到章节标题 — 退化为整篇单节（%s 段）", len(flat))
    elif len(sections) == 1 and sections[0].type == "front":
        # 全篇没有标题：唯一那节其实是整篇正文，别叫它 front matter
        sections[0].type = "full"

    out_warnings = [str(w) for w in (warnings or []) if str(w).strip()]
    if not any(s.paragraphs for s in sections):
        out_warnings.append("没有可读段落（可能是扫描件或纯图表页）")
    return PaperStructure(
        title=resolved_title,
        pages=page_count,
        sections=[s for s in sections if s.paragraphs],
        captions=captions,
        references_dropped=references_dropped,
        warnings=out_warnings,
    )


def _page_blocks(page: Any, *, page_no: int) -> list[Block]:
    """一页的 PyMuPDF block → ``Block``（只取文字块，保留字号/加粗启发信息）。"""
    try:
        data = page.get_text("dict")
    except Exception as e:  # pragma: no cover - 取字失败分支
        raise PaperStructureError(f"提取第 {page_no} 页结构失败：{e}") from e
    out: list[Block] = []
    for raw in data.get("blocks") or []:
        if int(raw.get("type", 0)) != 0:
            continue
        lines: list[str] = []
        sizes: list[float] = []
        bold = False
        for line in raw.get("lines") or []:
            spans = line.get("spans") or []
            lines.append("".join(str(sp.get("text") or "") for sp in spans))
            for span in spans:
                try:
                    sizes.append(float(span.get("size") or 0.0))
                except (TypeError, ValueError):
                    pass
                font = str(span.get("font") or "")
                flags = int(span.get("flags") or 0)
                if "bold" in font.lower() or (flags & 16):
                    bold = True
        text = "\n".join(lines).strip()
        if not text:
            continue
        bbox = raw.get("bbox") or (0.0, 0.0, 0.0, 0.0)
        try:
            x0, y0, x1, y1 = (float(v) for v in list(bbox)[:4])
        except (TypeError, ValueError):
            x0 = y0 = x1 = y1 = 0.0
        out.append(
            Block(
                text=text,
                x0=x0,
                y0=y0,
                x1=x1,
                y1=y1,
                size=max(sizes) if sizes else 0.0,
                bold=bold,
            )
        )
    return out


def extract_structure(
    pdf_path: Path,
    *,
    start: int = 1,
    end: int | None = None,
) -> PaperStructure:
    """读 PDF 指定页范围 → PaperStructure（缺依赖 / 加密 / 无页 → 明确中文失败）。"""
    try:
        fitz = _fitz()
    except PdfRenderError as e:
        raise PaperStructureError(str(e)) from e
    try:
        doc = fitz.open(str(pdf_path))
    except Exception as e:
        raise PaperStructureError(f"无法读取 PDF：{e}") from e
    try:
        if getattr(doc, "needs_pass", False) or getattr(doc, "is_encrypted", False):
            raise PaperStructureError("该 PDF 已加密，无法解析论文结构")
        count = int(doc.page_count)
        if count <= 0:
            raise PaperStructureError("该 PDF 没有任何页面")
        first = max(1, int(start))
        last = count if end is None else max(1, min(int(end), count))
        pages: list[PageBlocks] = []
        for index in range(first, last + 1):
            page = doc.load_page(index - 1)
            rect = page.rect
            pages.append(
                PageBlocks(
                    page=index,
                    width=float(rect.width),
                    height=float(rect.height),
                    blocks=_page_blocks(page, page_no=index),
                )
            )
    finally:
        doc.close()

    warnings: list[str] = []
    if last < count:
        warnings.append(f"只解析了第 {first}–{last} 页（共 {count} 页）")
    return structure_from_pages(
        pages,
        total_pages=count,
        detect_title=(first == 1),
        warnings=warnings,
    )

