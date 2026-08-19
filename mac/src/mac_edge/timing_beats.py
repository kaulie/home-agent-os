"""Local beat index for interval/cron steps (scheduler-owned, not Brain-computed)."""

from __future__ import annotations

from threading import Lock
from typing import Callable

_lock = Lock()
# (intent_id, step_num) -> beat_index
_BEATS: dict[tuple[str, int], int] = {}
_listener: Callable[[str, int, int], None] | None = None


def set_beat_listener(fn: Callable[[str, int, int], None] | None) -> None:
    global _listener
    _listener = fn


def beat_key(intent_id: str, step_num: int) -> tuple[str, int]:
    return (str(intent_id).strip(), int(step_num))


def _emit(intent_id: str, step_num: int, beat: int) -> None:
    fn = _listener
    if fn is None:
        return
    try:
        fn(str(intent_id).strip(), int(step_num), int(beat))
    except Exception:
        pass


def get_beat(intent_id: str, step_num: int) -> int:
    with _lock:
        return int(_BEATS.get(beat_key(intent_id, step_num), 0))


def set_beat(intent_id: str, step_num: int, beat: int) -> None:
    with _lock:
        _BEATS[beat_key(intent_id, step_num)] = max(0, int(beat))
    _emit(intent_id, step_num, max(0, int(beat)))


def advance_beat(intent_id: str, step_num: int) -> int:
    with _lock:
        k = beat_key(intent_id, step_num)
        nxt = int(_BEATS.get(k, 0)) + 1
        _BEATS[k] = nxt
    _emit(intent_id, step_num, nxt)
    return nxt


def clear_intent(intent_id: str) -> None:
    iid = str(intent_id).strip()
    with _lock:
        dead = [k for k in _BEATS if k[0] == iid]
        for k in dead:
            del _BEATS[k]
