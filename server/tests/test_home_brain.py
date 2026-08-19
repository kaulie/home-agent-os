"""home_brain.py persists intents in SQLite; ids continue after reconnect."""

from __future__ import annotations

import os
import sys
import json
import tempfile
import time
import unittest
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

    def _heartbeat(self, pid: str, *, age_sec: float = 0) -> None:
        received = time.time() - age_sec
        brain_db.put_heartbeat(
            pid,
            {
                "online_status": "online",
                "server_received_at": received,
                "reported_at": received,
            },
        )

    def tearDown(self) -> None:
        brain_db.reset()
        self._tmp.cleanup()

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

    def test_post_intent_persists_schema_columns(self) -> None:
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

    def test_pull_hides_terminal_and_filters_edge(self) -> None:
        client = hb.app.test_client()
        parsed = client.post(
            "/api/v1/devices/living-room/intents",
            json={
                "execution_plan": [
                    {"capability": "notify.speak", "step": 1, "assigned_edge_id": "edge-a"}
                ],
                "assigned_edge_id": "edge-a",
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
        )
        brain_db.reset(path=self.path)
        brain_db.init_db()
        rows = brain_db.list_intent_reviews(session_id="sess-a")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["session_id"], "sess-a")
        self.assertEqual(rows[0]["source"], "text")
        self.assertEqual(rows[0]["edge_id"], "phone-1")

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

    def test_sanitize_photo_without_capture_is_empty(self) -> None:
        intent = {"text": "拍照给我看看", "source": "text"}
        plan = [{"step": 1, "capability": "notify.speak"}]
        self.assertEqual(hb.sanitize_execution_plan(plan, intent), [])

    def test_planner_prompt_does_not_name_capabilities(self) -> None:
        named = (
            "light.set",
            "clock.now",
            "notify.speak",
            "camera.capture",
            "music.play",
            "query.content",
            "display.photo",
            "display.slideshow",
            "vision.perceive",
            "vision.ask",
            "endpoint.present",
            "endpoint.feedback",
        )
        prompt = hb.compact_prompt()
        for name in named:
            self.assertNotIn(name, prompt)
        for name in named:
            self.assertNotIn(name, hb.PLANNER_SYSTEM_PROMPT)

    def test_planner_prompt_trusts_advertised_description(self) -> None:
        prompt = hb.compact_prompt()
        self.assertIn("self-description is the source of truth", prompt)
        self.assertIn("optional output", prompt)
        self.assertIn("Advertised capability `description`", prompt)
        self.assertIn("description", hb.PLANNER_SYSTEM_PROMPT)
        self.assertIn("可选产出", hb.PLANNER_SYSTEM_PROMPT)

    def test_capability_registry_uses_runtime_description(self) -> None:
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
                                "description": (
                                    "客厅大路灯开或关。用户说开灯/关灯时用本能力。"
                                    "禁止拆成其他能力。必填 state=on 或 off。"
                                ),
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
        self.assertIn("开灯", light["description"])
        self.assertIn("禁止拆成其他能力", light["description"])
        self.assertEqual(light["input_schema"]["state"]["required"], True)

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
        self.assertEqual(pres["type"], "text")
        self.assertEqual(pres["from"], "state")
        self.assertEqual(pres["text"], "on")
        self.assertNotIn("image_url", pres)

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
            "ctx_param": {"capture_ref": dict(_CAPTURE_REF)},
        }
        pres = hb.assemble_presentation(intent)
        self.assertEqual(pres["type"], "image")
        self.assertEqual(pres["from"], "asset_ref")
        self.assertEqual(pres["channel"], "iphone")
        self.assertEqual(pres["endpoint"], "living-room-iphone-1")
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
                "capture_ref": dict(_CAPTURE_REF),
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
                "capture_ref": dict(_CAPTURE_REF),
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
                "capture_ref": dict(_CAPTURE_REF),
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
                "capture_ref": dict(_CAPTURE_REF),
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

    def test_assemble_presentation_endpoint_ttl_is_not_runtime_30s(self) -> None:
        self._register_endpoint("iphone-recent", "iphone")
        self._heartbeat("iphone-recent", age_sec=hb.ONLINE_TTL_SEC + 5)
        intent = {
            "text": "拍张照片我看一下",
            "source": "voice",
            "edge_id": "iphone-recent",
            "ctx_param": {"capture_ref": dict(_CAPTURE_REF)},
        }
        pres = hb.assemble_presentation(intent)
        self.assertGreater(hb.ENDPOINT_TTL_SEC, hb.ONLINE_TTL_SEC)
        self.assertEqual(pres["endpoint"], "iphone-recent")

    def test_assemble_presentation_stale_issuer_falls_back_to_live_endpoint(self) -> None:
        self._register_endpoint("iphone-stale", "iphone")
        self._register_endpoint("kindle-live", "kindle")
        self._heartbeat("iphone-stale", age_sec=hb.ENDPOINT_TTL_SEC + 10)
        self._heartbeat("kindle-live", age_sec=0)
        intent = {
            "text": "拍张照片我看一下",
            "source": "voice",
            "edge_id": "iphone-stale",
            "ctx_param": {"capture_ref": dict(_CAPTURE_REF)},
        }
        pres = hb.assemble_presentation(intent)
        self.assertEqual(pres["endpoint"], "kindle-live")
        self.assertEqual(pres["channel"], "kindle")

    def test_assemble_presentation_stale_issuer_alone_is_empty(self) -> None:
        self._register_endpoint("iphone-stale", "iphone")
        self._heartbeat("iphone-stale", age_sec=hb.ENDPOINT_TTL_SEC + 10)
        intent = {
            "text": "拍张照片我看一下",
            "source": "voice",
            "edge_id": "iphone-stale",
            "ctx_param": {"capture_ref": dict(_CAPTURE_REF)},
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

    def test_post_intent_accepts_participant_id(self) -> None:
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
                    "public_base": "http://192.168.3.65:8080",
                },
            },
        )
        self.assertEqual(reg.status_code, 200)
        reg_body = reg.get_json()
        self.assertTrue(reg_body.get("ok"))
        self.assertEqual(reg_body.get("asset_id"), "asset_test1")
        meta_only = client.get("/api/v1/assets/asset_test1")
        self.assertEqual(meta_only.status_code, 200)
        self.assertNotIn("storage", meta_only.get_json().get("asset") or {})
        with_grant = client.get("/api/v1/assets/asset_test1?intent_id=77")
        self.assertEqual(with_grant.status_code, 200)
        wg = with_grant.get_json()
        self.assertIn("storage", wg.get("asset") or {})


if __name__ == "__main__":
    unittest.main()
