"""Normalize User Console debug report client snapshots."""

from __future__ import annotations

from typing import Any


def normalize_client_snapshot(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    return dict(raw)


def merge_intent_context(
    context: dict[str, Any],
    client_snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    merged = dict(context)
    if client_snapshot:
        merged["client_snapshot"] = normalize_client_snapshot(client_snapshot)
    return merged
