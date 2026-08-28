"""Normalize Cursor agent token usage payloads."""

from __future__ import annotations

from typing import Any


def _pick_int(raw: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = raw.get(key)
        if value is None:
            continue
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            continue
    return 0


def normalize_token_usage(raw: Any) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    input_tokens = _pick_int(raw, "input_tokens", "inputTokens")
    output_tokens = _pick_int(raw, "output_tokens", "outputTokens")
    cache_read_tokens = _pick_int(raw, "cache_read_tokens", "cacheReadTokens")
    cache_write_tokens = _pick_int(raw, "cache_write_tokens", "cacheWriteTokens")
    if not any((input_tokens, output_tokens, cache_read_tokens, cache_write_tokens)):
        return {}
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_write_tokens": cache_write_tokens,
        "total_tokens": input_tokens + output_tokens,
    }


def empty_usage_summary() -> dict[str, int]:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "total_tokens": 0,
    }


def add_usage(target: dict[str, int], addition: dict[str, int]) -> None:
    for key in empty_usage_summary():
        target[key] = int(target.get(key) or 0) + int(addition.get(key) or 0)
