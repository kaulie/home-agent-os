"""paper.read Original 模式：忠实原文的**听觉清洗**（纯函数，不调 LLM）。

「不调 LLM」是本模式的关键设计：保真 = 不引入幻觉，且快（一篇 20 页论文秒级出脚本）。

允许（规则化、可单测的清理）：

| 规则 | 实现 |
|---|---|
| 断词修复 | ``meth-\\nod`` → ``method``（``_DEHYPHEN_RE``） |
| 续行拼接 | 行首小写/小标点的折行接回上一行（``_JOIN_LINE_RE``） |
| 删 URL / 邮箱 | ``_URL_RE`` / ``_EMAIL_RE`` |
| 删引文编号 | ``[12]`` / ``[1,2]`` / ``[3-5]`` / ``[Smith et al. 2020]`` |
| 删页码 / 页眉页脚 | 结构层已去 + 独立成行的数字（``_PAGE_NUM_LINE_RE``） |
| 删版式噪声 | arXiv 戳、Preprint / Under review / Copyright 等独立行（``_NOISE_LINE_RE``） |
| 公式语音化 | ``$$…$$`` → 「公式」；``$x$`` → 保留变量名 |
| 图表引用自然化 | 中文正文：``Fig. 2`` → 图二；英文正文：``Fig. 2`` → ``Figure 2`` |
| 标题朗读化 | 独立行标题 → 中文「下面是<标题>部分。」/ 英文 ``Next, the <标题> section.`` |
| 排版合并 | 多空格/多空行归一；caption 由结构层排除，不进正文 |

脚手架话术（标题、章节引言、图表引用）**跟随正文语言**（`text_lang.detect_lang`），
和 TTS 选音色用同一个判定 —— 否则英文论文里会突然冒出「图一」，听着中英夹生。

**Original 红线**（写进代码也写进 capability 文档，本模块不做任何一件）：

- 不总结作者观点、不加作者没说的结论、不改技术含义；
- 不删关键实验结果、不对方法加自己的解释、不用类比替换概念；
- 不补论文外知识（含模型自身知识）。

> Faithful to the paper, optimized for listening.
"""

from __future__ import annotations

import re
from typing import Any

from mac_edge.plugins.paper_structure import PaperStructure, Section
from mac_edge.plugins.text_lang import detect_lang, lang_key, normalize_lang

_CN_DIGITS = "零一二三四五六七八九"

_DEHYPHEN_RE = re.compile(r"(\w)-\s*\n\s*(\w)")
_JOIN_LINE_RE = re.compile(r"\n(?=[a-z,;:\u4e00-\u9fff])")
_URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.I)
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_BRACKET_CITE_RE = re.compile(r"\[[\d\s,;\u2013\u2014-]+\]")
_NAMED_CITE_RE = re.compile(r"\[[A-Z][^\]\n]{0,40}?\d{4}[a-z]?\]")
_DISPLAY_MATH_RE = re.compile(r"\$\$.+?\$\$", re.S)
_INLINE_MATH_RE = re.compile(r"\$([^$\n]{1,40})\$")
_LATEX_CMD_RE = re.compile(r"\\([A-Za-z]+)")
# 常见 LaTeX 命令 → 可朗读的英文（其余命令丢弃，只保留变量名/数字）
_LATEX_WORDS = {
    "alpha": "alpha",
    "beta": "beta",
    "gamma": "gamma",
    "delta": "delta",
    "epsilon": "epsilon",
    "varepsilon": "epsilon",
    "zeta": "zeta",
    "eta": "eta",
    "theta": "theta",
    "kappa": "kappa",
    "lambda": "lambda",
    "mu": "mu",
    "nu": "nu",
    "xi": "xi",
    "pi": "pi",
    "rho": "rho",
    "sigma": "sigma",
    "tau": "tau",
    "phi": "phi",
    "chi": "chi",
    "psi": "psi",
    "omega": "omega",
    "infty": "infinity",
    "sum": "sum",
    "prod": "product",
    "log": "log",
    "exp": "exp",
    "max": "max",
    "min": "min",
    "argmax": "arg max",
    "argmin": "arg min",
}
_STRAY_DOLLAR_RE = re.compile(r"\${1,2}")
_PAGE_NUM_LINE_RE = re.compile(r"(?m)^\s*\d{1,5}\s*$")
_NOISE_LINE_RE = re.compile(
    r"(?i)^(arxiv:\s*\S+.*|preprint\b.*|under\s+review\b.*|published\s+as\b.*|"
    r"copyright\b.*|all\s+rights\s+reserved.*|\u00a9.*)$"
)
_FIG_REF_RE = re.compile(r"\b(?:fig(?:ure)?s?\.?)\s*(\d{1,3})([a-z])?\)?", re.I)
_TABLE_REF_RE = re.compile(r"\b(?:tables?|tab\.?)\s*(\d{1,3})([a-z])?\)?", re.I)
_EQ_REF_RE = re.compile(r"\b(?:eq(?:uation)?s?\.?)\s*\(?(\d{1,3})\)?", re.I)
_ALGO_REF_RE = re.compile(r"\b(?:algorithms?|algos?)\s*(\d{1,3})\)?", re.I)
_SEC_REF_RE = re.compile(r"\b(?:sections?|sec\.?)\s*(\d{1,2}(?:\.\d{1,2})*)\b", re.I)
_MULTI_SPACE_RE = re.compile(r"[ \t\u3000]{2,}")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")
_DUP_PUNCT_RE = re.compile(r"([,;:])(?:\s*\1)+")
_SPACE_BEFORE_PUNCT_RE = re.compile(r"[ \t]+([,.;:!?\uff0c\u3002\uff1b\uff1a\uff01\uff1f])")
_EMPTY_PARENS_RE = re.compile(r"\(\s*\)|\[\s*\]")


def cn_number(value: Any) -> str:
    """阿拉伯数字 → 中文数字（1–99 用汉字，其余保留数字，读数更自然）。"""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return str(value)
    if n < 0 or n > 99:
        return str(n)
    if n < 10:
        return _CN_DIGITS[n]
    if n == 10:
        return "十"
    if n < 20:
        return "十" + _CN_DIGITS[n - 10]
    tens, ones = divmod(n, 10)
    return _CN_DIGITS[tens] + "十" + (_CN_DIGITS[ones] if ones else "")


def _naturalize_references(text: str, lang: str = "zh") -> str:
    """图表/公式/算法/章节引用 → 听觉自然的说法（规则化，不改含义）。

    措辞跟随**正文语言**：中文论文说「图二」，英文论文说「Figure 2」——否则英文句子
    里突然冒出「图一」，听感就会中英夹生。
    """
    if lang == "en":
        out = _FIG_REF_RE.sub(lambda m: f"Figure {m.group(1)}{m.group(2) or ''}", text)
        out = _TABLE_REF_RE.sub(lambda m: f"Table {m.group(1)}{m.group(2) or ''}", out)
        out = _EQ_REF_RE.sub(lambda m: f"Equation {m.group(1)}", out)
        out = _ALGO_REF_RE.sub(lambda m: f"Algorithm {m.group(1)}", out)
        return _SEC_REF_RE.sub(lambda m: f"Section {m.group(1)}", out)
    out = _FIG_REF_RE.sub(lambda m: f"图{cn_number(m.group(1))}{m.group(2) or ''}", text)
    out = _TABLE_REF_RE.sub(lambda m: f"表{cn_number(m.group(1))}{m.group(2) or ''}", out)
    out = _EQ_REF_RE.sub(lambda m: f"公式{cn_number(m.group(1))}", out)
    out = _ALGO_REF_RE.sub(lambda m: f"算法{cn_number(m.group(1))}", out)
    return _SEC_REF_RE.sub(lambda m: f"第 {m.group(1)} 节", out)


def _math_to_speech(text: str) -> str:
    """公式语音化：块级公式 → 「公式」；行内公式 → 保留变量名（LaTeX 命令转可朗读词）。"""
    out = _DISPLAY_MATH_RE.sub(" 公式 ", text)

    def _inline(match: re.Match[str]) -> str:
        def _cmd(cmd: re.Match[str]) -> str:
            return f" {_LATEX_WORDS.get(cmd.group(1).lower(), '')} "

        inner = _LATEX_CMD_RE.sub(_cmd, match.group(1))
        inner = re.sub(r"[{}_^]", " ", inner)
        return re.sub(r"\s+", " ", inner).strip() or "变量"

    out = _INLINE_MATH_RE.sub(lambda m: f" {_inline(m)} ", out)
    return _STRAY_DOLLAR_RE.sub(" ", out)


def _tidy(text: str) -> str:
    out = _MULTI_SPACE_RE.sub(" ", text)
    out = _DUP_PUNCT_RE.sub(r"\1", out)
    out = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", out)
    out = _EMPTY_PARENS_RE.sub(" ", out)
    out = _MULTI_NEWLINE_RE.sub("\n\n", out)
    lines = [line.strip() for line in out.split("\n")]
    return "\n".join(lines).strip()


def clean_body(text: str, *, lang: str = "zh") -> str:
    """正文听觉清洗（Original 模式允许的全部规则，顺序固定、幂等友好）。

    `lang`（`zh` / `en`）决定引用话术的语言，见 `_naturalize_references`。
    """
    body = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    body = _DEHYPHEN_RE.sub(r"\1\2", body)
    lines = [re.sub(r"[ \t\u3000]+", " ", line).strip() for line in body.split("\n")]
    kept: list[str] = []
    for line in lines:
        if not line:
            continue
        if _PAGE_NUM_LINE_RE.match(line) or _NOISE_LINE_RE.match(line):
            continue
        kept.append(line)
    body = "\n".join(kept)
    body = _URL_RE.sub(" ", body)
    body = _EMAIL_RE.sub(" ", body)
    body = _BRACKET_CITE_RE.sub(" ", body)
    body = _NAMED_CITE_RE.sub(" ", body)
    body = _math_to_speech(body)
    body = _naturalize_references(body, lang)
    body = _JOIN_LINE_RE.sub(" ", body)
    return _tidy(body)


def speakable_heading(heading: str, *, lang: str = "zh") -> str:
    """标题朗读化：独立行标题 → 「下面是<标题>部分。」/「Next, the <标题> section.」
    （空标题 → 空串）。"""
    raw = re.sub(r"\s+", " ", str(heading or "")).strip().rstrip(".:：")
    if not raw:
        return ""
    if lang == "en":
        return f"Next, the {raw} section."
    return f"下面是 {raw} 部分。"


def section_piece(section: Section, *, lang: str = "zh") -> dict[str, Any]:
    """一个章节 → 脚本片段（含标题朗读行；``text`` 就是进 TTS 的原文）。"""
    body = clean_body("\n".join(section.paragraphs), lang=lang)
    head = speakable_heading(section.heading, lang=lang)
    text = f"{head}\n{body}".strip() if head else body
    return {
        "type": section.type,
        "heading": section.heading,
        "text": text,
        "body": body,
        "chars": len(text),
        "page_start": section.start_page,
        "page_end": section.end_page,
    }


def structure_body_text(structure: PaperStructure) -> str:
    """结构里的正文文本（用于判定听读语言）。"""
    return "\n".join("\n".join(str(p or "") for p in (s.paragraphs or [])) for s in structure.sections)


def resolve_script_lang(structure: PaperStructure, lang: str | None = None) -> str:
    """听读脚本语言：显式 lang 优先，否则按正文自动判定 → `zh` / `en`。"""
    explicit = normalize_lang(lang)
    if explicit:
        return lang_key(explicit)
    return lang_key(detect_lang(structure_body_text(structure)))


def build_original_pieces(
    structure: PaperStructure, *, script_lang: str | None = None
) -> tuple[str, list[dict[str, Any]]]:
    """PaperStructure → ``(prefix, pieces)``：prefix 是标题朗读行，pieces 是各章节片段。

    ``script_lang`` 缺省按正文自动判定（英文论文用英文脚手架，中文论文用中文脚手架）。
    """
    lang = resolve_script_lang(structure, script_lang)
    title = re.sub(r"\s+", " ", str(structure.title or "")).strip().rstrip(".")
    if not title:
        prefix = ""
    elif lang == "en":
        prefix = f"Paper title: {title}."
    else:
        prefix = f"论文标题：{title}。"
    pieces = [section_piece(s, lang=lang) for s in structure.sections]
    return prefix, [p for p in pieces if str(p.get("text") or "").strip()]


def assemble_script(prefix: str, pieces: list[dict[str, Any]]) -> str:
    """把 prefix + pieces 拼成一段连续听读的 spoken script。"""
    parts = [prefix] if str(prefix or "").strip() else []
    parts.extend(str(p.get("text") or "") for p in pieces)
    return "\n\n".join(p.strip() for p in parts if str(p).strip())

