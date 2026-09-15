"""Local ledger: Brain peek adds work; local status/beat/synced drive execution."""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from mac_edge.brain_client import BrainError
from mac_edge.local_ledger import LocalLedger, bind, active
from mac_edge.timing_beats import clear_intent, get_beat, set_beat, set_beat_listener


EID = "edge-cam"
IID = "intent-local-1"


def _waiting_intent(
    *,
    iid: str = IID,
    status: int = 0,
    intent_status: str = "running",
    extra_outputs: dict | None = None,
) -> dict:
    rec: dict = {
        "id": iid,
        "status": intent_status,
        "intent_status": intent_status,
        "scheduler_node": EID,
        "execution_plan": [
            {
                "step": 1,
                "status": status,
                "assigned_edge_id": EID,
                "capability": "camera.capture",
            }
        ],
    }
    if extra_outputs:
        rec["step_outputs"] = extra_outputs
    return rec


class _FakeBrain:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.step_posts: list[tuple] = []
        self.intent_posts: list[tuple] = []

    def post_step_status(
        self,
        intent_id,
        step_num,
        *,
        step_status,
        edge_node_id,
        outputs=None,
        ts_ms=None,
        msg=None,
    ):
        if self.fail:
            raise BrainError("brain down", transient=True)
        self.step_posts.append(
            (str(intent_id), int(step_num), int(step_status), outputs, ts_ms, msg)
        )

    def post_intent_status(self, intent_id, *, status, edge_node_id, message=""):
        if self.fail:
            raise BrainError("brain down", transient=True)
        self.intent_posts.append((str(intent_id), str(status), message))


class _RejectRunningBrain(_FakeBrain):
    """Brain that has already terminated the intent: rejects RUNNING replays."""

    def post_step_status(
        self,
        intent_id,
        step_num,
        *,
        step_status,
        edge_node_id,
        outputs=None,
        ts_ms=None,
        msg=None,
    ):
        if int(step_status) == 1:
            raise BrainError(
                "step_status: intent is terminal; step cannot return to running"
            )
        return super().post_step_status(
            intent_id,
            step_num,
            step_status=step_status,
            edge_node_id=edge_node_id,
            outputs=outputs,
            ts_ms=ts_ms,
            msg=msg,
        )


class LocalLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "local_ledger.json"
        self.ledger = LocalLedger(self.path)
        clear_intent(IID)
        set_beat_listener(self.ledger.note_beat)
        bind(self.ledger)

    def tearDown(self) -> None:
        bind(None)
        set_beat_listener(None)
        clear_intent(IID)
        self._tmp.cleanup()

    def test_ingest_new_intent(self) -> None:
        added = self.ledger.ingest_peek([_waiting_intent()], EID)
        self.assertEqual(added, 1)
        rec = self.ledger.get(IID)
        self.assertIsNotNone(rec)
        assert rec is not None
        self.assertTrue(rec["synced"])
        self.assertTrue(rec["execution_plan"][0]["synced"])
        self.assertEqual(rec["execution_plan"][0]["status"], 0)

    def test_empty_peek_keeps_local(self) -> None:
        self.ledger.ingest_peek([_waiting_intent()], EID)
        self.ledger.set_step_status(IID, 1, 1)
        added = self.ledger.ingest_peek([], EID)
        self.assertEqual(added, 0)
        rec = self.ledger.get(IID)
        assert rec is not None
        self.assertEqual(rec["execution_plan"][0]["status"], 1)
        open_rows = self.ledger.snapshot_open(EID)
        self.assertEqual(len(open_rows), 1)
        self.assertEqual(open_rows[0]["id"], IID)

    def test_status_change_marks_unsynced_flush_marks_synced(self) -> None:
        self.ledger.ingest_peek([_waiting_intent()], EID)
        rec = self.ledger.get(IID)
        assert rec is not None
        self.assertTrue(rec["synced"])

        self.ledger.set_step_status(IID, 1, 2, outputs={"photo_url": "http://x/a.jpg"})
        rec = self.ledger.get(IID)
        assert rec is not None
        self.assertFalse(rec["execution_plan"][0]["synced"])
        self.assertEqual(rec["execution_plan"][0]["status"], 2)

        brain = _FakeBrain()
        posted = self.ledger.flush_to_brain(brain, EID)  # type: ignore[arg-type]
        self.assertGreaterEqual(posted, 1)
        self.assertEqual(brain.step_posts[0][2], 2)
        rec = self.ledger.get(IID)
        assert rec is not None
        self.assertTrue(rec["execution_plan"][0]["synced"])

    def test_brain_status_does_not_overwrite_local(self) -> None:
        self.ledger.ingest_peek([_waiting_intent(status=0)], EID)
        self.ledger.set_step_status(IID, 1, 0)
        # Brain later claims succeeded / waiting-mismatch — local wins.
        self.ledger.ingest_peek([_waiting_intent(status=2, intent_status="succeeded")], EID)
        rec = self.ledger.get(IID)
        assert rec is not None
        self.assertEqual(rec["execution_plan"][0]["status"], 0)
        self.assertNotEqual(rec["status"], "succeeded")

    def test_overlay_uses_local_plan(self) -> None:
        self.ledger.ingest_peek([_waiting_intent()], EID)
        self.ledger.set_step_status(IID, 1, 3)
        peeked = _waiting_intent(status=1, intent_status="running")
        merged = self.ledger.overlay_intent(peeked)
        self.assertEqual(merged["execution_plan"][0]["status"], 3)

    def test_flush_skipped_while_brain_down_then_replays_current(self) -> None:
        self.ledger.ingest_peek([_waiting_intent()], EID)
        self.ledger.set_step_status(IID, 1, 2)
        self.ledger.set_intent_status(IID, "running")
        down = _FakeBrain(fail=True)
        self.assertEqual(self.ledger.flush_to_brain(down, EID), 0)  # type: ignore[arg-type]
        rec = self.ledger.get(IID)
        assert rec is not None
        self.assertFalse(rec["execution_plan"][0]["synced"])

        up = _FakeBrain()
        posted = self.ledger.flush_to_brain(up, EID)  # type: ignore[arg-type]
        self.assertGreaterEqual(posted, 1)
        self.assertEqual(up.step_posts[-1][2], 2)
        rec = self.ledger.get(IID)
        assert rec is not None
        self.assertTrue(rec["execution_plan"][0]["synced"])

    def test_persist_reload_keeps_unsynced_and_beat(self) -> None:
        self.ledger.ingest_peek([_waiting_intent()], EID)
        set_beat(IID, 1, 4)
        self.ledger.note_beat(IID, 1, 4)
        self.ledger.set_step_status(IID, 1, 2)
        bind(None)
        set_beat_listener(None)
        clear_intent(IID)

        reloaded = LocalLedger(self.path)
        rec = reloaded.get(IID)
        assert rec is not None
        self.assertEqual(rec["execution_plan"][0]["status"], 2)
        self.assertFalse(rec["execution_plan"][0]["synced"])
        self.assertEqual(rec["execution_plan"][0]["beat"], 4)
        self.assertEqual(get_beat(IID, 1), 4)

    def test_running_is_queued_for_flush(self) -> None:
        self.ledger.ingest_peek([_waiting_intent()], EID)
        self.ledger.set_step_status(IID, 1, 1, ts_ms=50)
        rec = self.ledger.get(IID)
        assert rec is not None
        q = rec["execution_plan"][0].get("sync_queue") or []
        self.assertEqual([int(e["status"]) for e in q], [1])
        brain = _FakeBrain()
        self.assertEqual(self.ledger.flush_to_brain(brain, EID), 1)  # type: ignore[arg-type]
        self.assertEqual(brain.step_posts[0][2], 1)
        self.assertEqual(brain.step_posts[0][4], 50)

    def test_obsolete_running_dropped_then_terminal_event_flushed(self) -> None:
        # A stale RUNNING replay that Brain rejects (intent already terminal)
        # must be dropped so the later FAILED/SUCCESS events can flush.
        self.ledger.ingest_peek([_waiting_intent()], EID)
        self.ledger.set_step_status(IID, 1, 1, ts_ms=10)
        self.ledger.set_step_status(IID, 1, 3, ts_ms=20, msg="too late")
        brain = _RejectRunningBrain()
        posted = self.ledger.flush_to_brain(brain, EID)  # type: ignore[arg-type]
        self.assertEqual(posted, 1)
        self.assertEqual([p[2] for p in brain.step_posts], [3])
        self.assertEqual(brain.step_posts[0][5], "too late")
        rec = self.ledger.get(IID)
        assert rec is not None
        self.assertTrue(rec["execution_plan"][0]["synced"])

    def test_success_outputs_flush_past_stale_running(self) -> None:
        # file.convert-style: step2 ran RUNNING then SUCCEEDED with outputs, but
        # Brain already marked the intent terminal; the RUNNING replay is
        # dropped and the SUCCESS event still delivers its outputs.
        self.ledger.ingest_peek([_waiting_intent()], EID)
        self.ledger.set_step_status(IID, 1, 1, ts_ms=10)
        outputs = {
            "asset_ref": {"asset_id": "asset_pdf", "type": "document"},
            "page_count": 1,
            "status_text": "已转成 PDF",
        }
        self.ledger.set_step_status(IID, 1, 2, outputs=outputs, ts_ms=20)
        brain = _RejectRunningBrain()
        posted = self.ledger.flush_to_brain(brain, EID)  # type: ignore[arg-type]
        self.assertEqual(posted, 1)
        self.assertEqual(brain.step_posts[0][2], 2)
        self.assertEqual(brain.step_posts[0][3], outputs)
        rec = self.ledger.get(IID)
        assert rec is not None
        self.assertTrue(rec["execution_plan"][0]["synced"])

    def test_flush_replays_full_offline_timeline(self) -> None:
        self.ledger.ingest_peek([_waiting_intent()], EID)
        self.ledger.set_step_status(IID, 1, 1, ts_ms=10)
        self.ledger.set_step_status(IID, 1, 2, outputs={"photo_url": "http://x/a.jpg"}, ts_ms=20)
        self.ledger.set_step_status(IID, 1, 0, ts_ms=30)
        self.ledger.set_step_status(IID, 1, 1, ts_ms=40)
        self.ledger.set_step_status(IID, 1, 3, ts_ms=50)
        self.ledger.set_step_status(IID, 1, 0, ts_ms=60)
        down = _FakeBrain(fail=True)
        self.assertEqual(self.ledger.flush_to_brain(down, EID), 0)  # type: ignore[arg-type]
        up = _FakeBrain()
        posted = self.ledger.flush_to_brain(up, EID)  # type: ignore[arg-type]
        self.assertEqual(posted, 6)
        self.assertEqual([p[2] for p in up.step_posts], [1, 2, 0, 1, 3, 0])
        self.assertEqual([p[4] for p in up.step_posts], [10, 20, 30, 40, 50, 60])

    def test_flush_replays_succeeded_then_waiting(self) -> None:
        self.ledger.ingest_peek([_waiting_intent()], EID)
        self.ledger.set_step_status(IID, 1, 2, outputs={"photo_url": "http://x/a.jpg"}, ts_ms=100)
        self.ledger.set_step_status(IID, 1, 0, ts_ms=200)
        down = _FakeBrain(fail=True)
        self.assertEqual(self.ledger.flush_to_brain(down, EID), 0)  # type: ignore[arg-type]
        up = _FakeBrain()
        posted = self.ledger.flush_to_brain(up, EID)  # type: ignore[arg-type]
        self.assertGreaterEqual(posted, 2)
        statuses = [p[2] for p in up.step_posts]
        self.assertEqual(statuses[:2], [2, 0])
        self.assertEqual(up.step_posts[0][4], 100)
        self.assertEqual(up.step_posts[1][4], 200)

    def test_reclaim_running_queues_waiting_after_running(self) -> None:
        self.ledger.ingest_peek([_waiting_intent()], EID)
        self.ledger.set_step_status(IID, 1, 1, ts_ms=290)
        self.ledger.set_step_status(IID, 1, 0, ts_ms=300)
        rec = self.ledger.get(IID)
        assert rec is not None
        q = rec["execution_plan"][0].get("sync_queue") or []
        self.assertEqual([int(e["status"]) for e in q], [1, 0])
        up = _FakeBrain()
        self.ledger.flush_to_brain(up, EID)  # type: ignore[arg-type]
        self.assertEqual([p[2] for p in up.step_posts[:2]], [1, 0])
        self.assertEqual([p[4] for p in up.step_posts[:2]], [290, 300])

    def test_flush_failed_includes_msg(self) -> None:
        self.ledger.ingest_peek([_waiting_intent()], EID)
        self.ledger.set_step_status(
            IID, 1, 3, ts_ms=70, msg="camera.capture: GoPro shutter timeout"
        )
        rec = self.ledger.get(IID)
        assert rec is not None
        self.assertEqual(rec["execution_plan"][0]["msg"], "camera.capture: GoPro shutter timeout")
        brain = _FakeBrain()
        posted = self.ledger.flush_to_brain(brain, EID)  # type: ignore[arg-type]
        self.assertEqual(posted, 1)
        self.assertEqual(brain.step_posts[0][2], 3)
        self.assertEqual(brain.step_posts[0][5], "camera.capture: GoPro shutter timeout")

    def test_flush_failed_includes_outputs(self) -> None:
        # netease.music-style: the step FAILS but still reports a product (ncm-cli
        # login info) that the Brain needs to build the user-facing message.
        # id=763 regression: the ledger used to drop outputs on non-SUCCEEDED steps.
        self.ledger.ingest_peek([_waiting_intent()], EID)
        outputs = {
            "netease_login": {
                "logged_in": False,
                "reason": "未登录，请执行 ncm-cli login 完成登录",
                "login_url": "https://163cn.tv/bgl5Nc5N",
            }
        }
        self.ledger.set_step_status(
            IID, 1, 3, outputs=outputs, ts_ms=70, msg="ncm-cli 未返回 JSON：boom"
        )
        brain = _FakeBrain()
        posted = self.ledger.flush_to_brain(brain, EID)  # type: ignore[arg-type]
        self.assertEqual(posted, 1)
        self.assertEqual(brain.step_posts[0][2], 3)
        self.assertEqual(brain.step_posts[0][3], outputs)

    def test_failed_outputs_survive_brain_down_replay(self) -> None:
        self.ledger.ingest_peek([_waiting_intent()], EID)
        outputs = {"netease_login": {"logged_in": False, "login_url": "https://163cn.tv/x"}}
        self.ledger.set_step_status(IID, 1, 3, outputs=outputs, ts_ms=80)
        down = _FakeBrain(fail=True)
        self.assertEqual(self.ledger.flush_to_brain(down, EID), 0)  # type: ignore[arg-type]
        up = _FakeBrain()
        posted = self.ledger.flush_to_brain(up, EID)  # type: ignore[arg-type]
        self.assertGreaterEqual(posted, 1)
        self.assertEqual(up.step_posts[0][2], 3)
        self.assertEqual(up.step_posts[0][3], outputs)

    def test_non_terminal_outputs_are_not_carried(self) -> None:
        self.ledger.ingest_peek([_waiting_intent()], EID)
        self.ledger.set_step_status(IID, 1, 1, outputs={"junk": 1}, ts_ms=90)
        rec = self.ledger.get(IID)
        assert rec is not None
        q = rec["execution_plan"][0].get("sync_queue") or []
        self.assertEqual([int(e["status"]) for e in q], [1])
        self.assertNotIn("outputs", q[0])

    def test_recycled_id_replaces_terminal_local(self) -> None:
        old = _waiting_intent(intent_status="failed")
        old["text"] = "晋字笔画怎么写"
        old["intent_base_time"] = 100
        old["execution_plan"][0]["capability"] = "query.content"
        old["execution_plan"][0]["status"] = 3
        old["execution_plan"].append(
            {
                "step": 2,
                "status": 0,
                "assigned_edge_id": EID,
                "capability": "notify.speak",
            }
        )
        self.ledger.ingest_peek([old], EID)
        rec = self.ledger.get(IID)
        assert rec is not None
        self.assertEqual(rec["status"], "failed")
        self.assertEqual(rec["execution_plan"][1]["capability"], "notify.speak")

        fresh = _waiting_intent(intent_status="intent_parsed")
        fresh["text"] = "晋字笔画怎么写，投到电视上"
        fresh["intent_base_time"] = 200
        fresh["execution_plan"][0]["capability"] = "query.content"
        fresh["execution_plan"].append(
            {
                "step": 2,
                "status": 0,
                "assigned_edge_id": EID,
                "capability": "display.photo",
            }
        )
        added = self.ledger.ingest_peek([fresh], EID)
        self.assertEqual(added, 1)
        rec = self.ledger.get(IID)
        assert rec is not None
        self.assertEqual(rec["status"], "intent_parsed")
        self.assertEqual(rec["intent_base_time"], 200)
        caps = [s["capability"] for s in rec["execution_plan"]]
        self.assertEqual(caps, ["query.content", "display.photo"])
        self.assertEqual(rec["execution_plan"][0]["status"], 0)
        open_rows = self.ledger.snapshot_open(EID)
        self.assertEqual(len(open_rows), 1)

    def test_peek_updates_foreign_step_status_not_local(self) -> None:
        vision = "edge-vision"
        rec = {
            "id": IID,
            "status": "running",
            "intent_status": "running",
            "scheduler_node": "edge-cam",
            "execution_plan": [
                {
                    "step": 1,
                    "status": 1,
                    "assigned_edge_id": "edge-cam",
                    "capability": "camera.capture",
                },
                {
                    "step": 2,
                    "status": 0,
                    "assigned_edge_id": vision,
                    "capability": "vision.ask",
                },
            ],
        }
        self.ledger.ingest_peek([rec], vision)
        later = copy.deepcopy(rec)
        later["execution_plan"][0]["status"] = 2
        later["step_outputs"] = {"1": {"photo_url": "http://img/p.jpg"}}
        added = self.ledger.ingest_peek([later], vision)
        self.assertEqual(added, 0)
        got = self.ledger.get(IID)
        assert got is not None
        self.assertEqual(got["execution_plan"][0]["status"], 2)
        self.assertEqual(got["execution_plan"][1]["status"], 0)
        self.assertEqual(got["step_outputs"]["1"]["photo_url"], "http://img/p.jpg")

    def test_same_intent_peek_does_not_replace_local_status(self) -> None:
        first = _waiting_intent(intent_status="running")
        first["intent_base_time"] = 50
        self.ledger.ingest_peek([first], EID)
        self.ledger.set_step_status(IID, 1, 1)
        later = _waiting_intent(status=0, intent_status="intent_parsed")
        later["intent_base_time"] = 50
        added = self.ledger.ingest_peek([later], EID)
        self.assertEqual(added, 0)
        rec = self.ledger.get(IID)
        assert rec is not None
        self.assertEqual(rec["execution_plan"][0]["status"], 1)

    def test_stale_brain_ghost_not_reaccepted_after_drop(self) -> None:
        rec = _waiting_intent(intent_status="intent_dispatched")
        rec["intent_base_time"] = 9001
        rec["text"] = "关闭台灯"
        rec["execution_plan"] = [
            {
                "step": 1,
                "status": 0,
                "assigned_edge_id": EID,
                "capability": "light.set",
            }
        ]
        self.ledger.ingest_peek([rec], EID)
        self.ledger.set_step_status(IID, 1, 2, outputs={"state": "off"}, ts_ms=10)
        self.ledger.set_intent_status(IID, "succeeded")
        brain = _FakeBrain()
        self.ledger.flush_to_brain(brain, EID)  # type: ignore[arg-type]
        self.ledger.mark_step_synced(IID, 1, status=2, seq=1)
        self.ledger.mark_intent_synced(IID, status="succeeded")
        self.assertIsNone(self.ledger.get(IID))

        stale = copy.deepcopy(rec)
        stale["status"] = "intent_dispatched"
        stale["intent_status"] = "intent_dispatched"
        stale["execution_plan"][0]["status"] = 0
        added = self.ledger.ingest_peek([stale], EID)
        self.assertEqual(added, 0)
        self.assertIsNone(self.ledger.get(IID))

    def test_bind_active(self) -> None:
        self.assertIs(active(), self.ledger)


if __name__ == "__main__":
    unittest.main()
