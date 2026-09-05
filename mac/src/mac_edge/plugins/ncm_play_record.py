"""Sync BlackHole→mp3 capture while ncm-cli plays a track.

Default on (``MAC_EDGE_NCM_RECORD`` unset or truthy). Stop on duration timer,
or when the caller invokes ``stop_recording`` / next / previous.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from mac_edge.ncm_songs.store import data_dir as ncm_data_dir

log = logging.getLogger("mac_edge.ncm_play_record")

DEFAULT_INPUT = "none:BlackHole 2ch"
DEFAULT_DURATION_MS = 240_000
GRACE_SEC = 1.0
BITRATE = "320k"
STATE_FILE = "ncm_recording.json"
RECORDINGS_DIRNAME = "ncm_recordings"

_SAFE_NAME = re.compile(r"[^\w\u4e00-\u9fff\-]+", re.UNICODE)

_lock = threading.RLock()
_proc: subprocess.Popen[str] | None = None
_timer: threading.Timer | None = None
_out_path: Path | None = None
_playlist: list[dict[str, Any]] = []
_playlist_index: int = -1
_generation: int = 0


def _env_enabled() -> bool:
    raw = (os.environ.get("MAC_EDGE_NCM_RECORD") or "").strip().lower()
    if not raw:
        return True
    return raw not in ("0", "false", "no", "off", "disabled")


def _record_input() -> str:
    return (os.environ.get("MAC_EDGE_NCM_RECORD_INPUT") or "").strip() or DEFAULT_INPUT


def recordings_dir() -> Path:
    path = ncm_data_dir() / RECORDINGS_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def _state_path() -> Path:
    return ncm_data_dir() / STATE_FILE


def _ffmpeg_bin() -> str | None:
    override = (os.environ.get("MAC_EDGE_FFMPEG") or os.environ.get("FFMPEG") or "").strip()
    if override:
        p = Path(override).expanduser()
        if p.is_file():
            return str(p)
    return shutil.which("ffmpeg")


def sanitize_filename(name: str, *, max_len: int = 80) -> str:
    text = str(name or "").strip() or "unknown"
    text = _SAFE_NAME.sub("_", text).strip("._") or "unknown"
    return text[:max_len]


def _artist_label(record: dict[str, Any]) -> str:
    raw = record.get("artists")
    if isinstance(raw, list) and raw:
        first = raw[0]
        if isinstance(first, dict):
            return str(first.get("name") or "").strip()
        return str(first).strip()
    if isinstance(raw, str):
        return raw.strip()
    return ""


def _duration_ms(record: dict[str, Any]) -> int:
    raw = record.get("duration")
    if raw in (None, ""):
        return DEFAULT_DURATION_MS
    try:
        n = int(raw)
    except (TypeError, ValueError):
        try:
            n = int(float(str(raw).strip()))
        except (TypeError, ValueError):
            return DEFAULT_DURATION_MS
    if n <= 0:
        return DEFAULT_DURATION_MS
    # Search hits use milliseconds; tiny values are treated as seconds.
    if n < 1000:
        n *= 1000
    return n


def _output_path(record: dict[str, Any]) -> Path:
    title = sanitize_filename(str(record.get("name") or "").strip() or "unknown")
    artist_raw = _artist_label(record)
    artist = sanitize_filename(artist_raw) if artist_raw else ""
    oid = record.get("originalId")
    oid_part = str(oid).strip() if oid not in (None, "") else str(int(time.time()))
    stem = f"{title}_{artist}_{oid_part}" if artist else f"{title}_{oid_part}"
    return recordings_dir() / f"{stem}.mp3"


def _write_state(payload: dict[str, Any] | None) -> None:
    path = _state_path()
    try:
        if payload is None:
            if path.is_file():
                path.unlink()
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError as e:
        log.warning("ncm record state write failed: %s", e)


def _kill_pid(pid: int) -> None:
    if pid <= 0:
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            return
    deadline = time.time() + 1.5
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        except OSError:
            return
        time.sleep(0.05)
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass


def _cancel_timer_locked() -> None:
    global _timer
    if _timer is not None:
        _timer.cancel()
        _timer = None


def _stop_proc_locked() -> Path | None:
    global _proc, _out_path
    path = _out_path
    proc = _proc
    _proc = None
    _out_path = None
    if proc is None:
        return path
    pid = proc.pid
    if proc.poll() is None:
        _kill_pid(pid)
        try:
            proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            pass
    _write_state(None)
    return path


def _clear_playlist_locked() -> None:
    global _playlist, _playlist_index
    _playlist = []
    _playlist_index = -1


def stop_recording(*, clear_playlist: bool = True) -> Path | None:
    """Stop ffmpeg if running. Optionally clear playlist session."""
    global _generation
    with _lock:
        _cancel_timer_locked()
        path = _stop_proc_locked()
        if clear_playlist:
            _clear_playlist_locked()
        _generation += 1
        if path:
            log.info("ncm record stopped path=%s", path)
        return path


def cleanup_orphans() -> None:
    """Best-effort kill of a previous Edge process's recorder."""
    path = _state_path()
    if not path.is_file():
        return
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(raw, dict):
        return
    try:
        pid = int(raw.get("pid") or 0)
    except (TypeError, ValueError):
        pid = 0
    if pid > 0:
        log.info("ncm record cleanup orphan pid=%s", pid)
        _kill_pid(pid)
    try:
        path.unlink()
    except OSError:
        pass


def _schedule_stop_locked(duration_ms: int, generation: int) -> None:
    global _timer
    _cancel_timer_locked()
    delay = max(1.0, duration_ms / 1000.0 + GRACE_SEC)

    def _fire() -> None:
        with _lock:
            if generation != _generation:
                return
            _cancel_timer_locked()
            _stop_proc_locked()
            if _playlist and 0 <= _playlist_index < len(_playlist) - 1:
                _start_index_locked(_playlist_index + 1)

    _timer = threading.Timer(delay, _fire)
    _timer.daemon = True
    _timer.start()


def _start_index_locked(index: int) -> bool:
    if not _env_enabled():
        return False
    if index < 0 or index >= len(_playlist):
        return False
    return _spawn_locked(_playlist[index], playlist_index=index)


def _spawn_locked(record: dict[str, Any], *, playlist_index: int | None = None) -> bool:
    global _proc, _out_path, _playlist_index, _generation
    _cancel_timer_locked()
    _stop_proc_locked()

    bin_path = _ffmpeg_bin()
    if not bin_path:
        log.warning("ncm record skipped: ffmpeg not found")
        return False

    out = _output_path(record)
    duration_ms = _duration_ms(record)
    seconds = max(1, int(round(duration_ms / 1000.0 + GRACE_SEC)))
    log_path = out.with_suffix(out.suffix + ".log")
    argv = [
        bin_path,
        "-y",
        "-f",
        "avfoundation",
        "-i",
        _record_input(),
        "-c:a",
        "libmp3lame",
        "-b:a",
        BITRATE,
        "-t",
        str(seconds),
        str(out),
    ]
    try:
        log_f = open(log_path, "w", encoding="utf-8")  # noqa: SIM115
    except OSError as e:
        log.warning("ncm record log open failed: %s", e)
        return False
    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=log_f,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            text=True,
        )
    except OSError as e:
        log_f.close()
        log.warning("ncm record spawn failed: %s", e)
        return False
    log_f.close()

    _proc = proc
    _out_path = out
    if playlist_index is not None:
        _playlist_index = playlist_index
    _generation += 1
    gen = _generation
    _write_state(
        {
            "pid": proc.pid,
            "path": str(out),
            "originalId": record.get("originalId"),
            "name": record.get("name"),
            "duration_ms": duration_ms,
            "playlist_index": _playlist_index,
            "started_at": time.time(),
        }
    )
    _schedule_stop_locked(duration_ms, gen)
    log.info(
        "ncm record started pid=%s path=%s duration_ms=%s",
        proc.pid,
        out,
        duration_ms,
    )
    return True


def start_recording(record: dict[str, Any]) -> bool:
    """Stop any session and record a single track."""
    if not isinstance(record, dict):
        return False
    if not _env_enabled():
        return False
    with _lock:
        _clear_playlist_locked()
        return _spawn_locked(record, playlist_index=None)


def start_playlist_session(records: list[dict[str, Any]]) -> bool:
    """Record tracks in order using duration timers (and next/previous hooks)."""
    if not _env_enabled():
        return False
    cleaned = [r for r in records if isinstance(r, dict)]
    if not cleaned:
        return False
    with _lock:
        global _playlist, _playlist_index
        _playlist = cleaned
        _playlist_index = 0
        return _spawn_locked(cleaned[0], playlist_index=0)


def on_next() -> bool:
    """After music.next: finish current file and start the next playlist track."""
    global _generation
    with _lock:
        if not _playlist:
            _cancel_timer_locked()
            path = _stop_proc_locked()
            _generation += 1
            if path:
                log.info("ncm record stopped path=%s", path)
            return False
        nxt = _playlist_index + 1
        if nxt >= len(_playlist):
            _clear_playlist_locked()
            _cancel_timer_locked()
            path = _stop_proc_locked()
            _generation += 1
            if path:
                log.info("ncm record stopped path=%s", path)
            return False
        return _start_index_locked(nxt)


def on_previous() -> bool:
    """After music.previous: finish current file and start the previous track."""
    global _generation
    with _lock:
        if not _playlist:
            _cancel_timer_locked()
            path = _stop_proc_locked()
            _generation += 1
            if path:
                log.info("ncm record stopped path=%s", path)
            return False
        prev = _playlist_index - 1
        if prev < 0:
            _clear_playlist_locked()
            _cancel_timer_locked()
            path = _stop_proc_locked()
            _generation += 1
            if path:
                log.info("ncm record stopped path=%s", path)
            return False
        return _start_index_locked(prev)


try:
    cleanup_orphans()
except Exception as e:  # noqa: BLE001 — best-effort boot hygiene
    log.warning("ncm record orphan cleanup failed: %s", e)
