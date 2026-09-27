"""`POST /api/v1/intent` 的 `source=dev`（手机 Dev Task 下发）回归测试。

历史 bug：`jsonify(..., intent_id=view.get("task_id"), task_kind="dev_task", **view)`
与 `view` 里的同名键撞车 → `TypeError: jsonify() got multiple values for keyword
argument 'intent_id'` → 接口 **500**。这里把「下发成功」的返回结构钉住。
"""

from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

SERVER = Path(__file__).resolve().parents[1]
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

try:
    import flask  # noqa: F401
except ImportError:  # pragma: no cover
    flask = None

import db as brain_db  # noqa: E402

if flask is not None:
    import home_brain as hb  # noqa: E402
else:  # pragma: no cover
    hb = None

# 真实 submit_agent_task → task_to_api_view 的键（含与显式字段同名的那几个）
DEV_VIEW = {
    "task_id": 4242,
    "intent_id": 4242,
    "task_kind": "dev_task",
    "text": "修一下这个 bug",
    "attachments": [],
    "attachment_asset_ids": [],
    "attachment_scope": "task",
    "status": "queued",
    "created_at": "2026-09-16 19:00:00",
    "updated_at": "2026-09-16 19:00:00",
    "finished_at": None,
    "msg": "",
    "result_text": "",
    "status_log": [{"status": "queued", "ts": 1789557000000}],
    "thread_id": 4242,
    "parent_task_id": None,
    "token_usage": None,
    "thread_token_usage": None,
}


@unittest.skipIf(flask is None, "flask not installed")
class IntentDevSourceTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        brain_db.reset(path=Path(self._tmp.name) / "brain.sqlite3")
        brain_db.init_db()
        self.addCleanup(brain_db.reset)
        self._register_live_issuer("iphone-origin")
        hb._REGISTERED_edges = brain_db.registration_ids()

    def _register_live_issuer(self, pid: str) -> None:
        now = time.time()
        brain_db.put_registration(
            {
                "participant_id": pid,
                "device_type": "iphone",
                "roles": ["intent_source", "endpoint"],
                "intent_sources": [{"source_id": "microphone", "channel": "voice"}],
            }
        )
        brain_db.put_heartbeat(
            pid,
            {
                "online_status": "online",
                "server_received_at": now,
                "reported_at": now,
                "schedule_eligible": True,
            },
        )

    def test_dev_source_returns_200_and_dev_task_view(self) -> None:
        client = hb.app.test_client()
        with mock.patch.object(hb, "submit_agent_task", return_value=dict(DEV_VIEW)) as submit:
            resp = client.post(
                "/api/v1/intent",
                json={"text": "修一下这个 bug", "source": "dev", "participant_id": "iphone-origin"},
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["source"], "dev")
        self.assertTrue(body["intent_origin"])
        self.assertEqual(body["task_kind"], "dev_task")
        # 显式字段优先：intent_id = 任务号，intent_status = 任务状态
        self.assertEqual(body["intent_id"], 4242)
        self.assertEqual(body["intent_status"], "queued")
        self.assertIn("已下发开发任务", body["reply"])
        # 其余 dev 视图字段照旧透传
        self.assertEqual(body["task_id"], 4242)
        self.assertEqual(body["thread_id"], 4242)
        self.assertEqual(body["status"], "queued")
        self.assertEqual(body["status_log"], DEV_VIEW["status_log"])
        self.assertEqual(submit.call_args.args[0], "修一下这个 bug")

    def test_dev_source_with_minimal_view_still_works(self) -> None:
        """即便上游视图很薄（只有 task_id/status），也不能再 500。"""
        client = hb.app.test_client()
        with mock.patch.object(
            hb, "submit_agent_task", return_value={"task_id": 7, "status": "queued"}
        ):
            resp = client.post(
                "/api/v1/intent",
                json={"text": "空视图", "source": "dev", "participant_id": "iphone-origin"},
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["intent_id"], 7)
        self.assertEqual(body["intent_status"], "queued")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
