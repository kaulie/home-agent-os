"""Interval: a failed beat must end and re-arm; stale RUNNING is reclaimable."""

from __future__ import annotations

import time
import unittest

from mac_edge.brain_time import BRAIN_CLOCK
from mac_edge.executor import (
    STEP_FAILED,
    STEP_RUNNING,
    STEP_SUCCEEDED,
    STEP_WAITING,
    _EXECUTING_STEPS,
    _advance_skipped_beats,
    _step_open_for_run,
    find_next_eligible_local_step,
    plan_has_remaining_work,
    skip_passed_interval_triggers,
    step_status,
)
from mac_edge.execution_timing import parse_execution_timing
from mac_edge.timing_beats import clear_intent, get_beat, set_beat


def _now_ms() -> int:
    return int(time.time() * 1000)


class IntervalSchedulingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = _now_ms()
        BRAIN_CLOCK.apply_heartbeat(self.now)
        self.eid = "edge-cam"
        self.iid = "intent-interval"
        clear_intent(self.iid)
        _EXECUTING_STEPS.clear()

    def tearDown(self) -> None:
        _EXECUTING_STEPS.clear()
        clear_intent(self.iid)

    def _interval_plan(self, *, status: int) -> list[dict]:
        return [
            {
                "step": 1,
                "status": status,
                "assigned_edge_id": self.eid,
                "capability": "camera.capture",
                "execution_timing": {
                    "mode": "interval",
                    "interval_sec": 60,
                    "first_exec_time": self.now - 5_000,
                    "count": 30,
                },
            }
        ]

    def test_stale_running_is_reclaimable(self) -> None:
        plan = self._interval_plan(status=STEP_RUNNING)
        self.assertTrue(_step_open_for_run(plan[0], self.iid, 1))
        nxt = find_next_eligible_local_step(plan, self.eid, intent_id=self.iid)
        self.assertIsNotNone(nxt)
        assert nxt is not None
        self.assertEqual(int(nxt["step"]), 1)

    def test_live_running_is_not_reclaimed(self) -> None:
        plan = self._interval_plan(status=STEP_RUNNING)
        _EXECUTING_STEPS.add((self.iid, 1))
        self.assertFalse(_step_open_for_run(plan[0], self.iid, 1))
        self.assertIsNone(find_next_eligible_local_step(plan, self.eid, intent_id=self.iid))

    def test_waiting_interval_still_eligible_when_due(self) -> None:
        plan = self._interval_plan(status=STEP_WAITING)
        nxt = find_next_eligible_local_step(plan, self.eid, intent_id=self.iid)
        self.assertIsNotNone(nxt)

    def test_succeeded_one_shot_not_reclaimed(self) -> None:
        plan = [
            {
                "step": 1,
                "status": STEP_SUCCEEDED,
                "assigned_edge_id": self.eid,
                "capability": "camera.capture",
                "execution_timing": {"mode": "immediate"},
            }
        ]
        self.assertFalse(_step_open_for_run(plan[0], self.iid, 1))
        self.assertIsNone(find_next_eligible_local_step(plan, self.eid, intent_id=self.iid))

    def test_future_interval_beat_not_due(self) -> None:
        set_beat(self.iid, 1, 1)
        plan = [
            {
                "step": 1,
                "status": STEP_WAITING,
                "assigned_edge_id": self.eid,
                "capability": "camera.capture",
                "execution_timing": {
                    "mode": "interval",
                    "interval_sec": 60,
                    "first_exec_time": self.now,
                    "count": 30,
                },
            }
        ]
        # beat 1 is still in the future relative to first_exec_time
        self.assertIsNone(find_next_eligible_local_step(plan, self.eid, intent_id=self.iid))

    def test_slow_beat_does_not_catch_up_passed_slot(self) -> None:
        """Interval from the plan (7s here, not a hardcoded minute): skip passed slots."""
        interval_sec = 7
        first = self.now - 10_000
        set_beat(self.iid, 1, 1)
        step = {
            "step": 1,
            "status": STEP_WAITING,
            "assigned_edge_id": self.eid,
            "capability": "camera.capture",
            "execution_timing": {
                "mode": "interval",
                "interval_sec": interval_sec,
                "first_exec_time": first,
                "count": 30,
            },
        }
        timing = parse_execution_timing(step)
        skipped = skip_passed_interval_triggers(self.iid, 1, timing, self.now)
        self.assertGreaterEqual(skipped, 1)
        nxt_beat = get_beat(self.iid, 1)
        planned_ms = first + nxt_beat * interval_sec * 1000
        self.assertGreater(planned_ms, self.now)
        self.assertIsNone(
            find_next_eligible_local_step([step], self.eid, intent_id=self.iid)
        )

    def test_on_time_next_slot_is_not_skipped(self) -> None:
        interval_sec = 7
        first = self.now - 1_000
        set_beat(self.iid, 1, 1)
        step = {
            "step": 1,
            "status": STEP_WAITING,
            "assigned_edge_id": self.eid,
            "capability": "camera.capture",
            "execution_timing": {
                "mode": "interval",
                "interval_sec": interval_sec,
                "first_exec_time": first,
                "count": 8,
            },
        }
        timing = parse_execution_timing(step)
        skipped = skip_passed_interval_triggers(self.iid, 1, timing, self.now)
        self.assertEqual(skipped, 0)
        self.assertEqual(get_beat(self.iid, 1), 1)

    def test_interval_beat_succeeded_still_has_remaining_work(self) -> None:
        set_beat(self.iid, 1, 1)
        plan = [
            {
                "step": 1,
                "status": STEP_SUCCEEDED,
                "assigned_edge_id": self.eid,
                "capability": "camera.capture",
                "execution_timing": {
                    "mode": "interval",
                    "interval_sec": 60,
                    "first_exec_time": self.now,
                    "count": 30,
                },
            }
        ]
        self.assertTrue(plan_has_remaining_work(plan, intent_id=self.iid))
        _advance_skipped_beats(plan, self.iid, self.eid)
        self.assertEqual(step_status(plan[0]), STEP_WAITING)

    def test_failed_interval_still_has_remaining_work(self) -> None:
        plan = self._interval_plan(status=STEP_FAILED)
        self.assertTrue(plan_has_remaining_work(plan))
        self.assertTrue(_step_open_for_run(plan[0], self.iid, 1))

    def test_one_shot_failed_has_no_remaining_work(self) -> None:
        plan = [
            {
                "step": 1,
                "status": STEP_FAILED,
                "assigned_edge_id": self.eid,
                "capability": "camera.capture",
                "execution_timing": {"mode": "immediate"},
            }
        ]
        self.assertFalse(plan_has_remaining_work(plan))
        self.assertFalse(_step_open_for_run(plan[0], self.iid, 1))

    def test_failed_interval_rearms_waiting_for_next_slot(self) -> None:
        set_beat(self.iid, 1, 1)
        plan = [
            {
                "step": 1,
                "status": STEP_FAILED,
                "assigned_edge_id": self.eid,
                "capability": "camera.capture",
                "execution_timing": {
                    "mode": "interval",
                    "interval_sec": 60,
                    "first_exec_time": self.now,
                    "count": 30,
                },
            }
        ]
        _advance_skipped_beats(plan, self.iid, self.eid)
        self.assertEqual(step_status(plan[0]), STEP_WAITING)
        self.assertIsNone(
            find_next_eligible_local_step(plan, self.eid, intent_id=self.iid)
        )

    def test_stale_running_past_count_is_closed(self) -> None:
        first = self.now - 2 * 60 * 60 * 1000
        plan = [
            {
                "step": 1,
                "status": STEP_RUNNING,
                "assigned_edge_id": self.eid,
                "capability": "camera.capture",
                "execution_timing": {
                    "mode": "interval",
                    "interval_sec": 60,
                    "first_exec_time": first,
                    "count": 30,
                },
            }
        ]
        _advance_skipped_beats(plan, self.iid, self.eid)
        self.assertEqual(step_status(plan[0]), STEP_SUCCEEDED)
        self.assertGreaterEqual(get_beat(self.iid, 1), 30)
        self.assertIsNone(
            find_next_eligible_local_step(plan, self.eid, intent_id=self.iid)
        )
        self.assertFalse(plan_has_remaining_work(plan, intent_id=self.iid))

    def test_live_running_is_not_skipped_even_if_late(self) -> None:
        first = self.now - 2 * 60 * 60 * 1000
        plan = [
            {
                "step": 1,
                "status": STEP_RUNNING,
                "assigned_edge_id": self.eid,
                "capability": "camera.capture",
                "execution_timing": {
                    "mode": "interval",
                    "interval_sec": 60,
                    "first_exec_time": first,
                    "count": 30,
                },
            }
        ]
        _EXECUTING_STEPS.add((self.iid, 1))
        _advance_skipped_beats(plan, self.iid, self.eid)
        self.assertEqual(step_status(plan[0]), STEP_RUNNING)
        self.assertEqual(get_beat(self.iid, 1), 0)


class FailedIntentPeekTests(unittest.TestCase):
    def test_interval_failed_still_has_work(self) -> None:
        from mac_edge.brain_client import _recurring_series_still_open

        now = int(time.time() * 1000)
        item = {
            "status": "failed",
            "execution_plan": [
                {
                    "step": 1,
                    "status": 3,
                    "execution_timing": {
                        "mode": "interval",
                        "interval_sec": 60,
                        "first_exec_time": now,
                        "count": 30,
                    },
                }
            ],
        }
        self.assertTrue(_recurring_series_still_open(item, now))

    def test_one_shot_failed_has_no_recurring_work(self) -> None:
        from mac_edge.brain_client import _recurring_series_still_open

        item = {
            "status": "failed",
            "execution_plan": [
                {
                    "step": 1,
                    "status": 3,
                    "execution_timing": {"mode": "immediate"},
                }
            ],
        }
        self.assertFalse(_recurring_series_still_open(item))

    def test_interval_past_last_beat_is_closed(self) -> None:
        from mac_edge.brain_client import _recurring_series_still_open

        now = int(time.time() * 1000)
        item = {
            "status": "succeeded",
            "execution_plan": [
                {
                    "step": 1,
                    "status": 2,
                    "execution_timing": {
                        "mode": "interval",
                        "interval_sec": 60,
                        "first_exec_time": now - 2 * 60 * 60 * 1000,
                        "count": 30,
                    },
                }
            ],
        }
        self.assertFalse(_recurring_series_still_open(item, now))


if __name__ == "__main__":
    unittest.main()
