"""Admin API views for agent-bridge Fleet status."""

from __future__ import annotations

from typing import Any

import agent_bridge_client as bridge

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


def _agent_row(row: dict[str, Any]) -> dict[str, Any]:
    handle = str(row.get("handle") or "").strip()
    return {
        "handle": handle,
        "display_name": DISPLAY_NAMES.get(handle, handle),
        "agent_id": row.get("agent_id"),
        "last_wake_at": row.get("last_wake_at"),
        "running_run_id": row.get("running_run_id"),
        "running_status": row.get("running_status"),
        "is_running": bool(row.get("running_run_id")),
        "has_session": bool(row.get("agent_id")),
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
        }

    agents_raw = agents_payload.get("agents") or []
    agents: list[dict[str, Any]] = []
    if isinstance(agents_raw, list):
        for row in agents_raw:
            if isinstance(row, dict):
                agents.append(_agent_row(row))

    runs_raw = runs_payload.get("runs") or []
    runs: list[dict[str, Any]] = []
    if isinstance(runs_raw, list):
        for row in runs_raw:
            if isinstance(row, dict):
                runs.append(row)

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
    }


def wake_fleet_agent(handle: str, *, text: str = "") -> dict[str, Any]:
    if not bridge.bridge_enabled():
        return {"ok": False, "error": "agent-bridge 未启用"}
    try:
        result = bridge.wake_agent(handle, text=text, pull_chat=False)
    except bridge.AgentBridgeError as err:
        return {"ok": False, "error": str(err)}
    return {"ok": True, **result}
