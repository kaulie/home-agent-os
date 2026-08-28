"""Follow-up ## 派单 parsing and status_log behavior."""

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
from dev_task_followups import parse_followup_dispatches  # noqa: E402


class FollowupParseTests(unittest.TestCase):
    def test_parse_dispatch_lines(self) -> None:
        md = """## 结论
ok

## 派单
- @capability: 查 point_to_character 超时
- @runtime：核对 120s timeout
- @controller: should skip
- 无
"""
        items = parse_followup_dispatches(md)
        handles = [i["handle"] for i in items]
        self.assertEqual(handles, ["capability", "runtime"])
        self.assertIn("超时", items[0]["text"])

    def test_parse_none(self) -> None:
        self.assertEqual(
            parse_followup_dispatches("## 结论\nx\n\n## 派单\n- 无\n"),
            [],
        )


class StatusLogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = agent_task_store.reset_store(Path(self.tmp.name) / "agent_tasks.json")
        dev_task._active_task_ids.clear()

    def test_append_status_after_update_still_logs(self) -> None:
        task = self.store.create("hello")
        self.store.update(task.task_id, status="running")
        self.store.append_status(task.task_id, "running")
        self.store.update(task.task_id, status="summary_pending")
        self.store.append_status(task.task_id, "summary_pending", handle="controller")
        got = self.store.get(task.task_id)
        assert got is not None
        statuses = [row.get("status") for row in got.status_log]
        self.assertIn("running", statuses)
        self.assertIn("summary_pending", statuses)
        self.assertEqual(got.status, "summary_pending")

    def test_poll_records_running_and_open(self) -> None:
        calls: list[str] = []

        def fake_get_run(_run_id: str):
            if len(calls) == 0:
                calls.append("running")
                return {
                    "status": "running",
                    "events": [{"type": "tool", "name": "Shell", "text": "Shell ls"}],
                }
            calls.append("finished")
            return {
                "status": "finished",
                "result": "## 结论\nok\n\n## 派单\n- 无\n",
                "events": [
                    {"type": "tool", "name": "Shell", "text": "Shell ls"},
                    {"type": "assistant", "text": "## 结论\nok\n\n## 派单\n- 无\n"},
                ],
            }

        with patch("dev_task.ensure_poller_started"), patch(
            "dev_task.bridge.submit_command",
            return_value={"run_id": "run-1", "status": "queued"},
        ), patch("dev_task.bridge.get_run", side_effect=fake_get_run), patch(
            "dev_task.bridge.bridge_enabled", return_value=True
        ):
            view = dev_task.submit_agent_task("fix", target_handle="controller")
            task_id = int(view["task_id"])
            self.assertEqual(list(dev_task._active_task_ids), [task_id])
            dev_task.poll_agent_tasks()
            mid = self.store.get(task_id)
            assert mid is not None
            self.assertEqual(calls, ["running"], msg=f"status_log={mid.status_log}")
            self.assertEqual(mid.status, "running")
            dev_task.poll_agent_tasks()
        got = self.store.get(task_id)
        assert got is not None
        statuses = [row.get("status") for row in got.status_log]
        self.assertIn("running", statuses)
        self.assertIn("open", statuses)
        self.assertTrue(any(e.get("type") == "tool" for e in got.events))
        self.assertEqual(calls, ["running", "finished"])

    def test_auto_dispatch_followups(self) -> None:
        created: list[tuple] = []

        def fake_submit(text, **kwargs):
            created.append((text, kwargs.get("target_handle")))
            child = self.store.create(
                text,
                parent_task_id=kwargs.get("parent_task_id"),
                thread_id=kwargs.get("thread_id"),
            )
            self.store.update(child.task_id, target_handle=kwargs.get("target_handle") or "")
            return {"task_id": child.task_id, "status": "queued"}

        parent = self.store.create("investigate", category="bug_fix")
        self.store.update(parent.task_id, target_handle="controller", thread_id=parent.task_id)
        with patch("dev_task.submit_agent_task", side_effect=fake_submit):
            dev_task._complete_agent_turn(
                parent.task_id,
                succeeded=True,
                answer_text=(
                    "## 结论\n需要 capability\n\n"
                    "## 派单\n"
                    "- @capability: 修 reading.point_to_character 超时\n"
                    "- @sre: 上 IAtuhLSy 拉日志\n"
                ),
                bridge_status="finished",
            )
        self.assertEqual(
            created,
            [
                ("修 reading.point_to_character 超时", "capability"),
                ("上 IAtuhLSy 拉日志", "sre"),
            ],
        )
        parent_got = self.store.get(parent.task_id)
        assert parent_got is not None
        dispatch_msgs = [
            row.get("msg")
            for row in parent_got.status_log
            if row.get("kind") == "dispatch"
        ]
        self.assertEqual(len(dispatch_msgs), 2)


if __name__ == "__main__":
    unittest.main()
