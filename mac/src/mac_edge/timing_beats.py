"""Local beat index for interval/cron steps (scheduler-owned, not Brain-computed)."""

from __future__ import annotations

from threading import Lock

_lock = Lock()
# (intent_id, step_num) -> beat_index
_BEATS: dict[tuple[str, int], int] = {}


def beat_key(intent_id: str, step_num: int) -> tuple[str, int]:
    return (str(intent_id).strip(), int(step_num))


def get_beat(intent_id: str, step_num: int) -> int:
    with _lock:
        return int(_BEATS.get(beat_key(intent_id, step_num), 0))


def set_beat(intent_id: str, step_num: int, beat: int) -> None:
    with _lock:
        _BEATS[beat_key(intent_id, step_num)] = max(0, int(beat))


def advance_beat(intent_id: str, step_num: int) -> int:
    with _lock:
        k = beat_key(intent_id, step_num)
        nxt = int(_BEATS.get(k, 0)) + 1
        _BEATS[k] = nxt
        return nxt


def clear_intent(intent_id: str) -> None:
    iid = str(intent_id).strip()
    with _lock:
        dead = [k for k in _BEATS if k[0] == iid]
        for k in dead:
            del _BEATS[k]
