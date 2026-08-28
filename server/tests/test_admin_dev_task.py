"""Admin dev_task API for HomeAgent Admin mobile controller."""

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
os.environ["BRAIN_ENABLE_DEV_TASK_POLLER"] = "1"

try:
    import flask  # noqa: F401
except ImportError:  # pragma: no cover
    flask = None  # type: ignore

if flask is not None:
    import agent_task_store  # noqa: E402
    import db as brain_db  # noqa: E402
    import home_brain as hb  # noqa: E402
else:
    agent_task_store = None  # type: ignore
    brain_db = None  # type: ignore
    hb = None  # type: ignore


@unittest.skipUnless(flask is not None, "flask not installed in this interpreter")
class AdminDevTaskTests(unittest.TestCase):
    def setUp(self) -> None:
        assert hb is not None
        assert brain_db is not None
        assert agent_task_store is not None
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "brain.sqlite3"
        brain_db.reset(path=self.path)
        brain_db.init_db()
        agent_task_store.reset_store(Path(self.tmp.name) / "agent_tasks.json")
        hb._REGISTERED_edges = brain_db.registration_ids()

    def test_post_admin_dev_task_does_not_create_intent(self) -> None:
        assert hb is not None
        client = hb.app.test_client()
        with patch("dev_task.bridge.submit_command") as submit:
            submit.return_value = {"run_id": "run-admin-1", "status": "queued"}
            resp = client.post(
                "/api/v1/admin/dev_task",
                json={"text": "列出 server 目录"},
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body.get("ok"))
        self.assertEqual(body.get("task_kind"), "dev_task")
        self.assertEqual(body["dev_task"]["bridge_run_id"], "run-admin-1")
        task_id = int(body["task_id"])
        self.assertEqual(body.get("intent_id"), task_id)
        self.assertFalse(hb.get_intent(task_id))

    def test_list_admin_dev_tasks_only_agent_store(self) -> None:
        assert hb is not None
        client = hb.app.test_client()
        with patch("dev_task.bridge.submit_command") as submit:
            submit.return_value = {"run_id": "run-a", "status": "queued"}
            client.post("/api/v1/admin/dev_task", json={"text": "dev one"})
        hb.new_intent({"status": "intent_received", "text": "normal", "source": "text"})
        resp = client.get("/api/v1/admin/dev_tasks?limit=10")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body.get("ok"))
        tasks = body.get("tasks") or []
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].get("text"), "dev one")


if __name__ == "__main__":
    unittest.main()
