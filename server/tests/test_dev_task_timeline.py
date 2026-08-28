"""Dev Task activity timeline."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

os.environ["BRAIN_SKIP_LLM_WORKER"] = "1"

import agent_task_store  # noqa: E402
import dev_task_timeline  # noqa: E402


class DevTaskTimelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = agent_task_store.reset_store(Path(self.tmp.name) / "agent_tasks.json")

    def test_build_thread_timeline_with_roles_and_status_flow(self) -> None:
        root = self.store.create("分析 intent 失败", category="bug_fix")
        self.store.update(
            root.task_id,
            target_handle="brain",
            status="running",
            events=[
                {"type": "assistant", "text": "我先查日志", "ts": root.created_at + 2},
                {"type": "assistant", "text": "根因是 hydrate 门", "ts": root.created_at + 5},
            ],
        )
        self.store.append_status(
            root.task_id,
            "running",
            handle="brain",
            kind="dispatch",
        )
        self.store.append_status(root.task_id, "summary_pending")
        self.store.update(
            root.task_id,
            status="succeeded",
            closing_summary_md="## 结论\n已修复",
        )
        self.store.append_status(
            root.task_id,
            "succeeded",
            actor="boss",
            kind="user_confirm",
            msg="用户确认结项",
        )

        follow = self.store.create(
            "再补一条测试",
            parent_task_id=root.task_id,
        )
        self.store.update(follow.task_id, target_handle="runtime", status="queued")
        self.store.append_status(follow.task_id, "queued", handle="runtime", kind="dispatch")

        messages, _ = self.store.list_tasks(thread_id=root.task_id, limit=10)
        timeline = dev_task_timeline.build_thread_activity_timeline(messages)

        self.assertEqual(timeline["thread_id"], root.task_id)
        handles = {row["handle"] for row in timeline["participants"]}
        self.assertIn("boss", handles)
        self.assertIn("brain", handles)
        self.assertIn("runtime", handles)

        kinds = [row["kind"] for row in timeline["entries"]]
        self.assertIn("user_input", kinds)
        self.assertIn("dispatch", kinds)
        self.assertIn("agent_output", kinds)
        self.assertIn("user_confirm", kinds)

        self.assertTrue(timeline["status_flow"])
        statuses = [row["status"] for row in timeline["status_flow"]]
        self.assertIn("queued", statuses)
        self.assertIn("summary_pending", statuses)
        self.assertIn("succeeded", statuses)

        brain = next(row for row in timeline["role_summaries"] if row["handle"] == "brain")
        self.assertGreater(brain["output_count"], 0)
        self.assertIn("hydrate", brain["work_preview"])


if __name__ == "__main__":
    unittest.main()
