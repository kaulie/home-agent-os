"""Global mode state via global_events."""

from __future__ import annotations

from typing import Any

import db as brain_db

MODE_KIND = "mode"
READING_MODE = "reading"


def get_active_mode() -> str | None:
    return brain_db.resolve_active_mode()


def enter_mode(
    mode: str,
    *,
    edge_id: str = "",
    intent_id: str | int | None = None,
    payload: dict[str, Any] | None = None,
) -> int:
    subject = str(mode or "").strip()
    if not subject:
        raise ValueError("mode is required")
    active = get_active_mode()
    if active and active != subject:
        brain_db.append_global_event(
            {
                "kind": MODE_KIND,
                "action": "deactivate",
                "subject": active,
                "edge_id": edge_id,
                "intent_id": intent_id,
            }
        )
    body = dict(payload or {})
    return brain_db.append_global_event(
        {
            "kind": MODE_KIND,
            "action": "activate",
            "subject": subject,
            "payload": body or None,
            "edge_id": edge_id,
            "intent_id": intent_id,
        }
    )


def exit_mode(
    mode: str,
    *,
    edge_id: str = "",
    intent_id: str | int | None = None,
    payload: dict[str, Any] | None = None,
) -> int:
    subject = str(mode or "").strip()
    if not subject:
        raise ValueError("mode is required")
    return brain_db.append_global_event(
        {
            "kind": MODE_KIND,
            "action": "deactivate",
            "subject": subject,
            "payload": dict(payload or {}) or None,
            "edge_id": edge_id,
            "intent_id": intent_id,
        }
    )
