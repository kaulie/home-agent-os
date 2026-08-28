"""Agent Debug Gateway API tests."""

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
    import debug_gateway  # noqa: E402
    import debug_issue_store  # noqa: E402
    import db as brain_db  # noqa: E402
    import home_brain as hb  # noqa: E402
else:
    agent_task_store = None  # type: ignore
    debug_issue_store = None  # type: ignore
    brain_db = None  # type: ignore
    hb = None  # type: ignore


@unittest.skipUnless(flask is not None, "flask not installed in this interpreter")
class DebugGatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        assert hb is not None
        assert brain_db is not None
        assert agent_task_store is not None
        assert debug_issue_store is not None
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "brain.sqlite3"
        brain_db.reset(path=self.path)
        brain_db.init_db()
        agent_task_store.reset_store(Path(self.tmp.name) / "agent_tasks.json")
        debug_issue_store.reset_store(Path(self.tmp.name) / "debug_issues.json")
        hb._REGISTERED_edges = brain_db.registration_ids()

    def _seed_intent(self, *, edge_id: str = "living-room-android") -> int:
        assert hb is not None
        intent_id = hb.new_intent(
            {
                "status": "failed",
                "text": "用GoPro拍张照片",
                "source": "text",
                "edge_id": edge_id,
                "msg": "家里有多台同能力设备",
            }
        )
        return int(intent_id)

    def test_post_debug_report_creates_issue_and_dev_task(self) -> None:
        assert hb is not None
        intent_id = self._seed_intent()
        client = hb.app.test_client()
        with patch("dev_task.bridge.submit_command") as submit:
            submit.return_value = {"run_id": "run-debug-1", "status": "queued"}
            resp = client.post(
                "/api/v1/debug/report",
                json={
                    "intent_id": intent_id,
                    "participant_id": "living-room-android",
                    "client_snapshot": {"journey": "test logistics"},
                },
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body.get("ok"))
        self.assertEqual(body.get("message"), "已提交反馈，正在分析。")
        self.assertEqual(body.get("intent_id"), intent_id)
        issue_id = int(body["issue_id"])
        detail = client.get(f"/api/v1/admin/debug/issue/{issue_id}")
        self.assertEqual(detail.status_code, 200)
        payload = detail.get_json()
        issue = payload.get("issue") if isinstance(payload.get("issue"), dict) else payload
        snap = (issue.get("context") or {}).get("client_snapshot") or {}
        self.assertEqual(snap.get("journey"), "test logistics")

    def test_post_debug_report_rejects_wrong_participant(self) -> None:
        assert hb is not None
        intent_id = self._seed_intent(edge_id="edge-a")
        client = hb.app.test_client()
        resp = client.post(
            "/api/v1/debug/report",
            json={"intent_id": intent_id, "participant_id": "edge-b"},
        )
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertFalse(body.get("ok"))

    def test_post_debug_report_with_other_problem_type(self) -> None:
        assert hb is not None
        intent_id = self._seed_intent()
        client = hb.app.test_client()
        with patch("dev_task.bridge.submit_command") as submit:
            submit.return_value = {"run_id": "run-debug-other", "status": "queued"}
            resp = client.post(
                "/api/v1/debug/report",
                json={
                    "intent_id": intent_id,
                    "participant_id": "living-room-android",
                    "problem_type": "other",
                    "user_summary": "语音识别错了，我说的是客厅不是卧室",
                },
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body.get("ok"))
        issue_id = int(body["issue_id"])
        detail = client.get(f"/api/v1/admin/debug/issue/{issue_id}")
        self.assertEqual(detail.status_code, 200)
        payload = detail.get_json()
        issue = payload.get("issue") if isinstance(payload.get("issue"), dict) else payload
        self.assertEqual(issue.get("problem_type"), "other")
        self.assertEqual(issue.get("problem_type_label"), "其他")
        self.assertIn("语音识别错了", issue.get("user_summary") or "")

    def test_post_debug_report_with_attachments(self) -> None:
        assert hb is not None
        intent_id = self._seed_intent()
        client = hb.app.test_client()
        with patch("dev_task.bridge.submit_command") as submit:
            submit.return_value = {"run_id": "run-debug-attach", "status": "queued"}
            resp = client.post(
                "/api/v1/debug/report",
                json={
                    "intent_id": intent_id,
                    "participant_id": "living-room-android",
                    "problem_type": "execution_error",
                    "attachments": [
                        {"asset_id": "asset_abc123", "kind": "image", "mime_type": "image/jpeg"},
                        {"asset_id": "asset_abc123", "kind": "image"},
                        {"asset_id": "asset_def456", "kind": "file", "filename": "log.txt"},
                    ],
                },
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body.get("ok"))
        issue_id = int(body["issue_id"])
        detail = client.get(f"/api/v1/admin/debug/issue/{issue_id}")
        issue = detail.get_json().get("issue") or detail.get_json()
        attachments = issue.get("attachments") or []
        self.assertEqual(len(attachments), 2)
        self.assertEqual(attachments[0]["asset_id"], "asset_abc123")
        self.assertEqual(attachments[0]["kind"], "image")
        self.assertEqual(attachments[1]["kind"], "file")
        self.assertEqual(issue.get("attachment_asset_ids"), ["asset_abc123", "asset_def456"])

    def test_admin_list_debug_issues(self) -> None:
        assert hb is not None
        intent_id = self._seed_intent()
        client = hb.app.test_client()
        with patch("dev_task.bridge.submit_command") as submit:
            submit.return_value = {"run_id": "run-debug-2", "status": "queued"}
            client.post(
                "/api/v1/debug/report",
                json={"intent_id": intent_id, "participant_id": "living-room-android"},
            )
        resp = client.get("/api/v1/admin/debug/issues?limit=10")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body.get("ok"))
        issues = body.get("issues") or []
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["intent_id"], intent_id)
        self.assertIn("dev_task", issues[0])

    def test_build_agent_prompt_requires_structured_sections(self) -> None:
        assert debug_gateway is not None
        issue = debug_issue_store.DebugIssue(
            issue_id=1,
            intent_id=42,
            session_id="sess-1",
            source="user_console",
            participant_id="living-room-android",
            status="analyzing",
            user_summary="执行失败",
            problem_type="execution_error",
            attachments=[],
            task_id=7,
            error="",
            context={"user_input": "开灯", "intent_status": "failed", "error": "timeout"},
            created_at="2026-08-27T12:00:00Z",
            updated_at="2026-08-27T12:00:00Z",
        )
        prompt = debug_gateway.build_agent_prompt(issue, issue.context)
        self.assertIn("## 根因分析", prompt)
        self.assertIn("## 修复建议", prompt)
        self.assertIn("- 优先级：", prompt)
        self.assertIn("- 负责人：", prompt)
        self.assertIn("- 预期收益：", prompt)
        self.assertNotIn(
            "Analyze root cause, cite evidence, and give a concise fix recommendation.",
            prompt,
        )


if __name__ == "__main__":
    unittest.main()
