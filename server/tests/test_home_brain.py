"""home_brain.py persists intents in SQLite; ids continue after reconnect."""

from __future__ import annotations

import os
import sys
import json
import io
import queue
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

os.environ["BRAIN_SKIP_LLM_WORKER"] = "1"

try:
    import flask  # noqa: F401
except ImportError:  # pragma: no cover
    flask = None  # type: ignore

import db as brain_db  # noqa: E402

if flask is not None:
    import home_brain as hb  # noqa: E402
else:
    hb = None  # type: ignore

_CAPTURE_REF = {
    "asset_id": "asset_01TESTPHOTO",
    "type": "image",
    "mime_type": "image/jpeg",
}


@unittest.skipUnless(flask is not None, "flask not installed in this interpreter")
class HomeBrainPersistTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "brain.sqlite3"
        brain_db.reset(path=self.path)
        brain_db.init_db()
        hb._REGISTERED_edges = brain_db.registration_ids()
        hb.rebuild_capability_maps()
        hb.mock_cache.clear()
        self._qwen_flag = os.environ.get("QWEN_PLANNER")
        os.environ["QWEN_PLANNER"] = "0"

    def _heartbeat(self, pid: str, *, age_sec: float = 0, schedule_eligible: bool = True) -> None:
        received = time.time() - age_sec
        brain_db.put_heartbeat(
            pid,
            {
                "online_status": "online",
                "server_received_at": received,
                "reported_at": received,
                "schedule_eligible": schedule_eligible,
            },
        )

    def _register_live_issuer(self, pid: str, *, device_type: str = "iphone") -> None:
        brain_db.put_registration(
            {
                "participant_id": pid,
                "device_type": device_type,
                "roles": ["intent_source", "endpoint"],
                "intent_sources": [{"source_id": "microphone", "channel": "voice"}],
                "endpoints": [
                    {
                        "endpoint_id": f"{device_type}.display",
                        "supported_presentation": ["image", "text"],
                    }
                ],
            }
        )
        self._heartbeat(pid)

    def tearDown(self) -> None:
        self._drop_qwen_queue()
        if self._qwen_flag is None:
            os.environ.pop("QWEN_PLANNER", None)
        else:
            os.environ["QWEN_PLANNER"] = self._qwen_flag
        brain_db.reset()
        self._tmp.cleanup()

    def _drop_qwen_queue(self) -> None:
        if hb is None:
            return
        while True:
            try:
                hb.qwen_task_queue.get_nowait()
            except queue.Empty:
                return
            hb.qwen_task_queue.task_done()

    def _flush_qwen_shadow(self) -> int:
        flushed = 0
        while True:
            try:
                task = hb.qwen_task_queue.get_nowait()
            except queue.Empty:
                return flushed
            try:
                hb._process_qwen_task(task)
            finally:
                hb.qwen_task_queue.task_done()
                flushed += 1

    def test_intent_survives_reconnect_and_ids_continue(self) -> None:
        iid = hb.new_intent(
            {
                "status": "intent_received",
                "text": "现在几点了",
                "status_log": [{"status": "intent_received", "ts": 1}],
            }
        )
        self.assertEqual(iid, 1)
        hb.update_intent_status(iid, "intent_parsed")

        brain_db.reset(path=self.path)
        brain_db.init_db()

        got = hb.get_intent(iid)
        self.assertEqual(got.get("id"), 1)
        self.assertEqual(got.get("status"), "intent_parsed")
        self.assertEqual(got.get("text"), "现在几点了")
        logs = got.get("status_log") or []
        self.assertTrue(any(row.get("status") == "intent_parsed" for row in logs))

        iid2 = hb.new_intent(
            {
                "status": "intent_received",
                "text": "下一单",
                "status_log": [],
            }
        )
        self.assertEqual(iid2, 2)

    def test_register_survives_reconnect(self) -> None:
        client = hb.app.test_client()
        resp = client.get("/api/v1/edge-register")
        self.assertEqual(resp.status_code, 200)
        edge_id = resp.get_json()["edge_id"]

        brain_db.reset(path=self.path)
        brain_db.init_db()
        hb._REGISTERED_edges = brain_db.registration_ids()

        self.assertIn(edge_id, hb._REGISTERED_edges)
        self.assertIsNotNone(brain_db.get_registration(edge_id))

    def test_health_and_get_intent_path(self) -> None:
        iid = hb.new_intent(
            {
                "status": "intent_received",
                "text": "health",
                "status_log": [],
            }
        )
        client = hb.app.test_client()
        health = client.get("/health")
        self.assertEqual(health.status_code, 200)
        body = health.get_json()
        self.assertTrue(body["ok"])
        self.assertIn("brain.sqlite3", str(body.get("db") or ""))

        missing = client.get("/api/v1/intent/999999")
        self.assertEqual(missing.status_code, 404)

        found = client.get(f"/api/v1/intent/{iid}")
        self.assertEqual(found.status_code, 200)
        self.assertEqual(found.get_json().get("text"), "health")

    def test_ping_returns_server_time_and_optional_skew(self) -> None:
        client = hb.app.test_client()
        before_ms = int(time.time() * 1000)
        resp = client.get("/api/v1/ping")
        after_ms = int(time.time() * 1000)
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body.get("app"), "brain")
        server_ms = int(body["server_time_ms"])
        self.assertGreaterEqual(server_ms, before_ms - 1000)
        self.assertLessEqual(server_ms, after_ms + 1000)
        self.assertIn("server_time", body)

        client_ms = server_ms - 250
        skewed = client.get(f"/api/v1/ping?client_time_ms={client_ms}")
        self.assertEqual(skewed.status_code, 200)
        sbody = skewed.get_json()
        self.assertEqual(sbody.get("client_time_ms"), client_ms)
        self.assertAlmostEqual(int(sbody["skew_ms"]), 250, delta=2000)

        bad = client.get("/api/v1/ping?client_time_ms=nope")
        self.assertEqual(bad.status_code, 400)

        alias = client.get("/ping")
        self.assertEqual(alias.status_code, 200)
        self.assertTrue(alias.get_json().get("ok"))

        head = client.head("/api/v1/ping")
        self.assertEqual(head.status_code, 200)

    def test_post_intent_persists_schema_columns(self) -> None:
        self._register_live_issuer("phone-1")
        client = hb.app.test_client()
        resp = client.post(
            "/api/v1/intent",
            json={
                "text": "现在几点了",
                "source": "voice",
                "edge_id": "phone-1",
                "session_id": "sess-a",
            },
        )
        self.assertEqual(resp.status_code, 200)
        iid = resp.get_json()["intent_id"]
        brain_db.reset(path=self.path)
        brain_db.init_db()
        job = brain_db.get_job(iid)
        assert job is not None
        self.assertEqual(job["text"], "现在几点了")
        self.assertEqual(job["source"], "voice")
        self.assertEqual(job["edge_id"], "phone-1")
        self.assertEqual(job["status"], "intent_received")
        self.assertTrue(job.get("intent_base_time"))
        self.assertEqual(job.get("base_time"), job.get("intent_base_time"))
        self.assertTrue(job.get("status_log"))
        self.assertTrue(job.get("steps"))
        self.assertEqual(job["intent_origin"], "lan")
        self.assertEqual(resp.get_json().get("intent_origin"), "lan")
        detail = client.get(f"/api/v1/intent_detail?intent_id={iid}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.get_json().get("intent_origin"), "lan")
        listed = client.get(
            "/api/v1/intents",
            query_string={"participant_id": "phone-1"},
        )
        self.assertEqual(listed.status_code, 200)
        rows = listed.get_json().get("intents") or []
        self.assertEqual(rows[0].get("intent_origin"), "lan")
        by_path = client.get(f"/api/v1/intent/{iid}")
        self.assertEqual(by_path.get_json().get("intent_origin"), "lan")

    def test_intent_origin_instance_is_authoritative(self) -> None:
        self._register_live_issuer("phone-1")
        client = hb.app.test_client()
        prev = os.environ.get("BRAIN_ORIGIN")
        os.environ["BRAIN_ORIGIN"] = "cloud"
        try:
            self.assertEqual(hb.instance_intent_origin(), "cloud")
            resp = client.post(
                "/api/v1/intent",
                json={
                    "text": "现在几点了",
                    "source": "text",
                    "edge_id": "phone-1",
                    "intent_origin": "lan",
                },
            )
            self.assertEqual(resp.status_code, 200)
            body = resp.get_json()
            self.assertEqual(body.get("intent_origin"), "cloud")
            iid = body["intent_id"]
            job = brain_db.get_job(iid)
            assert job is not None
            self.assertEqual(job["intent_origin"], "cloud")
            hb.update_intent_status(iid, "intent_parsed")
            after = brain_db.get_job(iid)
            assert after is not None
            self.assertEqual(after["intent_origin"], "cloud")
            os.environ["BRAIN_ORIGIN"] = "not-valid"
            self.assertEqual(hb.instance_intent_origin(), "lan")
            coerced = client.post(
                "/api/v1/intent",
                json={
                    "text": "开灯",
                    "edge_id": "phone-1",
                    "intent_origin": "vpn",
                },
            )
            self.assertEqual(coerced.status_code, 200)
            self.assertEqual(coerced.get_json().get("intent_origin"), "lan")
            health = client.get("/health")
            self.assertEqual(health.get_json().get("brain_origin"), "lan")
        finally:
            if prev is None:
                os.environ.pop("BRAIN_ORIGIN", None)
            else:
                os.environ["BRAIN_ORIGIN"] = prev

    def test_empty_plan_is_failed_not_parsed(self) -> None:
        iid = hb.new_intent(
            {
                "status": "intent_received",
                "text": "随便说说",
                "source": "text",
                "status_log": [],
            }
        )
        hb.do_execution_plan(iid, [])
        hb.mark_intent_failed(iid, hb._EMPTY_PLAN_MSG)
        brain_db.reset(path=self.path)
        brain_db.init_db()
        job = brain_db.get_job(iid)
        assert job is not None
        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["msg"], hb._EMPTY_PLAN_MSG)
        self.assertEqual(job["error"], hb._EMPTY_PLAN_MSG)

    def test_empty_plan_failure_msg_uses_missing_capability_reason(self) -> None:
        notes = {
            "missing_capabilities": [
                {
                    "capability": "camera.capture",
                    "reason": "拍照节点当前不在线，无法拍照",
                }
            ]
        }
        self.assertEqual(
            hb._empty_plan_failure_msg(notes, {"reason": "ignored"}),
            "拍照节点当前不在线，无法拍照",
        )
        self.assertEqual(
            hb._empty_plan_failure_msg({"missing_capabilities": []}, {"reason": "没有匹配能力"}),
            "没有匹配能力",
        )

    def test_ark_http_error_msg_account_overdue_surfaces_real_cause(self) -> None:
        # No HTTP error -> fall back to original empty-plan diagnostics.
        self.assertIsNone(hb._ark_http_error_msg(None))
        self.assertIsNone(hb._ark_http_error_msg({}))
        self.assertIsNone(hb._ark_http_error_msg({"http_status": 200}))
        self.assertIsNone(hb._ark_http_error_msg({"http_status": 0}))
        self.assertEqual(
            hb._ark_http_error_msg(
                {"http_status": 401, "error": {"code": "AuthenticationError"}}
            ),
            "规划服务 401，检查 ARK_API_KEY",
        )
        msg = hb._ark_http_error_msg(
            {
                "http_status": 403,
                "error": {
                    "code": "AccountOverdueError",
                    "message": "The request failed because your account has an overdue balance.",
                    "type": "Forbidden",
                },
            }
        )
        self.assertIn("403", msg)
        self.assertIn("AccountOverdueError", msg)
        self.assertIn("欠费", msg)

    def test_ark_http_error_msg_unknown_code_includes_message_and_caps(self) -> None:
        long_msg = "rate limited " * 200
        msg = hb._ark_http_error_msg(
            {
                "http_status": 429,
                "error": {"code": "TooManyRequests", "message": long_msg},
            }
        )
        self.assertIn("429", msg)
        self.assertIn("TooManyRequests", msg)
        self.assertIn("rate limited", msg)
        self.assertLessEqual(len(msg), hb._ARK_HTTP_MSG_MAX)

    def test_apply_failure_presentation_fills_text(self) -> None:
        intent = {
            "text": "拍照",
            "source": "voice",
            "edge_id": "iphone-1",
            "presentation": {"type": "text", "from": "answer_text"},
        }
        hb._apply_failure_presentation(intent, "拍照节点当前不在线，无法拍照")
        self.assertEqual(intent["presentation"]["type"], "text")
        self.assertEqual(intent["presentation"]["from"], "msg")
        self.assertEqual(intent["presentation"]["text"], "拍照节点当前不在线，无法拍照")

    # --- ncm-cli login loss: human reason + link only for iPhone origin ---

    _LOGIN_URL = "https://163cn.tv/bgl5Nc5N"

    def _login_failure_intent(self, *, issuer: str, login_url: str | None = None) -> dict:
        """Intent whose music step failed because ncm-cli is logged out."""
        info: dict = {
            "logged_in": False,
            "reason": "未登录，请执行 ncm-cli login 完成登录",
        }
        url = self._LOGIN_URL if login_url is None else login_url
        if url:
            info["login_url"] = url
        return {
            "text": "播放五月天的歌",
            "source": "voice",
            "intent_origin": "lan",
            "edge_id": issuer,
            "source_context": {"device_id": issuer},
            "execution_plan": [{"step": 1, "capability": "music.play"}],
            "step_outputs": {"1": {"netease_login": info}},
        }

    def test_failure_presentation_login_link_hidden_for_mac_origin(self) -> None:
        self._register_endpoint("living-room-mac", "mac")
        intent = self._login_failure_intent(issuer="living-room-mac")
        raw = "ncm-cli 未返回 JSON：error: unknown command 'playlist'"
        text = hb._apply_failure_presentation(intent, raw)
        self.assertNotIn("playlist", text)
        self.assertNotIn("163cn.tv", text)
        self.assertIn("登录已失效", text)
        self.assertEqual(intent["presentation"]["text"], text)
        self.assertEqual(intent["presentation"]["from"], "msg")

    def test_failure_presentation_login_link_shown_for_iphone_origin(self) -> None:
        self._register_endpoint("living-room-iphone-1", "iphone")
        intent = self._login_failure_intent(issuer="living-room-iphone-1")
        text = hb._apply_failure_presentation(intent, "ncm-cli 未返回 JSON：boom")
        self.assertIn(self._LOGIN_URL, text)
        self.assertIn("登录已失效", text)
        self.assertEqual(intent["presentation"]["text"], text)

    def test_failure_presentation_login_link_hidden_without_url(self) -> None:
        self._register_endpoint("living-room-iphone-1", "iphone")
        intent = self._login_failure_intent(issuer="living-room-iphone-1", login_url="")
        text = hb._apply_failure_presentation(intent, "boom")
        self.assertIn("登录已失效", text)
        self.assertNotIn("http", text)

    def test_failure_presentation_login_link_hidden_for_unknown_device(self) -> None:
        intent = self._login_failure_intent(issuer="ghost-1")
        text = hb._apply_failure_presentation(intent, "boom")
        self.assertIn("登录已失效", text)
        self.assertNotIn("163cn.tv", text)

    def test_failure_presentation_non_login_failure_keeps_msg(self) -> None:
        intent = {
            "text": "拍照",
            "source": "voice",
            "edge_id": "x",
            "step_outputs": {"1": {"answer_text": "noop"}},
        }
        text = hb._apply_failure_presentation(intent, "拍照节点当前不在线")
        self.assertEqual(text, "拍照节点当前不在线")
        self.assertEqual(intent["presentation"]["text"], "拍照节点当前不在线")

    def test_client_hint_reuses_participant_id(self) -> None:
        client = hb.app.test_client()
        first = client.post(
            "/api/v1/edge-register",
            json={"client_hint": "living-room-mac", "display_name": "Mac", "room": "living-room"},
        )
        self.assertEqual(first.status_code, 200)
        edge_id = first.get_json()["edge_id"]
        second = client.post(
            "/api/v1/edge-register",
            json={"client_hint": "living-room-mac"},
        )
        self.assertEqual(second.get_json()["edge_id"], edge_id)
        brain_db.reset(path=self.path)
        brain_db.init_db()
        hb._REGISTERED_edges = brain_db.registration_ids()
        third = client.post(
            "/api/v1/edge-register",
            json={"client_hint": "living-room-mac"},
        )
        self.assertEqual(third.get_json()["edge_id"], edge_id)
        rec = brain_db.get_registration(edge_id)
        assert rec is not None
        self.assertEqual(rec["client_hint"], "living-room-mac")
        self.assertEqual(rec["location"], "living-room")

    def test_heartbeat_skew_is_persisted(self) -> None:
        client = hb.app.test_client()
        edge_id = client.post("/api/v1/edge-register", json={"client_hint": "skew-mac"}).get_json()["edge_id"]
        far = int(time.time() * 1000) - (6 * 60 * 1000)
        resp = client.post(
            "/api/v1/edge-heartbeat",
            json={
                "edge_id": edge_id,
                "client_time_ms": far,
                "online_status": "online",
                "services": [
                    {
                        "service_id": "local.notify",
                        "capabilities": [{"capability_id": "notify.speak"}],
                    }
                ],
            },
        )
        self.assertEqual(resp.status_code, 400)
        brain_db.reset(path=self.path)
        brain_db.init_db()
        beats = brain_db.list_heartbeats()
        self.assertIn(edge_id, beats)
        self.assertFalse(beats[edge_id]["schedule_eligible"])
        self.assertTrue(beats[edge_id].get("schedule_reject_reason"))

    def test_heartbeat_ingests_cloud_usage_delta(self) -> None:
        client = hb.app.test_client()
        edge_id = client.post(
            "/api/v1/edge-register", json={"client_hint": "cloud-usage-mac"}
        ).get_json()["edge_id"]
        now_ms = int(time.time() * 1000)
        resp = client.post(
            "/api/v1/edge-heartbeat",
            json={
                "edge_id": edge_id,
                "client_time_ms": now_ms,
                "online_status": "online",
                "cloud_usage_delta": [
                    {"service_id": "volc.stt", "ok": 2, "fail": 1},
                    {"bad": True},
                ],
                "services": [
                    {
                        "service_id": "local.notify",
                        "capabilities": [{"capability_id": "notify.speak"}],
                    }
                ],
            },
        )
        self.assertEqual(resp.status_code, 200)
        rows = brain_db.aggregate_cloud_calls()
        by_id = {row["service_id"]: row for row in rows}
        self.assertEqual(by_id["volc.stt"]["count"], 3)
        self.assertEqual(by_id["volc.stt"]["ok"], 2)
        self.assertEqual(by_id["volc.stt"]["fail"], 1)

    def test_pull_hides_terminal_and_filters_edge(self) -> None:
        client = hb.app.test_client()
        parsed = client.post(
            "/api/v1/devices/living-room/intents",
            json={
                "execution_plan": [
                    {"capability": "notify.speak", "step": 1, "assigned_edge_id": "edge-a"}
                ],
            },
        ).get_json()
        client.post(
            "/api/v1/devices/living-room/intents",
            json={"execution_plan": [], "text": "empty"},
        )
        shown = client.get(
            "/api/v1/devices/living-room/intents?edge_id=edge-a&last=10"
        ).get_json()["intents"]
        ids = {row["id"] for row in shown}
        self.assertIn(parsed["id"], ids)
        hidden = client.get(
            "/api/v1/devices/living-room/intents?edge_id=edge-b&last=10"
        ).get_json()["intents"]
        self.assertEqual(hidden, [])

    def test_pull_ignores_leftover_whole_job_assignee_fields(self) -> None:
        client = hb.app.test_client()
        leftover = client.post(
            "/api/v1/devices/living-room/intents",
            json={
                "execution_plan": [
                    {"capability": "notify.speak", "step": 1, "assigned_edge_id": "edge-a"}
                ],
                "assigned_edge_id": "edge-b",
                "scheduler_node": "edge-b",
            },
        ).get_json()
        self.assertNotIn("assigned_edge_id", leftover)
        self.assertNotIn("scheduler_node", leftover)
        shown_a = client.get(
            "/api/v1/devices/living-room/intents?edge_id=edge-a&last=10"
        ).get_json()["intents"]
        self.assertIn(leftover["id"], {row["id"] for row in shown_a})
        shown_b = client.get(
            "/api/v1/devices/living-room/intents?edge_id=edge-b&last=10"
        ).get_json()["intents"]
        self.assertEqual(shown_b, [])

    def test_step_status_records_edge_id_in_step_log(self) -> None:
        iid = hb.new_intent(
            {
                "status": "running",
                "text": "now",
                "status_log": [],
                "execution_plan": [
                    {
                        "step": 1,
                        "capability": "clock.now",
                        "assigned_edge_id": "mac-runtime",
                    }
                ],
            }
        )
        client = hb.app.test_client()
        resp = client.post(
            f"/api/v1/intent/{iid}/step/1/status",
            json={
                "step_status": "2",
                "edge_node_id": "mac-runtime",
                "ts": 1,
                "outputs": {"time_text": "noon"},
            },
        )
        self.assertEqual(resp.status_code, 200)
        got = hb.get_intent(iid)
        log = got.get("step_log") or []
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["edge_id"], "mac-runtime")
        self.assertEqual(log[0]["step"], 1)
        self.assertEqual(log[0]["status"], 2)

    def test_review_keeps_session_id(self) -> None:
        iid = hb.new_intent({"status": "intent_received", "text": "hi", "status_log": []})
        hb._record_intent_review(
            iid,
            text="hi",
            session_id="sess-a",
            source="text",
            edge_id="phone-1",
            raw="{}",
            parsed={"plan": []},
            plan=[],
            cost_ms=321,
            request_payload={"model": "ep-test", "messages": [{"role": "user", "content": "hi"}]},
            response_json={"usage": {"total_tokens": 4}},
        )
        brain_db.reset(path=self.path)
        brain_db.init_db()
        rows = brain_db.list_intent_reviews(session_id="sess-a")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["session_id"], "sess-a")
        self.assertEqual(rows[0]["source"], "text")
        self.assertEqual(rows[0]["edge_id"], "phone-1")
        self.assertEqual(rows[0]["cost_ms"], 321)
        self.assertEqual(rows[0]["request_payload"]["model"], "ep-test")
        self.assertEqual(rows[0]["raw_response"], "{}")
        self.assertEqual(rows[0]["response_json"]["usage"]["total_tokens"], 4)

    def test_sanitize_photo_look_drops_display_and_present(self) -> None:
        intent = {"text": "拍张照片我看一下", "source": "voice"}
        plan = [
            {"step": 1, "capability": "camera.capture"},
            {"step": 2, "capability": "display.photo"},
            {"step": 3, "capability": "endpoint.present"},
            {"step": 4, "capability": "notify.speak"},
        ]
        cleaned = hb.sanitize_execution_plan(plan, intent)
        self.assertEqual([s["capability"] for s in cleaned], ["camera.capture"])
        self.assertEqual(cleaned[0]["step"], 1)

    def test_sanitize_keeps_display_when_user_asks_tv(self) -> None:
        intent = {"text": "拍张照片投到电视", "source": "voice"}
        plan = [
            {"step": 1, "capability": "camera.capture"},
            {"step": 2, "capability": "display.photo"},
        ]
        cleaned = hb.sanitize_execution_plan(plan, intent)
        self.assertEqual(
            [s["capability"] for s in cleaned],
            ["camera.capture", "display.photo"],
        )

    def test_sanitize_folds_capture_upload_into_composite(self) -> None:
        self._register_photo_runtimes()
        intent = {"text": "拍张照片我看一下", "source": "voice"}
        plan = [
            {
                "step": 1,
                "capability": "camera.capture",
                "assigned_edge_id": "android-1",
                "output_constrict": {
                    "capture_ref": {"type": "string", "data_dest": "context"}
                },
            },
            {
                "step": 2,
                "capability": "asset.upload",
                "assigned_edge_id": "iphone-1",
                "input_constrict": {"capture_ref": "$capture_ref"},
                "output_constrict": {
                    "asset_ref": {"type": "string", "data_dest": "context"}
                },
            },
        ]
        cleaned = hb.sanitize_execution_plan(plan, intent)
        self.assertEqual([s["capability"] for s in cleaned], ["camera.capture_and_upload"])
        self.assertEqual(cleaned[0]["step"], 1)
        self.assertEqual(cleaned[0]["assigned_edge_id"], "android-1")
        self.assertNotIn("capture_ref", cleaned[0].get("input_constrict") or {})
        self.assertIn("asset_ref", cleaned[0].get("output_constrict") or {})

    def test_sanitize_keeps_standalone_upload(self) -> None:
        intent = {"text": "把刚才那张传到云上", "source": "text"}
        plan = [
            {
                "step": 1,
                "capability": "asset.upload",
                "input_constrict": {"asset_ref": "$asset_ref", "dest": "cloud"},
            }
        ]
        cleaned = hb.sanitize_execution_plan(plan, intent)
        self.assertEqual([s["capability"] for s in cleaned], ["asset.upload"])

    def test_do_execution_plan_assigns_composite_to_available_runtime(self) -> None:
        self._register_photo_runtimes()
        iid = hb.new_intent(
            {
                "status": "intent_received",
                "text": "拍张照片我看一下",
                "source": "voice",
                "edge_id": "iphone-1",
            }
        )
        hb.do_execution_plan(
            iid,
            hb.sanitize_execution_plan(
                [
                    {
                        "step": 1,
                        "capability": "camera.capture",
                        "assigned_edge_id": "android-1",
                        "output_constrict": {
                            "capture_ref": {"type": "string", "data_dest": "context"}
                        },
                    },
                    {
                        "step": 2,
                        "capability": "asset.upload",
                        "assigned_edge_id": "iphone-1",
                        "input_constrict": {"capture_ref": "$capture_ref"},
                        "output_constrict": {
                            "asset_ref": {"type": "string", "data_dest": "context"}
                        },
                    },
                ],
                {"text": "拍张照片我看一下"},
            ),
        )
        got = hb.get_intent(iid)
        plan = got["execution_plan"]
        self.assertEqual([s["capability"] for s in plan], ["camera.capture_and_upload"])
        self.assertEqual(plan[0]["assigned_edge_id"], "android-1")

    def test_plan_persists_available_capabilities_for_replay(self) -> None:
        self._register_photo_runtimes()
        iid = hb.new_intent(
            {
                "status": "intent_received",
                "text": "拍张照片我看一下",
                "source": "voice",
                "edge_id": "iphone-1",
            }
        )
        hb.do_execution_plan(
            iid,
            hb.sanitize_execution_plan(
                [
                    {
                        "step": 1,
                        "capability": "camera.capture",
                        "assigned_edge_id": "android-1",
                        "output_constrict": {
                            "capture_ref": {"type": "string", "data_dest": "context"}
                        },
                    },
                    {
                        "step": 2,
                        "capability": "asset.upload",
                        "assigned_edge_id": "iphone-1",
                        "input_constrict": {"capture_ref": "$capture_ref"},
                        "output_constrict": {
                            "asset_ref": {"type": "string", "data_dest": "context"}
                        },
                    },
                ],
                {"text": "拍张照片我看一下"},
            ),
        )
        job = brain_db.get_job(iid)
        assert job is not None
        caps = job.get("available_capabilities") or []
        self.assertTrue(caps)
        pairs = {
            (row.get("capability_id"), row.get("edge_id") or row.get("assigned_edge_id"))
            for row in caps
            if isinstance(row, dict)
        }
        self.assertIn(("camera.capture", "android-1"), pairs)
        self.assertNotIn(("camera.capture", "iphone-1"), pairs)
        android_capture = next(
            row
            for row in caps
            if row.get("capability_id") == "camera.capture"
            and row.get("edge_id") == "android-1"
        )
        self.assertEqual(android_capture.get("composition"), "atomic")
        detail = hb.app.test_client().get(f"/api/v1/intent_detail?intent_id={iid}")
        self.assertEqual(detail.status_code, 200)
        body = detail.get_json()
        # available_capabilities is persisted on the job (replay) but stripped from
        # the public intent_detail response (perf: too large to ship every poll).
        self.assertIsNone(body.get("available_capabilities"))
        job2 = brain_db.get_job(iid)
        assert job2 is not None
        self.assertEqual(job2.get("available_capabilities"), caps)

    def test_reconcile_fails_orphan_dispatched_jobs_on_boot(self) -> None:
        # A job dispatched before a restart is orphaned; boot must close it.
        old = hb.new_intent(
            {"status": "intent_received", "text": "几点了", "source": "voice"}
        )
        brain_db.put_job({"id": old, "intent_id": old, "status": "intent_dispatched",
                          "updated_at": time.time() - 600})
        fresh = hb.new_intent(
            {"status": "intent_received", "text": "几点了", "source": "voice"}
        )
        brain_db.put_job({"id": fresh, "intent_id": fresh, "status": "intent_dispatched",
                          "updated_at": time.time() - 10})
        closed = hb._reconcile_orphan_jobs()
        self.assertEqual(closed, 1)
        self.assertEqual(hb.get_intent(old)["status"], "failed")
        # Fresh in-flight (within grace) is left alone, not failed.
        self.assertEqual(hb.get_intent(fresh)["status"], "intent_dispatched")
        # intent_received is re-queued, never reconciled to failed.
        recv = hb.new_intent(
            {"status": "intent_received", "text": "几点了", "source": "voice"}
        )
        brain_db.put_job({"id": recv, "intent_id": recv, "status": "intent_received",
                          "updated_at": time.time() - 600})
        self.assertEqual(hb._reconcile_orphan_jobs(), 0)
        self.assertEqual(hb.get_intent(recv)["status"], "intent_received")

    def test_do_execution_plan_rejects_split_capture_upload(self) -> None:
        self._register_split_atomic_runtimes()
        iid = hb.new_intent(
            {
                "status": "intent_received",
                "text": "拍张照片我看一下",
                "source": "voice",
            }
        )
        with self.assertRaises(hb.CaptureUploadSplitError):
            hb.do_execution_plan(
                iid,
                [
                    {
                        "step": 1,
                        "capability": "camera.capture",
                        "assigned_edge_id": "android-1",
                        "input_constrict": {},
                        "output_constrict": {
                            "capture_ref": {"type": "string", "data_dest": "context"}
                        },
                    },
                    {
                        "step": 2,
                        "capability": "asset.upload",
                        "assigned_edge_id": "iphone-1",
                        "input_constrict": {"capture_ref": "$capture_ref"},
                        "output_constrict": {
                            "asset_ref": {"type": "string", "data_dest": "context"}
                        },
                    },
                ],
            )

    def test_sanitize_does_not_fold_without_composite_provider(self) -> None:
        self._register_split_atomic_runtimes()
        cleaned = hb.sanitize_execution_plan(
            [
                {
                    "step": 1,
                    "capability": "camera.capture",
                    "assigned_edge_id": "android-1",
                    "output_constrict": {
                        "capture_ref": {"type": "string", "data_dest": "context"}
                    },
                },
                {
                    "step": 2,
                    "capability": "asset.upload",
                    "assigned_edge_id": "iphone-1",
                    "input_constrict": {"capture_ref": "$capture_ref"},
                    "output_constrict": {
                        "asset_ref": {"type": "string", "data_dest": "context"}
                    },
                },
            ],
            {"text": "拍张照片我看一下"},
        )
        self.assertEqual(
            [s["capability"] for s in cleaned],
            ["camera.capture", "asset.upload"],
        )

    def test_catalog_includes_composite_composition_fields(self) -> None:
        self._register_photo_runtimes()
        rows = hb._capability_registry_for_prompt()
        composite = next(
            r
            for r in rows
            if r["capability_id"] == "camera.capture_and_upload"
            and r.get("edge_id") == "android-1"
        )
        self.assertEqual(composite["composition"], "composite")
        self.assertEqual(composite["decomposes_to"], ["camera.capture", "asset.upload"])
        self.assertTrue(str(composite.get("prefer_when") or "").strip())
        capture = next(
            r
            for r in rows
            if r["capability_id"] == "camera.capture" and r.get("edge_id") == "android-1"
        )
        self.assertEqual(capture["composition"], "atomic")
        self.assertNotIn("decomposes_to", capture)
        self.assertNotIn("prefer_when", capture)

    def test_reading_point_to_character_ads_are_composite(self) -> None:
        from capability_ads import composition_of, decomposes_to

        self.assertEqual(composition_of("reading.point_to_character"), "composite")
        self.assertEqual(
            decomposes_to("reading.point_to_character"),
            ["reading.detect_finger", "reading.ocr_at_finger", "reading.rank_pointed"],
        )
        self.assertEqual(composition_of("reading.detect_finger"), "atomic")
        self.assertEqual(decomposes_to("reading.detect_finger"), [])
        self.assertEqual(composition_of("reading.ocr_at_finger"), "atomic")
        self.assertEqual(composition_of("reading.rank_pointed"), "atomic")

    def test_process_llm_task_folds_split_capture_upload(self) -> None:
        from unittest.mock import patch

        self._register_photo_runtimes()
        iid = hb.new_intent(
            {
                "status": "intent_received",
                "text": "拍张照片我看一下",
                "source": "voice",
                "edge_id": "iphone-1",
                "status_log": [],
            }
        )
        ans = json.dumps(
            {
                "goal": "show a new photo",
                "reason": "user wants to see a capture",
                "plan": [
                    {
                        "step": 1,
                        "capability": "camera.capture",
                        "assigned_edge_id": "android-1",
                        "output_constrict": {
                            "capture_ref": {"type": "string", "data_dest": "context"}
                        },
                    },
                    {
                        "step": 2,
                        "capability": "asset.upload",
                        "assigned_edge_id": "iphone-1",
                        "input_constrict": {"capture_ref": "$capture_ref"},
                        "output_constrict": {
                            "asset_ref": {"type": "string", "data_dest": "context"}
                        },
                    },
                ],
                "presentation": {"type": "image", "from": "asset_ref"},
                "missing_capabilities": [],
                "better_capabilities": [],
            }
        )
        ark = {
            "ans": ans,
            "cost_ms": 10,
            "request_payload": {"model": "ep-test", "messages": []},
            "response_json": {"choices": [{"message": {"content": ans}}]},
            "cache_hit": False,
        }
        with patch.object(hb, "call_ark", return_value=ark):
            hb._process_llm_task(
                {
                    "question": "拍张照片我看一下",
                    "session_id": "sess-photo",
                    "user_id": "u1",
                    "intent_id": iid,
                    "source": "voice",
                    "edge_id": "iphone-1",
                }
            )
        got = hb.get_intent(iid)
        plan = got["execution_plan"]
        self.assertEqual([s["capability"] for s in plan], ["camera.capture_and_upload"])
        self.assertEqual(plan[0]["assigned_edge_id"], "android-1")
        self.assertNotEqual(got.get("status"), "failed")

    def _register_photo_runtimes(self) -> None:
        def _caps(*, capture_ok: bool) -> list[dict]:
            return [
                {
                    "capability_id": "camera.capture",
                    "composition": "atomic",
                    "kind": "input",
                    "available": capture_ok,
                    "input_schema": {},
                    "output_schema": {},
                },
                {
                    "capability_id": "camera.capture_and_upload",
                    "composition": "composite",
                    "decomposes_to": ["camera.capture", "asset.upload"],
                    "prefer_when": "拍照后还有后续动作",
                    "kind": "action",
                    "available": capture_ok,
                    "input_schema": {},
                    "output_schema": {},
                },
            ]

        def _put(pid: str, *, capture_ok: bool) -> None:
            brain_db.put_registration(
                {
                    "participant_id": pid,
                    "display_name": pid,
                    "device_type": "phone",
                    "roles": ["runtime"],
                    "services": [
                        {
                            "service_id": "gopro.camera",
                            "group": "camera",
                            "capabilities": _caps(capture_ok=capture_ok),
                        },
                        {
                            "service_id": "local.asset",
                            "group": "asset",
                            "capabilities": [
                                {
                                    "capability_id": "asset.upload",
                                    "composition": "atomic",
                                    "kind": "action",
                                    "available": True,
                                    "input_schema": {},
                                    "output_schema": {},
                                }
                            ],
                        },
                    ],
                }
            )
            received = time.time()
            brain_db.put_heartbeat(
                pid,
                {
                    "online_status": "online",
                    "server_received_at": received,
                    "reported_at": received,
                    "schedule_eligible": True,
                    "services": [
                        {
                            "service_id": "gopro.camera",
                            "group": "camera",
                            "edge_id": pid,
                            "capabilities": _caps(capture_ok=capture_ok),
                        },
                        {
                            "service_id": "local.asset",
                            "group": "asset",
                            "edge_id": pid,
                            "capabilities": [
                                {
                                    "capability_id": "asset.upload",
                                    "composition": "atomic",
                                    "available": True,
                                    "input_schema": {},
                                    "output_schema": {},
                                }
                            ],
                        },
                    ],
                },
            )

        _put("android-1", capture_ok=True)
        _put("iphone-1", capture_ok=False)
        hb._REGISTERED_edges = brain_db.registration_ids()
        hb.rebuild_capability_maps()

    def _register_split_atomic_runtimes(self) -> None:
        """Capture only on android, upload only on iphone; no composite ads."""
        received = time.time()

        def _put(pid: str, services: list[dict]) -> None:
            brain_db.put_registration(
                {
                    "participant_id": pid,
                    "display_name": pid,
                    "device_type": "phone",
                    "roles": ["runtime"],
                    "services": services,
                }
            )
            brain_db.put_heartbeat(
                pid,
                {
                    "online_status": "online",
                    "server_received_at": received,
                    "reported_at": received,
                    "schedule_eligible": True,
                    "services": services,
                },
            )

        _put(
            "android-1",
            [
                {
                    "service_id": "gopro.camera",
                    "group": "camera",
                    "edge_id": "android-1",
                    "capabilities": [
                        {
                            "capability_id": "camera.capture",
                            "composition": "atomic",
                            "kind": "input",
                            "available": True,
                            "input_schema": {},
                            "output_schema": {},
                        }
                    ],
                }
            ],
        )
        _put(
            "iphone-1",
            [
                {
                    "service_id": "local.asset",
                    "group": "asset",
                    "edge_id": "iphone-1",
                    "capabilities": [
                        {
                            "capability_id": "asset.upload",
                            "composition": "atomic",
                            "kind": "action",
                            "available": True,
                            "input_schema": {},
                            "output_schema": {},
                        }
                    ],
                }
            ],
        )
        hb._REGISTERED_edges = brain_db.registration_ids()
        hb.rebuild_capability_maps()

    def test_sanitize_restores_stripped_query_for_image_cast(self) -> None:
        intent = {"text": "来张战斗机的图片投到电视上", "source": "voice"}
        plan = [
            {
                "step": 1,
                "capability": "query.content",
                "input_constrict": {"query": "战斗机", "upload_dest": "lan"},
                "output_constrict": {
                    "asset_ref": {"type": "string", "data_dest": "context"}
                },
            },
            {
                "step": 2,
                "capability": "display.photo",
                "input_constrict": {"asset_ref": "$asset_ref"},
            },
        ]
        cleaned = hb.sanitize_execution_plan(plan, intent)
        self.assertEqual(cleaned[0]["input_constrict"]["query"], intent["text"])
        self.assertEqual(cleaned[0]["input_constrict"]["want_image"], "true")
        self.assertEqual(cleaned[0]["input_constrict"]["upload_dest"], "lan")
        self.assertEqual(cleaned[1]["capability"], "display.photo")
        self.assertEqual(cleaned[1]["input_constrict"]["asset_ref"], "$asset_ref")

    def test_sanitize_rewrites_legacy_image_ref_to_asset_ref(self) -> None:
        intent = {"text": "来张战斗机的图片投到电视上", "source": "voice"}
        plan = [
            {
                "step": 1,
                "capability": "query.content",
                "input_constrict": {"query": "战斗机"},
                "output_constrict": {
                    "image_ref": {"type": "string", "data_dest": "context"}
                },
            },
            {
                "step": 2,
                "capability": "display.photo",
                "input_constrict": {"image_ref": "$image_ref"},
            },
        ]
        cleaned = hb.sanitize_execution_plan(plan, intent)
        self.assertIn("asset_ref", cleaned[0]["output_constrict"])
        self.assertNotIn("image_ref", cleaned[0]["output_constrict"])
        self.assertEqual(cleaned[1]["input_constrict"]["asset_ref"], "$asset_ref")
        self.assertNotIn("image_ref", cleaned[1]["input_constrict"])
        self.assertEqual(cleaned[0]["input_constrict"]["want_image"], "true")

    def test_sanitize_keeps_capture_ref(self) -> None:
        intent = {"text": "拍张照片传到图床", "source": "voice"}
        plan = [
            {
                "step": 1,
                "capability": "camera.capture",
                "output_constrict": {
                    "capture_ref": {"type": "string", "data_dest": "context"}
                },
            },
            {
                "step": 2,
                "capability": "asset.upload",
                "input_constrict": {"capture_ref": "$capture_ref"},
            },
        ]
        cleaned = hb.sanitize_execution_plan(plan, intent)
        self.assertIn("capture_ref", cleaned[0]["output_constrict"])
        self.assertNotIn("asset_ref", cleaned[0]["output_constrict"])
        self.assertEqual(cleaned[1]["input_constrict"]["capture_ref"], "$capture_ref")
        self.assertNotIn("asset_ref", cleaned[1]["input_constrict"])

    def test_sanitize_does_not_rewrite_plain_fact_query(self) -> None:
        intent = {"text": "战斗机是什么", "source": "text"}
        plan = [
            {
                "step": 1,
                "capability": "query.content",
                "input_constrict": {"query": "战斗机是什么"},
                "output_constrict": {
                    "answer_text": {"type": "string", "data_dest": "context"}
                },
            }
        ]
        cleaned = hb.sanitize_execution_plan(plan, intent)
        self.assertEqual(cleaned[0]["input_constrict"]["query"], "战斗机是什么")
        self.assertNotIn("want_image", cleaned[0]["input_constrict"])

    def test_sanitize_strips_llm_notify_speak(self) -> None:
        intent = {"text": "播放歌曲十年", "source": "voice"}
        plan = [
            {"step": 1, "capability": "music.play"},
            {
                "step": 2,
                "capability": "notify.speak",
                "input_constrict": {"text": "$answer_text"},
            },
        ]
        cleaned = hb.sanitize_execution_plan(plan, intent)
        self.assertEqual([s["capability"] for s in cleaned], ["music.play"])

    def test_extract_llm_presentation_keeps_audio_type(self) -> None:
        planned = hb.extract_llm_presentation(
            json.dumps(
                {
                    "presentation": {"type": "audio", "from": "time_text"},
                    "plan": [{"step": 1, "capability": "clock.now"}],
                }
            )
        )
        self.assertEqual(planned.get("type"), "audio")
        self.assertEqual(planned.get("from"), "time_text")
        self.assertTrue(
            hb._planner_wants_speak({"presentation": planned})
        )
        self.assertFalse(
            hb._planner_wants_speak(
                {"presentation": {"type": "text", "from": "time_text"}}
            )
        )

    def test_assemble_presentation_keeps_planner_audio_type(self) -> None:
        pres = hb.assemble_presentation(
            {
                "text": "现在几点了",
                "source": "voice",
                "ctx_param": {"time_text": "中午十二点"},
                "presentation": {"type": "audio", "from": "time_text"},
            }
        )
        self.assertEqual(pres["type"], "audio")
        self.assertEqual(pres["from"], "time_text")
        self.assertEqual(pres["text"], "中午十二点")

    def test_succeeded_does_not_attach_pending_speak_delivery(self) -> None:
        iid = hb.new_intent(
            {
                "status": "running",
                "text": "现在几点了",
                "source": "voice",
                "edge_id": "iphone-1",
                "assigned_edge_id": "edge-mac-laptop",
                "execution_plan": [
                    {
                        "step": 1,
                        "capability": "clock.now",
                        "assigned_edge_id": "edge-mac-laptop",
                    }
                ],
                "ctx_param": {"time_text": "中午十二点"},
                "presentation": {
                    "type": "audio",
                    "from": "time_text",
                },
            }
        )
        client = hb.app.test_client()
        resp = client.post(
            f"/api/v1/intent/{iid}/status",
            json={
                "intent_status": "succeeded",
                "edge_node_id": "edge-mac-laptop",
            },
        )
        self.assertEqual(resp.status_code, 200)
        job = hb.get_intent(iid)
        self.assertEqual(job.get("presentation", {}).get("type"), "audio")
        self.assertFalse(job.get("pending_delivery"))

    def test_keywords_without_planner_audio_have_no_pending_delivery(self) -> None:
        prev = dict(hb._EDGES)
        hb._EDGES = {
            "edge-mac-laptop": {
                "edge_id": "edge-mac-laptop",
                "online_status": "online",
                "schedule_eligible": True,
                "client_hint": "living-room-mac",
                "services": [
                    {
                        "service_id": "local.notify",
                        "capabilities": [{"capability_id": "notify.speak"}],
                    }
                ],
            }
        }
        try:
            iid = hb.new_intent(
                {
                    "status": "running",
                    "text": "现在几点了语音播报",
                    "source": "voice",
                    "ctx_param": {"time_text": "中午十二点"},
                    "presentation": {
                        "type": "text",
                        "from": "time_text",
                        "text": "中午十二点",
                    },
                }
            )
            client = hb.app.test_client()
            client.post(
                f"/api/v1/intent/{iid}/status",
                json={"intent_status": "succeeded"},
            )
            self.assertFalse(hb.get_intent(iid).get("pending_delivery"))
        finally:
            hb._EDGES = prev

    def test_sanitize_photo_without_capture_is_empty(self) -> None:
        intent = {"text": "拍照给我看看", "source": "text"}
        plan = [{"step": 1, "capability": "notify.speak"}]
        self.assertEqual(hb.sanitize_execution_plan(plan, intent), [])

    def test_planner_prompt_does_not_name_capabilities(self) -> None:
        named = (
            "light.set",
            "climate.set",
            "aquarium.set",
            "lock.status",
            "clock.now",
            "math.calculate",
            "notify.speak",
            "voicewakeup.echo",
            "camera.capture",
            "camera.capture_and_upload",
            "asset.upload",
            "music.play",
            "query.content",
            "search.images",
            "display.photo",
            "display.slideshow",
            "vision.perceive",
            "vision.ask",
            "endpoint.present",
            "endpoint.feedback",
            "capabilities.summary",
            "asset.inventory",
            "image.ocr",
        )
        prompt = hb.compact_prompt()
        for name in named:
            self.assertNotIn(name, prompt)
        self.assertFalse(hasattr(hb, "PLANNER_SYSTEM_PROMPT"))

    def test_planner_prompt_trusts_structured_capability_ads(self) -> None:
        prompt = hb.compact_prompt()
        self.assertIn("planner_recognize", prompt)
        self.assertIn("do_not_dispatch", prompt)
        self.assertIn("typical_triggers", prompt)
        self.assertIn("prefer_when", prompt)
        self.assertIn("decomposes_to", prompt)
        self.assertIn("composition", prompt)
        self.assertIn("not** authoritative", prompt)

    def test_planner_prompt_delay_is_not_a_missing_capability(self) -> None:
        prompt = hb.compact_prompt()
        self.assertIn("Scheduling is never a capability gap", prompt)
        self.assertIn("execution_timing.mode", prompt)
        self.assertIn("5分钟后提醒", prompt)
        self.assertNotIn("notify.speak", prompt)

    def test_planner_prompt_has_no_input_placeholders(self) -> None:
        prompt = hb.compact_prompt()
        self.assertNotIn("{USER_INTENT}", prompt)
        self.assertNotIn("{CAPABILITY_REGISTRY}", prompt)
        self.assertNotIn("{OUPUT_SCHEMA}", prompt)
        self.assertIn("last resort", prompt)
        self.assertIn("<capability_id of the local-clock reader>", prompt)
        self.assertIn("**user** message", prompt)

    def test_planner_user_message_carries_intent_and_catalog(self) -> None:
        caps = [
            {
                "capability_id": "clock.now",
                "role": "本机时钟读取器",
                "planner_recognize": "读取本机墙上时钟",
                "typical_triggers": ["现在几点了"],
                "edge_id": "edge-a",
                "display_name": "laptop",
            }
        ]
        msg = hb._planner_user_message(
            user_intent={"text": "现在几点了"},
            memory={"recent_assets": []},
            world_state={"nodes": []},
            capabilities=caps,
            endpoints=[],
            presentation_schema=hb._PLANNER_PRESENTATION_SCHEMA,
            output_schema=hb._PLANNER_OUTPUT_SCHEMA,
            candidates=hb._candidate_capability_rows("现在几点了", caps),
        )
        self.assertIn("现在几点了", msg)
        self.assertIn("clock.now", msg)
        self.assertIn("<Available Capabilities>", msg)
        self.assertIn("<OUTPUT_SCHEMA>", msg)
        self.assertIn("additionalProperties", msg)
        hits = hb._candidate_capability_rows("现在几点了", caps)
        self.assertEqual(hits[0]["capability_id"], "clock.now")

    def test_planner_memory_includes_recent_assets(self) -> None:
        aid = brain_db.put_asset(
            {
                "asset_id": "asset_mem_1",
                "type": "image",
                "status": "available",
            }
        )
        memory = hb._planner_memory({"session_id": "sess-mem"})
        ids = [row["asset_ref"]["asset_id"] for row in memory["recent_assets"]]
        self.assertIn(aid, ids)

    def test_capability_registry_uses_runtime_structured_ads(self) -> None:
        now = time.time()
        brain_db.put_registration(
            {
                "participant_id": "home-server",
                "device_type": "mac",
                "roles": ["runtime"],
            }
        )
        brain_db.put_heartbeat(
            "home-server",
            {
                "online_status": "online",
                "server_received_at": now,
                "reported_at": now,
                "services": [
                    {
                        "service_id": "livingroom.ceiling_light",
                        "group": "light",
                        "capabilities": [
                            {
                                "capability_id": "light.set",
                                "role": "灯光控制器",
                                "planner_recognize": "开关灯 / 调亮度",
                                "typical_triggers": ["开灯", "关灯", "亮度 50"],
                                "do_not_dispatch": ["放歌", "TTS", "拍照"],
                                "input_schema": {
                                    "state": {"type": "string", "required": True}
                                },
                                "output_schema": {"state": {"type": "string"}},
                            }
                        ],
                    }
                ],
            },
        )
        rows = hb._capability_registry_for_prompt()
        light = next(r for r in rows if r["capability_id"] == "light.set")
        self.assertEqual(light["role"], "灯光控制器")
        self.assertEqual(light["planner_recognize"], "开关灯 / 调亮度")
        self.assertIn("开灯", light["typical_triggers"])
        self.assertIn("放歌", light["do_not_dispatch"])
        self.assertEqual(light["input_schema"]["state"]["required"], True)
        self.assertEqual(light.get("composition") or "atomic", "atomic")
        self.assertNotIn("decomposes_to", light)
        self.assertNotIn("prefer_when", light)

    def test_assemble_presentation_light_set_is_text_from_state(self) -> None:
        self._register_endpoint("living-room-iphone-1", "iphone")
        self._heartbeat("living-room-iphone-1")
        intent = {
            "text": "开灯",
            "source": "voice",
            "edge_id": "living-room-iphone-1",
            "presentation": {"type": "text", "from": "state"},
            "execution_plan": [{"step": 1, "capability": "light.set"}],
            "ctx_param": {"state": "on"},
        }
        pres = hb.assemble_presentation(intent)
        self.assertEqual(pres["type"], "audio")
        self.assertEqual(pres["from"], "state")
        self.assertEqual(pres["text"], "on")
        self.assertNotIn("image_url", pres)

    def test_presentation_kind_voice_asset_inventory_is_audio(self) -> None:
        kind, field = hb._presentation_kind_from_plan(
            {
                "source": "voice",
                "text": "一共多少张照片",
                "execution_plan": [{"step": 1, "capability": "asset.inventory"}],
            }
        )
        self.assertEqual(kind, "audio")
        self.assertEqual(field, "answer_text")

    def test_presentation_kind_voice_asset_inventory_cast_stays_image(self) -> None:
        kind, field = hb._presentation_kind_from_plan(
            {
                "source": "voice",
                "text": "把最新照片投到电视上",
                "execution_plan": [
                    {"step": 1, "capability": "asset.inventory"},
                    {"step": 2, "capability": "display.photo"},
                ],
            }
        )
        self.assertEqual(kind, "image")
        self.assertEqual(field, "asset_ref")

    def test_assemble_presentation_voice_inventory_count_is_audio(self) -> None:
        self._register_endpoint("living-room-iphone-1", "iphone")
        self._heartbeat("living-room-iphone-1")
        intent = {
            "text": "一共多少张照片",
            "source": "voice",
            "edge_id": "living-room-iphone-1",
            "execution_plan": [
                {"step": 1, "capability": "asset.inventory"},
                {"step": 2, "capability": "notify.speak"},
            ],
            "ctx_param": {"answer_text": "一共登记了 76 张照片。"},
            "step_outputs": {
                "1": {"answer_text": "一共登记了 76 张照片。", "count": "76"}
            },
        }
        pres = hb.assemble_presentation(intent)
        self.assertEqual(pres["type"], "audio")
        self.assertEqual(pres["from"], "answer_text")
        self.assertEqual(pres["text"], "一共登记了 76 张照片。")

    def test_assemble_presentation_audio_asset_is_audio_not_image(self) -> None:
        """id=617: 「看一下最新的文件」选中一条录音，绝不能按 image 投屏。

        asset.inventory 返回最新的 audio asset 时，呈现必须降为 audio 播放，
        而不是把 audio bytes 当图片发给 image-only 的 iphone.display。
        """
        self._register_endpoint("living-room-iphone-1", "iphone")
        self._heartbeat("living-room-iphone-1")
        intent = {
            "text": "看一下最新的文件",
            "source": "voice",
            "edge_id": "living-room-iphone-1",
            "execution_plan": [{"step": 1, "capability": "asset.inventory"}],
            "presentation": {"type": "image", "from": "asset_ref"},
            "ctx_param": {
                "answer_text": "一共登记了 101 个资源。",
                "asset_ref": {
                    "asset_id": "asset_7745313f74241faed0649382",
                    "type": "audio",
                    "mime_type": "audio/mp4",
                },
            },
        }
        pres = hb.assemble_presentation(intent)
        self.assertEqual(pres["type"], "audio")
        self.assertEqual(pres["from"], "asset_ref")
        self.assertEqual(pres["asset_ref"]["type"], "audio")

    def test_assemble_presentation_image_asset_stays_image(self) -> None:
        """回归：id=590「看一下最新的照片」仍是 image presentation，不被误判。"""
        self._register_endpoint("living-room-iphone-1", "iphone")
        self._heartbeat("living-room-iphone-1")
        intent = {
            "text": "看一下最新的照片",
            "source": "voice",
            "edge_id": "living-room-iphone-1",
            "execution_plan": [{"step": 1, "capability": "asset.inventory"}],
            "presentation": {"type": "image", "from": "asset_ref"},
            "ctx_param": {
                "answer_text": "这是按登记顺序的第 1 张照片。",
                "asset_ref": {
                    "asset_id": "asset_27831fac7836c08db4c542cc",
                    "type": "image",
                    "mime_type": "image/png",
                },
            },
        }
        pres = hb.assemble_presentation(intent)
        self.assertEqual(pres["type"], "image")
        self.assertEqual(pres["from"], "asset_ref")
        self.assertEqual(pres["asset_ref"]["type"], "image")

    def test_assemble_presentation_document_asset_is_document_preview(self) -> None:
        """id=637: 「看下最新的pdf文档」应 document 预览，不是 answer_text。"""
        self._register_endpoint("living-room-iphone-1", "iphone")
        self._heartbeat("living-room-iphone-1")
        intent = {
            "text": "看下最新的pdf文档",
            "source": "text",
            "edge_id": "living-room-iphone-1",
            "execution_plan": [{"step": 1, "capability": "asset.inventory"}],
            "presentation": {"type": "text", "from": "answer_text"},
            "ctx_param": {
                "answer_text": "这是按登记顺序的第 1 张document。",
                "asset_ref": {
                    "asset_id": "asset_05563d7eb33dbf460a0be521",
                    "type": "document",
                    "mime_type": "application/pdf",
                },
            },
        }
        pres = hb.assemble_presentation(intent)
        self.assertEqual(pres["type"], "document")
        self.assertEqual(pres["from"], "asset_ref")
        self.assertEqual(pres["asset_ref"]["type"], "document")
        self.assertEqual(pres["asset_ref"]["asset_id"], "asset_05563d7eb33dbf460a0be521")

    def test_normalize_presentation_plan_keeps_document(self) -> None:
        """#677: planner 的 document 骨架不能被归一化丢掉（prompt/schema 都列了 document）。"""
        planned = hb._normalize_presentation_plan({"type": "document", "from": "asset_ref"})
        self.assertEqual(planned.get("type"), "document")
        self.assertEqual(planned.get("from"), "asset_ref")

    def test_extract_llm_presentation_keeps_document_type(self) -> None:
        planned = hb.extract_llm_presentation(
            json.dumps(
                {
                    "goal": "把最新的URL转成PDF",
                    "presentation": {"type": "document", "from": "asset_ref"},
                }
            )
        )
        self.assertEqual(planned.get("type"), "document")

    def test_presentation_kind_url_to_pdf_keeps_document(self) -> None:
        """#677: planner 明确要 document 预览时，asset.inventory 分支不得改回 answer_text。"""
        kind, field = hb._presentation_kind_from_plan(
            {
                "text": "把最新的URL转成PDF",
                "source": "text",
                "presentation": {"type": "document", "from": "asset_ref"},
                "execution_plan": [
                    {
                        "step": 1,
                        "capability": "asset.inventory",
                        "output_constrict": {"asset_ref": {"type": "object"}},
                    },
                    {
                        "step": 2,
                        "capability": "web.scraper",
                        "output_constrict": {"asset_ref": {"type": "object"}},
                    },
                ],
            }
        )
        self.assertEqual(kind, "document")
        self.assertEqual(field, "asset_ref")

    def test_assemble_presentation_url_asset_is_not_document_preview(self) -> None:
        """#677: inventory 交出的 type=url 资产不能被当 PDF 预览。"""
        self._register_endpoint("living-room-iphone-1", "iphone")
        self._heartbeat("living-room-iphone-1")
        intent = {
            "intent_id": 677,
            "text": "把最新的URL转成PDF",
            "source": "text",
            "edge_id": "living-room-iphone-1",
            "presentation": {"type": "document", "from": "asset_ref"},
            "execution_plan": [{"step": 1, "capability": "asset.inventory"}],
            "ctx_param": {
                "answer_text": "这是按登记顺序的第 1 张url。",
                "asset_ref": {
                    "asset_id": "asset_url_link_1",
                    "type": "url",
                    "mime_type": "text/uri-list",
                },
            },
        }
        pres = hb.assemble_presentation(intent)
        self.assertEqual(pres["type"], "text")
        self.assertEqual(pres["text"], "这是按登记顺序的第 1 张url。")
        self.assertNotIn("asset_ref", pres)

    def test_assemble_presentation_document_type_image_asset_still_shows_image(self) -> None:
        """planner 说 document 但命中 image（如「看一下最新的文件」最新是照片）→ 仍展示图片，不因 #677 守卫退成文字。"""
        self._register_endpoint("living-room-iphone-1", "iphone")
        self._heartbeat("living-room-iphone-1")
        intent = {
            "intent_id": 680,
            "text": "看一下最新的文件",
            "source": "text",
            "edge_id": "living-room-iphone-1",
            "presentation": {"type": "document", "from": "asset_ref"},
            "execution_plan": [{"step": 1, "capability": "asset.inventory"}],
            "ctx_param": {
                "answer_text": "这是按登记顺序的第 1 张image。",
                "asset_ref": {
                    "asset_id": "asset_img_680",
                    "type": "image",
                    "mime_type": "image/jpeg",
                },
            },
        }
        pres = hb.assemble_presentation(intent)
        self.assertEqual(pres["type"], "image")
        self.assertEqual(pres["asset_ref"]["asset_id"], "asset_img_680")

    def test_assemble_presentation_intent_document_is_previewed(self) -> None:
        """#677: 本 intent 新产出的 PDF 必须在发起端预览，而不是只回 inventory 文案。"""
        self._register_endpoint("living-room-iphone-1", "iphone")
        self._heartbeat("living-room-iphone-1")
        brain_db.put_asset(
            {
                "asset_id": "asset_pdf_677",
                "type": "document",
                "mime_type": "application/pdf",
                "status": "available",
                "producer_capability": "web.scraper",
                "origin_intent_id": "677",
            }
        )
        intent = {
            "intent_id": 677,
            "text": "把最新的URL转成PDF",
            "source": "text",
            "edge_id": "living-room-iphone-1",
            "execution_plan": [
                {"step": 1, "capability": "asset.inventory"},
                {"step": 2, "capability": "web.scraper"},
            ],
            "ctx_param": {
                "answer_text": "这是按登记顺序的第 1 张url。",
                "asset_ref": {
                    "asset_id": "asset_pdf_677",
                    "type": "document",
                    "mime_type": "application/pdf",
                },
            },
        }
        pres = hb.assemble_presentation(intent)
        self.assertEqual(pres["type"], "document")
        self.assertEqual(pres["from"], "asset_ref")
        self.assertEqual(pres["asset_ref"]["asset_id"], "asset_pdf_677")
        self.assertEqual(pres["endpoint"], "living-room-iphone-1")

    def test_assemble_presentation_voice_intent_document_stays_spoken(self) -> None:
        """voice 发起「转成PDF」保持「念一句」的对称交付，不抢成静态文档。"""
        self._register_endpoint("living-room-iphone-1", "iphone")
        self._heartbeat("living-room-iphone-1")
        brain_db.put_asset(
            {
                "asset_id": "asset_pdf_678",
                "type": "document",
                "mime_type": "application/pdf",
                "status": "available",
                "producer_capability": "web.scraper",
                "origin_intent_id": "678",
            }
        )
        intent = {
            "intent_id": 678,
            "text": "把最新的URL转成PDF",
            "source": "voice",
            "edge_id": "living-room-iphone-1",
            "execution_plan": [
                {"step": 1, "capability": "asset.inventory"},
                {"step": 2, "capability": "web.scraper"},
            ],
            "ctx_param": {
                "answer_text": "已从最新链接抓取正文并转成 PDF。",
                "asset_ref": {
                    "asset_id": "asset_pdf_678",
                    "type": "document",
                    "mime_type": "application/pdf",
                },
            },
        }
        pres = hb.assemble_presentation(intent)
        self.assertEqual(pres["type"], "audio")
        self.assertEqual(pres["from"], "answer_text")

    def test_assemble_presentation_other_intent_document_not_auto_previewed(self) -> None:
        """别人登记的文档（origin_intent_id 不是本 intent）不因本次执行被自动预览。"""
        self._register_endpoint("living-room-iphone-1", "iphone")
        self._heartbeat("living-room-iphone-1")
        brain_db.put_asset(
            {
                "asset_id": "asset_pdf_other",
                "type": "document",
                "mime_type": "application/pdf",
                "status": "available",
                "origin_intent_id": "601",
            }
        )
        intent = {
            "intent_id": 679,
            "text": "把这份PDF打印出来",
            "source": "text",
            "edge_id": "living-room-iphone-1",
            "execution_plan": [
                {"step": 1, "capability": "asset.inventory"},
                {"step": 2, "capability": "printer.print"},
            ],
            "ctx_param": {
                "answer_text": "已把这份 PDF 发到打印机。",
                "asset_ref": {
                    "asset_id": "asset_pdf_other",
                    "type": "document",
                    "mime_type": "application/pdf",
                },
            },
        }
        pres = hb.assemble_presentation(intent)
        self.assertEqual(pres["type"], "text")
        self.assertEqual(pres["from"], "answer_text")

    def test_assemble_presentation_inventory_count_stays_text(self) -> None:
        """盘点数量不问「看」，仍走 answer_text，不升 document。"""
        self._register_endpoint("living-room-iphone-1", "iphone")
        self._heartbeat("living-room-iphone-1")
        intent = {
            "text": "今天拍了几张照片",
            "source": "text",
            "edge_id": "living-room-iphone-1",
            "execution_plan": [{"step": 1, "capability": "asset.inventory"}],
            "presentation": {"type": "text", "from": "answer_text"},
            "ctx_param": {
                "answer_text": "一共登记了 3 张照片。",
                "count": "3",
            },
        }
        pres = hb.assemble_presentation(intent)
        self.assertEqual(pres["type"], "text")
        self.assertEqual(pres["from"], "answer_text")
        self.assertNotIn("asset_ref", pres)

    def test_presentation_kind_infers_math_calculate(self) -> None:
        kind, field = hb._presentation_kind_from_plan(
            {"execution_plan": [{"step": 1, "capability": "math.calculate"}]}
        )
        self.assertEqual(kind, "text")
        self.assertEqual(field, "answer_text")

    def test_presentation_kind_infers_climate_set(self) -> None:
        kind, field = hb._presentation_kind_from_plan(
            {"execution_plan": [{"step": 1, "capability": "climate.set"}]}
        )
        self.assertEqual(kind, "text")
        self.assertEqual(field, "status_text")

    def test_presentation_kind_infers_aquarium_and_lock(self) -> None:
        kind, field = hb._presentation_kind_from_plan(
            {"execution_plan": [{"step": 1, "capability": "aquarium.set"}]}
        )
        self.assertEqual(kind, "text")
        self.assertEqual(field, "status_text")
        kind, field = hb._presentation_kind_from_plan(
            {"execution_plan": [{"step": 1, "capability": "lock.status"}]}
        )
        self.assertEqual(kind, "text")
        self.assertEqual(field, "status_text")

    def test_assemble_presentation_image_for_voice(self) -> None:
        brain_db.put_registration(
            {
                "participant_id": "living-room-iphone-1",
                "device_type": "iphone",
                "roles": ["intent_source", "endpoint"],
                "endpoints": [
                    {
                        "endpoint_id": "iphone.display",
                        "supported_presentation": ["image", "text"],
                    }
                ],
            }
        )
        self._heartbeat("living-room-iphone-1")
        intent = {
            "text": "拍张照片我看一下",
            "source": "voice",
            "edge_id": "living-room-iphone-1",
            "status": "succeeded",
            "ctx_param": {"asset_ref": dict(_CAPTURE_REF)},
        }
        pres = hb.assemble_presentation(intent)
        self.assertEqual(pres["type"], "image")
        self.assertEqual(pres["from"], "asset_ref")
        self.assertEqual(pres["channel"], "iphone")
        self.assertEqual(pres["endpoint"], "living-room-iphone-1")
        self.assertEqual(pres["endpoint_id"], "iphone.display")
        self.assertEqual(pres["asset_ref"], _CAPTURE_REF)
        self.assertNotIn("image_url", pres)
        self.assertNotIn("photo_url", pres)
        got = hb._job_to_intent(intent)
        self.assertEqual(got["presentation"]["type"], "image")
        self.assertEqual(got["presentation"]["endpoint"], "living-room-iphone-1")
        self.assertEqual(got["presentation"]["asset_ref"], _CAPTURE_REF)

    def test_assemble_presentation_follows_planner_type_not_photo_url(self) -> None:
        self._register_endpoint("living-room-iphone-1", "iphone")
        self._heartbeat("living-room-iphone-1")
        intent = {
            "text": "客厅里有几个人",
            "source": "voice",
            "edge_id": "living-room-iphone-1",
            "presentation": {"type": "text", "from": "summary"},
            "execution_plan": [
                {"step": 1, "capability": "camera.capture"},
                {"step": 2, "capability": "vision.perceive"},
            ],
            "ctx_param": {
                "photo_url": "http://example/p.jpg",
                "asset_ref": dict(_CAPTURE_REF),
                "summary": "客厅内一名男子在书桌前。",
            },
        }
        pres = hb.assemble_presentation(intent)
        self.assertEqual(pres["type"], "text")
        self.assertEqual(pres["from"], "summary")
        self.assertEqual(pres["text"], "客厅内一名男子在书桌前。")
        self.assertNotIn("image_url", pres)
        self.assertNotIn("asset_ref", pres)

    def test_assemble_presentation_text_plan_does_not_show_photo_while_waiting(self) -> None:
        self._register_endpoint("living-room-iphone-1", "iphone")
        self._heartbeat("living-room-iphone-1")
        intent = {
            "text": "how many people",
            "source": "voice",
            "edge_id": "living-room-iphone-1",
            "presentation": {"type": "text", "from": "summary"},
            "execution_plan": [
                {"step": 1, "capability": "camera.capture"},
                {"step": 2, "capability": "vision.perceive"},
            ],
            "ctx_param": {
                "photo_url": "http://example/p.jpg",
                "asset_ref": dict(_CAPTURE_REF),
            },
        }
        pres = hb.assemble_presentation(intent)
        self.assertEqual(pres["type"], "text")
        self.assertNotIn("image_url", pres)
        self.assertNotIn("asset_ref", pres)

    def test_assemble_presentation_perceive_plan_is_text_without_keywords(self) -> None:
        self._register_endpoint("living-room-iphone-1", "iphone")
        self._heartbeat("living-room-iphone-1")
        intent = {
            "text": "look at the room",
            "source": "voice",
            "edge_id": "living-room-iphone-1",
            "execution_plan": [
                {"step": 1, "capability": "camera.capture"},
                {"step": 2, "capability": "vision.perceive"},
            ],
            "ctx_param": {
                "photo_url": "http://example/p.jpg",
                "asset_ref": dict(_CAPTURE_REF),
                "summary": "one person at the desk",
            },
        }
        pres = hb.assemble_presentation(intent)
        self.assertEqual(pres["type"], "text")
        self.assertEqual(pres["text"], "one person at the desk")
        self.assertNotIn("asset_ref", pres)

    def test_assemble_presentation_ignores_stale_image_output_when_plan_is_perceive(self) -> None:
        self._register_endpoint("living-room-iphone-1", "iphone")
        self._heartbeat("living-room-iphone-1")
        intent = {
            "text": "look at the room",
            "source": "voice",
            "edge_id": "living-room-iphone-1",
            "presentation": {
                "type": "image",
                "image_url": "http://example/p.jpg",
                "channel": "iphone",
            },
            "execution_plan": [
                {"step": 1, "capability": "camera.capture"},
                {"step": 2, "capability": "vision.perceive"},
            ],
            "ctx_param": {
                "photo_url": "http://example/p.jpg",
                "asset_ref": dict(_CAPTURE_REF),
                "summary": "one person at the desk",
            },
        }
        pres = hb.assemble_presentation(intent)
        self.assertEqual(pres["type"], "text")
        self.assertEqual(pres["text"], "one person at the desk")
        self.assertNotIn("asset_ref", pres)

    def test_extract_llm_presentation(self) -> None:
        raw = json.dumps(
            {
                "plan": [{"step": 1, "capability": "camera.capture"}],
                "presentation": {"type": "image", "from": "asset_ref"},
            }
        )
        self.assertEqual(
            hb.extract_llm_presentation(raw),
            {"type": "image", "from": "asset_ref"},
        )

    def test_assemble_presentation_ignores_photo_url(self) -> None:
        self._register_endpoint("living-room-iphone-1", "iphone")
        self._heartbeat("living-room-iphone-1")
        intent = {
            "text": "拍张照片我看一下",
            "source": "voice",
            "edge_id": "living-room-iphone-1",
            "ctx_param": {"photo_url": "http://example/p.jpg"},
        }
        pres = hb.assemble_presentation(intent)
        self.assertIsNone(pres)

    def test_extract_llm_capability_notes_empty_and_normalized(self) -> None:
        empty = hb.extract_llm_capability_notes('{"plan":[]}')
        self.assertEqual(empty["missing_capabilities"], [])
        self.assertEqual(empty["better_capabilities"], [])
        raw = json.dumps(
            {
                "missing_capabilities": ["vacuum.clean"],
                "better_capabilities": [
                    {"capability": "light.dim", "reason": "need brightness"}
                ],
            }
        )
        notes = hb.extract_llm_capability_notes(raw)
        self.assertEqual(
            notes["missing_capabilities"],
            [{"capability": "vacuum.clean", "reason": ""}],
        )
        self.assertEqual(
            notes["better_capabilities"],
            [{"capability": "light.dim", "reason": "need brightness"}],
        )

    def test_job_to_intent_attaches_planner_notes(self) -> None:
        iid = hb.new_intent(
            {
                "status": "intent_parsed",
                "text": "clean the floor",
                "status_log": [],
            }
        )
        hb._record_intent_review(
            iid,
            text="clean the floor",
            parsed={
                "missing_capabilities": [
                    {"capability": "robot.vacuum", "reason": "no advertised cleaner"}
                ],
                "better_capabilities": [],
            },
        )
        got = hb.get_intent(iid)
        self.assertEqual(got["missing_capabilities"][0]["capability"], "robot.vacuum")
        self.assertEqual(got["better_capabilities"], [])

    def test_planner_notes_fallback_to_raw_when_parsed_is_plan_list(self) -> None:
        iid = hb.new_intent(
            {
                "status": "intent_parsed",
                "text": "how far is 14000 km",
                "status_log": [],
            }
        )
        hb._record_intent_review(
            iid,
            text="how far is 14000 km",
            parsed=[{"step": 1, "capability": "query.content"}],
            raw=json.dumps(
                {
                    "plan": [{"step": 1, "capability": "query.content"}],
                    "missing_capabilities": [],
                    "better_capabilities": [
                        {"capability": "geo.distance", "reason": "need a distance explainer"}
                    ],
                }
            ),
        )
        got = hb.get_intent(iid)
        self.assertEqual(got["missing_capabilities"], [])
        self.assertEqual(got["better_capabilities"][0]["capability"], "geo.distance")

    def test_get_intent_drops_null_context_fields(self) -> None:
        iid = hb.new_intent(
            {
                "status": "failed",
                "text": "how far",
                "status_log": [],
                "ctx_param": {"answer_text": None, "summary": "ok"},
            }
        )
        got = hb.get_intent(iid)
        self.assertNotIn("answer_text", got["ctx_param"])
        self.assertEqual(got["ctx_param"]["summary"], "ok")

    def test_status_update_missing_intent_returns_404(self) -> None:
        client = hb.app.test_client()
        resp = client.post(
            "/api/v1/intent/999999/status",
            json={"intent_status": "running", "edge_node_id": "edge-test"},
        )
        self.assertEqual(resp.status_code, 404, resp.get_json())
        self.assertIn("intent not exist", resp.get_json().get("err_msg", ""))

    def test_step_status_missing_intent_returns_404(self) -> None:
        client = hb.app.test_client()
        resp = client.post(
            "/api/v1/intent/999999/step/1/status",
            json={"step_status": "1", "edge_node_id": "edge-test"},
        )
        self.assertEqual(resp.status_code, 404, resp.get_json())
        self.assertIn("intent not exist", resp.get_json().get("err_msg", ""))

    def test_intent_detail_missing_returns_404(self) -> None:
        client = hb.app.test_client()
        resp = client.get("/api/v1/intent_detail?intent_id=999999")
        self.assertEqual(resp.status_code, 404, resp.get_json())
        self.assertIn("intent not exist", resp.get_json().get("err_msg", ""))

    def test_status_does_not_regress_from_failed(self) -> None:
        iid = hb.new_intent(
            {
                "status": "failed",
                "text": "how far",
                "status_log": [],
                "msg": "timeout",
            }
        )
        client = hb.app.test_client()
        resp = client.post(
            f"/api/v1/intent/{iid}/status",
            json={"intent_status": "running"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("terminal", resp.get_json().get("err_msg", ""))
        got = hb.get_intent(iid)
        self.assertEqual(got["status"], "failed")
        self.assertEqual(got["msg"], "timeout")
        running = [row for row in got["status_log"] if row.get("status") == "running"]
        self.assertEqual(running, [])

    def test_step_status_does_not_regress_from_failed(self) -> None:
        iid = hb.new_intent(
            {
                "status": "running",
                "text": "how far",
                "status_log": [],
                "execution_plan": [
                    {
                        "step": 1,
                        "capability": "query.content",
                        "status": 3,
                        "msg": "timeout",
                    }
                ],
            }
        )
        client = hb.app.test_client()
        resp = client.post(
            f"/api/v1/intent/{iid}/step/1/status",
            json={"step_status": "1"},
        )
        self.assertIn("terminal", resp.get_json().get("err_msg", ""))
        got = hb.get_intent(iid)
        self.assertEqual(got["execution_plan"][0]["status"], 3)
        self.assertEqual(got["execution_plan"][0]["msg"], "timeout")
        self.assertEqual(
            [row.get("status") for row in got.get("step_log") or []],
            [],
        )

    def test_step_running_rejected_when_intent_failed(self) -> None:
        iid = hb.new_intent(
            {
                "status": "failed",
                "text": "how far",
                "msg": "timeout",
                "status_log": [],
                "execution_plan": [
                    {"step": 1, "capability": "query.content", "status": 3}
                ],
            }
        )
        client = hb.app.test_client()
        resp = client.post(
            f"/api/v1/intent/{iid}/step/1/status",
            json={"step_status": "1"},
        )
        self.assertIn("terminal", resp.get_json().get("err_msg", ""))
        got = hb.get_intent(iid)
        self.assertEqual(got["status"], "failed")
        self.assertEqual(got["execution_plan"][0]["status"], 3)

    def test_failed_capture_fails_intent_without_waiting_upload(self) -> None:
        iid = hb.new_intent(
            {
                "status": "running",
                "text": "拍张照片我看一下",
                "status_log": [{"status": "running", "ts": 1}],
                "execution_plan": [
                    {
                        "step": 1,
                        "capability": "camera.capture",
                        "assigned_edge_id": "iphone-1",
                        "output_constrict": {
                            "capture_ref": {"data_dest": "context", "type": "string"}
                        },
                    },
                    {
                        "step": 2,
                        "capability": "asset.upload",
                        "assigned_edge_id": "iphone-1",
                        "input_constrict": {"capture_ref": "$capture_ref"},
                        "output_constrict": {
                            "asset_ref": {"data_dest": "context", "type": "string"}
                        },
                    },
                ],
            }
        )
        client = hb.app.test_client()
        msg = "拍照不可用：连不上 GoPro timeout"
        resp = client.post(
            f"/api/v1/intent/{iid}/step/1/status",
            json={
                "step_status": "3",
                "edge_node_id": "iphone-1",
                "msg": msg,
                "outputs": {},
            },
        )
        self.assertEqual(resp.status_code, 200)
        got = hb.get_intent(iid)
        self.assertEqual(got["status"], "failed")
        self.assertEqual(got["msg"], msg)
        self.assertEqual(got["error"], msg)
        self.assertEqual(int(got["execution_plan"][0]["status"]), 3)
        self.assertEqual(int(got["execution_plan"][1]["status"]), 3)
        self.assertEqual(
            got["execution_plan"][1].get("msg"),
            hb._PENDING_STEP_ABANDONED_MSG,
        )
        self.assertEqual(got["presentation"]["from"], "msg")
        self.assertEqual(got["presentation"]["text"], msg)
        self.assertIn("failed", [row.get("status") for row in got.get("status_log") or []])

    def test_upload_failure_after_capture_success_reports_upload_not_capture(self) -> None:
        iid = hb.new_intent(
            {
                "status": "running",
                "text": "拍张照片传到云上",
                "status_log": [{"status": "running", "ts": 1}],
                "execution_plan": [
                    {
                        "step": 1,
                        "capability": "camera.capture",
                        "assigned_edge_id": "iphone-1",
                        "output_constrict": {
                            "capture_ref": {"data_dest": "context", "type": "string"}
                        },
                    },
                    {
                        "step": 2,
                        "capability": "asset.upload",
                        "assigned_edge_id": "iphone-1",
                        "input_constrict": {"capture_ref": "$capture_ref"},
                        "output_constrict": {
                            "asset_ref": {"data_dest": "context", "type": "string"}
                        },
                    },
                ],
            }
        )
        client = hb.app.test_client()
        # Step 1 (capture) succeeds and yields a capture_ref.
        resp1 = client.post(
            f"/api/v1/intent/{iid}/step/1/status",
            json={
                "step_status": "2",
                "edge_node_id": "iphone-1",
                "outputs": {
                    "capture_ref": '{"capture_id":"cap_abc123","type":"image","mime_type":"image/jpeg"}'
                },
            },
        )
        self.assertEqual(resp1.status_code, 200)
        # Step 2 (upload) fails.
        upload_msg = "上传失败：上传 HTTP 500：boom"
        resp2 = client.post(
            f"/api/v1/intent/{iid}/step/2/status",
            json={
                "step_status": "3",
                "edge_node_id": "iphone-1",
                "msg": upload_msg,
                "outputs": {},
            },
        )
        self.assertEqual(resp2.status_code, 200)
        got = hb.get_intent(iid)
        self.assertEqual(got["status"], "failed")
        # Capture step stayed succeeded; only the upload step failed.
        self.assertEqual(int(got["execution_plan"][0]["status"]), 2)
        self.assertEqual(int(got["execution_plan"][1]["status"]), 3)
        # The user-facing msg must reflect the UPLOAD failure, never "拍照失败",
        # and must acknowledge the capture succeeded and is kept locally.
        self.assertNotIn("拍照失败", got["msg"])
        self.assertIn("上传", got["msg"])
        self.assertIn("拍照成功", got["msg"])
        self.assertEqual(got["presentation"]["text"], got["msg"])

    def test_get_intent_heals_stuck_running_after_step_fail(self) -> None:
        msg = "拍照不可用：连不上 GoPro timeout"
        iid = hb.new_intent(
            {
                "status": "running",
                "text": "拍张照片我看一下",
                "msg": msg,
                "error": msg,
                "status_log": [{"status": "running", "ts": 1}],
                "execution_plan": [
                    {
                        "step": 1,
                        "capability": "camera.capture",
                        "status": 3,
                        "msg": msg,
                    },
                    {
                        "step": 2,
                        "capability": "asset.upload",
                    },
                ],
            }
        )
        got = hb.get_intent(iid)
        self.assertEqual(got["status"], "failed")
        self.assertEqual(got["msg"], msg)
        self.assertEqual(int(got["execution_plan"][1]["status"]), 3)
        stored = brain_db.get_job(iid)
        self.assertEqual(stored["status"], "failed")

    def test_assemble_presentation_endpoint_is_not_issuer_unless_endpoint_role(self) -> None:
        brain_db.put_registration(
            {
                "participant_id": "mac-runtime",
                "device_type": "mac",
                "roles": ["runtime"],
                "services": [{"service_id": "local.notify", "capabilities": []}],
            }
        )
        brain_db.put_registration(
            {
                "participant_id": "kindle-1",
                "device_type": "kindle",
                "roles": ["endpoint"],
                "endpoints": [
                    {
                        "endpoint_id": "kindle_browser",
                        "supported_presentation": ["html", "text", "image"],
                    }
                ],
            }
        )
        self._heartbeat("kindle-1")
        intent = {
            "text": "现在几点了",
            "source": "text",
            "edge_id": "mac-runtime",
            "ctx_param": {"time_text": "22:00"},
        }
        pres = hb.assemble_presentation(intent)
        self.assertEqual(pres["endpoint"], "kindle-1")
        self.assertEqual(pres["channel"], "kindle")
        self.assertNotEqual(pres["endpoint"], intent["edge_id"])

    def test_assemble_presentation_music_play_text_falls_to_live_display(self) -> None:
        """Intent 119 shape: voice from Mac (not Endpoint) + music.play on Chromecast.

        Top-level presentation.channel=chromecast is Response Target fallback,
        not proof that Cast / display.photo ran. music.play has empty outputs.
        """
        brain_db.put_registration(
            {
                "participant_id": "edge-mac",
                "device_type": "mac",
                "roles": ["intent_source", "runtime"],
                "intent_sources": [{"source_id": "mac.usb_microphone", "channel": "voice"}],
            }
        )
        brain_db.put_registration(
            {
                "participant_id": "edge-cast",
                "device_type": "chromecast",
                "roles": ["runtime", "endpoint"],
                "endpoints": [
                    {
                        "endpoint_id": "chromecast.display",
                        "supported_presentation": ["image", "text", "video"],
                    }
                ],
                "services": [
                    {
                        "service_id": "netease.music",
                        "capabilities": [{"capability_id": "music.play"}],
                    }
                ],
            }
        )
        self._heartbeat("edge-mac")
        self._heartbeat("edge-cast")
        intent = {
            "text": "播放歌曲同桌的你。",
            "source": "voice",
            "edge_id": "edge-mac",
            "output_affinity": {
                "participant_id": "edge-mac",
                "reason": "input_source",
            },
            "execution_plan": [
                {
                    "step": 1,
                    "capability": "music.play",
                    "assigned_edge_id": "edge-cast",
                    "status": 2,
                }
            ],
            "step_outputs": {"1": {}},
            "presentation": {"type": "text"},
            "status": "succeeded",
        }
        pres = hb.assemble_presentation(intent)
        self.assertEqual(pres["type"], "text")
        self.assertNotIn("text", pres)
        self.assertEqual(pres["endpoint"], "edge-cast")
        self.assertEqual(pres["endpoint_id"], "chromecast.display")
        self.assertEqual(pres["channel"], "chromecast")

    def test_assemble_presentation_unregistered_issuer_has_empty_endpoint(self) -> None:
        intent = {
            "text": "现在几点了",
            "source": "voice",
            "participant_id": "unknown-poster",
            "ctx_param": {"time_text": "22:00"},
        }
        pres = hb.assemble_presentation(intent)
        self.assertEqual(pres["type"], "text")
        self.assertEqual(pres["endpoint"], "")
        self.assertEqual(pres["text"], "22:00")

    def _register_endpoint(self, pid: str, device_type: str) -> None:
        brain_db.put_registration(
            {
                "participant_id": pid,
                "device_type": device_type,
                "roles": ["endpoint"],
                "endpoints": [
                    {
                        "endpoint_id": f"{device_type}.display",
                        "supported_presentation": ["image", "text"],
                    }
                ],
            }
        )

    def test_assemble_presentation_picks_newer_heartbeat(self) -> None:
        self._register_endpoint("kindle-stale", "kindle")
        self._register_endpoint("kindle-fresh", "kindle")
        self._heartbeat("kindle-stale", age_sec=hb.ENDPOINT_TTL_SEC + 5)
        self._heartbeat("kindle-fresh", age_sec=1)
        intent = {
            "text": "现在几点了",
            "source": "text",
            "edge_id": "mac-runtime",
            "ctx_param": {"time_text": "22:00"},
        }
        pres = hb.assemble_presentation(intent)
        self.assertEqual(pres["endpoint"], "kindle-fresh")

    def test_assemble_presentation_endpoint_ttl_is_not_runtime_online_ttl(self) -> None:
        self._register_endpoint("iphone-recent", "iphone")
        self._heartbeat("iphone-recent", age_sec=hb.ONLINE_TTL_SEC + 5)
        intent = {
            "text": "拍张照片我看一下",
            "source": "voice",
            "edge_id": "iphone-recent",
            "ctx_param": {"asset_ref": dict(_CAPTURE_REF)},
        }
        pres = hb.assemble_presentation(intent)
        self.assertGreater(hb.ENDPOINT_TTL_SEC, hb.ONLINE_TTL_SEC)
        self.assertEqual(pres["endpoint"], "iphone-recent")

    def test_assemble_presentation_issuer_endpoint_needs_live_heartbeat(self) -> None:
        self._register_endpoint("iphone-source", "iphone")
        intent = {
            "text": "现在几点了语音播报",
            "source": "voice",
            "edge_id": "iphone-source",
            "ctx_param": {"time_text": "22:00"},
        }
        pres = hb.assemble_presentation(intent)
        self.assertEqual(pres["endpoint"], "")

        self._heartbeat("iphone-source")
        pres = hb.assemble_presentation(intent)
        self.assertEqual(pres["endpoint"], "iphone-source")
        self.assertEqual(pres["channel"], "iphone")

    def test_assemble_presentation_stale_issuer_falls_back_to_live_endpoint(self) -> None:
        self._register_endpoint("iphone-stale", "iphone")
        self._register_endpoint("kindle-live", "kindle")
        self._heartbeat("iphone-stale", age_sec=hb.ENDPOINT_TTL_SEC + 10)
        self._heartbeat("kindle-live", age_sec=0)
        intent = {
            "text": "拍张照片我看一下",
            "source": "voice",
            "edge_id": "iphone-stale",
            "ctx_param": {"asset_ref": dict(_CAPTURE_REF)},
        }
        pres = hb.assemble_presentation(intent)
        self.assertEqual(pres["endpoint"], "kindle-live")
        self.assertEqual(pres["channel"], "kindle")

    def test_assemble_presentation_stale_issuer_endpoint_alone_is_empty(self) -> None:
        self._register_endpoint("iphone-stale", "iphone")
        self._heartbeat("iphone-stale", age_sec=hb.ENDPOINT_TTL_SEC + 10)
        intent = {
            "text": "拍张照片我看一下",
            "source": "voice",
            "edge_id": "iphone-stale",
            "ctx_param": {"asset_ref": dict(_CAPTURE_REF)},
        }
        pres = hb.assemble_presentation(intent)
        self.assertEqual(pres["endpoint"], "")

    def test_assemble_presentation_never_heartbeated_endpoint_is_empty(self) -> None:
        self._register_endpoint("kindle-silent", "kindle")
        intent = {
            "text": "现在几点了",
            "source": "text",
            "participant_id": "mac-runtime",
            "ctx_param": {"time_text": "22:00"},
        }
        pres = hb.assemble_presentation(intent)
        self.assertEqual(pres["endpoint"], "")

    def test_assemble_presentation_prefers_input_source_over_newer_endpoint(self) -> None:
        self._register_live_issuer("iphone-origin")
        self._register_endpoint("kindle-fresh", "kindle")
        self._heartbeat("kindle-fresh", age_sec=0)
        intent = {
            "text": "现在几点了",
            "source": "voice",
            "edge_id": "iphone-origin",
            "ctx_param": {"time_text": "22:00"},
        }
        pres = hb.assemble_presentation(intent)
        self.assertEqual(pres["endpoint"], "iphone-origin")
        self.assertEqual(pres["channel"], "iphone")

    def test_assemble_presentation_audio_stays_on_iphone_display(self) -> None:
        """iPhone Endpoint ads image/text, not audio. Voice reply must still land there."""
        self._register_live_issuer("iphone-origin")
        self._register_endpoint("kindle-fresh", "kindle")
        self._heartbeat("kindle-fresh", age_sec=0)
        intent = {
            "text": "现在几点了",
            "source": "voice",
            "edge_id": "iphone-origin",
            "presentation": {"type": "audio", "from": "time_text"},
            "ctx_param": {"time_text": "晚上七点"},
        }
        pres = hb.assemble_presentation(intent)
        self.assertEqual(pres["type"], "audio")
        self.assertEqual(pres["endpoint"], "iphone-origin")
        self.assertNotEqual(pres["endpoint"], "kindle-fresh")
        self.assertEqual(pres["text"], "晚上七点")

    def test_assemble_presentation_execution_target_is_not_response_target(self) -> None:
        self._register_live_issuer("iphone-origin")
        self._register_endpoint("kindle-live", "kindle")
        self._heartbeat("kindle-live")
        intent = {
            "text": "拍张照片我看一下",
            "source": "voice",
            "edge_id": "iphone-origin",
            "execution_plan": [
                {
                    "step": 1,
                    "capability": "camera.capture",
                    "assigned_edge_id": "gopro-1",
                }
            ],
            "ctx_param": {"asset_ref": dict(_CAPTURE_REF)},
        }
        pres = hb.assemble_presentation(intent)
        self.assertEqual(pres["type"], "image")
        self.assertEqual(pres["endpoint"], "iphone-origin")
        self.assertNotEqual(pres["endpoint"], "gopro-1")
        self.assertNotEqual(pres["endpoint"], "kindle-live")

    def test_assemble_presentation_explicit_tv_overrides_source_affinity(self) -> None:
        self._register_live_issuer("iphone-origin")
        brain_db.put_registration(
            {
                "participant_id": "living-tv",
                "device_type": "chromecast",
                "roles": ["endpoint"],
                "endpoints": [
                    {
                        "endpoint_id": "living_room_tv",
                        "supported_presentation": ["image", "text"],
                    }
                ],
            }
        )
        self._heartbeat("living-tv")
        intent = {
            "text": "把这张照片显示到电视上",
            "source": "text",
            "edge_id": "iphone-origin",
            "presentation": {"type": "image", "from": "asset_ref"},
            "ctx_param": {"asset_ref": dict(_CAPTURE_REF)},
        }
        pres = hb.assemble_presentation(intent)
        self.assertEqual(pres["endpoint"], "living-tv")
        self.assertEqual(pres["endpoint_id"], "living_room_tv")

    def test_post_intent_records_source_context(self) -> None:
        self._register_live_issuer("iphone-origin")
        client = hb.app.test_client()
        resp = client.post(
            "/api/v1/intent",
            json={
                "text": "现在几点了",
                "source": "voice",
                "participant_id": "iphone-origin",
                "session_id": "sess-1",
            },
        )
        self.assertEqual(resp.status_code, 200, resp.get_json())
        job = brain_db.get_job(resp.get_json()["intent_id"])
        assert job is not None
        ctx = job.get("ctx_param") or {}
        self.assertEqual(ctx.get("session_id") or job.get("session_id"), "sess-1")
        src_ctx = ctx.get("source_context") or job.get("source_context") or {}
        self.assertEqual(src_ctx["device_id"], "iphone-origin")
        self.assertEqual(src_ctx["endpoint_id"], "microphone")
        self.assertEqual(src_ctx["capability_id"], "voice.input")
        affinity = ctx.get("output_affinity") or job.get("output_affinity") or {}
        self.assertEqual(affinity["participant_id"], "iphone-origin")
        self.assertEqual(affinity["reason"], "input_source")
        detail = hb.get_intent(resp.get_json()["intent_id"])
        self.assertEqual(detail["source_context"]["device_id"], "iphone-origin")
        self.assertEqual(detail["output_affinity"]["reason"], "input_source")

    def test_voice_from_iphone_does_not_speak_on_unrelated_mac(self) -> None:
        self._register_live_issuer("iphone-origin")
        self._register_voice_runtime("mac-speaker")
        iid = hb.new_intent(
            {
                "status": "intent_received",
                "text": "现在几点了",
                "source": "voice",
                "edge_id": "iphone-origin",
                "presentation": {"type": "audio", "from": "time_text"},
            }
        )
        hb.do_execution_plan(
            iid,
            [
                {
                    "step": 1,
                    "capability": "clock.now",
                    "assigned_edge_id": "mac-speaker",
                    "input_constrict": {},
                    "output_constrict": {"time_text": {}},
                }
            ],
        )
        plan = hb.get_intent(iid)["execution_plan"]
        speak = [s for s in plan if s.get("capability") == "notify.speak"]
        self.assertEqual(speak, [])
        # clock.now is kind=system: Brain reads its own clock in-process, so the
        # step is reassigned to the system edge regardless of the incoming hint.
        self.assertEqual(plan[0]["capability"], "clock.now")
        self.assertEqual(plan[0]["assigned_edge_id"], "system")

    def test_post_intent_accepts_participant_id(self) -> None:
        self._register_live_issuer("iphone-origin")
        client = hb.app.test_client()
        resp = client.post(
            "/api/v1/intent",
            json={
                "text": "拍张照片我看一下",
                "source": "voice",
                "participant_id": "iphone-origin",
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["edge_id"], "iphone-origin")
        job = brain_db.get_job(body["intent_id"])
        assert job is not None
        self.assertEqual(job["edge_id"], "iphone-origin")
        self.assertEqual(job["source"], "voice")

    def test_post_intent_rejects_missing_unregistered_and_stale_issuer(self) -> None:
        client = hb.app.test_client()
        missing = client.post("/api/v1/intent", json={"text": "现在几点了"})
        self.assertEqual(missing.status_code, 400)
        self.assertIn("register and heartbeat", missing.get_json()["error"])

        unknown = client.post(
            "/api/v1/intent",
            json={"text": "现在几点了", "participant_id": "no-such-phone"},
        )
        self.assertEqual(unknown.status_code, 401)
        self.assertIn("register first", unknown.get_json()["error"])

        self._register_endpoint("iphone-silent", "iphone")
        silent = client.post(
            "/api/v1/intent",
            json={"text": "现在几点了", "participant_id": "iphone-silent"},
        )
        self.assertEqual(silent.status_code, 403)
        self.assertIn("heartbeat required", silent.get_json()["error"])

        self._heartbeat("iphone-silent", age_sec=hb.ENDPOINT_TTL_SEC + 10)
        stale = client.post(
            "/api/v1/intent",
            json={"text": "现在几点了", "participant_id": "iphone-silent"},
        )
        self.assertEqual(stale.status_code, 403)

        self._heartbeat("iphone-silent", schedule_eligible=False)
        skewed = client.post(
            "/api/v1/intent",
            json={"text": "现在几点了", "participant_id": "iphone-silent"},
        )
        self.assertEqual(skewed.status_code, 403)

        self._heartbeat("iphone-silent")
        no_source = client.post(
            "/api/v1/intent",
            json={"text": "现在几点了", "participant_id": "iphone-silent"},
        )
        self.assertEqual(no_source.status_code, 403)
        self.assertIn("intent_source", no_source.get_json()["error"])

        self._register_live_issuer("iphone-ok")
        ok = client.post(
            "/api/v1/intent",
            json={"text": "现在几点了", "participant_id": "iphone-ok"},
        )
        self.assertEqual(ok.status_code, 200)
        self.assertTrue(ok.get_json()["ok"])

        self._heartbeat("iphone-ok", schedule_eligible=False)
        clock = client.post(
            "/api/v1/intent",
            json={"text": "现在几点了", "participant_id": "iphone-ok"},
        )
        self.assertEqual(clock.status_code, 403)
        self.assertIn("schedule_eligible", clock.get_json()["error"])

    def test_list_intents_by_participant_caps_limit_at_five(self) -> None:
        pid = "iphone-origin"
        for i in range(1, 9):
            brain_db.put_job(
                {
                    "intent_id": i,
                    "id": i,
                    "status": "succeeded",
                    "text": f"t{i}",
                    "source": "voice",
                    "edge_id": pid if i != 3 else "other-phone",
                }
            )
        client = hb.app.test_client()
        missing = client.get("/api/v1/intents")
        self.assertEqual(missing.status_code, 400)
        huge = client.get(
            "/api/v1/intents",
            query_string={"participant_id": pid, "limit": 99},
        )
        self.assertEqual(huge.status_code, 200)
        body = huge.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["limit"], 5)
        ids = [int(row["intent_id"]) for row in body["intents"]]
        self.assertEqual(ids, [8, 7, 6, 5, 4])
        self.assertEqual(body["next_before_id"], 4)
        self.assertFalse(body["exhausted"])
        page2 = client.get(
            "/api/v1/intents",
            query_string={"participant_id": pid, "before_id": 4, "limit": 5},
        )
        body2 = page2.get_json()
        ids2 = [int(row["intent_id"]) for row in body2["intents"]]
        self.assertEqual(ids2, [2, 1])
        self.assertTrue(body2["exhausted"])

    def test_assets_register_and_fetch_with_grant(self) -> None:
        client = hb.app.test_client()
        reg = client.post(
            "/api/v1/assets",
            json={
                "asset_id": "asset_test1",
                "type": "image",
                "mime_type": "image/jpeg",
                "intent_id": "77",
                "execution_id": "77",
                "producer": "camera.capture",
                "storage": {
                    "backend": "img_server",
                    "key": "pic.jpg",
                    "preview_key": "pic_preview.jpg",
                    "cloud_preview_key": "pic_preview.jpg",
                    "public_base": "http://192.168.3.65:8080",
                    "cloud_public_base": "http://115.190.153.53:8080",
                    "cloud_key": "pic.jpg",
                },
            },
        )
        self.assertEqual(reg.status_code, 200)
        reg_body = reg.get_json()
        self.assertTrue(reg_body.get("ok"))
        self.assertEqual(reg_body.get("asset_id"), "asset_test1")
        listed = client.get("/api/v1/assets?type=image&intent_id=77")
        self.assertEqual(listed.status_code, 200)
        list_body = listed.get_json()
        self.assertTrue(list_body.get("ok"))
        self.assertGreaterEqual(int(list_body.get("count") or 0), 1)
        aids = [
            (row.get("asset_ref") or {}).get("asset_id")
            for row in (list_body.get("assets") or [])
        ]
        self.assertIn("asset_test1", aids)
        reg_asset = reg_body.get("asset") or {}
        self.assertNotIn("storage", reg_asset)
        self.assertIn("stream", reg_asset)
        self.assertIn("/content", reg_asset["stream"].get("href", ""))
        meta_only = client.get("/api/v1/assets/asset_test1")
        self.assertEqual(meta_only.status_code, 200)
        self.assertNotIn("storage", meta_only.get_json().get("asset") or {})
        with_grant = client.get("/api/v1/assets/asset_test1?intent_id=77")
        self.assertEqual(with_grant.status_code, 200)
        wg = with_grant.get_json()
        asset = wg.get("asset") or {}
        self.assertNotIn("storage", asset)
        self.assertIn("stream", asset)
        self.assertIn("representation=preview", asset["stream"].get("href", ""))
        self.assertNotIn("image_url", asset)
        self._register_runtime("mac-runtime-asset")
        runtime = client.get(
            "/api/v1/assets/asset_test1?intent_id=77&edge_id=mac-runtime-asset"
        )
        self.assertEqual(runtime.status_code, 200)
        rt_asset = runtime.get_json().get("asset") or {}
        storage = rt_asset.get("storage") or {}
        self.assertEqual(storage.get("backend"), "img_server")
        self.assertEqual(storage.get("key"), "pic.jpg")
        self.assertNotIn("url", storage)
        denied = client.get("/api/v1/assets/asset_test1/content")
        self.assertEqual(denied.status_code, 403)

    def test_parse_asset_day_window_yesterday(self) -> None:
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("Asia/Shanghai")
        now = datetime.now(tz)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        yday_start = today_start - timedelta(days=1)
        window = hb._parse_asset_day_window("yesterday", "Asia/Shanghai")
        self.assertIsNotNone(window)
        start, end = window
        self.assertAlmostEqual(start, yday_start.timestamp(), delta=2)
        self.assertAlmostEqual(end, today_start.timestamp(), delta=2)
        self.assertEqual(
            hb._parse_asset_day_window("昨天", "Asia/Shanghai"),
            window,
        )
        self.assertIsNone(hb._parse_asset_day_window("yesterday_from_$now_iso", None))

    def test_assets_list_day_yesterday(self) -> None:
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("Asia/Shanghai")
        yday_noon = datetime.now(tz).replace(
            hour=12, minute=0, second=0, microsecond=0
        ) - timedelta(days=1)
        brain_db.put_asset(
            {
                "asset_id": "asset_yday1",
                "type": "image",
                "mime_type": "image/jpeg",
                "status": "available",
                "producer_capability": "camera.capture",
                "intent_id": "88",
                "created_at": yday_noon.timestamp(),
                "storage": {"backend": "img_server", "key": "yday.jpg"},
            }
        )
        client = hb.app.test_client()
        listed = client.get("/api/v1/assets?type=image&day=yesterday")
        self.assertEqual(listed.status_code, 200)
        body = listed.get_json()
        self.assertTrue(body.get("ok"))
        aids = [
            (row.get("asset_ref") or {}).get("asset_id")
            for row in (body.get("assets") or [])
        ]
        self.assertIn("asset_yday1", aids)
        today = client.get("/api/v1/assets?type=image&day=today")
        self.assertEqual(today.status_code, 200)
        today_aids = [
            (row.get("asset_ref") or {}).get("asset_id")
            for row in (today.get_json().get("assets") or [])
        ]
        self.assertNotIn("asset_yday1", today_aids)
        bad = client.get("/api/v1/assets?day=yesterday_from_$now_iso")
        self.assertEqual(bad.status_code, 400)
        self.assertIn("yesterday", str(bad.get_json().get("error") or ""))

    def test_asset_content_streams_bytes(self) -> None:
        from unittest.mock import MagicMock, patch

        client = hb.app.test_client()
        client.post(
            "/api/v1/assets",
            json={
                "asset_id": "asset_stream1",
                "type": "image",
                "mime_type": "image/png",
                "intent_id": "88",
                "execution_id": "88",
                "storage": {
                    "backend": "img_server",
                    "key": "x.png",
                    "cloud_public_base": "http://115.190.153.53:8080",
                    "cloud_key": "x.png",
                },
            },
        )
        fake = MagicMock()
        fake.headers = {"Content-Type": "image/png", "Content-Length": "8"}
        fake.read.side_effect = [b"\x89PNG\r\n\x1a\n", b""]
        fake.close = MagicMock()
        with patch("urllib.request.urlopen", return_value=fake):
            resp = client.get("/api/v1/assets/asset_stream1/content?intent_id=88")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content_type.split(";")[0], "image/png")
        self.assertEqual(resp.data, b"\x89PNG\r\n\x1a\n")

    def test_inventory_presentation_grants_content_for_older_asset(self) -> None:
        """intent 103 style: asset.inventory shows a photo from another intent."""
        from unittest.mock import MagicMock, patch

        client = hb.app.test_client()
        client.post(
            "/api/v1/assets",
            json={
                "asset_id": "asset_old_photo",
                "type": "image",
                "mime_type": "image/png",
                "intent_id": "1",
                "execution_id": "1",
                "storage": {
                    "backend": "img_server",
                    "key": "old.png",
                    "cloud_public_base": "http://example.invalid",
                    "cloud_key": "old.png",
                },
            },
        )
        self.assertFalse(brain_db.has_asset_grant("asset_old_photo", 103))
        brain_db.put_job(
            {
                "intent_id": 103,
                "id": 103,
                "status": "succeeded",
                "text": "我看一下最新的一张照片",
                "source": "voice",
                "presentation": {
                    "type": "image",
                    "from": "asset_ref",
                    "asset_ref": {
                        "asset_id": "asset_old_photo",
                        "type": "image",
                        "mime_type": "image/png",
                    },
                },
            }
        )
        fake = MagicMock()
        fake.headers = {"Content-Type": "image/png", "Content-Length": "8"}
        fake.read.side_effect = [b"\x89PNG\r\n\x1a\n", b""]
        fake.close = MagicMock()
        with patch("urllib.request.urlopen", return_value=fake):
            denied = client.get("/api/v1/assets/asset_old_photo/content")
            resp = client.get(
                "/api/v1/assets/asset_old_photo/content?intent_id=103"
            )
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data, b"\x89PNG\r\n\x1a\n")
        self.assertTrue(brain_db.has_asset_grant("asset_old_photo", 103))

    def test_do_execution_plan_grants_input_asset_ref(self) -> None:
        """intent 194 style: planner binds an older iPhone photo into a later step."""
        self._register_runtime("mac-runtime-read", cap="reading.point_to_character")
        brain_db.put_asset(
            {
                "asset_id": "asset_iphone_photo",
                "type": "image",
                "mime_type": "image/jpeg",
                "status": "available",
                "producer_capability": "iphone.photo",
                "producer_edge_id": "iphone-origin",
                "storage": {
                    "backend": "img_server",
                    "key": "photo.jpg",
                    "public_base": "http://192.168.0.88:8080",
                },
            }
        )
        iid = hb.new_intent(
            {
                "status": "intent_received",
                "text": "最新的照片里面手指的是哪个字",
                "source": "voice",
                "edge_id": "iphone-origin",
            }
        )
        self.assertFalse(brain_db.has_asset_grant("asset_iphone_photo", iid))
        hb.do_execution_plan(
            iid,
            [
                {
                    "step": 1,
                    "capability": "reading.point_to_character",
                    "assigned_edge_id": "mac-runtime-read",
                    "input_constrict": {
                        "asset_ref": {
                            "asset_id": "asset_iphone_photo",
                            "type": "image",
                            "mime_type": "image/jpeg",
                        }
                    },
                    "output_constrict": {"answer_text": {}, "character": {}},
                }
            ],
        )
        self.assertTrue(brain_db.has_asset_grant("asset_iphone_photo", iid))
        client = hb.app.test_client()
        runtime = client.get(
            f"/api/v1/assets/asset_iphone_photo?intent_id={iid}&edge_id=mac-runtime-read"
        )
        self.assertEqual(runtime.status_code, 200)
        storage = (runtime.get_json().get("asset") or {}).get("storage") or {}
        self.assertEqual(storage.get("backend"), "img_server")
        self.assertEqual(storage.get("key"), "photo.jpg")

    def test_assemble_presentation_grants_shown_asset_ref(self) -> None:
        brain_db.put_asset(
            {
                "asset_id": "asset_shown",
                "type": "image",
                "mime_type": "image/png",
                "intent_id": "1",
                "status": "available",
            }
        )
        intent = {
            "id": 501,
            "intent_id": 501,
            "text": "看最新照片",
            "presentation": {"type": "image", "from": "asset_ref"},
            "execution_plan": [{"step": 1, "capability": "asset.inventory"}],
            "step_outputs": {
                "1": {
                    "asset_ref": {
                        "asset_id": "asset_shown",
                        "type": "image",
                        "mime_type": "image/png",
                    }
                }
            },
        }
        pres = hb.assemble_presentation(intent)
        self.assertEqual(pres["asset_ref"]["asset_id"], "asset_shown")
        self.assertTrue(brain_db.has_asset_grant("asset_shown", 501))

    def test_asset_preview_only_content(self) -> None:
        from unittest.mock import MagicMock, patch

        client = hb.app.test_client()
        client.post(
            "/api/v1/assets",
            json={
                "asset_id": "asset_preview_only",
                "type": "image",
                "mime_type": "image/jpeg",
                "intent_id": "90",
                "execution_id": "90",
                "storage": {
                    "backend": "img_server",
                    "preview_key": "prev.jpg",
                    "cloud_public_base": "http://115.190.153.53:8080",
                    "cloud_preview_key": "prev.jpg",
                },
            },
        )
        fake = MagicMock()
        fake.headers = {"Content-Type": "image/jpeg", "Content-Length": "3"}
        fake.read.side_effect = [b"\xff\xd8\xff", b""]
        fake.close = MagicMock()
        with patch("urllib.request.urlopen", return_value=fake):
            resp = client.get(
                "/api/v1/assets/asset_preview_only/content?intent_id=90&representation=preview"
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data, b"\xff\xd8\xff")
        with patch("urllib.request.urlopen", return_value=fake):
            orig = client.get(
                "/api/v1/assets/asset_preview_only/content?intent_id=90&representation=original"
            )
        self.assertEqual(orig.status_code, 502)

    def test_as_asset_ref_unwraps_json_string_from_edge(self) -> None:
        """Edge often reports asset_ref as a JSON string; that string is not the asset_id."""
        blob = json.dumps(_CAPTURE_REF)
        self.assertEqual(hb._as_asset_ref(blob), _CAPTURE_REF)
        nested = {"asset_id": blob, "type": "image"}
        self.assertEqual(hb._as_asset_ref(nested)["asset_id"], _CAPTURE_REF["asset_id"])

    def test_assemble_presentation_unwraps_string_asset_ref(self) -> None:
        """intent 1422: context.asset_ref was a JSON string; clients then 404 on that blob as path."""
        self._register_endpoint("living-room-iphone-1", "iphone")
        self._heartbeat("living-room-iphone-1")
        blob = json.dumps(
            {
                "asset_id": "asset_5960bdc9868317150b7188d9",
                "mime_type": "image/jpeg",
                "type": "image",
            }
        )
        intent = {
            "text": "拍照",
            "source": "voice",
            "edge_id": "living-room-iphone-1",
            "status": "succeeded",
            "execution_plan": [{"step": 1, "capability": "camera.capture"}],
            "ctx_param": {"asset_ref": blob},
            "step_outputs": {
                "1": {
                    "asset_id": "asset_5960bdc9868317150b7188d9",
                    "asset_ref": blob,
                }
            },
        }
        pres = hb.assemble_presentation(intent)
        self.assertEqual(pres["type"], "image")
        self.assertEqual(
            pres["asset_ref"]["asset_id"], "asset_5960bdc9868317150b7188d9"
        )
        self.assertFalse(str(pres["asset_ref"]["asset_id"]).startswith("{"))

    def test_assemble_presentation_never_emits_image_url(self) -> None:
        self._register_endpoint("living-room-iphone-1", "iphone")
        self._heartbeat("living-room-iphone-1")
        intent = {
            "text": "拍张照片我看一下",
            "source": "voice",
            "edge_id": "living-room-iphone-1",
            "presentation": {
                "type": "image",
                "from": "asset_ref",
                "image_url": "http://evil.example/x.jpg",
                "photo_url": "http://evil.example/y.jpg",
            },
            "execution_plan": [{"step": 1, "capability": "camera.capture"}],
            "ctx_param": {"asset_ref": dict(_CAPTURE_REF)},
        }
        pres = hb.assemble_presentation(intent)
        self.assertEqual(pres["type"], "image")
        self.assertEqual(pres["from"], "asset_ref")
        self.assertEqual(pres["asset_ref"], _CAPTURE_REF)
        self.assertNotIn("image_url", pres)
        self.assertNotIn("photo_url", pres)

    def test_assemble_presentation_image_from_asset_refs_list(self) -> None:
        """intent 479 style: inventory only wrote asset_refs[]; still show an image."""
        self._register_endpoint("living-room-iphone-1", "iphone")
        self._heartbeat("living-room-iphone-1")
        refs = [
            {"asset_id": "asset_1", "type": "image"},
            {"asset_id": "asset_2", "type": "image"},
            {"asset_id": "asset_3", "type": "image"},
            {"asset_id": "asset_4", "type": "image"},
            {"asset_id": "asset_5", "type": "image"},
        ]
        intent = {
            "text": "给我看一下拍的第五张照片",
            "source": "voice",
            "edge_id": "living-room-iphone-1",
            "presentation": {"type": "image", "from": "asset_ref", "channel": "iphone"},
            "execution_plan": [{"step": 1, "capability": "asset.inventory"}],
            "ctx_param": {
                "answer_text": "一共登记了 107 张照片。",
                "asset_refs": json.dumps(refs, ensure_ascii=False),
            },
            "step_outputs": {
                "1": {
                    "answer_text": "一共登记了 107 张照片。",
                    "asset_refs": json.dumps(refs, ensure_ascii=False),
                    "count": "107",
                }
            },
        }
        pres = hb.assemble_presentation(intent)
        self.assertEqual(pres["type"], "image")
        self.assertEqual(pres["from"], "asset_ref")
        self.assertEqual(pres["asset_ref"]["asset_id"], "asset_5")
        self.assertNotEqual(pres.get("text"), "一共登记了 107 张照片。")

    def _register_runtime(self, pid: str, cap: str = "camera.capture") -> None:
        brain_db.put_registration(
            {
                "participant_id": pid,
                "display_name": "客厅 Mac",
                "device_type": "mac",
                "roles": ["runtime"],
                "services": [
                    {
                        "service_id": "gopro.camera",
                        "group": "camera",
                        "capabilities": [
                            {
                                "capability_id": cap,
                                "input_schema": {},
                                "output_schema": {},
                            }
                        ],
                    }
                ],
            }
        )
        self._heartbeat(pid)
        hb._REGISTERED_edges = brain_db.registration_ids()
        hb.rebuild_capability_maps()

    def test_music_play_prefers_mac_over_android_issuer(self) -> None:
        music_svc = {
            "service_id": "netease.music",
            "display_name": "网易云音乐",
            "capabilities": [{"capability_id": "music.play"}],
        }
        brain_db.put_registration(
            {
                "participant_id": "android-music",
                "device_type": "android",
                "roles": ["runtime", "intent_source"],
                "services": [music_svc],
            }
        )
        brain_db.put_registration(
            {
                "participant_id": "mac-music",
                "device_type": "mac",
                "client_hint": "living-room-mac",
                "roles": ["runtime"],
                "services": [music_svc],
            }
        )
        self._heartbeat("android-music")
        self._heartbeat("mac-music")
        hb._REGISTERED_edges = brain_db.registration_ids()
        hb.rebuild_capability_maps()
        step = {"step": 1, "capability": "music.play"}
        intent = {"text": "播放陈奕迅的十年", "edge_id": "android-music"}
        assigned = hb._assign_runtime_edge_id(step, "music.play", intent)
        self.assertEqual(assigned, "mac-music")

    def test_shortcut_music_play_skips_llm_prefers_mac(self) -> None:
        music_svc = {
            "service_id": "netease.music",
            "display_name": "网易云音乐",
            "capabilities": [{"capability_id": "music.play"}],
        }
        brain_db.put_registration(
            {
                "participant_id": "android-music",
                "device_type": "android",
                "roles": ["runtime", "intent_source"],
                "services": [music_svc],
            }
        )
        brain_db.put_registration(
            {
                "participant_id": "mac-music",
                "device_type": "mac",
                "client_hint": "living-room-mac",
                "roles": ["runtime"],
                "services": [music_svc],
            }
        )
        self._heartbeat("android-music")
        self._heartbeat("mac-music")
        hb._REGISTERED_edges = brain_db.registration_ids()
        hb.rebuild_capability_maps()
        client = hb.app.test_client()
        before_qsize = hb.task_queue.qsize()
        resp = client.post(
            "/api/v1/intent",
            json={
                "text": "播放陈奕迅的十年",
                "source": "voice",
                "participant_id": "android-music",
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["intent_status"], "intent_parsed")
        self.assertEqual(body["task_kind"], "shortcut")
        self.assertEqual(hb.task_queue.qsize(), before_qsize)
        plan = hb.get_intent(body["intent_id"])["execution_plan"]
        self.assertEqual(plan[0]["capability"], "music.play")
        self.assertEqual(plan[0]["assigned_edge_id"], "mac-music")
        ic = plan[0]["input_constrict"]
        self.assertEqual(ic.get("song"), "陈奕迅的十年")
        self.assertEqual(ic.get("user_input"), "播放陈奕迅的十年")
        self.assertEqual(ic.get("participant_id"), "android-music")
        self.assertEqual(ic.get("intent_id"), str(body["intent_id"]))
        reviews = brain_db.list_intent_reviews(body["intent_id"])
        shortcut = next(row for row in reviews if row.get("planner") == "shortcut")
        payload = shortcut.get("request_payload") or shortcut.get("request_json") or {}
        if isinstance(payload, str):
            payload = json.loads(payload)
        timing = payload.get("timing") or {}
        self.assertIn("match", timing)
        self.assertIn("plan", timing)
        self.assertIn("enqueue", timing)

    def test_ncm_play_issuer_prefers_source_device_id(self) -> None:
        self.assertEqual(
            hb._ncm_play_issuer_id(
                {
                    "edge_id": "mac-music",
                    "participant_id": "mac-music",
                    "source_context": {"device_id": "iphone-origin"},
                }
            ),
            "iphone-origin",
        )
        self.assertEqual(
            hb._ncm_play_issuer_id({"edge_id": "android-music"}),
            "android-music",
        )

    def test_do_execution_plan_stamps_music_play_issuer(self) -> None:
        music_svc = {
            "service_id": "netease.music",
            "display_name": "网易云音乐",
            "capabilities": [{"capability_id": "music.play"}],
        }
        brain_db.put_registration(
            {
                "participant_id": "iphone-origin",
                "device_type": "iphone",
                "roles": ["intent_source"],
                "services": [],
            }
        )
        brain_db.put_registration(
            {
                "participant_id": "mac-music",
                "device_type": "mac",
                "client_hint": "living-room-mac",
                "roles": ["runtime"],
                "services": [music_svc],
            }
        )
        self._heartbeat("mac-music")
        hb._REGISTERED_edges = brain_db.registration_ids()
        hb.rebuild_capability_maps()
        iid = hb.new_intent(
            {
                "status": "intent_received",
                "text": "播放十年",
                "source": "text",
                "edge_id": "mac-music",
                "ctx_param": {
                    "source_context": {"device_id": "iphone-origin"},
                },
            }
        )
        hb.do_execution_plan(
            iid,
            [
                {
                    "step": 1,
                    "capability": "music.play",
                    "assigned_edge_id": "mac-music",
                    "input_constrict": {"song": "十年"},
                    "output_constrict": {},
                }
            ],
        )
        play = next(
            s
            for s in hb.get_intent(iid)["execution_plan"]
            if s.get("capability") == "music.play"
        )
        ic = play["input_constrict"]
        self.assertEqual(ic.get("participant_id"), "iphone-origin")
        self.assertEqual(ic.get("intent_id"), str(iid))
        self.assertEqual(ic.get("song"), "十年")

    def test_shortcut_music_transport_skips_llm_not_play(self) -> None:
        music_svc = {
            "service_id": "netease.music",
            "display_name": "网易云音乐",
            "capabilities": [
                {"capability_id": "music.play"},
                {"capability_id": "music.pause"},
                {"capability_id": "music.stop"},
                {"capability_id": "music.next"},
            ],
        }
        brain_db.put_registration(
            {
                "participant_id": "android-music",
                "device_type": "android",
                "roles": ["runtime", "intent_source"],
                "services": [music_svc],
            }
        )
        brain_db.put_registration(
            {
                "participant_id": "mac-music",
                "device_type": "mac",
                "client_hint": "living-room-mac",
                "roles": ["runtime"],
                "services": [music_svc],
            }
        )
        self._heartbeat("android-music")
        self._heartbeat("mac-music")
        hb._REGISTERED_edges = brain_db.registration_ids()
        hb.rebuild_capability_maps()
        client = hb.app.test_client()
        before_qsize = hb.task_queue.qsize()
        cases = (
            ("停止播放", "music.stop"),
            ("暂停播放", "music.pause"),
            ("切歌", "music.next"),
        )
        for text, cap in cases:
            with self.subTest(text=text):
                resp = client.post(
                    "/api/v1/intent",
                    json={
                        "text": text,
                        "source": "voice",
                        "participant_id": "android-music",
                    },
                )
                self.assertEqual(resp.status_code, 200)
                body = resp.get_json()
                self.assertEqual(body["intent_status"], "intent_parsed")
                self.assertEqual(body["task_kind"], "shortcut")
                self.assertEqual(hb.task_queue.qsize(), before_qsize)
                plan = hb.get_intent(body["intent_id"])["execution_plan"]
                self.assertEqual(plan[0]["capability"], cap)
                self.assertEqual(plan[0]["assigned_edge_id"], "mac-music")
                self.assertEqual(plan[0]["input_constrict"].get("user_input"), text)
                self.assertNotIn("song", plan[0]["input_constrict"])

    def test_shortcut_tv_pdf_page_skips_llm(self) -> None:
        self._register_live_issuer("iphone-origin")
        brain_db.put_registration(
            {
                "participant_id": "mac-edge",
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
        self._heartbeat("mac-edge")
        hb._REGISTERED_edges = brain_db.registration_ids()
        hb.rebuild_capability_maps()
        client = hb.app.test_client()
        before_qsize = hb.task_queue.qsize()
        for text, action in (("电视下一页", "next"), ("电视上一页", "prev")):
            with self.subTest(text=text):
                resp = client.post(
                    "/api/v1/intent",
                    json={
                        "text": text,
                        "source": "voice",
                        "participant_id": "iphone-origin",
                    },
                )
                self.assertEqual(resp.status_code, 200)
                body = resp.get_json()
                self.assertEqual(body["intent_status"], "intent_parsed")
                self.assertEqual(body["task_kind"], "shortcut")
                self.assertEqual(hb.task_queue.qsize(), before_qsize)
                plan = hb.get_intent(body["intent_id"])["execution_plan"]
                self.assertEqual(plan[0]["capability"], "display.pdf.page")
                self.assertEqual(plan[0]["input_constrict"].get("action"), action)
                self.assertEqual(plan[0]["assigned_edge_id"], "mac-edge")

    def _register_voice_runtime(
        self, pid: str, *, with_speak: bool = True, with_echo: bool = True
    ) -> None:
        caps = [
            {
                "capability_id": "voice.stream",
                "kind": "input",
                "input_schema": {},
                "output_schema": {},
            }
        ]
        if with_echo:
            caps.append(
                {
                    "capability_id": "voicewakeup.echo",
                    "kind": "output",
                    "input_schema": {},
                    "output_schema": {},
                }
            )
        services = [
            {
                "service_id": "local.voice",
                "group": "voice",
                "capabilities": caps,
            }
        ]
        if with_speak:
            services.append(
                {
                    "service_id": "local.notify",
                    "group": "notify",
                    "capabilities": [
                        {
                            "capability_id": "notify.speak",
                            "kind": "output",
                            "input_schema": {},
                            "output_schema": {},
                        }
                    ],
                }
            )
        brain_db.put_registration(
            {
                "participant_id": pid,
                "display_name": "客厅 Mac",
                "device_type": "mac",
                "client_hint": "living-room-mac",
                "roles": ["runtime"],
                "services": services,
            }
        )
        self._heartbeat(pid)
        brain_db.put_heartbeat(
            pid,
            {
                "online_status": "online",
                "server_received_at": time.time(),
                "reported_at": time.time(),
                "schedule_eligible": True,
                "services": services,
            },
        )
        hb._REGISTERED_edges = brain_db.registration_ids()
        hb.rebuild_capability_maps()

    def test_voice_wake_does_not_create_an_intent(self) -> None:
        self._register_voice_runtime("mac-voice-1")
        client = hb.app.test_client()
        queued = hb.task_queue.qsize()
        resp = client.post(
            "/api/v1/voice/wake",
            json={"event": "wake", "participant_id": "mac-voice-1"},
        )
        self.assertEqual(resp.status_code, 200, resp.get_json())
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["text"], "我在呢")
        self.assertEqual(body["echo"], "我在呢")
        self.assertEqual(body["edge_id"], "mac-voice-1")
        self.assertTrue(body["local"])
        self.assertIsNone(body.get("intent_id"))
        self.assertEqual(hb.task_queue.qsize(), queued)
        self.assertNotIn("execution_plan", body)

    def test_voice_settings_default_and_admin_update(self) -> None:
        client = hb.app.test_client()
        pub = client.get("/api/v1/voice/settings")
        self.assertEqual(pub.status_code, 200, pub.get_json())
        self.assertEqual(pub.get_json()["wake_ack"], "我在呢")

        admin_get = client.get("/api/v1/admin/voice/settings")
        self.assertEqual(admin_get.status_code, 200)
        self.assertEqual(admin_get.get_json()["wake_ack"], "我在呢")

        updated = client.put(
            "/api/v1/admin/voice/settings",
            json={"wake_ack": "来了"},
        )
        self.assertEqual(updated.status_code, 200, updated.get_json())
        self.assertEqual(updated.get_json()["wake_ack"], "来了")

        self._register_voice_runtime("mac-voice-1")
        wake = client.post(
            "/api/v1/voice/wake",
            json={"event": "wake", "participant_id": "mac-voice-1"},
        )
        self.assertEqual(wake.get_json()["echo"], "来了")

        self._register_live_issuer("iphone-origin")
        reject = client.post(
            "/api/v1/intent",
            json={
                "text": "来了",
                "source": "voice",
                "participant_id": "iphone-origin",
            },
        )
        self.assertEqual(reject.status_code, 400)

    def test_admin_voice_settings_rejects_empty(self) -> None:
        client = hb.app.test_client()
        bad = client.put("/api/v1/admin/voice/settings", json={"wake_ack": "  "})
        self.assertEqual(bad.status_code, 400)

    def test_post_intent_rejects_wake_ack_utterance(self) -> None:
        self._register_live_issuer("iphone-origin")
        client = hb.app.test_client()
        resp = client.post(
            "/api/v1/intent",
            json={
                "text": "又咋了",
                "source": "voice",
                "participant_id": "iphone-origin",
            },
        )
        self.assertEqual(resp.status_code, 400, resp.get_json())
        self.assertIn("不进入意图理解", resp.get_json()["error"])
        punct = client.post(
            "/api/v1/intent",
            json={
                "text": "又咋了？",
                "source": "voice",
                "participant_id": "iphone-origin",
            },
        )
        self.assertEqual(punct.status_code, 400)
        mixed = client.post(
            "/api/v1/intent",
            json={
                "text": "他在他在家干嘛？又咋了？",
                "source": "voice",
                "participant_id": "iphone-origin",
            },
        )
        self.assertEqual(mixed.status_code, 200, mixed.get_json())
        ok = client.post(
            "/api/v1/intent",
            json={
                "text": "几点了",
                "source": "voice",
                "participant_id": "iphone-origin",
            },
        )
        self.assertEqual(ok.status_code, 200, ok.get_json())
        self.assertTrue(ok.get_json()["ok"])

    def test_voice_default_presentation_is_notify_speak_in_plan(self) -> None:
        self._register_voice_runtime("mac-voice-plan")
        iid = hb.new_intent(
            {
                "status": "intent_received",
                "text": "现在几点了",
                "source": "voice",
                "edge_id": "mac-voice-plan",
                "presentation": {"type": "audio", "from": "time_text"},
            }
        )
        hb.do_execution_plan(
            iid,
            [
                {
                    "step": 1,
                    "capability": "clock.now",
                    "assigned_edge_id": "mac-voice-plan",
                    "input_constrict": {},
                    "output_constrict": {"time_text": {}},
                }
            ],
        )
        job = hb.get_intent(iid)
        plan = job["execution_plan"]
        self.assertEqual(len(plan), 2)
        self.assertEqual(plan[0]["capability"], "clock.now")
        self.assertEqual(plan[1]["capability"], "notify.speak")
        self.assertEqual(plan[1]["assigned_edge_id"], "mac-voice-plan")
        self.assertEqual(plan[1]["input_constrict"]["text"], "$time_text")
        self.assertFalse(job.get("pending_delivery"))
        detail = hb.app.test_client().get(f"/api/v1/intent_detail?intent_id={iid}")
        shown = detail.get_json()["execution_plan"]
        self.assertEqual(shown[1]["capability"], "notify.speak")
        self.assertEqual(shown[1]["assigned_edge_id"], "mac-voice-plan")

    def test_voice_music_play_does_not_append_speak_without_answer_text(self) -> None:
        """music.play does not emit answer_text. Voice TTS must not bind $answer_text."""
        self._register_voice_runtime("mac-voice-music")
        self._register_runtime("cast-music", cap="music.play")
        iid = hb.new_intent(
            {
                "status": "intent_received",
                "text": "播放歌曲十年",
                "source": "voice",
                "edge_id": "mac-voice-music",
                "presentation": {"type": "text", "from": "answer_text"},
            }
        )
        hb.do_execution_plan(
            iid,
            [
                {
                    "step": 1,
                    "capability": "music.play",
                    "assigned_edge_id": "cast-music",
                    "input_constrict": {"song": "十年"},
                    "output_constrict": {},
                }
            ],
        )
        job = hb.get_intent(iid)
        plan = job["execution_plan"]
        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0]["capability"], "music.play")
        self.assertNotIn("notify.speak", [s.get("capability") for s in plan])

    def test_llm_speak_answer_text_dropped_when_music_play_emits_nothing(self) -> None:
        """Planner must not keep notify.speak $answer_text after music.play."""
        self._register_voice_runtime("mac-voice-music-llm")
        self._register_runtime("cast-music-llm", cap="music.play")
        iid = hb.new_intent(
            {
                "status": "intent_received",
                "text": "播放歌曲十年",
                "source": "voice",
                "edge_id": "mac-voice-music-llm",
                "presentation": {"type": "text", "from": "answer_text"},
            }
        )
        hb.do_execution_plan(
            iid,
            [
                {
                    "step": 1,
                    "capability": "music.play",
                    "assigned_edge_id": "cast-music-llm",
                    "input_constrict": {"song": "十年"},
                    "output_constrict": {},
                },
                {
                    "step": 2,
                    "capability": "notify.speak",
                    "assigned_edge_id": "mac-voice-music-llm",
                    "input_constrict": {"text": "$answer_text"},
                    "output_constrict": {},
                },
            ],
        )
        job = hb.get_intent(iid)
        plan = job["execution_plan"]
        self.assertEqual([s.get("capability") for s in plan], ["music.play"])
        self.assertNotEqual(job.get("presentation", {}).get("from"), "answer_text")

    def test_get_intent_backfills_text_from_review(self) -> None:
        brain_db.put_job({"intent_id": 77, "status": "failed"})
        brain_db.put_intent_review(
            {
                "intent_id": 77,
                "text": "播放歌曲十年。",
                "source": "voice",
            }
        )
        job = hb.get_intent(77)
        self.assertEqual(job.get("text"), "播放歌曲十年。")
        self.assertEqual(job.get("source"), "voice")

    def test_presentation_kind_ignores_answer_text_when_plan_does_not_emit_it(self) -> None:
        kind, field = hb._presentation_kind_from_plan(
            {
                "presentation": {"type": "text", "from": "answer_text"},
                "execution_plan": [{"step": 1, "capability": "music.play"}],
            }
        )
        self.assertEqual(kind, "")
        self.assertEqual(field, "")

    def test_voice_wake_rejects_non_voice_stream_and_other_events(self) -> None:
        client = hb.app.test_client()
        missing = client.post("/api/v1/voice/wake", json={"event": "wake"})
        self.assertEqual(missing.status_code, 400)

        unknown = client.post(
            "/api/v1/voice/wake",
            json={"event": "wake", "participant_id": "no-such-edge"},
        )
        self.assertEqual(unknown.status_code, 401)

        self._register_live_issuer("iphone-origin")
        no_voice = client.post(
            "/api/v1/voice/wake",
            json={"event": "wake", "participant_id": "iphone-origin"},
        )
        self.assertEqual(no_voice.status_code, 403)
        self.assertIn("voice.stream", no_voice.get_json()["error"])

        self._register_voice_runtime("mac-voice-2")
        bad_event = client.post(
            "/api/v1/voice/wake",
            json={"event": "command", "participant_id": "mac-voice-2"},
        )
        self.assertEqual(bad_event.status_code, 400)

    def test_voice_wake_does_not_require_echo_capability(self) -> None:
        self._register_voice_runtime("mac-voice-mute", with_echo=False)
        client = hb.app.test_client()
        resp = client.post(
            "/api/v1/voice/wake",
            json={"event": "wake", "participant_id": "mac-voice-mute"},
        )
        self.assertEqual(resp.status_code, 200, resp.get_json())
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["local"])
        self.assertIsNone(body.get("intent_id"))

    def test_list_capabilities_and_services(self) -> None:
        self._register_runtime("mac-cap-list", cap="light.set")
        client = hb.app.test_client()
        services = client.get("/api/v1/services")
        self.assertEqual(services.status_code, 200)
        svc_body = services.get_json()
        self.assertTrue(svc_body["ok"])
        self.assertGreaterEqual(svc_body["count"], 1)
        self.assertIn("gopro.camera", [s.get("service_id") for s in svc_body["services"]])

        caps = client.get("/api/v1/capabilities")
        self.assertEqual(caps.status_code, 200)
        cap_body = caps.get_json()
        self.assertTrue(cap_body["ok"])
        ids = [c["capability_id"] for c in cap_body["capabilities"]]
        # Edge-advertised non-system capability lists under that edge.
        self.assertIn("light.set", ids)
        row = next(c for c in cap_body["capabilities"] if c["capability_id"] == "light.set")
        self.assertEqual(row["edge_id"], "mac-cap-list")
        self.assertEqual(row["assigned_edge_id"], "mac-cap-list")
        self.assertIn("input_schema", row)
        self.assertIn("output_schema", row)
        # clock.now is kind=system: listed under the system edge, not any runtime.
        self.assertIn("clock.now", ids)
        clock_row = next(
            c for c in cap_body["capabilities"] if c["capability_id"] == "clock.now"
        )
        self.assertEqual(clock_row["edge_id"], "system")
        self.assertEqual(clock_row["assigned_edge_id"], "system")

        filtered = client.get(
            "/api/v1/capabilities",
            query_string={"capability_id": "light.set", "edge_id": "mac-cap-list"},
        )
        self.assertEqual(filtered.status_code, 200)
        fbody = filtered.get_json()
        self.assertEqual(fbody["count"], 1)
        self.assertEqual(fbody["capabilities"][0]["capability_id"], "light.set")

        missing = client.get(
            "/api/v1/capabilities",
            query_string={"capability_id": "no.such.cap"},
        )
        self.assertEqual(missing.get_json()["count"], 0)

    def test_admin_nodes_and_disable_capability(self) -> None:
        self._register_runtime("mac-admin")
        client = hb.app.test_client()
        listed = client.get("/api/v1/admin/nodes")
        self.assertEqual(listed.status_code, 200)
        nodes = listed.get_json()["nodes"]
        self.assertEqual(len(nodes), 1)
        node = nodes[0]
        self.assertEqual(node["participant_id"], "mac-admin")
        self.assertEqual(node["online_status"], "online")
        self.assertTrue(node["last_active_at"])
        caps = {c["capability_id"]: c for c in node["runtime_capabilities"]}
        self.assertTrue(caps["camera.capture"]["enabled"])
        self.assertIn("camera.capture", hb.capability_edge_mapping)

        toggled = client.post(
            "/api/v1/admin/policy",
            json={
                "participant_id": "mac-admin",
                "target_kind": "capability",
                "target_id": "camera.capture",
                "enabled": False,
            },
        )
        self.assertEqual(toggled.status_code, 200)
        self.assertNotIn("camera.capture", hb.capability_edge_mapping)
        beats = brain_db.list_heartbeats()["mac-admin"]
        self.assertEqual(
            beats["services"][0]["capabilities"][0]["capability_id"],
            "camera.capture",
        )
        listed = client.get("/api/v1/admin/nodes")
        caps = {
            c["capability_id"]: c
            for c in listed.get_json()["nodes"][0]["runtime_capabilities"]
        }
        self.assertFalse(caps["camera.capture"]["enabled"])

        logs = client.get("/api/v1/admin/logs")
        self.assertEqual(logs.status_code, 200)
        body = logs.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(len(body["logs"]), 1)
        row = body["logs"][0]
        self.assertEqual(row["action"], "policy_disable")
        self.assertEqual(row["result"], "ok")
        self.assertEqual(row["participant_id"], "mac-admin")
        self.assertEqual(row["target_id"], "camera.capture")
        self.assertIn("关掉", row["summary"])
        self.assertIn("camera.capture", row["summary"])
        self.assertEqual(row["actor"], "")

        nodes_again = client.get("/api/v1/admin/nodes")
        self.assertEqual(len(client.get("/api/v1/admin/logs").get_json()["logs"]), 1)
        self.assertEqual(nodes_again.status_code, 200)

        enabled = client.post(
            "/api/v1/admin/policy",
            json={
                "participant_id": "mac-admin",
                "target_kind": "capability",
                "target_id": "camera.capture",
                "enabled": True,
            },
        )
        self.assertEqual(enabled.status_code, 200)
        listed_logs = client.get("/api/v1/admin/logs?limit=10").get_json()["logs"]
        self.assertEqual(listed_logs[0]["action"], "policy_enable")
        self.assertEqual(len(listed_logs), 2)

        missing = client.post(
            "/api/v1/admin/policy",
            json={
                "participant_id": "no-such-node",
                "target_kind": "capability",
                "target_id": "camera.capture",
                "enabled": False,
            },
        )
        self.assertEqual(missing.status_code, 404)
        err_logs = client.get("/api/v1/admin/logs").get_json()["logs"]
        self.assertEqual(err_logs[0]["result"], "error")
        self.assertEqual(err_logs[0]["action"], "policy_disable")

        bulk = client.put(
            "/api/v1/admin/nodes/mac-admin/policy",
            json={"capabilities": {"camera.capture": False}},
        )
        self.assertEqual(bulk.status_code, 200)
        bulk_row = client.get("/api/v1/admin/logs").get_json()["logs"][0]
        self.assertEqual(bulk_row["action"], "policy_replace")
        self.assertEqual(bulk_row["result"], "ok")

    def test_admin_intents_lists_runtime_jobs(self) -> None:
        self._register_runtime("mac-rt")
        brain_db.put_job(
            {
                "intent_id": 9,
                "status": "succeeded",
                "text": "system only",
                "execution_plan": [
                    {
                        "step": 1,
                        "capability": "clock.now",
                        "assigned_edge_id": "system",
                        "status": "succeeded",
                    }
                ],
                "created_at": 1.0,
                "updated_at": 1.0,
            }
        )
        brain_db.put_job(
            {
                "intent_id": 10,
                "status": "succeeded",
                "text": "现在几点了",
                "edge_id": "iphone-1",
                "edge_node_id": "mac-rt",
                "msg": "下午四点",
                "execution_plan": [
                    {
                        "step": 1,
                        "capability": "clock.now",
                        "assigned_edge_id": "mac-rt",
                        "status": "succeeded",
                        "msg": "",
                    }
                ],
                "step_outputs": {"1": {"time_text": "下午四点"}},
                "presentation": {
                    "type": "text",
                    "text": "下午四点",
                    "from": "msg",
                },
                "created_at": 2.0,
                "updated_at": 3.0,
            }
        )
        brain_db.put_job(
            {
                "intent_id": 11,
                "status": "intent_parsed",
                "text": "排队中",
                "edge_id": "iphone-1",
                "execution_plan": [],
                "created_at": 4.0,
                "updated_at": 4.0,
            }
        )
        client = hb.app.test_client()
        resp = client.get("/api/v1/admin/intents")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        ids = [int(row["intent_id"]) for row in body["intents"]]
        self.assertEqual(ids, [11, 10])
        self.assertTrue(body["exhausted"])
        row = body["intents"][1]
        self.assertEqual(row["text"], "现在几点了")
        self.assertEqual(row["issuer_id"], "iphone-1")
        self.assertEqual(row["runtime_edge_ids"], ["mac-rt"])
        self.assertEqual(row["presentation"]["text"], "下午四点")
        self.assertEqual(row["execution_plan"][0]["capability"], "clock.now")
        page = client.get("/api/v1/admin/intents?limit=1")
        pbody = page.get_json()
        self.assertEqual([int(r["intent_id"]) for r in pbody["intents"]], [11])
        self.assertFalse(pbody["exhausted"])
        self.assertEqual(pbody["next_before_id"], 11)
        page2 = client.get("/api/v1/admin/intents?limit=1&before_id=11")
        p2 = page2.get_json()
        self.assertEqual([int(r["intent_id"]) for r in p2["intents"]], [10])

    def test_admin_disable_endpoint_role_skips_presentation(self) -> None:
        self._register_endpoint("iphone-admin", "iphone")
        self._heartbeat("iphone-admin")
        client = hb.app.test_client()
        client.post(
            "/api/v1/admin/policy",
            json={
                "participant_id": "iphone-admin",
                "target_kind": "role",
                "target_id": "endpoint",
                "enabled": False,
            },
        )
        pids = [pid for pid, _rec in hb._list_endpoint_participants()]
        self.assertNotIn("iphone-admin", pids)

    def test_admin_disable_intent_source_blocks_post_intent(self) -> None:
        self._register_live_issuer("iphone-source")
        client = hb.app.test_client()
        ok = client.post(
            "/api/v1/intent",
            json={"text": "现在几点了", "participant_id": "iphone-source"},
        )
        self.assertEqual(ok.status_code, 200)
        denied = client.post(
            "/api/v1/admin/policy",
            json={
                "participant_id": "iphone-source",
                "target_kind": "role",
                "target_id": "intent_source",
                "enabled": False,
            },
        )
        self.assertEqual(denied.status_code, 200)
        blocked = client.post(
            "/api/v1/intent",
            json={"text": "现在几点了", "participant_id": "iphone-source"},
        )
        self.assertEqual(blocked.status_code, 403)
        self.assertIn("intent_source", blocked.get_json()["error"])
        client.post(
            "/api/v1/admin/policy",
            json={
                "participant_id": "iphone-source",
                "target_kind": "role",
                "target_id": "intent_source",
                "enabled": True,
            },
        )
        allowed = client.post(
            "/api/v1/intent",
            json={"text": "现在几点了", "participant_id": "iphone-source"},
        )
        self.assertEqual(allowed.status_code, 200)

    def test_intent_feedback_api(self) -> None:
        client = hb.app.test_client()
        posted = client.post(
            "/api/v1/intent_feedback",
            json={
                "intent_id": 42,
                "participant_id": "iphone-source",
                "understanding": "accurate",
                "response_speed": "normal",
            },
        )
        self.assertEqual(posted.status_code, 200)
        body = posted.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["feedback"]["intent_id"], 42)
        got = client.get(
            "/api/v1/intent_feedback?intent_id=42&participant_id=iphone-source"
        )
        self.assertEqual(got.status_code, 200)
        row = got.get_json()["feedback"]
        self.assertEqual(row["response_speed"], "normal")
        bad = client.post(
            "/api/v1/intent_feedback",
            json={"intent_id": 42, "understanding": "accurate", "response_speed": "normal"},
        )
        self.assertEqual(bad.status_code, 400)

    def test_entities_api_list_get_put(self) -> None:
        client = hb.app.test_client()
        listed = client.get("/api/v1/entities?type=device")
        self.assertEqual(listed.status_code, 200)
        body = listed.get_json()
        self.assertTrue(body["ok"])
        self.assertGreaterEqual(body["count"], 4)
        ids = {e["entity_id"] for e in body["entities"]}
        self.assertIn("ent_dev_livingroom_ac", ids)
        got = client.get("/api/v1/entities/ent_dev_livingroom_ac")
        self.assertEqual(got.status_code, 200)
        ent = got.get_json()["entity"]
        self.assertEqual(ent["name"], "客厅空调")
        put = client.put(
            "/api/v1/entities/ent_dev_livingroom_ac",
            json={
                "type": "device",
                "name": "客厅空调",
                "metadata": {"room": "living-room"},
                "state": {"power": False},
                "references": {},
            },
        )
        self.assertEqual(put.status_code, 200)
        self.assertEqual(put.get_json()["entity"]["state"]["power"], False)
        bad = client.put(
            "/api/v1/entities/ent_x",
            json={"type": "recipe", "name": "x"},
        )
        self.assertEqual(bad.status_code, 400)

    def test_admin_html_not_on_brain(self) -> None:
        client = hb.app.test_client()
        resp = client.get("/admin")
        self.assertEqual(resp.status_code, 404)

    def test_assets_upload_requires_intent_and_file(self) -> None:
        from io import BytesIO

        upload_root = Path(self._tmp.name) / "uploads"
        hb.UPLOAD_DIR = upload_root
        hb._ASSET_UPLOAD_DIR = None
        client = hb.app.test_client()
        missing_intent = client.post(
            "/api/v1/assets/upload",
            data={"file": (BytesIO(b"abc"), "a.jpg")},
            content_type="multipart/form-data",
        )
        self.assertEqual(missing_intent.status_code, 400)
        self.assertIn("upload_intent", missing_intent.get_json().get("error", ""))
        missing_file = client.post(
            "/api/v1/assets/upload",
            data={"upload_intent": "document.scan"},
            content_type="multipart/form-data",
        )
        self.assertEqual(missing_file.status_code, 400)

    def test_assets_upload_registers_asset(self) -> None:
        from io import BytesIO
        from unittest.mock import patch

        client = hb.app.test_client()
        fake_store = {
            "saved_as": "aabbccdd_scan.jpg",
            "public_base": "http://192.168.0.88:8080",
            "url": "http://192.168.0.88:8080/aabbccdd_scan.jpg",
        }
        with patch.object(hb, "_put_bytes_on_img_server", return_value=fake_store):
            resp = client.post(
                "/api/v1/assets/upload",
                data={
                    "upload_intent": "document.scan",
                    "producer": "document.scan",
                    "edge_id": "iphone-test",
                    "type": "image",
                    "mime_type": "image/jpeg",
                    "file": (BytesIO(b"\xff\xd8\xfffakejpeg"), "scan.jpg"),
                },
                content_type="multipart/form-data",
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        aid = body["asset_id"]
        self.assertTrue(str(aid).startswith("asset_"))
        self.assertEqual(body["upload_intent"], "document.scan")
        self.assertEqual(body["type"], "image")
        self.assertEqual(body["asset_ref"]["asset_id"], aid)
        rec = brain_db.get_asset(aid)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["producer_capability"], "document.scan")
        storage = rec.get("storage") or {}
        self.assertEqual(storage.get("backend"), "img_server")
        self.assertEqual(storage.get("key"), "aabbccdd_scan.jpg")
        # public_base is DHCP-volatile and must NOT be persisted with the asset;
        # it is resolved fresh from img-server each time a URL is needed.
        self.assertNotIn("public_base", storage)

    def test_img_server_public_base_prefers_img_server_health(self) -> None:
        from unittest.mock import patch

        prev_origin = os.environ.get("BRAIN_ORIGIN")
        os.environ["BRAIN_ORIGIN"] = "lan"
        try:
            os.environ.pop("BRAIN_IMG_PUBLIC_BASE", None)
            os.environ.pop("PHOTO_PUBLIC_BASE", None)
            # img-server /health is authoritative when reachable.
            with patch.object(
                hb, "_img_server_health_public_base", return_value="http://192.168.3.44:8080"
            ), patch.object(
                hb, "_lan_img_server_public_base", return_value="http://192.168.0.88:8080"
            ):
                self.assertEqual(hb._img_server_public_base(), "http://192.168.3.44:8080")
            # When img-server /health is unreachable, fall back to LAN auto-detect.
            with patch.object(
                hb, "_img_server_health_public_base", return_value=""
            ), patch.object(
                hb, "_lan_img_server_public_base", return_value="http://192.168.0.88:8080"
            ):
                self.assertEqual(hb._img_server_public_base(), "http://192.168.0.88:8080")
                self.assertNotIn("192.168.3.73", hb._img_server_public_base())
        finally:
            if prev_origin is None:
                os.environ.pop("BRAIN_ORIGIN", None)
            else:
                os.environ["BRAIN_ORIGIN"] = prev_origin
            os.environ.pop("PHOTO_PUBLIC_BASE", None)

    def test_img_server_public_base_env_and_cloud_win(self) -> None:
        from unittest.mock import patch

        prev_origin = os.environ.get("BRAIN_ORIGIN")
        os.environ["BRAIN_ORIGIN"] = "lan"
        try:
            os.environ.pop("BRAIN_IMG_PUBLIC_BASE", None)
            os.environ.pop("PHOTO_PUBLIC_BASE", None)
            with patch.object(hb, "_img_server_health_public_base", return_value=""):
                # Explicit env override wins regardless of origin.
                os.environ["PHOTO_PUBLIC_BASE"] = "http://192.168.0.99:8080"
                self.assertEqual(hb._img_server_public_base(), "http://192.168.0.99:8080")
                # Cloud origin keeps the fixed cloud public base.
                os.environ.pop("PHOTO_PUBLIC_BASE", None)
                os.environ["BRAIN_ORIGIN"] = "cloud"
                self.assertEqual(hb._img_server_public_base(), "http://115.190.153.53:8080")
        finally:
            if prev_origin is None:
                os.environ.pop("BRAIN_ORIGIN", None)
            else:
                os.environ["BRAIN_ORIGIN"] = prev_origin
            os.environ.pop("PHOTO_PUBLIC_BASE", None)

    def test_lan_img_server_public_base_no_stale_lan_ip(self) -> None:
        base = hb._lan_img_server_public_base()
        self.assertTrue(base.startswith("http://"))
        self.assertTrue(base.endswith(":8080"))
        self.assertNotIn("192.168.3.73", base)

    def test_asset_media_urls_resolves_current_img_server_not_stored_base(self) -> None:
        # A legacy/incorrect row may still carry a stale LAN public_base in the
        # DB; the content proxy must ignore it and fetch the co-located img-server
        # (loopback default) instead of the dead stored IP.
        storage = {
            "backend": "img_server",
            "key": "x.png",
            "public_base": "http://192.168.3.73:8080",
        }
        urls = hb._asset_media_urls(storage, "http://127.0.0.1:9527/api/v1/assets/a1/content")
        self.assertIn("http://127.0.0.1:8080/x.png", urls)
        self.assertNotIn("http://192.168.3.73:8080/x.png", urls)
        # Explicit BRAIN_IMG_UPLOAD_URL (cloud sidecar etc.) is honored.
        prev = os.environ.get("BRAIN_IMG_UPLOAD_URL")
        os.environ["BRAIN_IMG_UPLOAD_URL"] = "http://127.0.0.1:18080/api/v1/photos/upload"
        try:
            urls2 = hb._asset_media_urls(storage, "http://127.0.0.1:9527/x")
            self.assertIn("http://127.0.0.1:18080/x.png", urls2)
        finally:
            if prev is None:
                os.environ.pop("BRAIN_IMG_UPLOAD_URL", None)
            else:
                os.environ["BRAIN_IMG_UPLOAD_URL"] = prev
        # A cloud mirror is still preferred for off-LAN consumers.
        storage["cloud_public_base"] = "http://115.190.153.53:8080"
        storage["cloud_key"] = "x.png"
        urls3 = hb._asset_media_urls(storage, "http://127.0.0.1:9527/x")
        self.assertEqual(urls3[0], "http://115.190.153.53:8080/x.png")

    def test_asset_media_urls_percent_encodes_chinese_keys(self) -> None:
        """id=639: content proxy must quote non-ASCII storage keys."""
        key = "f1103a10_当前Agent编排平台现状分析和创业空间.pdf"
        urls = hb._asset_media_urls(
            {"backend": "img_server", "key": key},
            "http://127.0.0.1:9527/api/v1/assets/a1/content",
        )
        self.assertTrue(urls)
        for u in urls:
            self.assertNotIn("当前", u)
            self.assertIn("%E5%BD%93%E5%89%8D", u)

    def test_assets_upload_fails_when_img_server_down(self) -> None:
        from io import BytesIO
        from unittest.mock import patch

        client = hb.app.test_client()
        with patch.object(
            hb, "_put_bytes_on_img_server", side_effect=RuntimeError("connection refused")
        ):
            resp = client.post(
                "/api/v1/assets/upload",
                data={
                    "upload_intent": "iphone.photo",
                    "file": (BytesIO(b"\xff\xd8\xff"), "a.jpg"),
                },
                content_type="multipart/form-data",
            )
        self.assertEqual(resp.status_code, 502)
        self.assertIn("img-server", resp.get_json().get("error", ""))

    def test_assets_upload_cloud_origin_uses_local_upload(self) -> None:
        from io import BytesIO
        from unittest.mock import patch

        jpeg = b"\xff\xd8\xffcloud-local"
        upload_root = Path(self._tmp.name) / "gopropics"
        prev_origin = os.environ.get("BRAIN_ORIGIN")
        prev_img = os.environ.get("BRAIN_IMG_UPLOAD_URL")
        prev_photo = os.environ.get("PHOTO_UPLOAD_URL")
        prev_upload = hb.UPLOAD_DIR
        prev_asset_dir = hb._ASSET_UPLOAD_DIR
        os.environ["BRAIN_ORIGIN"] = "cloud"
        os.environ.pop("BRAIN_IMG_UPLOAD_URL", None)
        os.environ.pop("PHOTO_UPLOAD_URL", None)
        hb.UPLOAD_DIR = upload_root
        hb._ASSET_UPLOAD_DIR = None
        client = hb.app.test_client()
        try:
            self.assertTrue(hb._use_local_upload_store())
            with patch.object(hb, "_put_bytes_on_img_server") as img_put:
                resp = client.post(
                    "/api/v1/assets/upload",
                    data={
                        "upload_intent": "asset.upload",
                        "producer": "asset.upload",
                        "edge_id": "iphone-test",
                        "intent_id": "1454",
                        "type": "image",
                        "mime_type": "image/jpeg",
                        "file": (BytesIO(jpeg), "living.jpg"),
                    },
                    content_type="multipart/form-data",
                )
            img_put.assert_not_called()
            self.assertEqual(resp.status_code, 200)
            body = resp.get_json()
            self.assertTrue(body["ok"])
            aid = body["asset_id"]
            rec = brain_db.get_asset(aid)
            assert rec is not None
            storage = rec.get("storage") or {}
            self.assertEqual(storage.get("backend"), "local_upload")
            key = str(storage.get("key") or "")
            self.assertTrue(key.endswith("_living.jpg"))
            disk = upload_root / "assets" / Path(key).name
            self.assertTrue(disk.is_file())
            self.assertEqual(disk.read_bytes(), jpeg)
            content = client.get(
                f"/api/v1/assets/{aid}/content",
                query_string={"intent_id": "1454"},
            )
            self.assertEqual(content.status_code, 200)
            self.assertEqual(content.data, jpeg)
        finally:
            hb.UPLOAD_DIR = prev_upload
            hb._ASSET_UPLOAD_DIR = prev_asset_dir
            if prev_origin is None:
                os.environ.pop("BRAIN_ORIGIN", None)
            else:
                os.environ["BRAIN_ORIGIN"] = prev_origin
            if prev_img is None:
                os.environ.pop("BRAIN_IMG_UPLOAD_URL", None)
            else:
                os.environ["BRAIN_IMG_UPLOAD_URL"] = prev_img
            if prev_photo is None:
                os.environ.pop("PHOTO_UPLOAD_URL", None)
            else:
                os.environ["PHOTO_UPLOAD_URL"] = prev_photo

    def test_assets_upload_cloud_explicit_img_url_still_uses_img_server(self) -> None:
        from io import BytesIO
        from unittest.mock import patch

        prev_origin = os.environ.get("BRAIN_ORIGIN")
        prev_img = os.environ.get("BRAIN_IMG_UPLOAD_URL")
        os.environ["BRAIN_ORIGIN"] = "cloud"
        os.environ["BRAIN_IMG_UPLOAD_URL"] = "http://127.0.0.1:18080/api/v1/photos/upload"
        try:
            self.assertFalse(hb._use_local_upload_store())
            client = hb.app.test_client()
            fake_store = {
                "saved_as": "aabbccdd_cloud.jpg",
                "public_base": "http://115.190.153.53:8080",
                "url": "http://115.190.153.53:8080/aabbccdd_cloud.jpg",
            }
            with patch.object(hb, "_put_bytes_on_img_server", return_value=fake_store) as img_put:
                resp = client.post(
                    "/api/v1/assets/upload",
                    data={
                        "upload_intent": "asset.upload",
                        "file": (BytesIO(b"\xff\xd8\xff"), "a.jpg"),
                    },
                    content_type="multipart/form-data",
                )
            img_put.assert_called_once()
            self.assertEqual(resp.status_code, 200)
            rec = brain_db.get_asset(resp.get_json()["asset_id"])
            self.assertEqual((rec.get("storage") or {}).get("backend"), "img_server")
        finally:
            if prev_origin is None:
                os.environ.pop("BRAIN_ORIGIN", None)
            else:
                os.environ["BRAIN_ORIGIN"] = prev_origin
            if prev_img is None:
                os.environ.pop("BRAIN_IMG_UPLOAD_URL", None)
            else:
                os.environ["BRAIN_IMG_UPLOAD_URL"] = prev_img

    def test_assets_upload_rejects_illegal_filename(self) -> None:
        from io import BytesIO
        from unittest.mock import patch

        upload_root = Path(self._tmp.name) / "uploads"
        hb.UPLOAD_DIR = upload_root
        hb._ASSET_UPLOAD_DIR = None
        with self.assertRaises(hb.AssetFilenameError):
            hb._validate_asset_filename("录音 12:57.m4a")
        self.assertEqual(
            hb._validate_asset_filename("录音_1257.m4a"),
            "录音_1257.m4a",
        )
        self.assertEqual(
            hb._safe_on_disk_name("录音_1257.m4a", prefix="aabbccddeeff"),
            "aabbccddeeff_录音_1257.m4a",
        )
        client = hb.app.test_client()
        bad = client.post(
            "/api/v1/assets/upload",
            data={
                "upload_intent": "iphone.audio",
                "producer": "iphone.audio",
                "edge_id": "iphone-test",
                "type": "audio",
                "mime_type": "audio/mp4",
                "file": (BytesIO(b"m4a-bytes"), "录音 12:57.m4a"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(bad.status_code, 400)
        self.assertIn("非法字符", bad.get_json().get("error", ""))
        assets_dir = upload_root / "assets"
        self.assertFalse(assets_dir.exists() and any(assets_dir.iterdir()))
        with patch.object(
            hb,
            "_put_bytes_on_img_server",
            return_value={
                "saved_as": "aabbccddeeff_录音_1257.m4a",
                "public_base": "http://192.168.0.88:8080",
                "url": "http://192.168.0.88:8080/aabbccddeeff_录音_1257.m4a",
            },
        ):
            ok = client.post(
                "/api/v1/assets/upload",
                data={
                    "upload_intent": "iphone.audio",
                    "producer": "iphone.audio",
                    "edge_id": "iphone-test",
                    "type": "audio",
                    "mime_type": "audio/mp4",
                    "file": (BytesIO(b"m4a-bytes"), "录音_1257.m4a"),
                },
                content_type="multipart/form-data",
            )
        self.assertEqual(ok.status_code, 200)
        rec = brain_db.get_asset(ok.get_json()["asset_id"])
        key = (rec.get("storage") or {}).get("key") or ""
        self.assertEqual(key, "aabbccddeeff_录音_1257.m4a")
        self.assertEqual((rec.get("storage") or {}).get("backend"), "img_server")
        self.assertEqual((rec.get("metadata") or {}).get("original_filename"), "录音_1257.m4a")

    def _register_named_climate(
        self,
        pid: str,
        *,
        service_id: str,
        display_name: str,
        edge_name: str,
    ) -> None:
        services = [
            {
                "service_id": service_id,
                "display_name": display_name,
                "group": "climate",
                "capabilities": [
                    {
                        "capability_id": "climate.set",
                        "kind": "action",
                        "role": f"{display_name}控制器",
                        "planner_recognize": f"控制「{display_name}」",
                        "typical_triggers": [f"打开{display_name}"],
                        "input_schema": {},
                        "output_schema": {},
                    }
                ],
            }
        ]
        brain_db.put_registration(
            {
                "participant_id": pid,
                "display_name": edge_name,
                "device_type": "mac",
                "roles": ["runtime"],
                "services": services,
            }
        )
        now = time.time()
        brain_db.put_heartbeat(
            pid,
            {
                "online_status": "online",
                "server_received_at": now,
                "reported_at": now,
                "schedule_eligible": True,
                "display_name": edge_name,
                "services": services,
            },
        )
        hb._REGISTERED_edges = brain_db.registration_ids()
        hb.rebuild_capability_maps()

    def test_unnamed_ac_with_two_named_instances_fails_listing_names(self) -> None:
        self._register_named_climate(
            "edge-living-ac",
            service_id="climate.living_room",
            display_name="客厅空调",
            edge_name="客厅 · Mac Edge",
        )
        self._register_named_climate(
            "edge-kids-ac",
            service_id="climate.kids_room",
            display_name="儿童房空调",
            edge_name="客厅 iPhone",
        )
        self.assertNotIn("climate.set", hb.capability_edge_mapping)
        iid = hb.new_intent(
            {
                "status": "intent_received",
                "text": "打开空调",
                "source": "text",
            }
        )
        with self.assertRaises(hb.AmbiguousCapabilityEdge) as ctx:
            hb.do_execution_plan(
                iid,
                [
                    {
                        "step": 1,
                        "capability": "climate.set",
                        "input_constrict": {"power": "on"},
                        "output_constrict": {},
                    }
                ],
            )
        msg = str(ctx.exception)
        self.assertIn("客厅空调", msg)
        self.assertIn("儿童房空调", msg)
        job = hb.get_intent(iid)
        self.assertFalse(job.get("execution_plan"))

    def test_gopro_in_utterance_picks_gopro_camera_on_same_edge(self) -> None:
        received = time.time()
        pid = "edge-android-dual-cam"

        def composite_caps() -> list[dict]:
            return [
                {
                    "capability_id": "camera.capture_and_upload",
                    "composition": "composite",
                    "kind": "action",
                    "available": True,
                    "input_schema": {},
                    "output_schema": {},
                }
            ]

        services_reg = [
            {
                "service_id": "android.camera",
                "display_name": "Android Camera",
                "group": "camera",
                "capabilities": composite_caps(),
            },
            {
                "service_id": "gopro.camera",
                "display_name": "GoPro Camera",
                "group": "camera",
                "capabilities": composite_caps(),
            },
        ]
        brain_db.put_registration(
            {
                "participant_id": pid,
                "display_name": "客厅 Android",
                "device_type": "android",
                "roles": ["runtime"],
                "services": services_reg,
            }
        )
        hb_services = [
            {**svc, "edge_id": pid, "capabilities": composite_caps()}
            for svc in services_reg
        ]
        brain_db.put_heartbeat(
            pid,
            {
                "online_status": "online",
                "server_received_at": received,
                "reported_at": received,
                "schedule_eligible": True,
                "services": hb_services,
            },
        )
        hb._REGISTERED_edges = brain_db.registration_ids()
        hb.rebuild_capability_maps()
        iid = hb.new_intent(
            {
                "status": "intent_received",
                "text": "用GoPro拍张照片我看一下",
                "source": "voice",
                "edge_id": pid,
            }
        )
        hb.do_execution_plan(
            iid,
            [
                {
                    "step": 1,
                    "capability": "camera.capture_and_upload",
                    "input_constrict": {},
                    "output_constrict": {
                        "asset_ref": {"type": "object", "data_dest": "context"},
                    },
                }
            ],
        )
        plan = hb.get_intent(iid)["execution_plan"]
        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0]["assigned_edge_id"], pid)
        self.assertEqual(plan[0]["input_constrict"].get("appliance"), "GoPro Camera")

    def test_same_named_instance_on_two_edges_picks_one(self) -> None:
        self._register_named_climate(
            "edge-mac-ac",
            service_id="climate.living_room",
            display_name="客厅空调",
            edge_name="客厅 · Mac Edge",
        )
        self._register_named_climate(
            "edge-phone-ac",
            service_id="climate.living_room",
            display_name="客厅空调",
            edge_name="客厅 iPhone",
        )
        self.assertNotIn("climate.set", hb.capability_edge_mapping)
        iid = hb.new_intent(
            {
                "status": "intent_received",
                "text": "打开客厅空调",
                "source": "text",
                "edge_id": "edge-phone-ac",
            }
        )
        hb.do_execution_plan(
            iid,
            [
                {
                    "step": 1,
                    "capability": "climate.set",
                    "input_constrict": {"power": "on"},
                    "output_constrict": {},
                }
            ],
        )
        plan = hb.get_intent(iid)["execution_plan"]
        self.assertEqual(plan[0]["assigned_edge_id"], "edge-phone-ac")
        self.assertEqual(plan[0]["input_constrict"].get("appliance"), "客厅空调")

    def test_named_kids_ac_selects_kids_instance(self) -> None:
        self._register_named_climate(
            "edge-mac-both",
            service_id="climate.living_room",
            display_name="客厅空调",
            edge_name="客厅 · Mac Edge",
        )
        self._register_named_climate(
            "edge-kids-ac",
            service_id="climate.kids_room",
            display_name="儿童房空调",
            edge_name="客厅 iPhone",
        )
        iid = hb.new_intent(
            {
                "status": "intent_received",
                "text": "打开儿童房空调",
                "source": "text",
            }
        )
        hb.do_execution_plan(
            iid,
            [
                {
                    "step": 1,
                    "capability": "climate.set",
                    "input_constrict": {"power": "on"},
                    "output_constrict": {},
                }
            ],
        )
        plan = hb.get_intent(iid)["execution_plan"]
        self.assertEqual(plan[0]["assigned_edge_id"], "edge-kids-ac")
        self.assertEqual(plan[0]["input_constrict"].get("appliance"), "儿童房空调")

    def test_llm_assigned_edge_id_selects_named_climate_instance(self) -> None:
        self._register_named_climate(
            "edge-living-ac",
            service_id="climate.living_room",
            display_name="客厅空调",
            edge_name="客厅 · Mac Edge",
        )
        self._register_named_climate(
            "edge-kids-ac",
            service_id="climate.kids_room",
            display_name="儿童房空调",
            edge_name="客厅 iPhone",
        )
        iid = hb.new_intent(
            {
                "status": "intent_received",
                "text": "关掉儿童房空调",
                "source": "text",
            }
        )
        hb.do_execution_plan(
            iid,
            [
                {
                    "step": 1,
                    "capability": "climate.set",
                    "assigned_edge_id": "edge-kids-ac",
                    "input_constrict": {"power": "off"},
                    "output_constrict": {},
                }
            ],
        )
        plan = hb.get_intent(iid)["execution_plan"]
        self.assertEqual(plan[0]["assigned_edge_id"], "edge-kids-ac")
        self.assertEqual(plan[0]["input_constrict"].get("appliance"), "儿童房空调")

    def test_unique_climate_edge_still_maps_without_assigned_edge_id(self) -> None:
        self._register_named_climate(
            "edge-only-ac",
            service_id="climate.living_room",
            display_name="客厅空调",
            edge_name="客厅 · Mac Edge",
        )
        self.assertEqual(hb.capability_edge_mapping.get("climate.set"), "edge-only-ac")
        iid = hb.new_intent(
            {
                "status": "intent_received",
                "text": "打开客厅空调",
                "source": "text",
            }
        )
        hb.do_execution_plan(
            iid,
            [
                {
                    "step": 1,
                    "capability": "climate.set",
                    "input_constrict": {"power": "on"},
                    "output_constrict": {},
                }
            ],
        )
        plan = hb.get_intent(iid)["execution_plan"]
        self.assertEqual(plan[0]["assigned_edge_id"], "edge-only-ac")
        self.assertEqual(plan[0]["input_constrict"].get("appliance"), "客厅空调")

    def test_issuer_mac_wins_over_llm_iphone_for_named_ac(self) -> None:
        """LLM pinning climate.set to iPhone must not beat Mac when the user named 客厅空调."""
        self._register_named_climate(
            "edge-mac-ac",
            service_id="climate.living_room",
            display_name="客厅空调",
            edge_name="客厅 · Mac Edge",
        )
        self._register_named_climate(
            "edge-phone-ac",
            service_id="climate.living_room",
            display_name="客厅空调",
            edge_name="客厅 iPhone",
        )
        iid = hb.new_intent(
            {
                "status": "intent_received",
                "text": "关闭客厅空调。",
                "source": "voice",
                "edge_id": "edge-mac-ac",
            }
        )
        hb.do_execution_plan(
            iid,
            [
                {
                    "step": 1,
                    "capability": "climate.set",
                    "assigned_edge_id": "edge-phone-ac",
                    "input_constrict": {"appliance": "客厅空调", "power": "off"},
                    "output_constrict": {},
                }
            ],
        )
        plan = hb.get_intent(iid)["execution_plan"]
        self.assertEqual(plan[0]["assigned_edge_id"], "edge-mac-ac")
        self.assertEqual(plan[0]["input_constrict"].get("appliance"), "客厅空调")

    def test_call_ark_returns_payload_cost_and_full_response(self) -> None:
        from unittest.mock import MagicMock, patch

        iid = hb.new_intent(
            {
                "status": "intent_received",
                "text": "现在几点了",
                "source": "text",
                "status_log": [],
            }
        )
        content = json.dumps({"goal": "clock", "plan": []})
        body = {
            "choices": [
                {
                    "message": {
                        "content": content,
                        "reasoning_content": "think",
                    }
                }
            ],
            "usage": {"total_tokens": 11},
        }
        fake = MagicMock()
        fake.read.return_value = json.dumps(body).encode("utf-8")
        with patch("urllib.request.urlopen", return_value=fake):
            result = hb.call_ark(
                "现在几点了",
                "sess-a",
                "u1",
                iid,
                0,
                intent=hb.get_intent(iid),
            )
        self.assertEqual(result["ans"], content)
        self.assertGreaterEqual(result["cost_ms"], 0)
        self.assertFalse(result["cache_hit"])
        payload = result["request_payload"]
        self.assertEqual(payload["model"], hb.MODEL_ID)
        self.assertEqual(payload["temperature"], 0.2)
        self.assertEqual(payload["max_tokens"], 4096)
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual(payload["extra_body"]["thinking"]["type"], "disabled")
        self.assertEqual(payload["messages"][0]["role"], "system")
        self.assertEqual(payload["messages"][1]["role"], "user")
        dumped = json.dumps(payload)
        self.assertNotIn("Authorization", dumped)
        self.assertNotIn("Bearer", dumped)
        self.assertEqual(result["response_json"]["usage"]["total_tokens"], 11)
        self.assertEqual(
            result["response_json"]["choices"][0]["message"]["reasoning_content"],
            "think",
        )

    def test_call_ark_cache_hit_cost_ms_zero(self) -> None:
        from unittest.mock import patch

        catalog: list[dict] = []
        fp = hb._capability_registry_fingerprint(catalog)
        hb.set_cache("现在几点了", '{"plan":[]}', "text", catalog_fingerprint=fp)
        iid = hb.new_intent(
            {
                "status": "intent_received",
                "text": "现在几点了",
                "source": "text",
                "status_log": [],
            }
        )
        with patch.object(hb, "_capability_registry_for_prompt", return_value=catalog):
            result = hb.call_ark(
                "现在几点了",
                "sess-a",
                "u1",
                iid,
                0,
                intent=hb.get_intent(iid),
            )
        self.assertTrue(result["cache_hit"])
        self.assertEqual(result["cost_ms"], 0)
        self.assertEqual(result["ans"], '{"plan":[]}')
        self.assertIsNone(result["request_payload"])

    def test_call_ark_http_401_keeps_payload_and_cost(self) -> None:
        from unittest.mock import patch

        iid = hb.new_intent(
            {
                "status": "intent_received",
                "text": "401 replay probe",
                "source": "text",
                "status_log": [],
            }
        )
        err = urllib.error.HTTPError(
            "http://ark.example/chat",
            401,
            "Unauthorized",
            hdrs={},
            fp=io.BytesIO(b'{"error":{"code":"AuthenticationError"}}'),
        )

        def _raise(_req, timeout=180):
            raise err

        with patch("urllib.request.urlopen", side_effect=_raise):
            result = hb.call_ark(
                "401 replay probe",
                "sess-a",
                "u1",
                iid,
                0,
                intent=hb.get_intent(iid),
            )
        self.assertEqual(result["ans"], "__ARK_HTTP_401__")
        self.assertGreaterEqual(result["cost_ms"], 0)
        self.assertEqual(result["request_payload"]["model"], hb.MODEL_ID)
        self.assertEqual(result["response_json"]["http_status"], 401)

    def test_process_llm_task_records_cost_payload_and_raw(self) -> None:
        from unittest.mock import patch

        iid = hb.new_intent(
            {
                "status": "intent_received",
                "text": "现在几点了",
                "source": "text",
                "session_id": "sess-a",
                "status_log": [],
            }
        )
        ans = json.dumps(
            {
                "goal": "clock",
                "reason": "ask time",
                "plan": [],
                "presentation": {},
                "missing_capabilities": [],
                "better_capabilities": [],
            }
        )
        ark = {
            "ans": ans,
            "cost_ms": 1234,
            "request_payload": {
                "model": "ep-test",
                "messages": [
                    {"role": "system", "content": "sys"},
                    {"role": "user", "content": "现在几点了"},
                ],
                "temperature": 0.2,
            },
            "response_json": {
                "choices": [{"message": {"content": ans}}],
                "usage": {"total_tokens": 9},
            },
            "cache_hit": False,
        }
        with patch.object(hb, "call_ark", return_value=ark):
            hb._process_llm_task(
                {
                    "question": "现在几点了",
                    "session_id": "sess-a",
                    "user_id": "u1",
                    "intent_id": iid,
                    "source": "text",
                    "edge_id": "phone-1",
                }
            )
        rows = brain_db.list_intent_reviews(iid)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["cost_ms"], 1234)
        self.assertEqual(rows[0]["request_payload"]["model"], "ep-test")
        self.assertEqual(rows[0]["raw_response"], ans)
        self.assertEqual(rows[0]["response_json"]["usage"]["total_tokens"], 9)
        detail = hb.app.test_client().get(f"/api/v1/intent_detail?intent_id={iid}")
        shown = detail.get_json()
        self.assertEqual(shown["planner_cost_ms"], 1234)
        self.assertTrue(shown["planner_has_request_payload"])
        admin = hb._admin_intent_view(hb.get_intent(iid))
        self.assertEqual(admin["planner_cost_ms"], 1234)
        self.assertTrue(admin["planner_has_request_payload"])

    def test_process_llm_task_http_403_marks_failed_with_provider_msg(self) -> None:
        from unittest.mock import patch

        iid = hb.new_intent(
            {
                "status": "intent_received",
                "text": "把链接 http://example.com/a 转为PDF",
                "source": "text",
                "status_log": [],
            }
        )
        ark = {
            "ans": "",
            "cost_ms": 150,
            "request_payload": {"model": "ep-test", "messages": []},
            "response_json": {
                "http_status": 403,
                "error": {
                    "code": "AccountOverdueError",
                    "message": "The request failed because your account has an overdue balance.",
                    "type": "Forbidden",
                },
            },
            "cache_hit": False,
        }
        with patch.object(hb, "call_ark", return_value=ark):
            hb._process_llm_task(
                {
                    "question": "把链接 http://example.com/a 转为PDF",
                    "session_id": "sess-a",
                    "user_id": "u1",
                    "intent_id": iid,
                    "source": "text",
                    "edge_id": "phone-1",
                }
            )
        job = hb.get_intent(iid)
        self.assertEqual(job["status"], "failed")
        self.assertIn("403", job["msg"])
        self.assertIn("AccountOverdueError", job["msg"])
        self.assertIn("欠费", job["msg"])
        self.assertEqual(
            job["presentation"]["text"], job["msg"]
        )
        rows = brain_db.list_intent_reviews(iid)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["response_json"]["http_status"], 403)

    def test_process_llm_task_exception_records_cost_and_payload(self) -> None:
        from unittest.mock import patch

        iid = hb.new_intent(
            {
                "status": "intent_received",
                "text": "现在几点了",
                "source": "text",
                "status_log": [],
            }
        )
        ark = {
            "ans": "not-json",
            "cost_ms": 50,
            "request_payload": {"model": "ep-test", "messages": []},
            "response_json": {"usage": {"total_tokens": 1}},
            "cache_hit": False,
        }
        with patch.object(hb, "call_ark", return_value=ark):
            with patch.object(
                hb, "sanitize_execution_plan", side_effect=RuntimeError("boom")
            ):
                hb._process_llm_task(
                    {
                        "question": "现在几点了",
                        "session_id": "sess-a",
                        "user_id": "u1",
                        "intent_id": iid,
                        "source": "text",
                        "edge_id": "phone-1",
                    }
                )
        rows = brain_db.list_intent_reviews(iid)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["cost_ms"], 50)
        self.assertEqual(rows[0]["request_payload"]["model"], "ep-test")
        self.assertEqual(rows[0]["raw_response"], "not-json")
        self.assertIn("boom", rows[0]["error"])

    def test_process_llm_task_call_ark_raise_still_stores_cost_ms(self) -> None:
        from unittest.mock import patch

        iid = hb.new_intent(
            {
                "status": "intent_received",
                "text": "现在几点了",
                "source": "text",
                "status_log": [],
            }
        )
        with patch.object(hb, "call_ark", side_effect=RuntimeError("no ark")):
            hb._process_llm_task(
                {
                    "question": "现在几点了",
                    "session_id": "sess-a",
                    "user_id": "u1",
                    "intent_id": iid,
                    "source": "text",
                    "edge_id": "phone-1",
                }
            )
        rows = brain_db.list_intent_reviews(iid)
        self.assertEqual(len(rows), 1)
        self.assertIsInstance(rows[0]["cost_ms"], int)
        self.assertGreaterEqual(rows[0]["cost_ms"], 0)
        self.assertIn("no ark", rows[0]["error"])

    def test_extract_llm_output_relaxed_strips_fence(self) -> None:
        raw = "```json\n{\"goal\":\"clock\",\"plan\":[]}\n```"
        self.assertEqual(hb.extract_llm_output(raw), {})
        self.assertEqual(hb.extract_llm_output_relaxed(raw)["goal"], "clock")

    def test_process_llm_task_records_qwen_shadow_without_enqueue(self) -> None:
        from unittest.mock import patch

        iid = hb.new_intent(
            {
                "status": "intent_received",
                "text": "晚上吃啥",
                "source": "text",
                "status_log": [],
            }
        )
        ans = json.dumps(
            {
                "goal": "clock",
                "reason": "ask time",
                "plan": [
                    {
                        "step": 1,
                        "capability": "clock.now",
                        "assigned_edge_id": "sys",
                        "input_constrict": {},
                        "output_constrict": {},
                        "execution_timing": {"mode": "immediate"},
                    }
                ],
                "presentation": {"type": "text", "from": "time_text"},
                "missing_capabilities": [],
                "better_capabilities": [],
            }
        )
        ark = {
            "ans": ans,
            "cost_ms": 10,
            "request_payload": {"model": "ep-test", "messages": []},
            "response_json": {"usage": {"total_tokens": 2}},
            "cache_hit": False,
        }
        qwen_ans = json.dumps(
            {
                "goal": "dinner",
                "reason": "no recipe capability",
                "plan": [],
                "presentation": {"type": "text"},
                "missing_capabilities": [{"capability": "recipe.suggest", "reason": "gap"}],
                "better_capabilities": [],
            }
        )
        qwen = {
            "ans": qwen_ans,
            "cost_ms": 77,
            "request_payload": {
                "model": "Qwen2.5-0.5B-Instruct",
                "text": "晚上吃啥",
                "system": "short",
            },
            "response_json": {"reply": qwen_ans},
            "error": None,
            "model": "Qwen2.5-0.5B-Instruct",
            "planner": "qwen",
        }
        with patch.object(hb, "qwen_planner_enabled", return_value=True):
            with patch.object(hb, "call_ark", return_value=ark):
                with patch.object(hb, "call_qwen_planner", return_value=qwen):
                    with patch.object(hb, "do_execution_plan") as do_plan:
                        hb._process_llm_task(
                            {
                                "question": "晚上吃啥",
                                "session_id": "sess-a",
                                "user_id": "u1",
                                "intent_id": iid,
                                "source": "text",
                                "edge_id": "phone-1",
                            }
                        )
                        self._flush_qwen_shadow()
        rows = brain_db.list_intent_reviews(iid)
        planners = [row["planner"] for row in rows]
        self.assertEqual(sorted(planners), ["ark", "qwen"])
        qwen_row = next(row for row in rows if row["planner"] == "qwen")
        self.assertEqual(qwen_row["model"], "Qwen2.5-0.5B-Instruct")
        self.assertEqual(qwen_row["cost_ms"], 77)
        self.assertEqual(qwen_row["request_payload"]["model"], "Qwen2.5-0.5B-Instruct")
        self.assertNotIn("thinking", json.dumps(qwen_row["request_payload"]))
        self.assertTrue(qwen_row["parsed_json"]["shadow"])
        self.assertEqual(do_plan.call_count, 1)

    def test_qwen_shadow_http_error_does_not_fail_intent(self) -> None:
        from unittest.mock import patch

        iid = hb.new_intent(
            {
                "status": "intent_received",
                "text": "现在几点了",
                "source": "text",
                "status_log": [],
            }
        )
        ans = json.dumps(
            {
                "goal": "clock",
                "reason": "ask time",
                "plan": [
                    {
                        "step": 1,
                        "capability": "clock.now",
                        "assigned_edge_id": "sys",
                        "input_constrict": {},
                        "output_constrict": {},
                        "execution_timing": {"mode": "immediate"},
                    }
                ],
                "presentation": {"type": "text", "from": "time_text"},
                "missing_capabilities": [],
                "better_capabilities": [],
            }
        )
        ark = {
            "ans": ans,
            "cost_ms": 11,
            "request_payload": {"model": "ep-test"},
            "response_json": {},
            "cache_hit": False,
        }
        qwen = {
            "ans": "",
            "cost_ms": 5,
            "request_payload": {"model": "Qwen2.5-0.5B-Instruct", "text": "x", "system": "y"},
            "response_json": {"http_status": 500, "body": "boom"},
            "error": "qwen HTTP 500",
            "model": "Qwen2.5-0.5B-Instruct",
            "planner": "qwen",
        }
        with patch.object(hb, "qwen_planner_enabled", return_value=True):
            with patch.object(hb, "call_ark", return_value=ark):
                with patch.object(hb, "call_qwen_planner", return_value=qwen):
                    with patch.object(
                        hb, "sanitize_execution_plan", side_effect=lambda plan, intent=None: plan or []
                    ):
                        with patch.object(hb, "do_execution_plan"):
                            hb._process_llm_task(
                                {
                                    "question": "现在几点了",
                                    "session_id": "sess-a",
                                    "user_id": "u1",
                                    "intent_id": iid,
                                    "source": "text",
                                    "edge_id": "phone-1",
                                }
                            )
                            self._flush_qwen_shadow()
        intent = hb.get_intent(iid)
        rows = brain_db.list_intent_reviews(iid)
        ark_row = next(row for row in rows if row["planner"] == "ark")
        qwen_row = next(row for row in rows if row["planner"] == "qwen")
        self.assertNotEqual(ark_row.get("error"), "qwen HTTP 500")
        self.assertEqual(qwen_row["error"], "qwen HTTP 500")
        self.assertIsNotNone(intent)

    def test_qwen_planner_enabled_only_with_flag(self) -> None:
        old = os.environ.get("QWEN_PLANNER")
        try:
            os.environ.pop("QWEN_PLANNER", None)
            self.assertFalse(hb.qwen_planner_enabled())
            os.environ["QWEN_PLANNER"] = "1"
            self.assertTrue(hb.qwen_planner_enabled())
            os.environ["QWEN_PLANNER"] = "0"
            self.assertFalse(hb.qwen_planner_enabled())
        finally:
            if old is None:
                os.environ.pop("QWEN_PLANNER", None)
            else:
                os.environ["QWEN_PLANNER"] = old
        self.assertIn("115.190.153.53:8090/chat", hb.QWEN_PLANNER_URL)
        self.assertGreaterEqual(float(hb.QWEN_PLANNER_TIMEOUT_SEC), 180.0)

    def test_call_qwen_posts_system_text_and_parses_ok_body(self) -> None:
        from unittest.mock import patch

        captured = {}

        class FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps(
                    {"ok": True, "text": '{"goal":"clock","plan":[]}'}
                ).encode("utf-8")

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["timeout"] = timeout
            captured["body"] = json.loads(req.data.decode("utf-8"))
            captured["method"] = req.get_method()
            return FakeResp()

        with patch.object(hb, "_planner_prompt_pair", return_value=("SYS", "USER TEXT")):
            with patch.object(hb.urllib.request, "urlopen", fake_urlopen):
                out = hb.call_qwen("现在几点了", intent={"id": 1})
        self.assertEqual(captured["url"], hb.QWEN_PLANNER_URL)
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["body"], {"system": "SYS", "text": "USER TEXT"})
        self.assertNotIn("extra_body", captured["body"])
        self.assertNotIn("response_format", captured["body"])
        self.assertNotIn("thinking", json.dumps(captured["body"]))
        self.assertEqual(out["ans"], '{"goal":"clock","plan":[]}')
        self.assertEqual(out["request_payload"], {"system": "SYS", "text": "USER TEXT"})
        self.assertIsNone(out["error"])

    def test_call_qwen_http_500_returns_error_not_raise(self) -> None:
        from unittest.mock import patch

        def fake_urlopen(req, timeout=None):
            raise urllib.error.HTTPError(
                hb.QWEN_PLANNER_URL,
                500,
                "Internal Server Error",
                {},
                io.BytesIO(b"boom"),
            )

        with patch.object(hb, "_planner_prompt_pair", return_value=("S", "T")):
            with patch.object(hb.urllib.request, "urlopen", fake_urlopen):
                out = hb.call_qwen("x", intent={"id": 9})
        self.assertIn("500", out["error"] or "")
        self.assertEqual(out["ans"], "")
        self.assertEqual(out["response_json"]["http_status"], 500)

    def test_process_llm_task_qwen_urlopen_failure_still_runs_doubao(self) -> None:
        from unittest.mock import patch

        iid = hb.new_intent(
            {
                "status": "intent_received",
                "text": "现在几点了",
                "source": "text",
                "status_log": [],
            }
        )
        ans = json.dumps(
            {
                "goal": "clock",
                "reason": "ask time",
                "plan": [
                    {
                        "step": 1,
                        "capability": "clock.now",
                        "assigned_edge_id": "sys",
                        "input_constrict": {},
                        "output_constrict": {},
                        "execution_timing": {"mode": "immediate"},
                    }
                ],
                "presentation": {"type": "text", "from": "time_text"},
                "missing_capabilities": [],
                "better_capabilities": [],
            }
        )
        ark = {
            "ans": ans,
            "cost_ms": 11,
            "request_payload": {"model": "ep-test"},
            "response_json": {},
            "cache_hit": False,
        }

        def fake_urlopen(req, timeout=None):
            raise urllib.error.HTTPError(
                hb.QWEN_PLANNER_URL,
                500,
                "err",
                {},
                io.BytesIO(b"boom"),
            )

        with patch.object(hb, "qwen_planner_enabled", return_value=True):
            with patch.object(hb, "call_ark", return_value=ark):
                with patch.object(hb, "_planner_prompt_pair", return_value=("S", "T")):
                    with patch.object(hb.urllib.request, "urlopen", fake_urlopen):
                        with patch.object(
                            hb,
                            "sanitize_execution_plan",
                            side_effect=lambda plan, intent=None: plan or [],
                        ):
                            with patch.object(hb, "do_execution_plan") as do_plan:
                                hb._process_llm_task(
                                    {
                                        "question": "现在几点了",
                                        "session_id": "sess-a",
                                        "user_id": "u1",
                                        "intent_id": iid,
                                        "source": "text",
                                        "edge_id": "phone-1",
                                    }
                                )
                                self._flush_qwen_shadow()
        intent = hb.get_intent(iid)
        rows = brain_db.list_intent_reviews(iid)
        planners = sorted(row["planner"] for row in rows)
        self.assertEqual(planners, ["ark", "qwen"])
        qwen_row = next(row for row in rows if row["planner"] == "qwen")
        ark_row = next(row for row in rows if row["planner"] == "ark")
        self.assertIn("500", qwen_row["error"] or "")
        self.assertEqual(do_plan.call_count, 1)
        self.assertNotEqual(ark_row.get("error"), qwen_row.get("error"))

    def test_qwen_shadow_timeout_does_not_fail_intent(self) -> None:
        from unittest.mock import patch

        iid = hb.new_intent(
            {
                "status": "intent_received",
                "text": "现在几点了",
                "source": "text",
                "status_log": [],
            }
        )
        ans = json.dumps(
            {
                "goal": "clock",
                "reason": "ask time",
                "plan": [
                    {
                        "step": 1,
                        "capability": "clock.now",
                        "assigned_edge_id": "sys",
                        "input_constrict": {},
                        "output_constrict": {},
                        "execution_timing": {"mode": "immediate"},
                    }
                ],
                "presentation": {"type": "text", "from": "time_text"},
                "missing_capabilities": [],
                "better_capabilities": [],
            }
        )
        ark = {
            "ans": ans,
            "cost_ms": 9,
            "request_payload": {"model": "ep-test"},
            "response_json": {},
            "cache_hit": True,
        }

        def fake_urlopen(req, timeout=None):
            raise TimeoutError("timed out")

        with patch.object(hb, "qwen_planner_enabled", return_value=True):
            with patch.object(hb, "call_ark", return_value=ark):
                with patch.object(hb, "_planner_prompt_pair", return_value=("S", "T")):
                    with patch.object(hb.urllib.request, "urlopen", fake_urlopen):
                        with patch.object(
                            hb,
                            "sanitize_execution_plan",
                            side_effect=lambda plan, intent=None: plan or [],
                        ):
                            with patch.object(hb, "do_execution_plan") as do_plan:
                                hb._process_llm_task(
                                    {
                                        "question": "现在几点了",
                                        "session_id": "sess-a",
                                        "user_id": "u1",
                                        "intent_id": iid,
                                        "source": "text",
                                        "edge_id": "phone-1",
                                    }
                                )
                                self._flush_qwen_shadow()
        intent = hb.get_intent(iid)
        rows = brain_db.list_intent_reviews(iid)
        qwen_row = next(row for row in rows if row["planner"] == "qwen")
        self.assertTrue(qwen_row.get("error"))
        self.assertEqual(do_plan.call_count, 1)
        ark_row = next(row for row in rows if row["planner"] == "ark")
        self.assertNotIn("timed out", str(ark_row.get("error") or "").lower())
        self.assertIsNotNone(intent)

    def test_qwen_still_called_on_doubao_cache_hit(self) -> None:
        from unittest.mock import patch

        iid = hb.new_intent(
            {
                "status": "intent_received",
                "text": "现在几点了",
                "source": "text",
                "status_log": [],
            }
        )
        ans = json.dumps(
            {
                "goal": "clock",
                "reason": "ask time",
                "plan": [
                    {
                        "step": 1,
                        "capability": "clock.now",
                        "assigned_edge_id": "sys",
                        "input_constrict": {},
                        "output_constrict": {},
                        "execution_timing": {"mode": "immediate"},
                    }
                ],
                "presentation": {"type": "text", "from": "time_text"},
                "missing_capabilities": [],
                "better_capabilities": [],
            }
        )
        ark = {
            "ans": ans,
            "cost_ms": 0,
            "request_payload": None,
            "response_json": None,
            "cache_hit": True,
        }
        qwen = {
            "ans": '{"goal":"shadow"}',
            "cost_ms": 3,
            "request_payload": {"system": "S", "text": "T"},
            "response_json": {"ok": True, "text": '{"goal":"shadow"}'},
            "error": None,
            "model": "Qwen2.5-0.5B-Instruct",
            "planner": "qwen",
        }
        with patch.object(hb, "qwen_planner_enabled", return_value=True):
            with patch.object(hb, "call_ark", return_value=ark):
                with patch.object(hb, "call_qwen_planner", return_value=qwen) as qwen_mock:
                    with patch.object(
                        hb,
                        "sanitize_execution_plan",
                        side_effect=lambda plan, intent=None: plan or [],
                    ):
                        with patch.object(hb, "do_execution_plan") as do_plan:
                            hb._process_llm_task(
                                {
                                    "question": "现在几点了",
                                    "session_id": "sess-a",
                                    "user_id": "u1",
                                    "intent_id": iid,
                                    "source": "text",
                                    "edge_id": "phone-1",
                                }
                            )
                            qwen_mock.assert_not_called()
                            self._flush_qwen_shadow()
        qwen_mock.assert_called()
        self.assertEqual(do_plan.call_count, 1)
        planners = [row["planner"] for row in brain_db.list_intent_reviews(iid)]
        self.assertEqual(sorted(planners), ["ark", "qwen"])

    def test_process_llm_task_returns_without_waiting_for_slow_qwen(self) -> None:
        from unittest.mock import patch

        iid = hb.new_intent(
            {
                "status": "intent_received",
                "text": "现在几点了",
                "source": "text",
                "status_log": [],
            }
        )
        ans = json.dumps(
            {
                "goal": "clock",
                "reason": "ask time",
                "plan": [
                    {
                        "step": 1,
                        "capability": "clock.now",
                        "assigned_edge_id": "sys",
                        "input_constrict": {},
                        "output_constrict": {},
                        "execution_timing": {"mode": "immediate"},
                    }
                ],
                "presentation": {"type": "text", "from": "time_text"},
                "missing_capabilities": [],
                "better_capabilities": [],
            }
        )
        ark = {
            "ans": ans,
            "cost_ms": 8,
            "request_payload": {"model": "ep-test"},
            "response_json": {},
            "cache_hit": False,
        }
        qwen = {
            "ans": '{"goal":"shadow"}',
            "cost_ms": 400,
            "request_payload": {"system": "S", "text": "T"},
            "response_json": {"ok": True, "text": '{"goal":"shadow"}'},
            "error": None,
            "model": "Qwen2.5-0.5B-Instruct",
            "planner": "qwen",
        }

        def slow_qwen(*args, **kwargs):
            time.sleep(0.4)
            return qwen

        with patch.object(hb, "qwen_planner_enabled", return_value=True):
            with patch.object(hb, "call_ark", return_value=ark):
                with patch.object(hb, "call_qwen_planner", side_effect=slow_qwen):
                    with patch.object(
                        hb,
                        "sanitize_execution_plan",
                        side_effect=lambda plan, intent=None: plan or [],
                    ):
                        with patch.object(hb, "do_execution_plan") as do_plan:
                            t0 = time.monotonic()
                            hb._process_llm_task(
                                {
                                    "question": "现在几点了",
                                    "session_id": "sess-a",
                                    "user_id": "u1",
                                    "intent_id": iid,
                                    "source": "text",
                                    "edge_id": "phone-1",
                                }
                            )
                            elapsed = time.monotonic() - t0
                            self.assertLess(elapsed, 0.25)
                            self.assertEqual(do_plan.call_count, 1)
                            planners = [
                                row["planner"] for row in brain_db.list_intent_reviews(iid)
                            ]
                            self.assertEqual(planners, ["ark"])
                            self.assertGreaterEqual(hb.qwen_task_queue.qsize(), 1)
                            self._flush_qwen_shadow()
        planners = [row["planner"] for row in brain_db.list_intent_reviews(iid)]
        self.assertEqual(sorted(planners), ["ark", "qwen"])
        qwen_row = next(
            row for row in brain_db.list_intent_reviews(iid) if row["planner"] == "qwen"
        )
        self.assertTrue(qwen_row["parsed_json"]["shadow"])

    def _register_reading_mac(self, pid: str = "mac-reading") -> None:
        brain_db.put_registration(
            {
                "participant_id": pid,
                "device_type": "mac",
                "roles": ["intent_source", "runtime", "endpoint"],
                "intent_sources": [{"source_id": "microphone", "channel": "voice"}],
                "endpoints": [
                    {
                        "endpoint_id": "mac.display",
                        "supported_presentation": ["text", "audio"],
                    }
                ],
                "services": [
                    {
                        "service_id": "local.camera",
                        "group": "camera",
                        "capabilities": [
                            {
                                "capability_id": "camera.capture_and_upload",
                                "input_schema": {},
                                "output_schema": {},
                            },
                            {
                                "capability_id": "reading.point_to_character",
                                "input_schema": {},
                                "output_schema": {},
                            },
                        ],
                    },
                    {
                        "service_id": "local.notify",
                        "group": "notify",
                        "capabilities": [
                            {
                                "capability_id": "notify.speak",
                                "input_schema": {},
                                "output_schema": {},
                            }
                        ],
                    },
                ],
            }
        )
        self._heartbeat(pid)
        hb._REGISTERED_edges = brain_db.registration_ids()
        hb.rebuild_capability_maps()

    def test_shortcut_enter_reading_mode_skips_llm(self) -> None:
        self._register_reading_mac()
        client = hb.app.test_client()
        before_qsize = hb.task_queue.qsize()
        resp = client.post(
            "/api/v1/intent",
            json={
                "text": "开启阅读模式",
                "source": "voice",
                "participant_id": "mac-reading",
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["intent_status"], "intent_parsed")
        self.assertEqual(body["task_kind"], "shortcut")
        self.assertEqual(hb.task_queue.qsize(), before_qsize)
        self.assertEqual(brain_db.resolve_active_mode(), "reading")
        plan = hb.get_intent(body["intent_id"])["execution_plan"]
        self.assertEqual(plan[0]["capability"], "notify.speak")

    def test_shortcut_reading_pipeline_when_mode_active(self) -> None:
        self._register_reading_mac()
        brain_db.append_global_event(
            {"kind": "mode", "action": "activate", "subject": "reading"}
        )
        client = hb.app.test_client()
        resp = client.post(
            "/api/v1/intent",
            json={
                "text": "这个字怎么读",
                "source": "voice",
                "participant_id": "mac-reading",
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["intent_status"], "intent_parsed")
        self.assertEqual(body["task_kind"], "shortcut")
        caps = [s["capability"] for s in hb.get_intent(body["intent_id"])["execution_plan"]]
        self.assertEqual(
            caps,
            [
                "camera.capture_and_upload",
                "reading.point_to_character",
                "notify.speak",
            ],
        )

    def test_shortcut_reading_existing_photo_skips_capture(self) -> None:
        self._register_reading_mac()
        brain_db.append_global_event(
            {"kind": "mode", "action": "activate", "subject": "reading"}
        )
        client = hb.app.test_client()
        resp = client.post(
            "/api/v1/intent",
            json={
                "text": "看下最新的一张照片里手指的那个字是什么",
                "source": "voice",
                "participant_id": "mac-reading",
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["intent_status"], "intent_parsed")
        self.assertEqual(body["task_kind"], "shortcut")
        caps = [s["capability"] for s in hb.get_intent(body["intent_id"])["execution_plan"]]
        self.assertEqual(
            caps,
            [
                "asset.inventory",
                "reading.point_to_character",
                "notify.speak",
            ],
        )

    def test_shortcut_reading_pipeline_fails_without_capture_device(self) -> None:
        self._register_live_issuer("iphone-offline")
        hb._REGISTERED_edges = brain_db.registration_ids()
        hb.rebuild_capability_maps()
        brain_db.append_global_event(
            {"kind": "mode", "action": "activate", "subject": "reading"}
        )
        client = hb.app.test_client()
        resp = client.post(
            "/api/v1/intent",
            json={
                "text": "这个字怎么读",
                "source": "voice",
                "participant_id": "iphone-offline",
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["intent_status"], "failed")
        self.assertEqual(body["task_kind"], "shortcut")
        self.assertIn("拍照", body.get("error") or body.get("reply") or "")

    def test_shortcut_reading_mode_unrelated_falls_through_to_queue(self) -> None:
        self._register_reading_mac()
        brain_db.append_global_event(
            {"kind": "mode", "action": "activate", "subject": "reading"}
        )
        client = hb.app.test_client()
        before_qsize = hb.task_queue.qsize()
        resp = client.post(
            "/api/v1/intent",
            json={
                "text": "开一下灯",
                "source": "voice",
                "participant_id": "mac-reading",
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["intent_status"], "intent_received")
        self.assertGreater(hb.task_queue.qsize(), before_qsize)

    def test_get_mode_api(self) -> None:
        brain_db.append_global_event(
            {"kind": "mode", "action": "activate", "subject": "reading"}
        )
        client = hb.app.test_client()
        resp = client.get("/api/v1/mode")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["mode"], "reading")
        self.assertGreaterEqual(len(body["events"]), 1)

    def test_intent_accepts_named_audio_refs_in_context(self) -> None:
        """pronunciation.assess: reference_audio + student_audio attached to an
        intent must land in ctx_param (typed audio) and get read grants."""
        self._register_live_issuer("phone-1")
        client = hb.app.test_client()
        resp = client.post(
            "/api/v1/intent",
            json={
                "text": "评测这段跟读",
                "edge_id": "phone-1",
                "context": {
                    "reference_audio": {
                        "asset_id": "asset_refaudio01",
                        "type": "audio",
                        "mime_type": "audio/wav",
                    },
                    "student_audio": {
                        "asset_id": "asset_stuaudio01",
                        "type": "audio",
                        "mime_type": "audio/wav",
                    },
                },
            },
        )
        self.assertEqual(resp.status_code, 200)
        iid = resp.get_json()["intent_id"]
        job = brain_db.get_job(iid)
        assert job is not None
        ctx = job.get("ctx_param") or job.get("context") or {}
        if isinstance(ctx, str):
            ctx = json.loads(ctx)
        self.assertEqual(ctx.get("reference_audio", {}).get("asset_id"), "asset_refaudio01")
        self.assertEqual(ctx.get("reference_audio", {}).get("type"), "audio")
        self.assertEqual(ctx.get("student_audio", {}).get("asset_id"), "asset_stuaudio01")
        self.assertEqual(ctx.get("student_audio", {}).get("type"), "audio")
        # Read grants issued for both audio assets.
        if callable(getattr(brain_db, "list_asset_grants", None)):
            grants = brain_db.list_asset_grants(intent_id=iid)
            aids = {g.get("asset_id") for g in (grants or [])}
            self.assertIn("asset_refaudio01", aids)
            self.assertIn("asset_stuaudio01", aids)


@unittest.skipUnless(flask is not None and hb is not None, "flask not installed")
class UrlAssetApiTests(unittest.TestCase):
    """POST /api/v1/assets/register：url 资产注册 / 授权读取 / content 302。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "brain.sqlite3"
        brain_db.reset(path=self.path)
        brain_db.init_db()
        hb._REGISTERED_edges = brain_db.registration_ids()
        hb.rebuild_capability_maps()
        hb.mock_cache.clear()
        self._qwen_flag = os.environ.get("QWEN_PLANNER")
        os.environ["QWEN_PLANNER"] = "0"

    def tearDown(self) -> None:
        if self._qwen_flag is None:
            os.environ.pop("QWEN_PLANNER", None)
        else:
            os.environ["QWEN_PLANNER"] = self._qwen_flag
        brain_db.reset()
        self._tmp.cleanup()

    def test_register_url_asset_and_content_redirect(self) -> None:
        client = hb.app.test_client()
        resp = client.post(
            "/api/v1/assets/register",
            json={
                "type": "url",
                "url": "https://example.com/page?x=1",
                "title": "示例",
                "intent_id": "1001",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        aid = data["asset_id"]
        self.assertEqual(data["type"], "url")
        self.assertEqual(data["url"], "https://example.com/page?x=1")

        rec = brain_db.get_asset(aid)
        self.assertEqual(rec["type"], "url")
        self.assertIn("url_target", rec.get("metadata", {}))

        # 授权 intent 取 /content → 302 到目标链接
        content = client.get(f"/api/v1/assets/{aid}/content?intent_id=1001")
        self.assertEqual(content.status_code, 302)
        self.assertEqual(content.headers.get("Location"), "https://example.com/page?x=1")

        # 非授权 public 视图：type=url 但隐藏 url_target
        view = client.get(f"/api/v1/assets/{aid}")
        self.assertEqual(view.status_code, 200)
        asset = view.get_json()["asset"]
        self.assertEqual(asset["type"], "url")
        self.assertNotIn("url_target", asset.get("metadata", {}))
        self.assertNotIn("url", asset)

    def test_register_rejects_bad_url_and_type(self) -> None:
        client = hb.app.test_client()
        bad = client.post(
            "/api/v1/assets/register", json={"type": "url", "url": "file:///etc/passwd"}
        )
        self.assertEqual(bad.status_code, 400)
        wrong_type = client.post(
            "/api/v1/assets/register",
            json={"type": "document", "url": "https://example.com/x"},
        )
        self.assertEqual(wrong_type.status_code, 400)


if __name__ == "__main__":
    unittest.main()

