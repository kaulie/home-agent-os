#!/usr/bin/env python3
"""Cursor hook: pull @controller Chatbox messages and optionally wake the agent.

Wakes on:
  - [dev-task] / [release] progress
  - [fleet] finished|failed
  - boss/owner/user formal @controller (human asks) — not skipped
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / ".cursor" / "dev-inbox-state.json"
CHAT_URL = (os.environ.get("CHAT_URL") or "http://127.0.0.1:8787").strip().rstrip("/")
HANDLE = (os.environ.get("DEV_INBOX_HANDLE") or "controller").strip() or "controller"

BOSS_SENDERS = frozenset({"boss", "owner", "user"})
_CONTROLLER_MENTION = re.compile(r"@controller\b", re.IGNORECASE)


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


def _is_cc_only_for_controller(body: str) -> bool:
    """True if @controller appears only inside a cc @… block (周知, not 派活)."""
    text = body or ""
    if not _CONTROLLER_MENTION.search(text):
        return False
    # Strip cc blocks; if no @controller left → cc-only.
    stripped = re.sub(
        r"(?i)(?<![A-Za-z0-9_])cc\s*:?\s*((?:@(?:[A-Za-z_]+|所有人)\s*)+)",
        " ",
        text,
    )
    return _CONTROLLER_MENTION.search(stripped) is None


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
    boss_asks: list[str] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        body = str(msg.get("body") or "").strip()
        sender = str(msg.get("from") or msg.get("from_handle") or "").strip().lower()
        if "[dev-task]" in body or "[release]" in body:
            lines.append(f"- [{sender}] {body}")
            continue
        if "[fleet]" in body:
            if "event=finished" in body or "event=failed" in body:
                fleet_done.append(f"- [{sender}] {body}")
            continue
        # Human @controller in Chat — must wake IDE (Fleet skips @controller on purpose).
        if sender in BOSS_SENDERS and _CONTROLLER_MENTION.search(body):
            if _is_cc_only_for_controller(body):
                continue
            boss_asks.append(f"- [{sender}] {body}")

    _save_since(last_id)
    if fleet_done:
        lines.extend(fleet_done)
    if boss_asks:
        lines.extend(boss_asks)
    if not lines:
        print("{}")
        return

    summary = "\n".join(lines)
    if boss_asks and not any("[dev-task]" in x or "[release]" in x or "[fleet]" in x for x in lines):
        followup = (
            "老板在 Agent Chatbox 正式 @controller 了。请立刻："
            "1) ack_msg ack_type=recv（✅ 收到）；"
            "2) 按 docs/agent-coordination.md 处理并 push_msg @boss 正式回复；"
            "3) 需要时再 wake Fleet。\n\n"
            f"{summary}"
        )
    else:
        followup = (
            "Agent Chatbox 有新进度（dev-task / release / fleet 终态"
            + (" / 老板 @controller" if boss_asks else "")
            + "）。请阅读并简短同步给用户，"
            "必要时在 smart_home_control 仓库里继续跟进或 wake 对应 Fleet handle："
            "产品改动须核对 [release] committed→tested→deployed。\n\n"
            f"{summary}"
        )
    print(json.dumps({"followup_message": followup}, ensure_ascii=False))


if __name__ == "__main__":
    main()
