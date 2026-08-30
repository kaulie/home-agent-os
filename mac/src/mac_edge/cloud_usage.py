"""Cross-process counters for Mac Edge / mac_voice public-cloud outbound requests.

mac_voice (STT) and mac_edge (heartbeat) are separate processes — counters live in a
JSON file under MAC_EDGE_DATA_DIR so increments from voice survive into Runtime
heartbeats.

One outbound HTTP/API call = one increment (ok or fail).
"""

from __future__ import annotations

import json
import logging
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

log = logging.getLogger("mac_edge.cloud_usage")

_mem_lock = threading.Lock()
# Process-local mirror only used when the store file is unavailable.
_mem: dict[str, dict[str, int]] = {}


def _default_data_dir() -> Path:
    env = (
        os.environ.get("MAC_EDGE_DATA_DIR")
        or os.environ.get("MAC_VOICE_DATA_DIR")
        or ""
    ).strip()
    if env:
        return Path(env).expanduser()
    # mac/src/mac_edge/cloud_usage.py → parents[2] = mac/
    return Path(__file__).resolve().parents[2] / "data"


def _store_path() -> Path:
    override = (os.environ.get("MAC_CLOUD_USAGE_PATH") or "").strip()
    if override:
        return Path(override).expanduser()
    return _default_data_dir() / "cloud_usage.json"


def _empty_bucket() -> dict[str, int]:
    return {"ok": 0, "fail": 0}


def _normalize(raw: Any) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    if not isinstance(raw, dict):
        return out
    for sid, bucket in raw.items():
        key = str(sid or "").strip()
        if not key or not isinstance(bucket, dict):
            continue
        try:
            ok_n = max(0, int(bucket.get("ok") or 0))
            fail_n = max(0, int(bucket.get("fail") or 0))
        except (TypeError, ValueError):
            continue
        if ok_n or fail_n:
            out[key] = {"ok": ok_n, "fail": fail_n}
    return out


def _read_unlocked(path: Path) -> dict[str, dict[str, int]]:
    try:
        if not path.is_file():
            return {}
        raw = json.loads(path.read_text(encoding="utf-8"))
        return _normalize(raw)
    except Exception:
        log.exception("cloud_usage read failed path=%s", path)
        return {}


def _write_unlocked(path: Path, data: dict[str, dict[str, int]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = {
        sid: {"ok": int(bucket["ok"]), "fail": int(bucket["fail"])}
        for sid, bucket in sorted(data.items())
        if bucket.get("ok") or bucket.get("fail")
    }
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=0), encoding="utf-8")
    tmp.replace(path)


@contextmanager
def _file_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    fh = lock_path.open("a+", encoding="utf-8")
    try:
        try:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        except Exception:
            # Best-effort on platforms without flock.
            pass
        yield
    finally:
        try:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        fh.close()


def _format(data: dict[str, dict[str, int]]) -> list[dict[str, Any]]:
    return [
        {
            "service_id": sid,
            "ok": int(bucket["ok"]),
            "fail": int(bucket["fail"]),
        }
        for sid, bucket in sorted(data.items())
        if bucket["ok"] or bucket["fail"]
    ]


def increment(service_id: str, ok: bool) -> None:
    sid = str(service_id or "").strip()
    if not sid:
        return
    path = _store_path()
    try:
        with _file_lock(path):
            data = _read_unlocked(path)
            bucket = data.setdefault(sid, _empty_bucket())
            if ok:
                bucket["ok"] += 1
            else:
                bucket["fail"] += 1
            _write_unlocked(path, data)
        return
    except Exception:
        log.exception("cloud_usage file increment failed; falling back to memory")
    with _mem_lock:
        bucket = _mem.setdefault(sid, _empty_bucket())
        if ok:
            bucket["ok"] += 1
        else:
            bucket["fail"] += 1


def snapshot() -> list[dict[str, Any]]:
    path = _store_path()
    try:
        with _file_lock(path):
            data = _read_unlocked(path)
        with _mem_lock:
            for sid, bucket in _mem.items():
                dest = data.setdefault(sid, _empty_bucket())
                dest["ok"] += int(bucket["ok"])
                dest["fail"] += int(bucket["fail"])
        return _format(data)
    except Exception:
        log.exception("cloud_usage snapshot failed; using memory only")
        with _mem_lock:
            return _format(_mem)


def drain() -> list[dict[str, Any]]:
    path = _store_path()
    try:
        with _file_lock(path):
            data = _read_unlocked(path)
            _write_unlocked(path, {})
        with _mem_lock:
            for sid, bucket in _mem.items():
                dest = data.setdefault(sid, _empty_bucket())
                dest["ok"] += int(bucket["ok"])
                dest["fail"] += int(bucket["fail"])
            _mem.clear()
        return _format(data)
    except Exception:
        log.exception("cloud_usage drain failed; draining memory only")
        with _mem_lock:
            out = _format(_mem)
            _mem.clear()
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
