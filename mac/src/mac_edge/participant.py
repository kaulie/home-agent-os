"""Participant Model wire for Runtime Agent register / heartbeat.

See docs/participant-model.md and docs/db-schema.md §4.2.
Pure Runtime nodes declare roles + services; no intent_sources / endpoints.
"""

from __future__ import annotations

import time
from typing import Any

ROLE_RUNTIME = "runtime"


def runtime_roles() -> list[str]:
    return [ROLE_RUNTIME]


def registration_payload(
    *,
    display_name: str,
    device_type: str,
    location: str,
    app_version: str,
    services: list[dict[str, Any]],
    client_hint: str | None = None,
    edge_id: str | None = None,
    reported_at: float | None = None,
    online_status: str | None = None,
    health: dict[str, Any] | None = None,
    client_time_ms: int | None = None,
) -> dict[str, Any]:
    """Build JSON body for POST /edge-register or /edge-heartbeat."""
    loc = (location or "living-room").strip() or "living-room"
    body: dict[str, Any] = {
        "display_name": display_name,
        "device_type": device_type,
        "location": loc,
        "room": loc,
        "app_version": app_version,
        "services": services,
        "roles": runtime_roles(),
        "role_runtime": True,
        "reported_at": float(reported_at if reported_at is not None else time.time()),
    }
    if client_hint:
        body["client_hint"] = client_hint
    if edge_id:
        body["edge_id"] = edge_id
    if online_status is not None:
        body["online_status"] = online_status
    if health is not None:
        body["health"] = health
    if client_time_ms is not None:
        body["client_time_ms"] = int(client_time_ms)
    return body
