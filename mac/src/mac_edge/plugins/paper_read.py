"""Mac Edge capability: paper.read — 论文听读（v1：**original 原文模式**）。

把 ``type=document``（PDF 论文）Asset 的指定页范围（缺省整份）解析成 **Paper Structure**
（`mac_edge.plugins.paper_structure`，确定性规则、不调 LLM），再按阅读模式产出
**一段可连续听读的 spoken script**，交给共享合成底层 `mac_edge.plugins.tts_file`
合成音频、上传 Brain 登记为 **audio Asset**：

```text
PDF/OCR Document → Paper Structure → paper.read → Spoken Content → TTS → Audio Artifact
paper.read ├── original   # 原文听读（v1 已交付，全程不调 LLM）
           └── explain    # AI 解析讲解（v1 保留未交付：明确中文失败，见 paper_explain）
```

- ``original``（默认）：**忠实原文**，只做听觉必需的清理与重排（断词/续行/引文编号/页码/
  URL/公式语音化/图表引用自然化/标题朗读化），结构层丢掉 References 及其后、不念 caption。
  引用话术与标题脚手架**跟随正文语言**（中文论文「图二 / 下面是…部分。」，英文论文
  「Figure 2 / Next, the … section.」），音色也用同一门语言 —— 英文论文不会再被中文音色念。
  红线：不总结、不解释、不补论文外知识 —— 详见 `mac_edge.plugins.paper_clean`。
- ``explain``：v1 只保留契约（`paper_explain`），调用时**明确中文失败**（不静默降级）。

与已上线的 `pdf.reader` 并存、由 planner 分工：`pdf.reader` 管「念一下这份 PDF」这类通用短
文档；`paper.read` 管**论文/长文献**的结构化听读（本能力会做结构、跳 References、给
``sections[]`` 索引）。

对外入口：``read_from_params(params, *, asset, ...)`` —— 与 `pdf.reader` / `pdf.to_images`
对齐，``asset`` 是 Runtime SDK 的 ``CapAsset`` 会话。
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Callable

from mac_edge.plugins.paper_clean import assemble_script, build_original_pieces, resolve_script_lang
from mac_edge.plugins.paper_explain import PaperExplainError, explain_script
from mac_edge.plugins.paper_structure import (
    PaperStructure,
    PaperStructureError,
    extract_structure,
)
from mac_edge.plugins.pdf_render import (
    PdfRenderError,
    normalize_page_range,
    pdf_page_count,
    pymupdf_available,
)
from mac_edge.plugins.tts_file import (
    TtsFileError,
    TtsResult,
    synthesize_speech,
    tts_available,
    truncate_text,
)

log = logging.getLogger("mac_edge.paper_read")

MODE_ORIGINAL = "original"
MODE_EXPLAIN = "explain"
MODES = (MODE_ORIGINAL, MODE_EXPLAIN)

# 单次听读页数安全上限（与 pdf.reader 同口径；文案提示缩小页范围）。
MAX_READ_PAGES = 200
# 单次合成字数上限（默认约 40 分钟语音）；入参 max_chars=0 表示不截断。
DEFAULT_MAX_CHARS = 12000
_PREVIEW_CHARS = 80
_MIME_EXT = {"audio/mpeg": ".mp3", "audio/mp4": ".m4a"}


class PaperReadError(Exception):
    """paper.read 明确中文失败（缺参 / 非 document / 读不了 / 无文字 / 合成失败）。"""


def paper_read_available() -> bool:
    """本机能不能听读论文：PyMuPDF 可导入（解析结构）+ 有可用 TTS 引擎。"""
    return pymupdf_available() and tts_available()


def _max_chars(raw: Any) -> int:
    """入参 max_chars 归一化（0 = 不截断）；缺省取 env 或 DEFAULT_MAX_CHARS。"""
    text = str(raw if raw is not None else "").strip()
    if text:
        try:
            value = int(float(text))
        except (TypeError, ValueError) as e:
            raise PaperReadError(f"max_chars 必须是数字：{raw!r}") from e
        if value < 0:
            raise PaperReadError(f"max_chars 不能为负数：{raw!r}")
        return value
    env = (os.environ.get("MAC_EDGE_PAPER_READ_MAX_CHARS") or "").strip()
    if env:
        try:
            value = int(float(env))
            if value >= 0:
                return value
        except ValueError:
            log.warning("invalid MAC_EDGE_PAPER_READ_MAX_CHARS=%r — use default", env)
    return DEFAULT_MAX_CHARS


def _mode(raw: Any) -> str:
    """阅读模式归一化：缺省 original；只接受 original / explain。"""
    text = str(raw if raw is not None else "").strip().lower()
    if not text:
        return MODE_ORIGINAL
    if text not in MODES:
        raise PaperReadError(f"mode 只能是 original / explain，收到 {raw!r}")
    return text


def _safe_stem(raw: Any, *, fallback: str) -> str:
    text = str(raw or "").strip()
    if text:
        text = Path(text.replace("\\", "/")).name.strip()
        text = re.sub(r"\.[Pp][Dd][Ff]$", "", text)
    cleaned = re.sub(r"[^A-Za-z0-9一-鿿_-]", "-", text)
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    if not cleaned:
        cleaned = fallback
    return cleaned[:60].rstrip("-") or fallback


def _work_dir(asset_id: str) -> Path:
    root = (os.environ.get("MAC_EDGE_DATA_DIR") or "").strip()
    if root:
        base = Path(root) / "paper-reader"
    else:
        base = Path(tempfile.gettempdir()) / "mac-edge-paper-reader"
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "-", str(asset_id or "").strip()) or "paper"
    return base / cleaned


def _fmt_duration(seconds: float | None) -> str:
    if not seconds or seconds <= 0:
        return "时长未知"
    total = int(round(seconds))
    if total < 60:
        return f"约 {total} 秒"
    return f"约 {total // 60} 分 {total % 60} 秒"


def _preview(text: str) -> str:
    body = re.sub(r"\s+", " ", (text or "")).strip()
    if len(body) <= _PREVIEW_CHARS:
        return body
    return body[:_PREVIEW_CHARS] + "…"


def _default_structure(pdf_path: Path, *, start: int, end: int) -> PaperStructure:
    return extract_structure(pdf_path, start=start, end=end)


def _sections_index(
    pieces: list[dict[str, Any]],
    *,
    prefix: str,
    total_chars: int,
    duration_sec: float | None,
) -> list[dict[str, Any]]:
    """section 级索引：每节的字数、页范围、在整段音频里的估算起始秒。

    ``est_offset_sec`` 用「字符数占比 × 总时长」估算（TTS 语速均匀，足够给端上做跳节
    参考；v1 只放 metadata，端上按节跳转要 v2 改端）。
    """
    total = max(1, int(total_chars))
    budget = total
    cursor = len(str(prefix or "")) + (2 if str(prefix or "").strip() else 0)
    out: list[dict[str, Any]] = []
    for index, piece in enumerate(pieces):
        text_len = len(str(piece.get("text") or ""))
        kept = 0
        if budget > 0:
            kept = min(text_len, budget)
            budget -= kept + 2
        offset = None
        if duration_sec:
            offset = round(float(duration_sec) * min(cursor, total) / total, 1)
        out.append(
            {
                "index": index,
                "type": piece.get("type") or "other",
                "heading": piece.get("heading") or "",
                "chars": kept,
                "page_start": piece.get("page_start"),
                "page_end": piece.get("page_end"),
                "est_offset_sec": offset,
            }
        )
        cursor += text_len + 2
    return out



def read_from_params(
    params: dict[str, Any],
    *,
    asset: Any,
    structure_fn: Callable[..., PaperStructure] | None = None,
    synthesize_fn: Callable[..., TtsResult] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Capability entry：校验 → 物化 PDF → 解析结构 → 清洗 → 合成音频 → 登记 audio Asset。"""
    from mac_edge.asset.types import AssetError

    if asset is None or not (
        hasattr(asset, "require_ref")
        and hasattr(asset, "materialize_file")
        and hasattr(asset, "upload_file")
    ):
        raise PaperReadError("paper.read 需要 CapAsset（Runtime SDK）")

    raw_params = params if isinstance(params, dict) else {}
    mode = _mode(raw_params.get("mode"))
    depth = str(raw_params.get("depth") or "overview").strip().lower() or "overview"
    try:
        ref = asset.require_ref(raw_params, "asset_ref")
    except AssetError as e:
        raise PaperReadError(f"paper.read 缺少或无效的 asset_ref：{e}") from e
    if str(ref.type or "").strip() != "document":
        raise PaperReadError(
            f"paper.read 只接受 type=document 的 Asset（PDF 论文），收到 type={ref.type!r}"
        )
    try:
        local_path = Path(asset.materialize_file(ref))
    except AssetError as e:
        raise PaperReadError(f"无法物化待听读论文：{e}") from e
    if not local_path.is_file():
        raise PaperReadError(f"待听读论文文件不存在：{local_path}")

    try:
        page_count = pdf_page_count(local_path)
        start, end = normalize_page_range(
            raw_params.get("page_start"),
            raw_params.get("page_end"),
            page_count=page_count,
            max_pages=MAX_READ_PAGES,
            what="听读",
        )
    except PdfRenderError as e:
        raise PaperReadError(str(e)) from e

    extract = structure_fn or _default_structure
    try:
        structure = extract(local_path, start=start, end=end)
    except (PaperStructureError, PdfRenderError) as e:
        raise PaperReadError(str(e)) from e

    if structure.chars <= 0:
        raise PaperReadError(
            f"PDF 第 {start}–{end} 页没有可听读的正文（可能是扫描件）：本能力不做 OCR，"
            "请先 pdf.to_images 渲染成图片，再用 image.ocr 识别"
        )


    if mode == MODE_EXPLAIN:
        try:
            explain_script(structure, depth=depth)
        except PaperExplainError as e:
            raise PaperReadError(str(e)) from e
        raise PaperReadError(  # pragma: no cover - explain 交付前走不到
            "paper.read explain 模式没有产出讲解稿"
        )

    # 听读语言：显式 lang 优先，否则按论文正文自动判定；脚手架话术与 TTS 音色用同一门语言
    script_lang = resolve_script_lang(structure, raw_params.get("lang"))
    prefix, pieces = build_original_pieces(structure, script_lang=script_lang)
    if not pieces:
        raise PaperReadError("听读失败：清洗后没有可朗读的正文")
    full_script = assemble_script(prefix, pieces)

    limit = _max_chars(raw_params.get("max_chars"))
    script, truncated = truncate_text(full_script, limit)
    if not script.strip():
        raise PaperReadError("听读失败：清洗后没有可朗读的正文")

    stem = _safe_stem(
        raw_params.get("name") or structure.title or "",
        fallback=f"paper-{ref.asset_id[:12]}",
    )
    # lang 不传（None）＝按正文语言自动判定音色；显式传入仍以调用方为准。
    # 这里与脚手架语言同源（script_lang），避免「英文正文 + 中文音色」或反之。
    lang = str(raw_params.get("lang") or "").strip() or script_lang
    voice = str(raw_params.get("voice") or "").strip() or None
    backend = str(raw_params.get("backend") or "").strip().lower() or None
    synthesize = synthesize_fn or synthesize_speech
    try:
        result = synthesize(
            script,
            _work_dir(ref.asset_id),
            stem=stem,
            backend=backend,
            voice=voice,
            speed=raw_params.get("speed"),
            lang=lang,
        )
    except TtsFileError as e:
        raise PaperReadError(str(e)) from e

    sections = _sections_index(
        pieces,
        prefix=prefix,
        total_chars=len(script),
        duration_sec=result.duration_sec,
    )

    ext = _MIME_EXT.get(str(result.mime_type or ""), ".mp3")
    try:
        audio_ref = asset.upload_file(
            result.path,
            producer="paper.read",
            mime_type=result.mime_type,
            asset_type="audio",
            filename=f"{stem}{ext}",
        )
    except AssetError as e:
        raise PaperReadError(f"听读音频上传登记失败：{e}") from e

    engine_label = (
        f"{result.engine}-tts 音色 {result.voice}"
        if result.engine == "edge"
        else f"macOS {result.engine} 音色 {result.voice}"
    )
    title_label = f"《{structure.title}》" if structure.title else "这篇论文"
    status_text = (
        f"已按原文模式听读{title_label}第 {start}–{end} 页（共 {page_count} 页，"
        f"{len(sections)} 节）共 {len(script)} 字，{_fmt_duration(result.duration_sec)}"
        f"（{engine_label}）"
    )
    if structure.references_dropped:
        status_text += f"；已跳过 References（{len(structure.captions)} 处图表说明不朗读）"
    if truncated:
        status_text += f"；已按上限 {limit} 字截断（可指定 page_start/page_end 分段听读）"
    if result.fallback_reason:
        status_text += "；神经音色不可用，已回退本机语音"
    status_text += "。音频已登记为 audio Asset。"

    outputs: dict[str, Any] = {
        "asset_ref": audio_ref.to_dict() if hasattr(audio_ref, "to_dict") else audio_ref,
        "mode": mode,
        "depth": depth if mode == MODE_EXPLAIN else None,
        "title": structure.title,
        "page_count": page_count,
        "page_start": start,
        "page_end": end,
        "sections": sections,
        "sections_count": len(sections),
        "chars": len(script),
        "chars_total": len(full_script),
        "truncated": bool(truncated),
        "duration_sec": result.duration_sec,
        "engine": result.engine,
        "voice": result.voice,
        "text_preview": _preview(script),
        "status_text": status_text,
    }
    log.info(
        "paper.read ok pdf_asset=%s mode=%s pages=%s-%s/%s sections=%s chars=%s truncated=%s "
        "engine=%s voice=%s audio=%s",
        ref.asset_id,
        mode,
        start,
        end,
        page_count,
        len(sections),
        len(script),
        truncated,
        result.engine,
        result.voice,
        getattr(audio_ref, "asset_id", "?"),
    )
    return (
        f"paper.read ok pdf_asset={ref.asset_id} mode={mode} pages={start}-{end} "
        f"sections={len(sections)} chars={len(script)} "
        f"audio_asset={getattr(audio_ref, 'asset_id', '?')} engine={result.engine}",
        outputs,
    )

