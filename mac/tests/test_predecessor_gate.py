"""Predecessor gate: delay display cannot run until capture status=2."""

from __future__ import annotations

import time
import unittest

from mac_edge.brain_time import BRAIN_CLOCK
from mac_edge.executor import (
    STEP_SUCCEEDED,
    STEP_WAITING,
    _hydrate_context,
    find_next_eligible_local_step,
    predecessors_all_succeeded,
)
from mac_edge.runtime_context import RuntimeContext, resolve_params

CAM = "edge-cam"
DISP = "edge-display"
URL_1 = "http://192.168.3.65:8080/GOPR1041.JPG"
URL_2 = "http://192.168.3.65:8080/GOPR1042.JPG"


def _now_ms() -> int:
    return int(time.time() * 1000)


def _capture_display_pair(*, capture_status: int, exec_time: int) -> list[dict]:
    timing = {"mode": "delay", "exec_time": exec_time}
    return [
        {
            "step": 1,
            "status": capture_status,
            "assigned_edge_id": CAM,
            "capability": "camera.capture",
            "execution_timing": timing,
            "output_constrict": {
                "photo_url": {"type": "string", "data_dest": "context"}
            },
        },
        {
            "step": 2,
            "status": STEP_WAITING,
            "assigned_edge_id": DISP,
            "capability": "display.photo",
            "execution_timing": dict(timing),
            "input_constrict": {"photo_url": "$photo_url"},
            "output_constrict": {},
        },
    ]


class PredecessorGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.exec_time = _now_ms() - 5_000
        BRAIN_CLOCK.apply_heartbeat(self.exec_time + 5_000)

    def test_delay_display_blocked_while_capture_waiting(self) -> None:
        plan = _capture_display_pair(
            capture_status=STEP_WAITING, exec_time=self.exec_time
        )
        self.assertFalse(predecessors_all_succeeded(plan, 2))
        self.assertIsNone(find_next_eligible_local_step(plan, DISP))

    def test_interval_display_blocked_while_capture_waiting(self) -> None:
        first = self.exec_time
        plan = [
            {
                "step": 1,
                "status": STEP_WAITING,
                "assigned_edge_id": CAM,
                "capability": "camera.capture",
                "execution_timing": {
                    "mode": "interval",
                    "interval_sec": 60,
                    "first_exec_time": first,
                },
            },
            {
                "step": 2,
                "status": STEP_WAITING,
                "assigned_edge_id": DISP,
                "capability": "display.photo",
                "execution_timing": {
                    "mode": "interval",
                    "interval_sec": 60,
                    "first_exec_time": first,
                },
                "input_constrict": {"photo_url": "$photo_url"},
            },
        ]
        self.assertIsNone(find_next_eligible_local_step(plan, DISP))

    def test_delay_display_eligible_after_capture_succeeded(self) -> None:
        plan = _capture_display_pair(
            capture_status=STEP_SUCCEEDED, exec_time=self.exec_time
        )
        self.assertTrue(predecessors_all_succeeded(plan, 2))
        nxt = find_next_eligible_local_step(plan, DISP)
        self.assertIsNotNone(nxt)
        assert nxt is not None
        self.assertEqual(int(nxt["step"]), 2)

    def test_later_capture_overwrites_photo_url(self) -> None:
        intent = {
            "execution_plan": [
                {
                    "step": 1,
                    "status": STEP_SUCCEEDED,
                    "capability": "camera.capture",
                    "output_constrict": {
                        "photo_url": {"type": "string", "data_dest": "context"}
                    },
                },
                {
                    "step": 2,
                    "status": STEP_SUCCEEDED,
                    "capability": "display.photo",
                    "output_constrict": {},
                },
                {
                    "step": 3,
                    "status": STEP_SUCCEEDED,
                    "capability": "camera.capture",
                    "output_constrict": {
                        "photo_url": {"type": "string", "data_dest": "context"}
                    },
                },
                {
                    "step": 4,
                    "status": STEP_WAITING,
                    "capability": "display.photo",
                    "input_constrict": {"photo_url": "$photo_url"},
                    "output_constrict": {},
                },
            ],
            "step_outputs": {
                "1": {"photo_url": URL_1},
                "2": {"photo_url": URL_1},
                "3": {"photo_url": URL_2},
            },
        }
        ctx = RuntimeContext()
        _hydrate_context(ctx, intent)
        params = resolve_params({"photo_url": "$photo_url"}, ctx)
        self.assertEqual(params["photo_url"], URL_2)


if __name__ == "__main__":
    unittest.main()
