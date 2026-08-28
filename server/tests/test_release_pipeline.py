"""Release pipeline unit tests."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SERVER = Path(__file__).resolve().parents[1]
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

import dev_console_db  # noqa: E402
import release_pipeline as rp  # noqa: E402


class ReleasePipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        dev_console_db.reset(path=Path(self.tmp.name) / "dev_console.sqlite3")

    def test_parse_release_body(self) -> None:
        ev = rp.parse_release_body(
            "@controller [release] stage=committed sha=abc1234 scope=server summary=fix planner",
            from_handle="brain",
            msg_id=9,
        )
        assert ev is not None
        self.assertEqual(ev.stage, "committed")
        self.assertEqual(ev.sha, "abc1234")
        self.assertEqual(ev.scope, "server")
        self.assertIn("fix planner", ev.summary)

    def test_apply_committed_then_tested_awaits_approval(self) -> None:
        rp.apply_event(
            rp.ReleaseEvent(
                stage="committed",
                sha="deadbeef0123456789",
                scope="ui",
                summary="button fix",
                by_handle="ui",
            )
        )
        view = rp.apply_event(
            rp.ReleaseEvent(
                stage="tested",
                sha="deadbee",
                result="pass",
                by_handle="quality",
            )
        )
        self.assertEqual(view["status"], "awaiting_approval")
        self.assertTrue(view["can_approve"])
        nodes = {p["node"]: p["done"] for p in view["pipeline"]}
        self.assertTrue(nodes["committed"])
        self.assertTrue(nodes["tested"])
        self.assertFalse(nodes["approved"])

    def test_approve_wakes_deploy(self) -> None:
        view = rp.apply_event(
            rp.ReleaseEvent(stage="committed", sha="cafe0001", summary="x", by_handle="brain")
        )
        rp.apply_event(
            rp.ReleaseEvent(stage="tested", sha="cafe0001", result="pass", by_handle="quality")
        )
        rid = int(view["release_id"])
        with patch("release_pipeline.wake_fleet_agent") as wake:
            wake.return_value = {"ok": True, "run_id": "run-1"}
            with patch("release_pipeline.agent_chat.send_boss_message"):
                out = rp.approve_release(rid, by="boss")
        self.assertTrue(out["ok"])
        self.assertEqual(out["release"]["status"], "deploying")
        wake.assert_called_once()
        self.assertIn("cafe0001", str(wake.call_args))

    def test_list_releases(self) -> None:
        rp.apply_event(
            rp.ReleaseEvent(stage="committed", sha="1111111", summary="a", by_handle="ui")
        )
        with patch("release_pipeline.sync_from_chat", return_value={"ok": True, "ingested": 0}):
            listed = rp.list_releases(limit=10)
        self.assertTrue(listed["ok"])
        self.assertGreaterEqual(listed["counts"]["total"], 1)


if __name__ == "__main__":
    unittest.main()
