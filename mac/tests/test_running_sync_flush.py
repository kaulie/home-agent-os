"""RUNNING must reach Brain synchronously; stale local RUNNING must reopen."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from mac_edge.config import Config, Identity
from mac_edge.executor import (
    STEP_RUNNING,
    STEP_WAITING,
    _advance_skipped_beats,
    _step_open_for_run,
    find_next_eligible_local_step,
    handle_intent,
)
from mac_edge.local_ledger import LocalLedger, bind as bind_ledger


def _cfg() -> Config:
    return Config(
        brain_base_url="http://example",
        interval_sec=3.0,
        identity=Identity(),
        data_dir=Path(tempfile.mkdtemp()),
        cast_display_url="http://127.0.0.1:9095/endpoint/display",
        capability_timeout_sec=300.0,
    )


EID = "edge-mac"
IID = "1488"


def _point_intent() -> dict:
    return {
        "id": IID,
        "intent_id": IID,
        "status": "intent_dispatched",
        "intent_status": "intent_dispatched",
        "execution_plan": [
            {
                "step": 1,
                "capability": "reading.point_to_character",
                "assigned_edge_id": EID,
                "input_constrict": {
                    "asset_ref": '{"asset_id":"asset_x","type":"image","mime_type":"image/jpeg"}',
                    "appliance": "Local Character Reading",
                },
                "output_constrict": {
                    "answer_text": {"type": "string", "data_dest": "context"},
                },
                "execution_timing": {"mode": "immediate"},
            }
        ],
    }


class RunningSyncFlushTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ledger = LocalLedger(Path(tempfile.mkdtemp()) / "ledger.json")
        bind_ledger(self.ledger)

    def tearDown(self) -> None:
        bind_ledger(None)

    def test_stale_running_reopens_for_run(self) -> None:
        step = {
            "step": 1,
            "status": STEP_RUNNING,
            "execution_timing": {"mode": "immediate"},
        }
        self.assertTrue(_step_open_for_run(step, IID, 1))
        self.assertEqual(step["status"], STEP_WAITING)

    def test_stale_running_becomes_eligible(self) -> None:
        plan = [
            {
                "step": 1,
                "status": STEP_RUNNING,
                "capability": "reading.point_to_character",
                "assigned_edge_id": EID,
                "execution_timing": {"mode": "immediate"},
            }
        ]
        nxt = find_next_eligible_local_step(plan, EID, intent_id=IID)
        self.assertIsNotNone(nxt)
        self.assertEqual(plan[0]["status"], STEP_WAITING)

    def test_handle_intent_sync_flushes_running_before_capability(self) -> None:
        self.ledger.ingest_peek([_point_intent()], EID)
        brain = MagicMock()
        brain.post_step_status.return_value = {"ok": True}
        brain.post_intent_status.return_value = {"ok": True}
        calls: list[str] = []

        def _run_cap(*_a, **_k):
            calls.append("cap")
            return True, "ok", {"answer_text": "手指指的是「字」。"}

        with patch(
            "mac_edge.executor.is_available",
            return_value=type("A", (), {"ok": True, "msg": ""})(),
        ), patch("mac_edge.executor._execute_capability_bounded", side_effect=_run_cap):
            handle_intent(_point_intent(), edge_id=EID, config=_cfg(), brain=brain)

        self.assertGreaterEqual(brain.post_step_status.call_count, 1)
        self.assertGreaterEqual(brain.post_intent_status.call_count, 1)
        self.assertTrue(calls, "capability should run after Brain RUNNING posts")
        first_step = brain.post_step_status.call_args_list[0]
        self.assertEqual(first_step.kwargs["step_status"], STEP_RUNNING)
        first_intent = brain.post_intent_status.call_args_list[0]
        self.assertEqual(first_intent.kwargs["status"], "running")

    def test_orphan_running_reset_in_advance_skipped_beats(self) -> None:
        plan = [
            {
                "step": 1,
                "status": STEP_RUNNING,
                "capability": "reading.point_to_character",
                "assigned_edge_id": EID,
                "execution_timing": {"mode": "immediate"},
            }
        ]
        _advance_skipped_beats(
            plan,
            IID,
            EID,
            brain=MagicMock(),
            intent={"step_log": []},
            config=_cfg(),
        )
        self.assertEqual(plan[0]["status"], STEP_WAITING)


if __name__ == "__main__":
    unittest.main()
