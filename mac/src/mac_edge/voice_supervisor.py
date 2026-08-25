"""Supervise mac_voice as a child process of mac_edge (shared edge_id)."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

log = logging.getLogger("mac_edge.voice_supervisor")


class VoiceSupervisor:
    """Start/stop `python -m mac_voice --live --post-intent` under Mac Runtime."""

    def __init__(
        self,
        *,
        mac_root: Path,
        edge_id_path: Path,
        brain_url: str,
        client_hint: str,
        enabled: bool,
        get_edge_id: Callable[[], str | None],
        python_exe: str | None = None,
        restart_sec: float = 5.0,
    ) -> None:
        self._mac_root = mac_root
        self._edge_id_path = edge_id_path
        self._brain_url = brain_url.rstrip("/")
        self._client_hint = client_hint
        self._enabled = enabled
        self._get_edge_id = get_edge_id
        venv_py = mac_root / ".venv" / "bin" / "python"
        if python_exe:
            self._python = python_exe
        elif venv_py.is_file():
            self._python = str(venv_py)
        else:
            self._python = sys.executable
        self._restart_sec = max(1.0, float(restart_sec))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._proc: subprocess.Popen[bytes] | None = None

    def start(self) -> None:
        if not self._enabled:
            log.info("voice supervisor disabled")
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="mac-edge-voice", daemon=True
        )
        self._thread.start()
        log.info("voice supervisor started")

    def stop(self) -> None:
        self._stop.set()
        self._kill_child()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=3.0)
        self._thread = None
        log.info("voice supervisor stopped")

    def _kill_child(self) -> None:
        proc = self._proc
        self._proc = None
        if not proc or proc.poll() is not None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=5.0)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def _resolved_edge_id(self) -> str:
        return (self._get_edge_id() or "").strip()

    def _loop(self) -> None:
        while not self._stop.is_set():
            eid = self._resolved_edge_id()
            if not eid:
                log.info("voice supervisor waiting for registered edge_id…")
                self._stop.wait(2.0)
                continue
            env = os.environ.copy()
            env["PYTHONPATH"] = str(self._mac_root / "src")
            env["MAC_EDGE_EDGE_ID"] = eid
            env["MAC_VOICE_BRAIN_URL"] = self._brain_url
            env["MAC_EDGE_BRAIN_URL"] = self._brain_url
            env["MAC_VOICE_CLIENT_HINT"] = self._client_hint
            env["MAC_EDGE_CLIENT_HINT"] = self._client_hint
            # Prefer Mac Runtime data dir for shared edge_id.json
            env.setdefault("MAC_EDGE_DATA_DIR", str(self._mac_root / "data"))
            log_path = self._mac_root / "logs" / "mac_voice.supervised.out.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            restart_delay = self._restart_sec
            try:
                with log_path.open("a", encoding="utf-8") as logf:
                    log.info(
                        "spawning mac_voice edge_id=%s python=%s", eid, self._python
                    )
                    self._proc = subprocess.Popen(
                        [
                            self._python,
                            "-m",
                            "mac_voice",
                            "--live",
                            "--post-intent",
                        ],
                        cwd=str(self._mac_root),
                        env=env,
                        stdout=logf,
                        stderr=subprocess.STDOUT,
                    )
                    spawned = eid
                    while not self._stop.is_set():
                        code = self._proc.poll()
                        if code is not None:
                            log.warning("mac_voice exited code=%s; restart soon", code)
                            break
                        current = self._resolved_edge_id()
                        if current != spawned:
                            log.info(
                                "edge_id changed %s → %s; restart mac_voice",
                                spawned,
                                current or "(none)",
                            )
                            restart_delay = 0.0
                            break
                        self._stop.wait(1.0)
            except Exception:
                log.exception("voice supervisor spawn failed")
            self._kill_child()
            if self._stop.is_set():
                break
            if restart_delay:
                self._stop.wait(restart_delay)
