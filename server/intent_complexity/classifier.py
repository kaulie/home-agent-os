"""Intent Complexity Classifier V1: analyze → score → classify. No execution."""

from __future__ import annotations

import time
from typing import Any

from .config import CLASSIFIER_VERSION
from .features import extract_features
from .score import classify_score, compute_score


def classify(
    text: str,
    *,
    intent_id: Any = None,
    weights: dict[str, float] | None = None,
    simple_max: float | None = None,
    medium_max: float | None = None,
) -> dict[str, Any]:
    src = str(text or "")
    features, candidates = extract_features(src)
    score = compute_score(features, weights=weights)
    classification = classify_score(score, simple_max=simple_max, medium_max=medium_max)
    result: dict[str, Any] = {
        "text": src,
        "timestamp": int(time.time() * 1000),
        "classifier_version": CLASSIFIER_VERSION,
        "features": features,
        "candidates": candidates,
        "score": score,
        "classification": classification,
    }
    if intent_id is not None and str(intent_id).strip() != "":
        result["intent_id"] = intent_id
    return result
