"""Rule-based feature extractor. Counts only; no LLM."""

from __future__ import annotations

import re
from typing import Any

from .matcher import match_candidates
from .patterns import (
    ACTION_RE,
    CJK_RE,
    CONDITION_RE,
    CONTEXT_RE,
    DEMONSTRATIVE_RE,
    PARALLEL_RE,
    SEQUENCE_RE,
    TEMPORAL_RE,
)

# Alias hits that do not name a device / capability. Used only for ambiguity.
_VAGUE_TERMS = frozenset({"亮一点", "调亮", "调暗", "弄亮一点", "弄暗一点"})


def _all_terms_underspecified(candidates: list[dict[str, Any]]) -> bool:
    """True only when every hit is a vague dimming phrase, not a named capability.

    Two-character names (拍照, 台灯) are specified. The old ``len >= 3`` cutoff
    treated them as underspecified and pushed 「拍照」 from SIMPLE (2) to MEDIUM (4).
    """
    terms = [str(t) for row in candidates for t in (row.get("terms") or [])]
    if not terms:
        return True
    return not any(t not in _VAGUE_TERMS for t in terms)


def _count(pattern: re.Pattern[str], text: str) -> int:
    return len(pattern.findall(text))


def token_count(text: str) -> int:
    """Weak tokenizer: each CJK ideograph is one token; Latin runs split on space."""
    n = 0
    buf: list[str] = []

    def flush() -> None:
        nonlocal n, buf
        if buf:
            n += 1
            buf = []

    for ch in text:
        if CJK_RE.match(ch):
            flush()
            n += 1
        elif ch.isspace():
            flush()
        elif ch.isalnum() or ch in "'’-":
            buf.append(ch)
        else:
            flush()
    flush()
    return n


def text_length_factor(character_count: int) -> float:
    return min(1.0, max(0.0, (character_count - 8) / 40.0))


def extract_features(text: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    src = str(text or "")
    candidates = match_candidates(src)
    action_n = _count(ACTION_RE, src)
    has_trigger = any(c.get("strength") == "trigger" for c in candidates)
    has_recognize = any(c.get("strength") == "recognize" for c in candidates)
    only_weak = (
        bool(candidates)
        and not has_trigger
        and not has_recognize
        and _all_terms_underspecified(candidates)
    )
    zero_with_action = (not candidates) and action_n > 0
    deixis = bool(DEMONSTRATIVE_RE.search(src))
    ambiguity = 1 if (zero_with_action or only_weak or deixis) else 0
    chars = len(src)
    features = {
        "capability_candidate_count": len(candidates),
        "action_count": action_n,
        "condition_count": _count(CONDITION_RE, src),
        "sequence_count": _count(SEQUENCE_RE, src),
        "parallel_count": _count(PARALLEL_RE, src),
        "temporal_count": _count(TEMPORAL_RE, src),
        "context_reference_count": _count(CONTEXT_RE, src),
        "ambiguity": ambiguity,
        "character_count": chars,
        "token_count": token_count(src),
        "text_length_factor": round(text_length_factor(chars), 4),
    }
    return features, candidates
