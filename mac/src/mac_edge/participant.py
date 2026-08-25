"""Participant Model wire for Runtime Agent register / heartbeat.

See docs/participant-model.md and docs/db-schema.md §4.2.
Runtime nodes declare roles + services. When hosting kind=input voice.stream,
heartbeat may also declare a light intent_sources entry (same edge_id; not a
separate participant).
"""

from __future__ import annotations

import time
from typing import Any

ROLE_RUNTIME = "runtime"
ROLE_INTENT_SOURCE = "intent_source"


def runtime_roles(*, with_intent_source: bool = False) -> list[str]:
    roles = [ROLE_RUNTIME]
    if with_intent_source:
        roles.append(ROLE_INTENT_SOURCE)
    return roles


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
    intent_sources: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build JSON body for POST /edge-register or /edge-heartbeat."""
    loc = (location or "living-room").strip() or "living-room"
    with_is = bool(intent_sources)
    body: dict[str, Any] = {
        "display_name": display_name,
        "device_type": device_type,
        "location": loc,
        "room": loc,
        "app_version": app_version,
        "services": services,
        "roles": runtime_roles(with_intent_source=with_is),
        "role_runtime": True,
        "role_intent_source": with_is,
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
    if intent_sources is not None:
        body["intent_sources"] = list(intent_sources)
    return body
