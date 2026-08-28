"""Canonical Fleet handle list (aligned with chat/mentions.py)."""

from __future__ import annotations

FLEET_HANDLES: tuple[str, ...] = (
    "coordinator",
    "controller",
    "brain",
    "runtime",
    "ui",
    "capability",
    "quality",
    "deploy",
    "sre",
    "dba",
)

HANDLE_ALIASES: dict[str, str] = {
    "intent": "ui",
    "endpoint": "ui",
    "observer": "coordinator",
}

DEFAULT_HANDLE = "controller"


def normalize_fleet_handle(raw: str | None) -> str | None:
    key = (raw or "").strip().lower().lstrip("@")
    if not key:
        return None
    mapped = HANDLE_ALIASES.get(key, key)
    if mapped in FLEET_HANDLES:
        return mapped
    return None
