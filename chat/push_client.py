"""Push a message into the local Agent Chatbox (127.0.0.1:8787)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


def chat_base_url() -> str:
    return (os.environ.get("CHAT_URL") or "http://127.0.0.1:8787").strip().rstrip("/")


def push_msg(from_handle: str, body: str, *, timeout: float = 3.0) -> bool:
    text = str(body or "").strip()
    if not text:
        return False
    sender = str(from_handle or "agent-bridge").strip() or "agent-bridge"
    payload = json.dumps({"from": sender, "body": text}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{chat_base_url()}/api/v1/push_msg",
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= int(resp.status) < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        return False
