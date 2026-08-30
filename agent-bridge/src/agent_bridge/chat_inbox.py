"""Poll Agent Chatbox and auto-enqueue Fleet wakes for @mentions."""

from __future__ import annotations

import json
import logging
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from agent_bridge.config import BridgeConfig
from agent_bridge.fleet_handles import DEFAULT_HANDLE, FLEET_HANDLES
from agent_bridge.fleet_state import FleetStateStore
from agent_bridge.runner import AgentRunner
from agent_bridge.state import StateStore
from agent_bridge.wake import CHAT_URL, wake_handle

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from chat.kinds import KIND_COMPLETE  # noqa: E402
from chat.mentions import MentionRoles, normalize_handle, parse_mention_roles  # noqa: E402

AUTO_WAKE_SKIP_HANDLES = frozenset({DEFAULT_HANDLE})
SYSTEM_FROM_HANDLES = frozenset({"agent-bridge"})
SYSTEM_TAG_RE = re.compile(r"\[(dev-task|fleet)\]", re.IGNORECASE)


def wake_targets_from_mentions(mentions: list[str]) -> list[str]:
    """Handles to auto-wake for @mentions. @all fans in to coordinator only."""
    if not mentions:
        return []
    if "all" in mentions:
        return ["coordinator"]
    targets: list[str] = []
    for handle in mentions:
        if handle not in FLEET_HANDLES:
            continue
        if handle in AUTO_WAKE_SKIP_HANDLES:
            continue
        if handle not in targets:
            targets.append(handle)
    return targets


def wake_plan_from_roles(roles: MentionRoles) -> dict[str, str]:
    """Map handle → wake role: 'action' | 'cc'. Action wins over cc."""
    plan: dict[str, str] = {}
    for handle in wake_targets_from_mentions(roles.cc):
        plan[handle] = "cc"
    for handle in wake_targets_from_mentions(roles.action):
        plan[handle] = "action"
    return plan


def should_auto_wake_message(
    *,
    from_handle: str,
    body: str,
    kind: str = "chat",
) -> bool:
    sender = normalize_handle(from_handle)
    text = (body or "").strip()
    if kind == KIND_COMPLETE:
        return True
    if not text:
        return False
    if sender in SYSTEM_FROM_HANDLES:
        return False
    if SYSTEM_TAG_RE.search(text):
        return False
    roles = parse_mention_roles(text)
    return bool(wake_plan_from_roles(roles))


def build_chat_task_text(
    *,
    msg_id: int,
    sender: str,
    body: str,
    kind: str = "chat",
    role: str = "action",
) -> str:
    lines = [
        f"Chatbox @{sender} (message #{msg_id}, kind={kind}):",
        "",
        body.strip(),
    ]
    if kind == KIND_COMPLETE:
        lines.extend(
            [
                "",
                "## Completion report",
                "Dispatcher should ack via POST /api/v1/ack_msg (badge on this message).",
                "Do NOT push_msg「我知道了」— use ack_msg instead.",
            ]
        )
        return "\n".join(lines)

    if role == "cc":
        lines.extend(
            [
                "",
                "## CC only (周知) → 👌 知道了",
                "You are CC — FYI only, not ownership.",
                f"POST http://127.0.0.1:8787/api/v1/ack_msg JSON "
                f'{{"from":"<your-handle>","message_id":{msg_id},"ack_type":"got"}} '
                "（👌 知道了）. Do NOT use ack_type=recv.",
                "Do NOT push_msg「知道了」/「收到」chat lines.",
                "Do NOT implement unless you are also the formal @ target.",
                "Then end this wake.",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "## Action owner (正式 @) → [status] + ✅ 收到",
                "You were formally @-mentioned to do work.",
                "1. FIRST push_msg a one-line status to the sender (and @controller if useful), e.g.",
                "   `@boss #<msg_id> [status] phase=idle WIP：无 tree=clean 对本指令：接做`",
                "   Fields: phase=idle|wip|blocked|pending; WIP；tree=clean|dirty(…); 对本指令=接做|pending|转交.",
                f"2. THEN POST ack_msg ack_type=recv (message_id={msg_id}) — ✅ 收到.",
                "3. Implement within your layer, or keep pending until WIP is committed "
                "(see agent-wip-discipline).",
                "4. When done/blocked/need to discuss: push_msg a real Chat message. "
                "Do not use chat lines that only say「收到」/「知道了」.",
                "5. To notify without forcing a reply: cc @boss / cc @peer.",
            ]
        )
    return "\n".join(lines)


class ChatInboxWatcher:
    """Background poller: @handle in Chatbox → enqueue a Fleet wake job."""

    def __init__(
        self,
        config: BridgeConfig,
        store: StateStore,
        fleet: FleetStateStore,
        runner: AgentRunner,
    ) -> None:
        self._config = config
        self._store = store
        self._fleet = fleet
        self._runner = runner
        self._state_path = config.data_dir / "chat_inbox_state.json"
        self._lock = threading.Lock()
        self._shutdown = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_message_id = 0
        self._enqueued: set[str] = set()
        self._fresh_install = not self._state_path.is_file()
        self._load_state()

    def _bootstrap_cursor(self) -> None:
        """Skip historical Chatbox backlog on first run; only wake for new messages."""
        messages = self._fetch_messages()
        max_id = 0
        for message in messages:
            max_id = max(max_id, int(message.get("id") or 0))
        self._last_message_id = max_id
        self._persist_state()
        log.info("chat inbox bootstrapped at message id %s (skipping backlog)", max_id)

    def _clamp_cursor_to_chat(self) -> None:
        """If Chat DB was reset (ids restarted), don't stay stuck past EOF."""
        messages = self._fetch_messages_from(0)
        if not messages:
            return
        max_id = max(int(m.get("id") or 0) for m in messages)
        if self._last_message_id > max_id:
            log.warning(
                "chat inbox cursor %s ahead of chat max id %s — clamping (DB reset?)",
                self._last_message_id,
                max_id,
            )
            self._last_message_id = max_id
            self._persist_state()

    def start(self) -> None:
        if not self._config.chat_inbox_enabled:
            log.info("chat inbox auto-wake disabled")
            return
        if self._fresh_install:
            self._bootstrap_cursor()
        else:
            self._clamp_cursor_to_chat()
        self._thread = threading.Thread(
            target=self._loop,
            name="chat-inbox-watcher",
            daemon=True,
        )
        self._thread.start()
        log.info(
            "chat inbox watcher started (poll=%ss, chat=%s, since_id=%s)",
            self._config.chat_inbox_poll_sec,
            CHAT_URL,
            self._last_message_id,
        )

    def shutdown(self) -> None:
        self._shutdown.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _load_state(self) -> None:
        if not self._state_path.is_file():
            return
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, TypeError):
            return
        self._last_message_id = int(data.get("last_message_id") or 0)
        rows = data.get("enqueued") or []
        if isinstance(rows, list):
            self._enqueued = {str(item) for item in rows}

    def _persist_state(self) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "last_message_id": self._last_message_id,
            "enqueued": sorted(self._enqueued),
        }
        tmp = self._state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._state_path)

    def _fetch_messages(self) -> list[dict[str, Any]]:
        return self._fetch_messages_from(self._last_message_id)

    def _fetch_messages_from(self, since_id: int) -> list[dict[str, Any]]:
        url = f"{CHAT_URL}/api/v1/messages?since_id={since_id}"
        try:
            with urllib.request.urlopen(url, timeout=5.0) as resp:
                raw = resp.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            log.debug("chat inbox fetch failed: %s", err)
            return []
        try:
            data = json.loads(raw or "{}")
        except json.JSONDecodeError:
            return []
        rows = data.get("messages") or []
        return [row for row in rows if isinstance(row, dict)]

    def _dedupe_key(self, msg_id: int, handle: str) -> str:
        return f"{msg_id}:{handle}"

    def _already_enqueued(self, msg_id: int, handle: str) -> bool:
        return self._dedupe_key(msg_id, handle) in self._enqueued

    def process_message(self, message: dict[str, Any]) -> list[dict[str, Any]]:
        msg_id = int(message.get("id") or 0)
        if msg_id <= 0:
            return []
        sender = str(message.get("from") or message.get("from_handle") or "").strip()
        body = str(message.get("body") or "").strip()
        kind = str(message.get("kind") or "chat")
        if message.get("recalled_at"):
            return []
        if not should_auto_wake_message(from_handle=sender, body=body, kind=kind):
            return []

        roles = parse_mention_roles(body)
        plan = wake_plan_from_roles(roles)
        if kind == KIND_COMPLETE:
            for handle in message.get("mentions") or []:
                if (
                    handle in FLEET_HANDLES
                    and handle not in AUTO_WAKE_SKIP_HANDLES
                    and handle != sender
                    and handle not in plan
                ):
                    plan[handle] = "action"
        results: list[dict[str, Any]] = []
        for handle, role in plan.items():
            if sender == handle:
                continue
            if self._already_enqueued(msg_id, handle):
                continue
            if not self._config.can_run():
                log.warning("chat inbox skip wake %s: agent backend not configured", handle)
                continue
            task_text = build_chat_task_text(
                msg_id=msg_id,
                sender=sender,
                body=body,
                kind=kind,
                role=role,
            )
            try:
                result = wake_handle(
                    handle,
                    store=self._store,
                    fleet=self._fleet,
                    runner=self._runner,
                    task_text=task_text,
                    pull_chat=False,
                    source_message_id=msg_id,
                    chat_role=role,
                )
            except ValueError as err:
                log.warning("chat inbox wake %s failed: %s", handle, err)
                continue
            self._enqueued.add(self._dedupe_key(msg_id, handle))
            log.info(
                "chat inbox enqueued wake handle=%s role=%s msg=%s run=%s",
                handle,
                role,
                msg_id,
                result.get("run_id"),
            )
            results.append(result)
        return results

    def _loop(self) -> None:
        while not self._shutdown.is_set():
            try:
                self._poll_once()
            except Exception:  # pragma: no cover
                log.exception("chat inbox poll failed")
            self._shutdown.wait(self._config.chat_inbox_poll_sec)

    def _poll_once(self) -> None:
        messages = self._fetch_messages()
        if not messages:
            return
        with self._lock:
            for message in messages:
                msg_id = int(message.get("id") or 0)
                if msg_id > self._last_message_id:
                    self._last_message_id = msg_id
                self.process_message(message)
            self._persist_state()
