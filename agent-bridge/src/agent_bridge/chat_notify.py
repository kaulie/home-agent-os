"""Notify open Cursor sessions via Agent Chatbox."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from chat.push_client import push_msg
except ImportError:  # pragma: no cover
    push_msg = None  # type: ignore


def notify_dev_task(
    event: str,
    *,
    run_id: str = "",
    intent_id: str = "",
    text: str = "",
    detail: str = "",
    status: str = "",
) -> None:
    if push_msg is None:
        return
    parts = ["@controller", "[dev-task]", event]
    if intent_id:
        parts.append(f"intent={intent_id}")
    if run_id:
        parts.append(f"run={run_id}")
    if status:
        parts.append(f"status={status}")
    if text:
        parts.append(f"task={text[:200]}")
    if detail:
        parts.append(detail[:500])
    body = " ".join(p for p in parts if p)
    ok = push_msg("agent-bridge", body)
    if not ok:
        log.debug("chat notify skipped (chat server unreachable)")
