"""Admin API views for agent-bridge Fleet status (+ Chat work alignment)."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

import agent_bridge_client as bridge
from agent_chat import resolve_chat_url

log = logging.getLogger(__name__)

DISPLAY_NAMES: dict[str, str] = {
    "coordinator": "system coordinator agent",
    "controller": "dev controller agent",
    "brain": "brain agent",
    "runtime": "runtime dev agent",
    "ui": "UI dev agent",
    "capability": "capability dev agent",
    "quality": "quality agent",
    "deploy": "deploy agent",
    "sre": "sre agent",
    "dba": "dba agent",
}

# Unified work phase: Chat reply + Fleet execution should match this.
PHASE_IDLE = "idle"
PHASE_AWAITING_RECV = "awaiting_recv"
PHASE_AWAITING_IDE = "awaiting_ide"
PHASE_QUEUED = "queued"
PHASE_RUNNING = "running"
PHASE_ACKED = "acked"

PHASE_LABELS = {
    PHASE_IDLE: "空闲",
    PHASE_AWAITING_RECV: "待签收",
    PHASE_AWAITING_IDE: "待 IDE",
    PHASE_QUEUED: "队列中",
    PHASE_RUNNING: "执行中",
    PHASE_ACKED: "已签收",
}


def _fetch_chat_work_board() -> dict[str, Any]:
    url = f"{resolve_chat_url()}/api/v1/work_board"
    try:
        with urllib.request.urlopen(url, timeout=3.0) as resp:
            raw = resp.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        log.debug("fleet work_board fetch failed: %s", err)
        return {}
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    handles = data.get("handles") if isinstance(data, dict) else None
    return handles if isinstance(handles, dict) else {}


def _derive_phase(
    handle: str,
    *,
    is_running: bool,
    is_queued: bool,
    awaiting_recv: list[dict[str, Any]],
    acked_open: list[dict[str, Any]],
    now: float | None = None,
    fresh_sec: float = 2 * 3600,
) -> tuple[str, bool, str | None]:
    """Return (phase, aligned, desync_note).

    Historical Chat without ✅ 签收 is shown as awaiting_recv, but only
    *fresh* misses (< fresh_sec) mark Fleet as misaligned.
    """
    import time as _time

    ts = float(now if now is not None else _time.time())
    fresh = []
    for row in awaiting_recv:
        created = row.get("created_at")
        if created is None:
            fresh.append(row)
            continue
        if ts - float(created) <= max(60.0, float(fresh_sec)):
            fresh.append(row)

    if is_running:
        return PHASE_RUNNING, True, None
    if is_queued:
        return PHASE_QUEUED, True, None

    if awaiting_recv:
        if handle == "controller":
            return PHASE_AWAITING_IDE, True, None
        if fresh:
            return (
                PHASE_AWAITING_RECV,
                False,
                f"Chat 有正式@未✅签收（#{fresh[0].get('id')}），Fleet 空闲",
            )
        # Older unsigned asks — surface phase, don't yell desync.
        return PHASE_AWAITING_RECV, True, None

    if acked_open:
        return PHASE_ACKED, True, None

    return PHASE_IDLE, True, None


def _agent_row(row: dict[str, Any], *, chat_work: dict[str, Any] | None = None) -> dict[str, Any]:
    handle = str(row.get("handle") or "").strip()
    work = (chat_work or {}).get(handle) or {}
    awaiting = list(work.get("awaiting_recv") or [])
    acked = list(work.get("acked_open") or [])
    is_running = bool(row.get("is_running") or row.get("running_run_id"))
    is_queued = bool(row.get("is_queued") or row.get("queued_run_id"))
    if not is_running and not is_queued:
        # Bridge older builds may only set running_*; treat queued via active_status
        active_status = str(row.get("active_status") or row.get("running_status") or "")
        if active_status == "queued":
            is_queued = True
        elif active_status == "running":
            is_running = True

    phase, aligned, desync = _derive_phase(
        handle,
        is_running=is_running,
        is_queued=is_queued,
        awaiting_recv=awaiting,
        acked_open=acked,
    )

    return {
        "handle": handle,
        "display_name": DISPLAY_NAMES.get(handle, handle),
        "agent_id": row.get("agent_id"),
        "last_wake_at": row.get("last_wake_at"),
        "running_run_id": row.get("running_run_id"),
        "running_status": row.get("running_status"),
        "queued_run_id": row.get("queued_run_id"),
        "active_run_id": row.get("active_run_id") or row.get("running_run_id") or row.get("queued_run_id"),
        "active_status": row.get("active_status")
        or row.get("running_status")
        or ("queued" if is_queued else None),
        "source_message_id": row.get("source_message_id"),
        "chat_role": row.get("chat_role"),
        "is_running": is_running,
        "is_queued": is_queued,
        "has_session": bool(row.get("agent_id") or row.get("has_session")),
        "phase": phase,
        "phase_label": PHASE_LABELS.get(phase, phase),
        "aligned": aligned,
        "desync": desync,
        "chat_awaiting_recv": awaiting[:5],
        "chat_acked_open": acked[:5],
        "chat_open_count": len(awaiting) + len(acked),
    }


def get_fleet_view() -> dict[str, Any]:
    if not bridge.bridge_enabled():
        return {
            "ok": False,
            "error": "agent-bridge 未启用",
            "bridge_url": bridge.bridge_base_url(),
            "bridge_ok": False,
            "agents": [],
            "runs": [],
            "work_aligned": True,
        }
    try:
        status = bridge.bridge_status()
        agents_payload = bridge.list_agents()
        runs_payload = bridge.list_runs(limit=20)
    except bridge.AgentBridgeError as err:
        return {
            "ok": False,
            "error": str(err),
            "bridge_url": bridge.bridge_base_url(),
            "bridge_ok": False,
            "agents": [],
            "runs": [],
            "work_aligned": True,
        }

    chat_work = _fetch_chat_work_board()

    agents_raw = agents_payload.get("agents") or []
    agents: list[dict[str, Any]] = []
    if isinstance(agents_raw, list):
        for row in agents_raw:
            if isinstance(row, dict):
                agents.append(_agent_row(row, chat_work=chat_work))

    # Ensure all roster handles appear even if bridge omitted one.
    seen = {a["handle"] for a in agents}
    for handle in DISPLAY_NAMES:
        if handle in seen:
            continue
        agents.append(
            _agent_row(
                {"handle": handle, "agent_id": None, "has_session": False},
                chat_work=chat_work,
            )
        )
    agents.sort(key=lambda a: a["handle"])

    runs_raw = runs_payload.get("runs") or []
    runs: list[dict[str, Any]] = []
    if isinstance(runs_raw, list):
        for row in runs_raw:
            if isinstance(row, dict):
                runs.append(row)

    desync_agents = [a["handle"] for a in agents if a.get("aligned") is False]
    return {
        "ok": True,
        "bridge_url": bridge.bridge_base_url(),
        "bridge_ok": True,
        "status": {
            "agent_id": status.get("agent_id"),
            "agent_connected": status.get("agent_connected"),
            "active_run_id": status.get("active_run_id"),
            "active_status": status.get("active_status"),
            "running_run_id": status.get("running_run_id"),
            "queue_depth": status.get("queue_depth"),
            "queued_count": status.get("queued_count"),
            "model": status.get("model"),
            "backend": status.get("backend"),
        },
        "agents": agents,
        "runs": runs,
        "work_aligned": not desync_agents,
        "desync_handles": desync_agents,
    }


def wake_fleet_agent(handle: str, *, text: str = "") -> dict[str, Any]:
    if not bridge.bridge_enabled():
        return {"ok": False, "error": "agent-bridge 未启用"}
    try:
        result = bridge.wake_agent(handle, text=text, pull_chat=False)
    except bridge.AgentBridgeError as err:
        return {"ok": False, "error": str(err)}
    return {"ok": True, **result}
