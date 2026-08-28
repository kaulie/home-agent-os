"""Wake Fleet workers: build prompts and optionally pull Chatbox backlog."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

from agent_bridge.agent_profiles import build_wake_prompt
from agent_bridge.fleet_handles import DEFAULT_HANDLE, normalize_fleet_handle
from agent_bridge.fleet_state import FleetStateStore
from agent_bridge.runner import AgentRunner
from agent_bridge.state import StateStore

log = logging.getLogger(__name__)

CHAT_URL = (os.environ.get("CHAT_URL") or "http://127.0.0.1:8787").strip().rstrip("/")


def fetch_chat_summary(handle: str, *, timeout: float = 3.0) -> str:
    url = f"{CHAT_URL}/api/v1/pull_msg?handle={handle}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError, OSError):
        return ""
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return ""
    lines: list[str] = []
    for msg in data.get("messages") or []:
        if not isinstance(msg, dict):
            continue
        sender = str(msg.get("from") or msg.get("from_handle") or "").strip()
        body = str(msg.get("body") or "").strip()
        if body:
            lines.append(f"- [{sender}] {body[:500]}")
    return "\n".join(lines)


def wake_handle(
    handle: str,
    *,
    store: StateStore,
    fleet: FleetStateStore,
    runner: AgentRunner,
    task_text: str = "",
    pull_chat: bool = True,
    attachments: list[dict[str, str]] | None = None,
    task_id: int | None = None,
) -> dict[str, Any]:
    normalized = normalize_fleet_handle(handle)
    if normalized is None:
        raise ValueError(f"unknown fleet handle: {handle}")

    chat_summary = fetch_chat_summary(normalized) if pull_chat else ""
    prompt = build_wake_prompt(
        normalized,
        task_text=task_text,
        chat_summary=chat_summary,
    )
    fleet.touch_wake(normalized)
    run = store.create_run(
        prompt,
        attachments=attachments,
        task_id=task_id,
        target_handle=normalized,
    )
    runner.enqueue(run.run_id)
    return {
        "handle": normalized,
        "run_id": run.run_id,
        "status": run.status,
        "queue_depth": runner.pending_queue_depth(),
    }


def wake_controller(
    *,
    store: StateStore,
    fleet: FleetStateStore,
    runner: AgentRunner,
    task_text: str = "",
    **kwargs: Any,
) -> dict[str, Any]:
    return wake_handle(
        DEFAULT_HANDLE,
        store=store,
        fleet=fleet,
        runner=runner,
        task_text=task_text,
        **kwargs,
    )
