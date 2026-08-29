"""Brain ↔ Mac Edge music linkage (local playback flag).

Brain queues `enter_music_mode` on heartbeat when user text mentions 播放/歌曲.
Mac acknowledges with heartbeat body `music_linkage: {mode: music}`.
The flag does not mute mac_voice: 面条 wake still works during a song.
TTS playback mute (又咋了 / notify.speak) is separate.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("mac_edge.music_linkage")

_FLAG_NAME = "music_mode"
_STALE_SEC = 6 * 3600.0
_lock = threading.Lock()
_state: dict[str, Any] = {}


def flag_path() -> Path:
    env = (os.environ.get("MAC_EDGE_DATA_DIR") or "").strip()
    if env:
        return Path(env).expanduser() / _FLAG_NAME
    return Path(__file__).resolve().parents[2] / "data" / _FLAG_NAME


def _read_file_state(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _write_file_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False) + "\n", encoding="utf-8")


def snapshot() -> dict[str, Any]:
    with _lock:
        if _state:
            return dict(_state)
    return _read_file_state(flag_path())


def is_active(*, stale_s: float = _STALE_SEC) -> bool:
    snap = snapshot()
    if str(snap.get("mode") or "").lower() != "music":
        return False
    try:
        since = float(snap.get("since") or 0)
    except (TypeError, ValueError):
        since = 0.0
    if since <= 0:
        return True
    return (time.time() - since) <= max(60.0, stale_s)


def enter(*, intent_id: str = "", trigger_text: str = "") -> None:
    now = time.time()
    state = {
        "mode": "music",
        "since": now,
        "intent_id": str(intent_id or "").strip(),
        "trigger_text": str(trigger_text or "").strip()[:240],
    }
    path = flag_path()
    with _lock:
        _state.clear()
        _state.update(state)
    try:
        _write_file_state(path, state)
    except OSError as e:
        log.warning("music linkage flag write failed: %s", e)
    log.info(
        "music mode ON intent=%s trigger=%r",
        state.get("intent_id") or "-",
        state.get("trigger_text") or "",
    )


def exit_mode(*, reason: str = "") -> None:
    with _lock:
        was = bool(_state) or is_active()
        _state.clear()
    try:
        flag_path().unlink(missing_ok=True)
    except OSError:
        pass
    if was:
        log.info("music mode OFF reason=%s", reason or "exit")


def heartbeat_ack() -> dict[str, Any] | None:
    snap = snapshot()
    mode = str(snap.get("mode") or "").strip().lower()
    if mode == "music" and is_active():
        return {
            "mode": "music",
            "intent_id": str(snap.get("intent_id") or ""),
        }
    return {"mode": "idle"}


def apply_brain_hint(hint: dict[str, Any] | None) -> bool:
    if not isinstance(hint, dict) or not hint:
        return False
    command = str(hint.get("command") or "").strip().lower()
    mode = str(hint.get("mode") or "").strip().lower()
    if command in ("enter_music_mode",) or mode == "enter":
        enter(
            intent_id=str(hint.get("intent_id") or ""),
            trigger_text=str(hint.get("trigger_text") or ""),
        )
        return True
    if command in ("exit_music_mode", "set_normal") or mode in ("voice", "idle"):
        exit_mode(reason=command or mode)
        return True
    if command == "music_mode_active" and mode == "music":
        return False
    return False


class MusicLinkageMute:
    """True while music mode flag is active.

    Listen no longer uses this to drop USB STT (wake must survive playback).
    Kept as an is_active() wrapper for tests / callers that inspect the flag.
    """

    def __call__(self) -> bool:
        on = is_active()
        return on
