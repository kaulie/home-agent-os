"""Dev Console DB tests."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]
REPO = SERVER.parent
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import agent_task_store
import debug_issue_store
import dev_console_db
import dev_task_attachments
from chat import db as chat_db


class DevConsoleDbTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "dev_console.sqlite3"
        agent_task_store.reset_store(self.db_path)
        debug_issue_store.reset_store(self.db_path)

    def tearDown(self) -> None:
        dev_console_db.reset()
        agent_task_store.reset_store()
        debug_issue_store.reset_store()
        self.tmp.cleanup()

    def test_dev_task_roundtrip(self) -> None:
        store = agent_task_store.get_store()
        task = store.create("ship feature", category="feature")
        got = store.get(task.task_id)
        self.assertIsNotNone(got)
        assert got is not None
        self.assertEqual(got.text, "ship feature")
        self.assertEqual(got.category, "feature")

        agent_task_store.reload_store()
        reloaded = agent_task_store.get_store().get(task.task_id)
        self.assertIsNotNone(reloaded)
        assert reloaded is not None
        self.assertEqual(reloaded.text, "ship feature")

    def test_debug_issue_roundtrip(self) -> None:
        store = debug_issue_store.get_store()
        issue = store.create(intent_id=42, user_summary="button broken")
        got = store.get(issue.issue_id)
        self.assertIsNotNone(got)
        assert got is not None
        self.assertEqual(got.intent_id, 42)

        debug_issue_store.reload_store()
        reloaded = debug_issue_store.get_store().get(issue.issue_id)
        self.assertIsNotNone(reloaded)

    def test_dev_console_assets_and_grants(self) -> None:
        dev_console_db.put_asset(
            {
                "asset_id": "asset_test123",
                "type": "image",
                "mime_type": "image/png",
                "status": "ready",
                "producer_capability": "dev_task.attachment",
                "storage": {"backend": "local_upload", "key": "x.png", "saved_as": "x.png"},
            }
        )
        dev_task_attachments.grant_attachments_for_task(
            7,
            [{"asset_id": "asset_test123", "kind": "image"}],
        )
        self.assertTrue(dev_console_db.has_asset_grant("asset_test123", "dev_task:7"))
        self.assertIsNotNone(dev_console_db.get_asset("asset_test123"))

    def test_chat_tables_in_same_db(self) -> None:
        chat_db.reset(path=self.db_path)
        chat_db.push_message(from_handle="boss", body="@brain hello from unified db")
        rows = chat_db.list_messages()
        self.assertEqual(len(rows), 1)
        self.assertIn("hello", rows[0]["body"])
        dev_console_db.reset(path=self.db_path)
        with dev_console_db.locked():
            conn = dev_console_db._connect()
            task_n = conn.execute("SELECT COUNT(*) FROM dev_tasks").fetchone()[0]
            msg_n = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        self.assertEqual(int(task_n), 0)
        self.assertEqual(int(msg_n), 1)


if __name__ == "__main__":
    unittest.main()
