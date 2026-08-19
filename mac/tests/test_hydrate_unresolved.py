"""Unresolved $vars must fail when no producer is still running (Q49)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from mac_edge.executor import (
    STEP_RUNNING,
    STEP_SUCCEEDED,
    STEP_WAITING,
    handle_intent,
    should_wait_for_unresolved,
    unique_assigned_edge_ids,
)


class UnresolvedHydrateTests(unittest.TestCase):
    def test_wait_while_producer_running(self) -> None:
        plan = [
            {
                "step": 1,
                "status": STEP_RUNNING,
                "capability": "camera.capture",
                "output_constrict": {
                    "photo_url": {"type": "string", "data_dest": "context"}
                },
            },
            {
                "step": 2,
                "status": STEP_WAITING,
                "capability": "display.photo",
                "input_constrict": {"photo_url": "$photo_url"},
            },
        ]
        self.assertTrue(should_wait_for_unresolved(plan, 2, "photo_url"))

    def test_fail_when_no_producer(self) -> None:
        plan = [
            {
                "step": 1,
                "status": STEP_SUCCEEDED,
                "capability": "query.content",
                "output_constrict": {
                    "answer_text": {"type": "string", "data_dest": "context"}
                },
            },
            {
                "step": 2,
                "status": STEP_WAITING,
                "capability": "endpoint.feedback",
                "input_constrict": {"photo_url": "$photo_url"},
            },
        ]
        self.assertFalse(should_wait_for_unresolved(plan, 2, "photo_url"))

    def test_fail_when_producer_already_succeeded(self) -> None:
        plan = [
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
                "status": STEP_WAITING,
                "capability": "display.photo",
                "input_constrict": {"photo_url": "$photo_url"},
            },
        ]
        self.assertFalse(should_wait_for_unresolved(plan, 2, "photo_url"))

    def test_handle_intent_fails_missing_photo_url(self) -> None:
        brain = MagicMock()
        config = MagicMock()
        intent = {
            "id": 49,
            "status": "running",
            "execution_plan": [
                {
                    "step": 1,
                    "status": STEP_SUCCEEDED,
                    "assigned_edge_id": "edge-a",
                    "capability": "query.content",
                    "output_constrict": {
                        "answer_text": {"type": "string", "data_dest": "context"}
                    },
                },
                {
                    "step": 2,
                    "status": STEP_WAITING,
                    "assigned_edge_id": "edge-a",
                    "capability": "endpoint.feedback",
                    "input_constrict": {"photo_url": "$photo_url"},
                },
            ],
        }
        with patch("mac_edge.local_ledger.active", return_value=None):
            handle_intent(intent, edge_id="edge-a", config=config, brain=brain)
        brain.post_intent_status.assert_called()
        kwargs = brain.post_intent_status.call_args.kwargs
        self.assertEqual(kwargs["status"], "failed")
        self.assertIn("photo_url", kwargs["message"])
        brain.post_step_status.assert_called()
        step_kwargs = brain.post_step_status.call_args.kwargs
        self.assertEqual(step_kwargs["step_status"], 3)
        self.assertIn("photo_url", step_kwargs.get("msg") or "")


class MixedAssignedEdgeTests(unittest.TestCase):
    def test_unique_ids(self) -> None:
        plan = [
            {"step": 1, "assigned_edge_id": "cam"},
            {"step": 2, "assigned_edge_id": "tv"},
            {"step": 3, "assigned_edge_id": "cam"},
        ]
        self.assertEqual(unique_assigned_edge_ids(plan), ["cam", "tv"])

    def test_handle_intent_allows_mixed_edges(self) -> None:
        brain = MagicMock()
        brain.fetch_intent_detail.return_value = None
        brain.begin_running_reports.return_value = (1, 1)
        config = MagicMock()
        intent = {
            "id": 10,
            "status": "intent_parsed",
            "execution_plan": [
                {
                    "step": 1,
                    "status": STEP_WAITING,
                    "assigned_edge_id": "edge-cam",
                    "capability": "camera.capture",
                },
                {
                    "step": 2,
                    "status": STEP_WAITING,
                    "assigned_edge_id": "edge-tv",
                    "capability": "display.photo",
                    "input_constrict": {"photo_url": "$photo_url"},
                },
            ],
        }
        with patch("mac_edge.local_ledger.active", return_value=None), patch(
            "mac_edge.executor._execute_capability",
            return_value=(True, "ok", {"photo_url": "http://x/a.jpg"}),
        ):
            handle_intent(intent, edge_id="edge-cam", config=config, brain=brain)
        for call in brain.post_intent_status.call_args_list:
            kwargs = call.kwargs
            if kwargs.get("status") == "failed":
                self.fail(f"unexpected failed: {kwargs.get('message')}")


class PresentationContextTests(unittest.TestCase):
    def test_publish_dict_is_json_not_repr(self) -> None:
        from mac_edge.runtime_context import RuntimeContext, resolve_params

        ctx = RuntimeContext()
        presentation = {
            "type": "image",
            "channel": "iphone",
            "image_url": "http://192.168.3.65:8080/a.jpg",
        }
        published = ctx.publish(
            {"presentation": presentation},
            {"presentation": {"type": "object", "data_dest": "context"}},
        )
        self.assertEqual(published, ["presentation"])
        raw = ctx.get("presentation") or ""
        self.assertTrue(raw.startswith("{"))
        self.assertNotIn("'", raw)
        params = resolve_params({"url": "$presentation.image_url"}, ctx)
        self.assertEqual(params["url"], presentation["image_url"])


if __name__ == "__main__":
    unittest.main()
