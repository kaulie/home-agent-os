"""Tunable weights and thresholds for Intent Complexity Classifier V1.

Operators may override via environment without code changes.
These are not planner rules and must not be inlined into home_brain.py.
"""

from __future__ import annotations

import os
from typing import Any

CLASSIFIER_VERSION = "v1-rule"

DEFAULT_WEIGHTS: dict[str, float] = {
    "capability_candidate_count": 1.0,
    "action_count": 1.0,
    "condition_count": 3.0,
    "sequence_count": 2.0,
    "parallel_count": 2.0,
    "temporal_count": 2.0,
    "context_reference_count": 1.0,
    "ambiguity": 2.0,
    "text_length_factor": 1.0,
}

DEFAULT_SIMPLE_MAX = 3.0
DEFAULT_MEDIUM_MAX = 7.0

_WEIGHT_ENV = {
    "capability_candidate_count": "INTENT_COMPLEXITY_W_CAPABILITY",
    "action_count": "INTENT_COMPLEXITY_W_ACTION",
    "condition_count": "INTENT_COMPLEXITY_W_CONDITION",
    "sequence_count": "INTENT_COMPLEXITY_W_SEQUENCE",
    "parallel_count": "INTENT_COMPLEXITY_W_PARALLEL",
    "temporal_count": "INTENT_COMPLEXITY_W_TEMPORAL",
    "context_reference_count": "INTENT_COMPLEXITY_W_CONTEXT",
    "ambiguity": "INTENT_COMPLEXITY_W_AMBIGUITY",
    "text_length_factor": "INTENT_COMPLEXITY_W_TEXT_LENGTH",
}


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def get_weights() -> dict[str, float]:
    out = dict(DEFAULT_WEIGHTS)
    for key, env_name in _WEIGHT_ENV.items():
        out[key] = _env_float(env_name, out[key])
    return out


def get_simple_max() -> float:
    return _env_float("INTENT_COMPLEXITY_SIMPLE_MAX", DEFAULT_SIMPLE_MAX)


def get_medium_max() -> float:
    return _env_float("INTENT_COMPLEXITY_MEDIUM_MAX", DEFAULT_MEDIUM_MAX)


def merge_weights(overrides: dict[str, Any] | None) -> dict[str, float]:
    merged = get_weights()
    if not overrides:
        return merged
    for key, value in overrides.items():
        if key not in merged:
            continue
        try:
            merged[key] = float(value)
        except (TypeError, ValueError):
            continue
    return merged
