#!/usr/bin/env python3
"""Cursor hook: pull @controller [dev-task] / [release] / [fleet] messages and optionally wake the agent."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / ".cursor" / "dev-inbox-state.json"
CHAT_URL = (os.environ.get("CHAT_URL") or "http://127.0.0.1:8787").strip().rstrip("/")
HANDLE = (os.environ.get("DEV_INBOX_HANDLE") or "controller").strip() or "controller"


def _load_since() -> int:
    if not STATE.is_file():
        return 0
    try:
        data = json.loads(STATE.read_text(encoding="utf-8"))
        return int(data.get("last_id") or 0)
    except (json.JSONDecodeError, TypeError, ValueError):
        return 0


def _save_since(last_id: int) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(
        json.dumps({"last_id": last_id, "handle": HANDLE}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    _ = sys.stdin.read()
    since_id = _load_since()
    url = f"{CHAT_URL}/api/v1/pull_msg?handle={HANDLE}&since_id={since_id}"
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            raw = resp.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError, OSError):
        print("{}")
        return

    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        print("{}")
        return

    messages = data.get("messages") or []
    last_id = int(data.get("last_id") or since_id)
    lines: list[str] = []
    fleet_done: list[str] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        body = str(msg.get("body") or "").strip()
        if "[dev-task]" in body or "[release]" in body:
            sender = str(msg.get("from") or msg.get("from_handle") or "").strip()
            lines.append(f"- [{sender}] {body}")
            continue
        if "[fleet]" not in body:
            continue
        if "event=finished" in body or "event=failed" in body:
            sender = str(msg.get("from") or msg.get("from_handle") or "").strip()
            fleet_done.append(f"- [{sender}] {body}")

    _save_since(last_id)
    if fleet_done:
        lines.extend(fleet_done)
    if not lines:
        print("{}")
        return

    summary = "\n".join(lines)
    followup = (
        "Agent Chatbox 有新进度（dev-task / release 节点 / fleet 终态）。请阅读并简短同步给用户，"
        "必要时在 smart_home_control 仓库里继续跟进或 wake 对应 Fleet handle："
        "产品改动须核对 [release] committed→tested→deployed。\n\n"
        f"{summary}"
    )
    print(json.dumps({"followup_message": followup}, ensure_ascii=False))


if __name__ == "__main__":
    main()
