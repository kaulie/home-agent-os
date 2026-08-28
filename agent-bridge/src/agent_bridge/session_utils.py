"""Shared helpers for Cursor agent / CLI session resume failures."""

from __future__ import annotations


def is_agent_not_found(err: Exception) -> bool:
    name = type(err).__name__.lower()
    if "notfound" in name or name.endswith("not_found"):
        return True
    msg = str(getattr(err, "message", None) or err).lower()
    return "agent" in msg and "not found" in msg


def is_stale_session_error(text: str) -> bool:
    low = (text or "").strip().lower()
    return "agent" in low and "not found" in low
