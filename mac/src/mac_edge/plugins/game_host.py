#!/usr/bin/env python3
"""Mac Edge: keep coin-catcher LAN server alive and expose game_url."""

from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
import threading
from pathlib import Path

log = logging.getLogger("mac_edge.game_host")

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SERVE = _REPO_ROOT / "games" / "coin-catcher" / "serve.py"
_PORT = int((os.environ.get("COIN_CATCHER_GAME_PORT") or "8102").strip() or "8102")
_proc: subprocess.Popen | None = None
_lock = threading.Lock()


def lan_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.168.3.1", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def game_url() -> str:
    return f"http://{lan_ip()}:{_PORT}/"


def ensure_running() -> str:
    """Start serve.py if not already listening; return LAN game URL."""
    global _proc
    if _probe_port():
        return game_url()
    with _lock:
        if _probe_port():
            return game_url()
        if _proc is not None and _proc.poll() is None:
            return game_url()
        if not _SERVE.is_file():
            raise RuntimeError(f"game serve.py missing: {_SERVE}")
        log.info("starting coin-catcher serve.py port=%s", _PORT)
        _proc = subprocess.Popen(
            [sys.executable, str(_SERVE)],
            cwd=str(_SERVE.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    for _ in range(30):
        if _probe_port():
            return game_url()
        import time

        time.sleep(0.2)
    raise RuntimeError(f"coin-catcher serve did not bind :{_PORT}")


def _probe_port() -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.4)
    try:
        sock.connect(("127.0.0.1", _PORT))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def stop() -> None:
    global _proc
    with _lock:
        if _proc is not None and _proc.poll() is None:
            _proc.terminate()
            try:
                _proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                _proc.kill()
        _proc = None
