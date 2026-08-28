"""Substring trigger matching for shortcut / mode intercept."""

from __future__ import annotations

import re

_RE_NORMALIZE = re.compile(
    "[\\s，。！？,.!?\"'""''、；;：:""（）()【】\\[\\]《》<>]"
)


def normalize_text(text: str) -> str:
    raw = str(text or "").strip().lower()
    return _RE_NORMALIZE.sub("", raw)


def matches_any(text: str, triggers: tuple[str, ...]) -> bool:
    norm = normalize_text(text)
    if not norm:
        return False
    for trigger in triggers:
        token = normalize_text(trigger)
        if token and token in norm:
            return True
    return False
