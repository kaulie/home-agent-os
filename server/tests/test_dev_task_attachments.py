"""Tests for Dev Task attachment helpers."""

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

import agent_task_store  # noqa: E402
import dev_task  # noqa: E402
import dev_task_attachments as dta  # noqa: E402


class DevTaskAttachmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        agent_task_store.reset_store(Path(self.tmp.name) / "agent_tasks.json")
        dev_task._active_task_ids.clear()

    def test_normalize_and_prompt(self) -> None:
        rows = dta.normalize_dev_task_attachments(
            [
                {
                    "asset_id": "asset_abc",
                    "kind": "image",
                    "mime_type": "image/jpeg",
                    "filename": "shot.jpg",
                }
            ]
        )
        self.assertEqual(rows[0]["asset_id"], "asset_abc")
        prompt = dta.build_dev_task_agent_text(
            "请分析截图",
            rows,
            local_paths={"asset_abc": "/tmp/shot.jpg"},
        )
        self.assertIn("请分析截图", prompt)
        self.assertIn("local_path=/tmp/shot.jpg", prompt)

    def test_submit_with_attachments_only(self) -> None:
        with patch("dev_task.bridge.submit_command") as submit:
            submit.return_value = {"run_id": "run-att", "status": "queued"}
            view = dev_task.submit_agent_task(
                "",
                attachments=[{"asset_id": "asset_only", "kind": "image"}],
            )
        self.assertEqual(view["attachments"][0]["asset_id"], "asset_only")
        submit.assert_called_once()
        args, kwargs = submit.call_args
        self.assertIn("asset_only", args[0])
        self.assertEqual(kwargs.get("task_id"), view["task_id"])

    def test_store_persists_attachments(self) -> None:
        store = agent_task_store.get_store()
        task = store.create(
            "with files",
            attachments=[{"asset_id": "asset_x", "kind": "file"}],
        )
        got = store.get(task.task_id)
        assert got is not None
        self.assertEqual(got.attachments[0]["asset_id"], "asset_x")


if __name__ == "__main__":
    unittest.main()
