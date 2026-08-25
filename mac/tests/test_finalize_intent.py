"""Intent must reach succeeded/failed when the plan has no remaining work."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from mac_edge.executor import (
    STEP_FAILED,
    STEP_SUCCEEDED,
    STEP_WAITING,
    finalize_intent_from_plan,
    handle_intent,
)
from mac_edge.scheduler import IntentScheduler


class FinalizeIntentTests(unittest.TestCase):
    def test_all_steps_succeeded_posts_succeeded(self) -> None:
        brain = MagicMock()
        plan = [
            {"step": 1, "status": STEP_SUCCEEDED, "capability": "clock.now"},
            {"step": 2, "status": STEP_SUCCEEDED, "capability": "notify.speak"},
        ]
        finalize_intent_from_plan(
            brain, "42", "edge-a", plan, current_wire="running"
        )
        brain.post_intent_status.assert_called_once()
        self.assertEqual(brain.post_intent_status.call_args.kwargs["status"], "succeeded")

    def test_failed_step_posts_failed_when_no_remaining_work(self) -> None:
        brain = MagicMock()
        plan = [
            {
                "step": 1,
                "status": STEP_FAILED,
                "capability": "query.content",
                "msg": "timeout",
            },
        ]
        finalize_intent_from_plan(
            brain, "19", "edge-a", plan, current_wire="running"
        )
        brain.post_intent_status.assert_called_once()
        kwargs = brain.post_intent_status.call_args.kwargs
        self.assertEqual(kwargs["status"], "failed")
        self.assertEqual(kwargs["message"], "timeout")

    def test_cross_edge_does_not_post_succeeded_while_peer_waiting(self) -> None:
        brain = MagicMock()
        plan = [
            {
                "step": 1,
                "status": STEP_SUCCEEDED,
                "assigned_edge_id": "edge-cam",
                "capability": "camera.capture",
            },
            {
                "step": 2,
                "status": STEP_WAITING,
                "assigned_edge_id": "edge-tv",
                "capability": "display.photo",
            },
        ]
        finalize_intent_from_plan(
            brain, "10", "edge-cam", plan, current_wire="running"
        )
        brain.post_intent_status.assert_not_called()

    def test_handle_intent_posts_succeeded_after_last_local_step(self) -> None:
        brain = MagicMock()
        brain.begin_running_reports.return_value = (1, 1)
        config = MagicMock()
        intent = {
            "id": 7,
            "status": "running",
            "execution_plan": [
                {
                    "step": 1,
                    "status": STEP_WAITING,
                    "assigned_edge_id": "edge-a",
                    "capability": "clock.now",
                },
                {
                    "step": 2,
                    "status": STEP_WAITING,
                    "assigned_edge_id": "edge-a",
                    "capability": "notify.speak",
                    "input_constrict": {"text": "hi"},
                },
            ],
        }

        def fake_exec(cap, asset, *, params, config):
            if cap == "clock.now":
                return True, "ok", {"time_text": "18:00"}
            if cap == "notify.speak":
                return True, "spoken", {}
            return False, "unknown", {}

        with patch("mac_edge.local_ledger.active", return_value=None), patch(
            "mac_edge.executor._execute_capability", side_effect=fake_exec
        ):
            handle_intent(intent, edge_id="edge-a", config=config, brain=brain)

        statuses = [
            c.kwargs.get("status")
            for c in brain.post_intent_status.call_args_list
        ]
        self.assertIn("succeeded", statuses)


class ReconcilePeekedTerminalTests(unittest.TestCase):
    def test_peeked_running_all_steps_succeeded_posts_succeeded(self) -> None:
        brain = MagicMock()
        sched = IntentScheduler()
        peeked = [
            {
                "id": 49,
                "status": "running",
                "execution_plan": [
                    {
                        "step": 1,
                        "status": STEP_SUCCEEDED,
                        "assigned_edge_id": "edge-a",
                        "capability": "query.content",
                    },
                ],
            }
        ]
        with patch("mac_edge.local_ledger.active", return_value=None):
            sched.reconcile_peeked_terminal(peeked, edge_id="edge-a", brain=brain)
        brain.post_intent_status.assert_called_once()
        self.assertEqual(
            brain.post_intent_status.call_args.kwargs["status"], "succeeded"
        )


if __name__ == "__main__":
    unittest.main()
