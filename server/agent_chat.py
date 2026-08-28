"""Admin proxy for Agent Chatbox + promote Chat to Dev Task."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from dev_task import submit_agent_task
from dev_task_category import normalize_category

_DEFAULT_LAN_CHAT = "http://127.0.0.1:8787"
_DEFAULT_CLOUD_TUNNEL_CHAT = "http://127.0.0.1:18787"


class AgentChatError(Exception):
    pass


def _is_cloud_brain() -> bool:
    raw = (os.environ.get("BRAIN_ORIGIN") or "").strip().lower()
    if raw == "cloud":
        return True
    if raw == "lan":
        return False
    try:
        here = str(Path(__file__).resolve())
    except OSError:
        here = ""
    return "/root/chat-gateway" in here


def resolve_chat_url() -> str:
    """LAN Brain → local chat; cloud Brain → SSH reverse tunnel to home Mac chat."""
    explicit = (os.environ.get("CHAT_URL") or "").strip().rstrip("/")
    if explicit:
        return explicit
    if _is_cloud_brain():
        port = (os.environ.get("CHAT_TUNNEL_PORT") or "18787").strip() or "18787"
        return f"http://127.0.0.1:{port}"
    return _DEFAULT_LAN_CHAT


def chat_enabled() -> bool:
    return (os.environ.get("AGENT_CHAT_ENABLED") or "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _request(method: str, path: str, *, body: dict[str, Any] | None = None, timeout: float = 8.0) -> Any:
    chat_url = resolve_chat_url()
    url = f"{chat_url}{path}"
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", errors="replace")
        raise AgentChatError(f"chat HTTP {err.code}: {detail[:300]}") from err
    except urllib.error.URLError as err:
        raise AgentChatError(f"chat unreachable: {err.reason}") from err
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as err:
        raise AgentChatError(f"chat returned invalid JSON: {raw[:200]}") from err


def get_chat_view(*, since_id: int = 0, since_ack_at: float = 0.0) -> dict[str, Any]:
    chat_url = resolve_chat_url()
    if not chat_enabled():
        return {
            "ok": False,
            "error": "Agent Chatbox 未启用",
            "chat_url": chat_url,
            "chat_ok": False,
            "messages": [],
            "ack_patches": [],
            "latest_ack_at": 0.0,
        }
    try:
        payload = _request(
            "GET",
            f"/api/v1/messages?since_id={max(0, int(since_id))}&since_ack_at={max(0.0, float(since_ack_at))}",
        )
    except AgentChatError as err:
        return {
            "ok": False,
            "error": str(err),
            "chat_url": chat_url,
            "chat_ok": False,
            "messages": [],
            "ack_patches": [],
            "latest_ack_at": 0.0,
        }
    messages = payload.get("messages") if isinstance(payload, dict) else []
    if not isinstance(messages, list):
        messages = []
    ack_patches = payload.get("ack_patches") if isinstance(payload, dict) else []
    if not isinstance(ack_patches, list):
        ack_patches = []
    latest_ack_at = payload.get("latest_ack_at") if isinstance(payload, dict) else 0.0
    try:
        latest_ack_at = float(latest_ack_at or 0)
    except (TypeError, ValueError):
        latest_ack_at = 0.0
    return {
        "ok": True,
        "chat_url": chat_url,
        "chat_ok": True,
        "messages": messages,
        "ack_patches": ack_patches,
        "latest_ack_at": latest_ack_at,
        "agents": payload.get("agents") if isinstance(payload, dict) else [],
        "handles": payload.get("handles") if isinstance(payload, dict) else [],
    }


def ack_chat_message(*, from_handle: str, message_id: int, ack_type: str = "ok") -> dict[str, Any]:
    if not chat_enabled():
        raise AgentChatError("Agent Chatbox 未启用")
    payload = _request(
        "POST",
        "/api/v1/ack_msg",
        body={
            "from": str(from_handle or "").strip(),
            "message_id": int(message_id),
            "ack_type": str(ack_type or "ok"),
        },
    )
    return _unwrap_chat_message(payload)


def ack_boss_message(message_id: int, *, ack_type: str = "ok") -> dict[str, Any]:
    return ack_chat_message(from_handle="boss", message_id=message_id, ack_type=ack_type)


def unack_chat_message(*, from_handle: str, message_id: int) -> dict[str, Any]:
    if not chat_enabled():
        raise AgentChatError("Agent Chatbox 未启用")
    payload = _request(
        "POST",
        "/api/v1/unack_msg",
        body={
            "from": str(from_handle or "").strip(),
            "message_id": int(message_id),
        },
    )
    return _unwrap_chat_message(payload)


def unack_boss_message(message_id: int) -> dict[str, Any]:
    return unack_chat_message(from_handle="boss", message_id=message_id)


def _unwrap_chat_message(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise AgentChatError("chat returned invalid message")
    inner = payload.get("message")
    if isinstance(inner, dict) and inner.get("id") is not None:
        return inner
    if payload.get("id") is not None:
        return payload
    raise AgentChatError("chat returned invalid message")


def send_boss_message(body: str) -> dict[str, Any]:
    text = str(body or "").strip()
    if not text:
        raise AgentChatError("body is empty")
    if not chat_enabled():
        raise AgentChatError("Agent Chatbox 未启用")
    payload = _request(
        "POST",
        "/api/v1/push_msg",
        body={"from": "boss", "body": text},
    )
    return _unwrap_chat_message(payload)


def build_promoted_task_text(
    task_text: str,
    background_messages: list[dict[str, Any]] | None = None,
) -> str:
    parts: list[str] = []
    rows = background_messages or []
    if rows:
        parts.append("## Background (Chatbox, reference only)")
        for row in rows:
            if not isinstance(row, dict):
                continue
            sender = str(row.get("from") or row.get("from_handle") or "").strip()
            body = str(row.get("body") or "").strip()
            if not body:
                continue
            parts.append(f"- [{sender}] {body[:2000]}")
        parts.append("")
    parts.append("## Task")
    parts.append(str(task_text or "").strip())
    return "\n".join(parts).strip()


def promote_chat_to_dev_task(
    *,
    task_text: str,
    target_handle: str | None = None,
    category: str | None = None,
    background_messages: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    trimmed = str(task_text or "").strip()
    if not trimmed:
        raise AgentChatError("task text is required")
    prompt = build_promoted_task_text(trimmed, background_messages)
    view = submit_agent_task(
        prompt,
        category=normalize_category(category),
        target_handle=target_handle,
    )
    return {"ok": True, **view}


def related_background_from_messages(
    messages: list[dict[str, Any]],
    *,
    anchor_id: int | None = None,
    limit: int = 8,
    message_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    """Pick chat rows for Dev Task background."""
    rows = [m for m in messages if isinstance(m, dict)]
    rows.sort(key=lambda m: int(m.get("id") or 0))
    if message_ids is not None:
        want = {int(i) for i in message_ids}
        rows = [m for m in rows if int(m.get("id") or 0) in want]
    elif anchor_id is not None:
        rows = [m for m in rows if int(m.get("id") or 0) <= int(anchor_id)]
        if limit > 0:
            rows = rows[-limit:]
    elif limit > 0:
        rows = rows[-limit:]
    return [
        {
            "id": m.get("id"),
            "from": m.get("from") or m.get("from_handle"),
            "body": m.get("body"),
        }
        for m in rows
        if str(m.get("body") or "").strip()
    ]
