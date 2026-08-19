"""Empty execution_plan must fail, not sit at intent_parsed."""

from __future__ import annotations

import sys
import unittest
from unittest.mock import MagicMock, patch

sys.modules.setdefault("httpx", MagicMock())

from mac_edge.brain_client import intent_relevant_to_edge
from mac_edge.executor import EMPTY_PLAN_MSG, fail_empty_plan_intent
from mac_edge.scheduler import IntentScheduler


class EmptyPlanSchedulerTest(unittest.TestCase):
    def test_empty_plan_posts_failed(self) -> None:
        brain = MagicMock()
        sched = IntentScheduler()
        intent = {
            "id": 7,
            "status": "intent_parsed",
            "scheduler_node": "edge-node-x",
            "execution_plan": [],
        }
        with patch("mac_edge.scheduler._ledger_active", return_value=None), patch(
            "mac_edge.scheduler._try_post_intent_status", return_value=True
        ) as post:
            sched.handle(intent, edge_id="edge-node-x", brain=brain)
        post.assert_called_once()
        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs["status"], "failed")
        self.assertIn("为空", kwargs["message"])


class EmptyPlanPeekTest(unittest.TestCase):
    def test_fail_without_scheduler_node(self) -> None:
        brain = MagicMock()
        intent = {
            "id": 1,
            "status": "intent_parsed",
            "scheduler_node": "",
            "execution_plan": [],
            "text": "14000千米是多远",
        }
        with patch(
            "mac_edge.executor._try_post_intent_status", return_value=True
        ) as post:
            handled = fail_empty_plan_intent(
                intent, edge_id="edge-node-x", brain=brain
            )
        self.assertTrue(handled)
        post.assert_called_once()
        self.assertEqual(post.call_args.kwargs["status"], "failed")
        self.assertEqual(post.call_args.kwargs["message"], EMPTY_PLAN_MSG)


class EmptyPlanRelevanceTest(unittest.TestCase):
    def test_empty_plan_visible_to_any_edge(self) -> None:
        intent = {
            "id": 1,
            "status": "intent_parsed",
            "execution_plan": [],
        }
        self.assertTrue(intent_relevant_to_edge(intent, "edge-a"))
        self.assertTrue(intent_relevant_to_edge(intent, "edge-b"))

    def test_nonempty_plan_still_requires_assignee(self) -> None:
        intent = {
            "id": 2,
            "status": "intent_parsed",
            "execution_plan": [
                {
                    "step": 1,
                    "capability": "query.content",
                    "assigned_edge_id": "edge-a",
                }
            ],
        }
        self.assertTrue(intent_relevant_to_edge(intent, "edge-a"))
        self.assertFalse(intent_relevant_to_edge(intent, "edge-b"))


if __name__ == "__main__":
    unittest.main()
