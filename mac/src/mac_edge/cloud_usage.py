"""Thread-safe counters for Mac Edge public-cloud outbound requests.

Runtime (@runtime) snapshots/drains around heartbeat. Capabilities only increment.
One outbound HTTP/API call = one increment (ok or fail).
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Any, Iterator

_lock = threading.Lock()
_counts: dict[str, dict[str, int]] = {}


def increment(service_id: str, ok: bool) -> None:
    sid = str(service_id or "").strip()
    if not sid:
        return
    with _lock:
        bucket = _counts.setdefault(sid, {"ok": 0, "fail": 0})
        if ok:
            bucket["ok"] += 1
        else:
            bucket["fail"] += 1


def snapshot() -> list[dict[str, Any]]:
    with _lock:
        return [
            {
                "service_id": sid,
                "ok": int(bucket["ok"]),
                "fail": int(bucket["fail"]),
            }
            for sid, bucket in sorted(_counts.items())
            if bucket["ok"] or bucket["fail"]
        ]


def drain() -> list[dict[str, Any]]:
    with _lock:
        out = [
            {
                "service_id": sid,
                "ok": int(bucket["ok"]),
                "fail": int(bucket["fail"]),
            }
            for sid, bucket in sorted(_counts.items())
            if bucket["ok"] or bucket["fail"]
        ]
        _counts.clear()
        return out


@contextmanager
def record(service_id: str) -> Iterator[None]:
    """Increment once when the ``with`` block exits (ok unless an exception)."""
    ok = False
    try:
        yield
        ok = True
    finally:
        increment(service_id, ok)
