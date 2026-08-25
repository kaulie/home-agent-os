"""Voice supervisor follows heartbeat-confirmed edge_id (not a stale cache)."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from mac_edge.voice_supervisor import VoiceSupervisor


class _AliveProc:
    def __init__(self) -> None:
        self.terminated = False

    def poll(self) -> int | None:
        return 0 if self.terminated else None

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float | None = None) -> int:
        self.terminated = True
        return 0

    def kill(self) -> None:
        self.terminated = True


class VoiceSupervisorTests(unittest.TestCase):
    def test_restarts_when_edge_id_changes(self) -> None:
        root = Path(tempfile.mkdtemp())
        current = ["edge-old"]
        spawned: list[str] = []
        procs: list[_AliveProc] = []

        def popen(*_args, **kwargs):
            env = kwargs.get("env") or {}
            spawned.append(env.get("MAC_EDGE_EDGE_ID", ""))
            proc = _AliveProc()
            procs.append(proc)
            return proc

        sup = VoiceSupervisor(
            mac_root=root,
            edge_id_path=root / "data" / "edge_id.json",
            brain_url="http://127.0.0.1:9527",
            client_hint="living-room-mac",
            enabled=True,
            get_edge_id=lambda: current[0],
            python_exe="/usr/bin/false",
            restart_sec=1.0,
        )
        with patch("mac_edge.voice_supervisor.subprocess.Popen", side_effect=popen):
            sup.start()
            deadline = time.monotonic() + 3.0
            while len(spawned) < 1 and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertEqual(spawned, ["edge-old"])
            current[0] = "edge-new"
            deadline = time.monotonic() + 3.0
            while len(spawned) < 2 and time.monotonic() < deadline:
                time.sleep(0.05)
            sup.stop()
        self.assertEqual(spawned[:2], ["edge-old", "edge-new"])
        self.assertTrue(procs[0].terminated)

    def test_waits_until_edge_id_ready(self) -> None:
        root = Path(tempfile.mkdtemp())
        current: list[str | None] = [None]
        spawned: list[str] = []

        def popen(*_args, **kwargs):
            env = kwargs.get("env") or {}
            spawned.append(env.get("MAC_EDGE_EDGE_ID", ""))
            return _AliveProc()

        sup = VoiceSupervisor(
            mac_root=root,
            edge_id_path=root / "data" / "edge_id.json",
            brain_url="http://127.0.0.1:9527",
            client_hint="living-room-mac",
            enabled=True,
            get_edge_id=lambda: current[0],
            python_exe="/usr/bin/false",
            restart_sec=1.0,
        )
        with patch("mac_edge.voice_supervisor.subprocess.Popen", side_effect=popen):
            sup.start()
            time.sleep(0.3)
            self.assertEqual(spawned, [])
            current[0] = "edge-ready"
            deadline = time.monotonic() + 3.0
            while not spawned and time.monotonic() < deadline:
                time.sleep(0.05)
            sup.stop()
        self.assertEqual(spawned[:1], ["edge-ready"])


if __name__ == "__main__":
    unittest.main()
