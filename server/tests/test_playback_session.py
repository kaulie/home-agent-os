"""playback_sessions 表 + capability→scene 挂钩 + 查询接口测试。"""

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
import playback_session  # noqa: E402

if flask is not None:
    import home_brain as hb  # noqa: E402
else:  # pragma: no cover
    hb = None


class PlaybackSessionDbTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "brain.sqlite3"
        brain_db.reset(path=self.path)
        brain_db.init_db()

    def tearDown(self) -> None:
        brain_db.reset()
        self._tmp.cleanup()

    def test_upsert_get_roundtrip(self) -> None:
        sid = brain_db.upsert_playback_session(
            {
                "scene": "tv_pdf",
                "edge_id": "mac-edge",
                "target": "小米电视 DLNA",
                "asset_id": "asset_1",
                "position": 1,
                "total": 3,
                "state": "playing",
                "payload": {"status_text": "已把 PDF 投到电视，第 1 页 / 共 3 页"},
                "last_intent_id": "100",
            }
        )
        self.assertGreater(sid, 0)
        row = brain_db.get_playback_session("tv_pdf")
        assert row is not None
        self.assertEqual(row["session_id"], sid)
        self.assertEqual(row["edge_id"], "mac-edge")
        self.assertEqual(row["position"], 1)
        self.assertEqual(row["total"], 3)
        self.assertEqual(row["state"], "playing")
        self.assertEqual(row["payload"]["status_text"], "已把 PDF 投到电视，第 1 页 / 共 3 页")
        self.assertEqual(row["last_intent_id"], "100")

    def test_upsert_latest_wins_same_scene_edge(self) -> None:
        sid1 = brain_db.upsert_playback_session(
            {"scene": "tv_pdf", "edge_id": "mac-edge", "state": "playing", "position": 1, "total": 3}
        )
        sid2 = brain_db.upsert_playback_session(
            {"scene": "tv_pdf", "edge_id": "mac-edge", "state": "playing", "position": 2, "total": 3}
        )
        self.assertEqual(sid1, sid2)
        row = brain_db.get_playback_session("tv_pdf", edge_id="mac-edge")
        assert row is not None
        self.assertEqual(row["position"], 2)
        rows = brain_db.list_playback_sessions(scene="tv_pdf")
        self.assertEqual(len(rows), 1)

    def test_scenes_and_edges_isolated(self) -> None:
        brain_db.upsert_playback_session(
            {"scene": "tv_pdf", "edge_id": "mac-edge", "state": "playing", "position": 2}
        )
        brain_db.upsert_playback_session(
            {"scene": "music", "edge_id": "mac-edge", "state": "playing", "position": 30}
        )
        brain_db.upsert_playback_session(
            {"scene": "tv_pdf", "edge_id": "other-edge", "state": "paused", "position": 5}
        )
        self.assertEqual(len(brain_db.list_playback_sessions()), 3)
        self.assertEqual(len(brain_db.list_playback_sessions(scene="tv_pdf")), 2)
        music = brain_db.get_playback_session("music")
        assert music is not None
        self.assertEqual(music["position"], 30)

    def test_required_fields_validated(self) -> None:
        with self.assertRaises(ValueError):
            brain_db.upsert_playback_session({"scene": "", "edge_id": "e", "state": "playing"})
        with self.assertRaises(ValueError):
            brain_db.upsert_playback_session({"scene": "tv_pdf", "edge_id": "", "state": "playing"})
        with self.assertRaises(ValueError):
            brain_db.upsert_playback_session({"scene": "tv_pdf", "edge_id": "e", "state": ""})


class PlaybackSessionMappingTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "brain.sqlite3"
        brain_db.reset(path=self.path)
        brain_db.init_db()

    def tearDown(self) -> None:
        brain_db.reset()
        self._tmp.cleanup()

    def _intent(self, capability: str, constrict: dict | None = None) -> dict:
        return {
            "intent_id": "55",
            "execution_plan": [
                {
                    "step": 1,
                    "capability": capability,
                    "input_constrict": constrict or {},
                    "assigned_edge_id": "mac-edge",
                }
            ],
        }

    def test_display_pdf_page_outputs_mapped(self) -> None:
        sid = playback_session.record_from_step(
            intent=self._intent("display.pdf.page", {"action": "next", "appliance": "小米电视 DLNA"}),
            step_id=1,
            step_status=2,
            outputs={"page": 2, "page_count": 3, "asset_id": "asset_9", "status_text": "已翻到第 2 页 / 共 3 页"},
        )
        self.assertIsNotNone(sid)
        row = brain_db.get_playback_session("tv_pdf")
        assert row is not None
        self.assertEqual(row["scene"], "tv_pdf")
        self.assertEqual(row["edge_id"], "mac-edge")
        self.assertEqual(row["target"], "小米电视 DLNA")
        self.assertEqual(row["asset_id"], "asset_9")
        self.assertEqual(row["position"], 2)
        self.assertEqual(row["total"], 3)
        self.assertEqual(row["state"], "playing")
        self.assertEqual(row["payload"]["status_text"], "已翻到第 2 页 / 共 3 页")
        self.assertEqual(row["last_intent_id"], "55")

    def test_unmapped_capability_noop(self) -> None:
        sid = playback_session.record_from_step(
            intent=self._intent("music.pause"),
            step_id=1,
            step_status=2,
            outputs={"ok": True},
        )
        self.assertIsNone(sid)
        self.assertEqual(brain_db.list_playback_sessions(), [])

    def test_failed_step_noop(self) -> None:
        sid = playback_session.record_from_step(
            intent=self._intent("display.pdf.page"),
            step_id=1,
            step_status=3,
            outputs={},
        )
        self.assertIsNone(sid)
        self.assertEqual(brain_db.list_playback_sessions(), [])


@unittest.skipIf(flask is None, "flask not installed")
class PlaybackSessionApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "brain.sqlite3"
        brain_db.reset(path=self.path)
        brain_db.init_db()
        brain_db.put_registration(
            {
                "participant_id": "iphone-origin",
                "device_type": "iphone",
                "roles": ["intent_source", "endpoint"],
                "intent_sources": [{"source_id": "microphone", "channel": "voice"}],
                "endpoints": [
                    {"endpoint_id": "iphone.display", "supported_presentation": ["text"]}
                ],
            }
        )
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
        now = time.time()
        for pid in ("iphone-origin", "mac-edge"):
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
        hb.rebuild_capability_maps()

    def tearDown(self) -> None:
        brain_db.reset()
        self._tmp.cleanup()

    def test_step_report_writes_session_and_gets_back(self) -> None:
        client = hb.app.test_client()
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
        intent_id = resp.get_json()["intent_id"]

        # edge 执行完回报 step 成功（带页码 outputs）
        report = client.post(
            f"/api/v1/intent/{intent_id}/step/1/status",
            json={
                "step_status": "2",
                "status": "2",
                "edge_node_id": "mac-edge",
                "ts": int(time.time() * 1000),
                "outputs": {
                    "page": 2,
                    "page_count": 3,
                    "asset_id": "asset_9",
                    "status_text": "已翻到第 2 页 / 共 3 页",
                },
            },
        )
        self.assertEqual(report.status_code, 200)

        got = client.get("/api/v1/playback_session?scene=tv_pdf")
        self.assertEqual(got.status_code, 200)
        body = got.get_json()
        self.assertTrue(body["ok"])
        session = body["session"]
        self.assertEqual(session["scene"], "tv_pdf")
        self.assertEqual(session["edge_id"], "mac-edge")
        self.assertEqual(session["position"], 2)
        self.assertEqual(session["total"], 3)
        self.assertEqual(session["state"], "playing")
        self.assertEqual(session["payload"]["status_text"], "已翻到第 2 页 / 共 3 页")

    def test_get_requires_scene_and_handles_empty(self) -> None:
        client = hb.app.test_client()
        missing = client.get("/api/v1/playback_session")
        self.assertEqual(missing.status_code, 400)
        empty = client.get("/api/v1/playback_session?scene=tv_pdf")
        self.assertEqual(empty.status_code, 200)
        self.assertIsNone(empty.get_json()["session"])


if __name__ == "__main__":
    unittest.main()
