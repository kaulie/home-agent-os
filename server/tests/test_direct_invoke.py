"""POST /api/v1/intent capability/params 直派通路测试（Console 按钮等 UI 控制面）。"""

from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path

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


@unittest.skipIf(flask is None, "flask not installed")
class DirectInvokeApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "brain.sqlite3"
        brain_db.reset(path=self.path)
        brain_db.init_db()
        self._register_live_issuer("iphone-origin")
        # 清掉 home_brain 进程内缓存，避免用例间污染
        hb._REGISTERED_edges = brain_db.registration_ids()
        hb.rebuild_capability_maps()

    def tearDown(self) -> None:
        brain_db.reset()
        self._tmp.cleanup()

    def _heartbeat(self, pid: str) -> None:
        now = time.time()
        brain_db.put_heartbeat(
            pid,
            {
                "online_status": "online",
                "server_received_at": now,
                "reported_at": now,
                "schedule_eligible": True,
            },
        )

    def _register_live_issuer(self, pid: str) -> None:
        brain_db.put_registration(
            {
                "participant_id": pid,
                "device_type": "iphone",
                "roles": ["intent_source", "endpoint"],
                "intent_sources": [{"source_id": "microphone", "channel": "voice"}],
                "endpoints": [
                    {
                        "endpoint_id": "iphone.display",
                        "supported_presentation": ["image", "text"],
                    }
                ],
            }
        )
        self._heartbeat(pid)
        hb._REGISTERED_edges = brain_db.registration_ids()

    def _register_pdf_edge(self, pid: str = "mac-edge") -> None:
        brain_db.put_registration(
            {
                "participant_id": pid,
                "device_type": "mac",
                "roles": ["runtime"],
                "services": [
                    {
                        "service_id": "local.display",
                        "capabilities": [{"capability_id": "display.pdf.page"}],
                    }
                ],
            }
        )
        self._heartbeat(pid)
        hb._REGISTERED_edges = brain_db.registration_ids()
        hb.rebuild_capability_maps()

    def test_direct_invoke_dispatches_single_step(self) -> None:
        self._register_pdf_edge()
        client = hb.app.test_client()
        before_qsize = hb.task_queue.qsize()
        resp = client.post(
            "/api/v1/intent",
            json={
                "text": "下一页",
                "source": "text",
                "participant_id": "iphone-origin",
                "capability": "display.pdf.page",
                "params": {"action": "next"},
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["intent_status"], "intent_parsed")
        self.assertEqual(body["task_kind"], "direct_invoke")
        # 绕过 LLM 规划：不排队
        self.assertEqual(hb.task_queue.qsize(), before_qsize)
        plan = hb.get_intent(body["intent_id"])["execution_plan"]
        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0]["capability"], "display.pdf.page")
        self.assertEqual(plan[0]["input_constrict"].get("action"), "next")
        self.assertEqual(plan[0]["assigned_edge_id"], "mac-edge")

    def test_direct_invoke_empty_text_accepted(self) -> None:
        self._register_pdf_edge()
        client = hb.app.test_client()
        resp = client.post(
            "/api/v1/intent",
            json={
                "participant_id": "iphone-origin",
                "capability": "display.pdf.page",
                "params": {"action": "prev"},
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["task_kind"], "direct_invoke")
        plan = hb.get_intent(body["intent_id"])["execution_plan"]
        self.assertEqual(plan[0]["input_constrict"].get("action"), "prev")

    def test_direct_invoke_params_default_empty(self) -> None:
        self._register_pdf_edge()
        client = hb.app.test_client()
        resp = client.post(
            "/api/v1/intent",
            json={
                "text": "翻页",
                "participant_id": "iphone-origin",
                "capability": "display.pdf.page",
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        plan = hb.get_intent(body["intent_id"])["execution_plan"]
        # 无 params 时不应注入调用方参数（appliance 为派发层选边注入）
        self.assertLessEqual(set(plan[0]["input_constrict"]), {"appliance"})

    def test_direct_invoke_no_provider_fails(self) -> None:
        client = hb.app.test_client()
        before_qsize = hb.task_queue.qsize()
        resp = client.post(
            "/api/v1/intent",
            json={
                "text": "下一页",
                "participant_id": "iphone-origin",
                "capability": "display.pdf.page",
                "params": {"action": "next"},
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["intent_status"], "failed")
        self.assertEqual(body["task_kind"], "direct_invoke")
        self.assertIn("display.pdf.page", body["error"])
        self.assertEqual(hb.task_queue.qsize(), before_qsize)

    def test_direct_invoke_system_capability_allowed(self) -> None:
        # system 能力（Brain 内执行）无 edge 广告，门禁应放行
        client = hb.app.test_client()
        before_qsize = hb.task_queue.qsize()
        resp = client.post(
            "/api/v1/intent",
            json={
                "text": "现在几点",
                "participant_id": "iphone-origin",
                "capability": "clock.now",
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["task_kind"], "direct_invoke")
        self.assertNotEqual(body["intent_status"], "failed")
        self.assertEqual(hb.task_queue.qsize(), before_qsize)
        intent = hb.get_intent(body["intent_id"])
        plan = intent["execution_plan"]
        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0]["capability"], "clock.now")
        self.assertEqual(intent["status"], "succeeded")

    def test_no_capability_still_llm_path(self) -> None:
        client = hb.app.test_client()
        before_qsize = hb.task_queue.qsize()
        resp = client.post(
            "/api/v1/intent",
            json={
                "text": "给我讲一个太空故事",
                "participant_id": "iphone-origin",
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["intent_status"], "intent_received")
        self.assertNotIn("task_kind", body)
        self.assertEqual(hb.task_queue.qsize(), before_qsize + 1)


if __name__ == "__main__":
    unittest.main()
