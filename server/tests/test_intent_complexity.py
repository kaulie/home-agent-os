"""Intent Complexity Classifier V1: rules, ads matcher, observe-only APIs."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SERVER = Path(__file__).resolve().parents[1]
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

os.environ["BRAIN_SKIP_LLM_WORKER"] = "1"

try:
    import flask  # noqa: F401
except ImportError:  # pragma: no cover
    flask = None  # type: ignore

import db as brain_db  # noqa: E402
from capability_ads import ADS  # noqa: E402
from intent_complexity import CLASSIFIER_VERSION, classify  # noqa: E402
from intent_complexity.matcher import ALIASES, match_candidates  # noqa: E402

if flask is not None:
    import home_brain as hb  # noqa: E402
else:
    hb = None  # type: ignore


class FeatureExtractorTest(unittest.TestCase):
    def test_golden_simple_open_light(self) -> None:
        result = classify("打开客厅灯。")
        self.assertEqual(result["classification"], "SIMPLE")
        self.assertLessEqual(abs(result["score"] - 2.0), 1.0)
        ids = {row["capability_id"] for row in result["candidates"]}
        self.assertIn("light.set", ids)
        self.assertEqual(result["features"]["condition_count"], 0)
        self.assertEqual(result["features"]["sequence_count"], 0)

    def test_golden_medium_cast_last_photo(self) -> None:
        result = classify("把刚才拍的照片投到电视上。")
        self.assertEqual(result["classification"], "MEDIUM")
        self.assertGreaterEqual(result["features"]["context_reference_count"], 1)
        ids = {row["capability_id"] for row in result["candidates"]}
        self.assertIn("display.photo", ids)

    def test_golden_complex_conditional_cast_and_ask(self) -> None:
        result = classify(
            "如果刚才拍的照片里有人，就把它投到电视上，然后告诉我照片里有几个人。"
        )
        self.assertEqual(result["classification"], "COMPLEX")
        self.assertGreaterEqual(result["features"]["condition_count"], 1)
        self.assertGreaterEqual(result["features"]["sequence_count"], 1)
        self.assertGreaterEqual(result["features"]["capability_candidate_count"], 2)

    def test_condition_sequence_parallel_temporal_context(self) -> None:
        cond = classify("如果下雨就关窗")
        self.assertGreaterEqual(cond["features"]["condition_count"], 1)
        seq = classify("先拍照，然后投到电视上。")
        self.assertGreaterEqual(seq["features"]["sequence_count"], 1)
        par = classify("把客厅和餐厅的灯都打开。")
        self.assertGreaterEqual(par["features"]["parallel_count"], 1)
        temporal = classify("10分钟后关灯")
        self.assertGreaterEqual(temporal["features"]["temporal_count"], 1)
        ctx = classify("把刚才那张图投屏")
        self.assertGreaterEqual(ctx["features"]["context_reference_count"], 1)

    def test_dim_a_bit_is_ambiguous(self) -> None:
        result = classify("弄亮一点")
        self.assertEqual(result["features"]["ambiguity"], 1)

    def test_capture_is_simple(self) -> None:
        for text in ("拍照", "拍一张", "拍照。"):
            result = classify(text)
            self.assertEqual(result["classification"], "SIMPLE", text)
            self.assertLessEqual(result["score"], 3.0, text)
            self.assertEqual(result["features"]["ambiguity"], 0, text)
            ids = {row["capability_id"] for row in result["candidates"]}
            self.assertIn("camera.capture", ids, text)

    def test_weights_change_score(self) -> None:
        text = "打开客厅灯。"
        base = classify(text)
        boosted = classify(
            text,
            weights={
                "capability_candidate_count": 10.0,
                "action_count": 10.0,
                "condition_count": 0.0,
                "sequence_count": 0.0,
                "parallel_count": 0.0,
                "temporal_count": 0.0,
                "context_reference_count": 0.0,
                "ambiguity": 0.0,
                "text_length_factor": 0.0,
            },
        )
        self.assertNotEqual(base["score"], boosted["score"])
        self.assertGreater(boosted["score"], base["score"])
        forced = classify(text, simple_max=0.0, medium_max=0.0)
        self.assertEqual(forced["classification"], "COMPLEX")

    def test_vocab_gaps_get_candidates(self) -> None:
        call = classify("给李秀平打电话")
        self.assertIn("phone.call", {row["capability_id"] for row in call["candidates"]})
        self.assertGreaterEqual(call["features"]["capability_candidate_count"], 1)

        lamp = classify("打打开台灯。")
        self.assertIn("light.set", {row["capability_id"] for row in lamp["candidates"]})

        date = classify("今天是几月几号？")
        self.assertIn("clock.now", {row["capability_id"] for row in date["candidates"]})

        recent = classify("看一下刚才的照片")
        self.assertIn("asset.inventory", {row["capability_id"] for row in recent["candidates"]})

        last = classify("看一下最最最后一张照片")
        self.assertIn("asset.inventory", {row["capability_id"] for row in last["candidates"]})

    def test_matcher_only_uses_ads_ids(self) -> None:
        self.assertTrue(set(ALIASES).issubset(set(ADS)))
        hits = match_candidates("打开客厅灯，投到电视上，告诉我照片里有几个人")
        for row in hits:
            self.assertIn(row["capability_id"], ADS)
            self.assertIn(row["strength"], {"trigger", "recognize", "alias"})
        classified = classify("打开客厅灯")
        for row in classified["candidates"]:
            self.assertIn(row["capability_id"], ADS)
        self.assertEqual(classified["classifier_version"], CLASSIFIER_VERSION)

    def test_capture_ad_does_not_own_upload(self) -> None:
        ad = ADS["camera.capture"]
        self.assertTrue(
            any("上传" in x or "图床" in x for x in ad["do_not_dispatch"]),
            ad["do_not_dispatch"],
        )
        self.assertIn("capture_ref", ad["planner_recognize"])
        self.assertNotIn("photo_url", ad["planner_recognize"])

    def test_asset_upload_ad_is_separate_step(self) -> None:
        ad = ADS["asset.upload"]
        self.assertEqual(ad["kind"], "action")
        self.assertIn("$capture_ref", ad["planner_recognize"])
        self.assertTrue(
            any("传到云上" in t or "图床" in t for t in ad["typical_triggers"]),
            ad["typical_triggers"],
        )
        self.assertIn("拍照", ad["do_not_dispatch"])

    def test_plan_helpers_split_capture_and_upload(self) -> None:
        from edge_services import plan_asset_upload, plan_camera_capture

        capture = plan_camera_capture()[0]
        self.assertEqual(capture["capability"], "camera.capture")
        self.assertIn("capture_ref", capture["output_constrict"])
        self.assertNotIn("photo_url", capture["output_constrict"])
        upload = plan_asset_upload()[0]
        self.assertEqual(upload["capability"], "asset.upload")
        self.assertEqual(upload["input_constrict"]["capture_ref"], "$capture_ref")


@unittest.skipUnless(flask is not None, "flask not installed in this interpreter")
class IntentClassifyApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "brain.sqlite3"
        brain_db.reset(path=self.path)
        brain_db.init_db()
        hb._REGISTERED_edges = brain_db.registration_ids()
        hb.rebuild_capability_maps()

    def tearDown(self) -> None:
        brain_db.reset()
        self._tmp.cleanup()

    def _register_live_issuer(self, pid: str) -> None:
        import time

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
        hb._REGISTERED_edges = brain_db.registration_ids()

    def test_classify_api_contract(self) -> None:
        client = hb.app.test_client()
        missing = client.post("/api/v1/intent_classify", json={})
        self.assertEqual(missing.status_code, 400)
        self.assertFalse(missing.get_json()["ok"])
        resp = client.post(
            "/api/v1/intent_classify",
            json={"text": "打开客厅灯。"},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["classification"], "SIMPLE")
        self.assertIn("score", body)
        self.assertIn("features", body)
        self.assertIn("candidates", body)
        self.assertEqual(body["classifier_version"], CLASSIFIER_VERSION)
        self.assertNotIn("execution_plan", body)
        stats = client.get("/api/v1/intent_classify/stats")
        self.assertEqual(stats.status_code, 200)
        payload = stats.get_json()
        self.assertTrue(payload["ok"])
        self.assertGreaterEqual(payload["n"], 1)
        self.assertIn("simple_rate", payload)
        self.assertNotIn("text", payload)

    def test_post_intent_still_queues_and_hides_classification(self) -> None:
        self._register_live_issuer("iphone-origin")
        client = hb.app.test_client()
        queued = hb.task_queue.qsize()
        resp = client.post(
            "/api/v1/intent",
            json={
                "text": "打开客厅灯。",
                "source": "text",
                "participant_id": "iphone-origin",
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["intent_status"], "intent_received")
        self.assertNotIn("classification", body)
        self.assertEqual(hb.task_queue.qsize(), queued + 1)
        iid = body["intent_id"]
        job = brain_db.get_job(iid)
        assert job is not None
        self.assertEqual(job["status"], "intent_received")
        self.assertEqual(job.get("execution_plan") or [], [])
        events = brain_db.list_intent_classification_events(iid)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["classification"], "SIMPLE")
        detail = client.get(f"/api/v1/intent_detail?intent_id={iid}")
        shown = detail.get_json()
        self.assertNotIn("classification", shown)
        self.assertEqual(shown.get("execution_plan") or [], [])

    def test_classify_failure_does_not_block_intent(self) -> None:
        self._register_live_issuer("iphone-origin")
        client = hb.app.test_client()
        queued = hb.task_queue.qsize()
        with mock.patch.object(
            hb, "classify_intent_complexity", side_effect=RuntimeError("boom")
        ):
            resp = client.post(
                "/api/v1/intent",
                json={
                    "text": "现在几点了",
                    "participant_id": "iphone-origin",
                },
            )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["ok"])
        self.assertEqual(resp.get_json()["intent_status"], "intent_received")
        self.assertEqual(hb.task_queue.qsize(), queued + 1)


if __name__ == "__main__":
    unittest.main()
