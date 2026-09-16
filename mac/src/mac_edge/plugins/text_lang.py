"""正文语言判定（纯函数，无依赖）：给「按语言选音色 / 选脚手架话术」共用。

为什么需要：一篇英文论文若用中文音色朗读，会带明显口音、语调也不对；反过来中文论文用
英文音色同理。调用方（TTS 合成层 `tts_file`、听读脚本清洗层 `paper_clean`）都用这里的
**同一个**判定，保证「脚本措辞」和「音色」是同一门语言。
"""

from __future__ import annotations

import re
from typing import Any

# CJK 字数 vs 拉丁词数（比按字母数比更稳：中文里的英文术语不会把语言带偏）
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_LATIN_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\u2019-]*")
# 中文占比阈值：CJK 字数 ≥ 拉丁词数 * 该比例即判为中文正文
_ZH_MIN_RATIO = 0.3

ZH = "zh"
EN = "en"


def normalize_lang(lang: Any) -> str:
    """lang 归一化：空 / `auto` / `detect` 视为「未指定」（返回 ""，交给正文判定）。"""
    text = str(lang or "").strip().lower().replace("-", "_")
    if not text or text in ("auto", "detect", "unknown", "none"):
        return ""
    return text


def detect_lang(text: str, *, default: str = "zh_CN") -> str:
    """按正文判定朗读语言：中文占比够高 → `zh_CN`，否则 `en_US`。

    - 纯英文（含数字/符号）：`en_US`
    - 纯中文：`zh_CN`
    - 中英混排：CJK 字数 ≥ 拉丁词数 * `_ZH_MIN_RATIO` 即判中文
    - 无字母可判（纯数字/符号）：`default`
    """
    body = str(text or "")
    cjk = len(_CJK_RE.findall(body))
    words = len(_LATIN_WORD_RE.findall(body))
    if cjk == 0 and words == 0:
        return default
    if cjk == 0:
        return "en_US"
    if words == 0:
        return "zh_CN"
    return "zh_CN" if cjk >= words * _ZH_MIN_RATIO else "en_US"


def lang_key(lang: Any) -> str:
    """语言归一化成两档 key：`zh` / `en`（`en_US` / `en-GB` / `EN` → `en`）。"""
    text = normalize_lang(lang)
    return ZH if text.startswith("zh") else EN
