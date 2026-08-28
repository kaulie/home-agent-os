"""Tests for Dev Task closing summaries."""

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
from dev_task_closing import extract_closing_draft, looks_like_markdown_summary  # noqa: E402


class DevTaskClosingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        agent_task_store.reset_store(Path(self.tmp.name) / "agent_tasks.json")
        dev_task._active_task_ids.clear()

    def test_poll_success_stays_open_until_boss_closes(self) -> None:
        with patch("dev_task.ensure_poller_started"), patch(
            "dev_task.bridge.submit_command"
        ) as submit, patch("dev_task.bridge.get_run") as get_run:
            submit.return_value = {"run_id": "run-1", "status": "queued"}
            get_run.return_value = {
                "status": "finished",
                "result": "## 结论\n排查完成\n\n## 派单\n- 无\n",
                "events": [],
            }
            view = dev_task.submit_agent_task("fix bug")
            task_id = int(view["task_id"])
            dev_task.poll_agent_tasks()
        got = dev_task.get_agent_task(task_id)
        assert got is not None
        self.assertEqual(got["status"], "open")
        self.assertFalse(got.get("closing_summary_md"))

        closed = dev_task.request_closing_summary(task_id, outcome="succeeded")
        assert closed is not None
        # Status machine advances immediately; summary is attached, not a gate.
        self.assertEqual(closed["status"], "succeeded")
        self.assertTrue(looks_like_markdown_summary(closed.get("closing_summary_md") or ""))
        self.assertIn("排查完成", closed.get("closing_summary_md") or "")

    def test_early_close_from_open(self) -> None:
        store = agent_task_store.get_store()
        task = store.create("investigate")
        store.update(task.task_id, status="open", result="## 结论\nstill broken\n", target_handle="controller")
        closed = dev_task.request_closing_summary(
            task.task_id, outcome="cancelled", note="先关掉"
        )
        assert closed is not None
        self.assertEqual(closed["status"], "cancelled")
        self.assertIn("先关掉", closed.get("closing_summary_md") or "")

    def test_cancel_running_goes_terminal(self) -> None:
        with patch("dev_task.ensure_poller_started"), patch(
            "dev_task.bridge.submit_command"
        ) as submit, patch("dev_task.bridge.get_run") as get_run:
            submit.return_value = {"run_id": "run-cancel", "status": "running"}
            view = dev_task.submit_agent_task("long task")
            task_id = int(view["task_id"])
            get_run.return_value = {"status": "cancelled", "events": []}
            dev_task.poll_agent_tasks()
        got = dev_task.get_agent_task(task_id)
        assert got is not None
        self.assertEqual(got["status"], "cancelled")
        self.assertTrue(got.get("closing_summary_md"))

    def test_extract_closing_draft_from_events(self) -> None:
        draft = extract_closing_draft(
            {
                "events": [
                    {"type": "assistant", "text": "## 结论\n失败\n\n## 原因\ntimeout"},
                ]
            },
            outcome="failed",
            task_text="do thing",
        )
        self.assertIn("失败", draft)


if __name__ == "__main__":
    unittest.main()
