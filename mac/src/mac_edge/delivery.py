"""Runtime delivery hook — TTS and other post-success side effects."""

from __future__ import annotations

import logging
from typing import Any

from mac_edge.brain_client import BrainClient
from mac_edge.plugins.notify_speak import NotifySpeakError, speak

log = logging.getLogger("mac_edge.delivery")


def _pending_for_edge(intent: dict[str, Any], edge_id: str) -> dict[str, Any] | None:
    pending = intent.get("pending_delivery")
    if not isinstance(pending, dict):
        return None
    want = str(pending.get("edge_id") or "").strip()
    if want != edge_id.strip():
        return None
    return pending


def run_pending_deliveries(
    intents: list[dict[str, Any]],
    *,
    edge_id: str,
    brain: BrainClient | None,
) -> int:
    """Execute pending_delivery rows assigned to this edge. Returns count handled."""
    handled = 0
    for intent in intents:
        if not isinstance(intent, dict):
            continue
        pending = _pending_for_edge(intent, edge_id)
        if not pending:
            continue
        iid = str(intent.get("id") or intent.get("intent_id") or "").strip()
        if not iid:
            continue
        kind = str(pending.get("kind") or "").strip().lower()
        if kind != "speak":
            log.warning("intent %s: unknown pending_delivery kind=%s", iid, kind)
            continue
        text = str(pending.get("text") or "").strip()
        if not text:
            log.warning("intent %s: pending_delivery speak missing text", iid)
            if brain is not None:
                brain.post_delivery_complete(iid, edge_node_id=edge_id)
            handled += 1
            continue
        try:
            speak(text, lang="zh_CN")
            log.info("intent %s: delivery speak OK (%d chars)", iid, len(text))
        except NotifySpeakError as exc:
            log.error("intent %s: delivery speak failed: %s", iid, exc)
        except Exception as exc:
            log.error("intent %s: delivery speak error: %s", iid, exc)
        if brain is not None:
            brain.post_delivery_complete(iid, edge_node_id=edge_id)
        handled += 1
    return handled
