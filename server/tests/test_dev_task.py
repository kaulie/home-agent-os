"""Agent task store and bridge polling."""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

SERVER = Path(__file__).resolve().parents[1]
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

os.environ["BRAIN_SKIP_LLM_WORKER"] = "1"
os.environ["BRAIN_ENABLE_DEV_TASK_POLLER"] = "1"

import agent_task_store  # noqa: E402
import db as brain_db  # noqa: E402
import dev_task  # noqa: E402


class AgentTaskStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = agent_task_store.reset_store(
            Path(self.tmp.name) / "agent_tasks.json"
        )
        brain_db.reset(path=Path(self.tmp.name) / "brain.sqlite3")
        brain_db.init_db()
        dev_task._active_task_ids.clear()

    def tearDown(self) -> None:
        brain_db.reset()

    def test_create_and_list(self) -> None:
        one = self.store.create("hello")
        two = self.store.create("world")
        rows, exhausted = self.store.list_tasks(limit=10)
        self.assertEqual(len(rows), 2)
        self.assertTrue(exhausted)
        self.assertEqual(rows[0].task_id, two.task_id)

    def test_submit_and_poll_success(self) -> None:
        with patch("dev_task.bridge.submit_command") as submit, patch(
            "dev_task.bridge.get_run"
        ) as get_run:
            submit.return_value = {"run_id": "run-1", "status": "queued"}
            get_run.return_value = {
                "status": "finished",
                "result": "done",
                "events": [{"type": "assistant", "text": "done"}],
            }
            view = dev_task.submit_agent_task("fix bug")
            task_id = int(view["task_id"])
            self.assertEqual(view["status"], "queued")
            dev_task.poll_agent_tasks()
        got = dev_task.get_agent_task(task_id)
        assert got is not None
        self.assertEqual(got["status"], "succeeded")
        self.assertEqual(got["result_text"], "done")

    def test_usage_stats(self) -> None:
        self.store.create("one")
        task = self.store.create("two")
        self.store.update(
            task.task_id,
            token_usage={
                "input_tokens": 100,
                "output_tokens": 20,
                "total_tokens": 120,
            },
        )
        stats = dev_task.get_agent_task_usage_stats(days=7)
        self.assertEqual(stats["period"]["task_count"], 1)
        self.assertEqual(stats["period"]["total_tokens"], 120)
        self.assertEqual(stats["period_key"], "days_7")

    def test_usage_stats_by_period(self) -> None:
        task = self.store.create("month task")
        self.store.update(
            task.task_id,
            token_usage={
                "input_tokens": 50,
                "output_tokens": 10,
                "total_tokens": 60,
            },
        )
        stats = dev_task.get_agent_task_usage_stats(period="month")
        self.assertEqual(stats["period_key"], "month")
        self.assertEqual(stats["period_label"], "本月")
        self.assertEqual(stats["period"]["task_count"], 1)
        self.assertEqual(len(stats["by_time"]), 1)
        self.assertEqual(stats["by_time"][0]["total_tokens"], 60)

    def test_usage_stats_cloud_calls(self) -> None:
        now = time.time()
        brain_db.record_cloud_call("ark.planner", 1, "brain", occurred_at=now)
        brain_db.record_cloud_call("ark.planner", 0, "brain", occurred_at=now)
        brain_db.record_cloud_call(
            "ark.vision", 1, "brain", occurred_at=now - 86400 * 30
        )

        stats = dev_task.get_agent_task_usage_stats(period="day")
        cloud = stats["cloud_calls"]
        period_by_id = {row["service_id"]: row for row in cloud["period"]}
        self.assertEqual(period_by_id["ark.planner"]["count"], 2)
        self.assertEqual(period_by_id["ark.planner"]["ok"], 1)
        self.assertEqual(period_by_id["ark.planner"]["fail"], 1)
        self.assertEqual(period_by_id["ark.planner"]["label"], "方舟规划")
        self.assertEqual(period_by_id["ark.vision"]["count"], 0)

        all_by_id = {row["service_id"]: row for row in cloud["all_time"]}
        self.assertEqual(all_by_id["ark.vision"]["count"], 1)
        self.assertIn("ark.query", period_by_id)
        self.assertEqual(period_by_id["ark.query"]["count"], 0)

    def test_thread_continue_and_messages(self) -> None:
        root = self.store.create("first message")
        child = self.store.create(
            "follow up",
            parent_task_id=root.task_id,
            thread_id=root.thread_id,
        )
        self.assertEqual(child.thread_id, root.thread_id)
        self.assertEqual(child.parent_task_id, root.task_id)

        roots, _ = self.store.list_tasks(limit=10, roots_only=True)
        self.assertEqual(len(roots), 1)
        self.assertEqual(roots[0].task_id, root.task_id)

        thread_rows, _ = self.store.list_tasks(limit=10, thread_id=root.thread_id)
        self.assertEqual(len(thread_rows), 2)

        view = dev_task.get_agent_task(root.task_id)
        assert view is not None
        msgs = view.get("thread_messages") or []
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0]["text"], "first message")
        self.assertEqual(msgs[1]["text"], "follow up")

        with patch("dev_task.bridge.submit_command") as submit:
            submit.return_value = {"run_id": "run-2", "status": "queued"}
            continued = dev_task.submit_agent_task("third", parent_task_id=child.task_id)
        self.assertEqual(continued["thread_id"], root.thread_id)
        self.assertEqual(continued["parent_task_id"], child.task_id)
        self.assertEqual(continued["category"], "other")

    def test_category_filter_and_update(self) -> None:
        bug = self.store.create("fix crash", category="bug_fix")
        chat = self.store.create("hello", category="chat")
        roots, _ = self.store.list_tasks(limit=10, roots_only=True, category="bug_fix")
        self.assertEqual(len(roots), 1)
        self.assertEqual(roots[0].task_id, bug.task_id)

        updated = self.store.set_thread_category(chat.task_id, "tech_discuss")
        assert updated is not None
        self.assertEqual(updated.category, "tech_discuss")

        view = dev_task.get_agent_task(bug.task_id)
        assert view is not None
        self.assertEqual(view["category"], "bug_fix")
        self.assertEqual(view["category_label"], "Issue 跟进")

    def test_reconcile_active_tasks(self) -> None:
        self.store.create("done task")
        task = self.store.create("still running")
        self.store.update(task.task_id, status="running", bridge_run_id="run-x")
        dev_task._active_task_ids.clear()
        dev_task._reconcile_active_tasks()
        self.assertIn(task.task_id, dev_task._active_task_ids)

    def test_cancel_agent_task(self) -> None:
        with patch("dev_task.bridge.submit_command") as submit, patch(
            "dev_task.bridge.cancel_run"
        ) as cancel_run:
            submit.return_value = {"run_id": "run-cancel", "status": "running"}
            view = dev_task.submit_agent_task("long task")
            task_id = int(view["task_id"])
            cancel_run.return_value = {
                "run_id": "run-cancel",
                "status": "running",
                "cancelled": True,
                "cancelling": True,
            }
            cancelling = dev_task.cancel_agent_task(task_id)
            assert cancelling is not None
            self.assertEqual(cancelling["dev_task"]["bridge_status"], "cancelling")

            cancel_run.return_value = {
                "run_id": "run-cancel",
                "status": "cancelled",
                "cancelled": True,
            }
            with patch("dev_task.bridge.get_run") as get_run:
                get_run.return_value = {"status": "cancelled", "events": []}
                dev_task.poll_agent_tasks()
            got = dev_task.get_agent_task(task_id)
            assert got is not None
            self.assertEqual(got["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
