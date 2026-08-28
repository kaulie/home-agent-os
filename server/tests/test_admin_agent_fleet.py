"""Admin agent_fleet API tests."""

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

os.environ["BRAIN_SKIP_LLM_WORKER"] = "1"

try:
    import flask  # noqa: F401
except ImportError:  # pragma: no cover
    flask = None  # type: ignore

if flask is not None:
    import db as brain_db  # noqa: E402
    import home_brain as hb  # noqa: E402
else:
    brain_db = None  # type: ignore
    hb = None  # type: ignore


@unittest.skipUnless(flask is not None, "flask not installed in this interpreter")
class AdminAgentFleetTests(unittest.TestCase):
    def setUp(self) -> None:
        assert hb is not None
        assert brain_db is not None
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        brain_db.reset(path=Path(self.tmp.name) / "brain.sqlite3")
        brain_db.init_db()
        hb._REGISTERED_edges = brain_db.registration_ids()

    def test_get_agent_fleet(self) -> None:
        assert hb is not None
        client = hb.app.test_client()
        with patch("agent_fleet.bridge.bridge_status") as status, patch(
            "agent_fleet.bridge.list_agents"
        ) as agents, patch("agent_fleet.bridge.list_runs") as runs:
            status.return_value = {"queue_depth": 0, "model": "composer-2.5", "backend": "cli"}
            agents.return_value = {
                "agents": [
                    {"handle": "brain", "agent_id": "sess-1", "running_run_id": None},
                ]
            }
            runs.return_value = {"runs": [{"run_id": "r1", "status": "finished", "target_handle": "brain"}]}
            resp = client.get("/api/v1/admin/agent_fleet")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body.get("ok"))
        self.assertEqual(len(body.get("agents") or []), 1)
        self.assertEqual(body["agents"][0]["handle"], "brain")
        self.assertEqual(len(body.get("runs") or []), 1)

    def test_wake_agent_fleet(self) -> None:
        assert hb is not None
        client = hb.app.test_client()
        with patch("agent_fleet.bridge.wake_agent") as wake:
            wake.return_value = {"handle": "runtime", "run_id": "abc", "status": "queued"}
            resp = client.post(
                "/api/v1/admin/agent_fleet/runtime/wake",
                json={"text": "fix hydrate"},
            )
        self.assertEqual(resp.status_code, 202)
        body = resp.get_json()
        self.assertTrue(body.get("ok"))
        self.assertEqual(body.get("run_id"), "abc")
        wake.assert_called_once()

    def test_post_dev_task_with_target_handle(self) -> None:
        assert hb is not None
        import agent_task_store  # noqa: E402

        agent_task_store.reset_store(Path(self.tmp.name) / "agent_tasks.json")
        client = hb.app.test_client()
        with patch("dev_task.bridge.submit_command") as submit:
            submit.return_value = {
                "run_id": "run-ui-1",
                "status": "queued",
                "target_handle": "ui",
            }
            resp = client.post(
                "/api/v1/admin/dev_task",
                json={"text": "fix mic button", "target_handle": "ui"},
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body.get("ok"))
        self.assertEqual(body["dev_task"]["target_handle"], "ui")
        submit.assert_called_once()
        kwargs = submit.call_args.kwargs
        self.assertEqual(kwargs.get("target_handle"), "ui")


if __name__ == "__main__":
    unittest.main()
