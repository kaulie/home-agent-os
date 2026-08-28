"""User feedback problem types for Agent Debug Gateway."""

from __future__ import annotations

PROBLEM_TYPES: dict[str, str] = {
    "intent_understanding": "意图理解不准确",
    "execution_error": "执行报错",
    "slow_response": "响应速度太慢",
    "other": "其他",
}


def normalize_problem_type(raw: str) -> str:
    key = (raw or "").strip().lower()
    if key in PROBLEM_TYPES:
        return key
    return ""


def problem_type_label(key: str) -> str:
    return PROBLEM_TYPES.get((key or "").strip().lower(), "")
