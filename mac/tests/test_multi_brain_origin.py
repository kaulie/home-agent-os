"""Dual-Brain: intent origin must survive separate MultiBrainClient instances."""

from __future__ import annotations

import unittest
from dataclasses import replace
from unittest.mock import MagicMock, patch

from mac_edge.config import Config
from mac_edge.multi_brain import (
    MultiBrainClient,
    _SHARED_INTENT_ORIGIN,
    _SHARED_ORIGIN_LOCK,
    intent_origin_brain_url,
    remember_intent_origin,
)


class MultiBrainOriginTests(unittest.TestCase):
    def setUp(self) -> None:
        with _SHARED_ORIGIN_LOCK:
            _SHARED_INTENT_ORIGIN.clear()

    def tearDown(self) -> None:
        with _SHARED_ORIGIN_LOCK:
            _SHARED_INTENT_ORIGIN.clear()

    def test_executor_client_routes_cloud_after_control_pull(self) -> None:
        cfg = replace(
            Config(brain_base_url="http://127.0.0.1:9527"),
            brain_base_urls=(
                "http://127.0.0.1:9527",
                "http://115.190.153.53:9527",
            ),
        )
        lan = MagicMock()
        cloud = MagicMock()
        cloud.pull_intents.return_value = [
            {"id": "1504", "intent_status": "intent_dispatched"},
        ]

        with patch.object(MultiBrainClient, "_open", lambda self: None):
            control = MultiBrainClient(list(cfg.brain_base_urls), config=cfg)
            control._base_urls = list(cfg.brain_base_urls)
            control._clients = [lan, cloud]
            control._by_url = {
                cfg.brain_base_urls[0]: lan,
                cfg.brain_base_urls[1]: cloud,
            }
            control.pull_intents("edge-node-test")

            executor = MultiBrainClient(list(cfg.brain_base_urls), config=cfg)
            executor._base_urls = list(cfg.brain_base_urls)
            executor._clients = [lan, cloud]
            executor._by_url = control._by_url

            url = executor._route_url_for_intent("1504")
            self.assertEqual(url, "http://115.190.153.53:9527")

    def test_remember_intent_origin_shared_across_instances(self) -> None:
        remember_intent_origin("99", "http://115.190.153.53:9527")
        cfg = replace(
            Config(brain_base_url="http://127.0.0.1:9527"),
            brain_base_urls=("http://127.0.0.1:9527", "http://115.190.153.53:9527"),
        )
        with patch.object(MultiBrainClient, "_open", lambda self: None):
            client = MultiBrainClient(list(cfg.brain_base_urls), config=cfg)
            client._base_urls = list(cfg.brain_base_urls)
            self.assertEqual(
                client._route_url_for_intent("99"),
                "http://115.190.153.53:9527",
            )

    def test_routed_post_probes_cloud_after_lan_404(self) -> None:
        from mac_edge.brain_client import BrainError

        cfg = replace(
            Config(brain_base_url="http://127.0.0.1:9527"),
            brain_base_urls=(
                "http://127.0.0.1:9527",
                "http://115.190.153.53:9527",
            ),
        )
        lan = MagicMock()
        cloud = MagicMock()
        lan.post_step_status.side_effect = BrainError(
            "post_step_status: intent not exist",
            status_code=404,
        )
        cloud.post_step_status.return_value = {"ok": True}

        with patch.object(MultiBrainClient, "_open", lambda self: None):
            client = MultiBrainClient(list(cfg.brain_base_urls), config=cfg)
            client._base_urls = list(cfg.brain_base_urls)
            client._clients = [lan, cloud]
            client._by_url = {
                cfg.brain_base_urls[0]: lan,
                cfg.brain_base_urls[1]: cloud,
            }
            out = client.post_step_status(
                "1504",
                1,
                step_status=2,
                edge_node_id="edge-node-test",
            )
        self.assertEqual(out, {"ok": True})
        cloud.post_step_status.assert_called_once()
        self.assertEqual(
            intent_origin_brain_url("1504"),
            "http://115.190.153.53:9527",
        )


if __name__ == "__main__":
    unittest.main()
