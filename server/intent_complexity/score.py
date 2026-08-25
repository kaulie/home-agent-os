"""Weighted score and SIMPLE / MEDIUM / COMPLEX buckets."""

from __future__ import annotations

from typing import Any

from .config import get_medium_max, get_simple_max, merge_weights

CLASS_SIMPLE = "SIMPLE"
CLASS_MEDIUM = "MEDIUM"
CLASS_COMPLEX = "COMPLEX"


def compute_score(
    features: dict[str, Any],
    *,
    weights: dict[str, float] | None = None,
) -> float:
    w = merge_weights(weights)
    total = 0.0
    total += w["capability_candidate_count"] * float(features.get("capability_candidate_count") or 0)
    total += w["action_count"] * float(features.get("action_count") or 0)
    total += w["condition_count"] * float(features.get("condition_count") or 0)
    total += w["sequence_count"] * float(features.get("sequence_count") or 0)
    total += w["parallel_count"] * float(features.get("parallel_count") or 0)
    total += w["temporal_count"] * float(features.get("temporal_count") or 0)
    total += w["context_reference_count"] * float(features.get("context_reference_count") or 0)
    total += w["ambiguity"] * float(features.get("ambiguity") or 0)
    total += w["text_length_factor"] * float(features.get("text_length_factor") or 0)
    return round(total, 4)


def classify_score(
    score: float,
    *,
    simple_max: float | None = None,
    medium_max: float | None = None,
) -> str:
    hi_simple = get_simple_max() if simple_max is None else float(simple_max)
    hi_medium = get_medium_max() if medium_max is None else float(medium_max)
    if score <= hi_simple:
        return CLASS_SIMPLE
    if score <= hi_medium:
        return CLASS_MEDIUM
    return CLASS_COMPLEX
