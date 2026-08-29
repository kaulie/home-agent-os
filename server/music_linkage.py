"""Brain-side music linkage for Mac Runtime.

When user intent text mentions playback/songs, Brain queues a one-shot hint on the
next heartbeat for music-capable online edges (Mac Runtime with music.* ads).

Mac Edge consumes `music_linkage` from heartbeat response and switches local
audio/STT profile (implementation lives on Mac — @runtime).

This module does NOT drive Home Mic / audio_pickup terminals.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

log = logging.getLogger("music_linkage")

try:
    import db as brain_db
except ImportError:  # pragma: no cover
    from server import db as brain_db  # type: ignore

MUSIC_MODE_KEYWORDS = ("播放", "歌曲", "放歌", "听歌", "音乐")

_MUSIC_CAP_PREFIXES = ("music.",)

_lock = threading.Lock()
_pending_enter: dict[str, dict[str, Any]] = {}
_active: dict[str, dict[str, Any]] = {}


def text_suggests_music_mode(text: str) -> bool:
    utterance = str(text or "").strip()
    if not utterance:
        return False
    return any(keyword in utterance for keyword in MUSIC_MODE_KEYWORDS)


def _edge_has_music_capability(services: Any) -> bool:
    if not isinstance(services, list):
        return False
    for svc in services:
        if not isinstance(svc, dict):
            continue
        caps = svc.get("capabilities")
        if not isinstance(caps, list):
            continue
        for cap in caps:
            if not isinstance(cap, dict):
                continue
            cid = str(cap.get("capability_id") or "").strip()
            if any(cid.startswith(prefix) for prefix in _MUSIC_CAP_PREFIXES):
                return True
    return False


def _music_capable_online_edges(edges: dict[str, dict[str, Any]]) -> list[str]:
    out: list[str] = []
    now = time.time()
    for edge_id, info in edges.items():
        if not isinstance(info, dict):
            continue
        if str(info.get("online_status") or "").lower() != "online":
            received = info.get("server_received_at")
            try:
                if received is None or (now - float(received)) > 120:
                    continue
            except (TypeError, ValueError):
                continue
        services = info.get("services")
        if not services:
            reg = info  # heartbeat row may mirror registration
        else:
            reg = info
        if not _edge_has_music_capability(services):
            # Fallback: Mac runtime device_type
            dt = str(reg.get("device_type") or "").lower()
            if dt not in ("mac", "macos", "mac_edge"):
                continue
        out.append(str(edge_id))
    return out


def on_user_intent_text(text: str, *, intent_id: int | str | None = None) -> list[str]:
    """Queue enter-music-mode hints for online music-capable edges."""
    if not text_suggests_music_mode(text):
        return []
    edges = brain_db.list_heartbeats()
    targets = _music_capable_online_edges(edges)
    if not targets:
        log.info(
            "music linkage: no online music-capable edge for intent=%s text=%r",
            intent_id,
            text[:80],
        )
        return []

    stamp = {
        "action": "enter_music_mode",
        "intent_id": str(intent_id) if intent_id is not None else "",
        "trigger_text": str(text or "")[:240],
        "queued_at": time.time(),
    }
    with _lock:
        for edge_id in targets:
            _pending_enter[edge_id] = dict(stamp)
    log.info(
        "music linkage: queued enter for %d edge(s) intent=%s",
        len(targets),
        intent_id,
    )
    return targets


def apply_heartbeat_ack(edge_id: str, body: dict[str, Any] | None) -> None:
    """Mac reports current music linkage mode in heartbeat body."""
    if not isinstance(body, dict):
        return
    raw = body.get("music_linkage")
    if not isinstance(raw, dict):
        return
    mode = str(raw.get("mode") or "").strip().lower()
    if mode not in ("music", "voice", "idle"):
        return
    eid = str(edge_id or "").strip()
    if not eid:
        return
    with _lock:
        _pending_enter.pop(eid, None)
        if mode == "music":
            _active[eid] = {
                "mode": "music",
                "since": time.time(),
                "intent_id": str(raw.get("intent_id") or ""),
            }
        elif mode in ("voice", "idle"):
            _active.pop(eid, None)


def heartbeat_payload(edge_id: str) -> dict[str, Any] | None:
    """One-shot hint for Mac on heartbeat; cleared after delivery."""
    eid = str(edge_id or "").strip()
    if not eid:
        return None
    with _lock:
        pending = _pending_enter.pop(eid, None)
        active = _active.get(eid)
    if pending:
        return {
            "command": pending.get("action") or "enter_music_mode",
            "mode": "enter",
            "intent_id": pending.get("intent_id") or "",
            "trigger_text": pending.get("trigger_text") or "",
        }
    if active:
        return {
            "command": "music_mode_active",
            "mode": "music",
            "since": active.get("since"),
            "intent_id": active.get("intent_id") or "",
        }
    return None


def status() -> dict[str, Any]:
    with _lock:
        return {
            "pending": dict(_pending_enter),
            "active": dict(_active),
            "keywords": list(MUSIC_MODE_KEYWORDS),
        }
