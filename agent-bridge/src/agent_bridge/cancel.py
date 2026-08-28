"""Cooperative cancellation for in-flight agent runs."""

from __future__ import annotations

import subprocess
import threading

_lock = threading.Lock()
_procs: dict[str, subprocess.Popen] = {}
_cancelled: set[str] = set()


def mark_cancelled(run_id: str) -> bool:
    """Mark a run cancelled and terminate its subprocess if registered."""
    proc: subprocess.Popen | None = None
    with _lock:
        rid = str(run_id)
        if rid in _cancelled:
            return False
        _cancelled.add(rid)
        proc = _procs.get(rid)
    if proc is not None:
        _terminate(proc)
    return True


def is_cancelled(run_id: str) -> bool:
    with _lock:
        return str(run_id) in _cancelled


def register_proc(run_id: str, proc: subprocess.Popen) -> None:
    with _lock:
        _procs[str(run_id)] = proc


def clear_run(run_id: str) -> None:
    with _lock:
        rid = str(run_id)
        _cancelled.discard(rid)
        _procs.pop(rid, None)


def _terminate(proc: subprocess.Popen) -> None:
    try:
        proc.terminate()
    except Exception:
        pass
    try:
        proc.wait(timeout=2)
        return
    except Exception:
        pass
    try:
        proc.kill()
    except Exception:
        pass
