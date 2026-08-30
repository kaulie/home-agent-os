"""Heartbeat cloud_usage_delta wire (dual-Brain safe snapshot)."""

from __future__ import annotations

import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

from mac_edge.brain_client import BrainClient, HeartbeatResult
from mac_edge.cloud_usage import drain, increment, snapshot
from mac_edge.config import Config, Identity
from mac_edge.multi_brain import MultiBrainClient


def _cfg(**kwargs) -> Config:
    base = dict(
        brain_base_url="http://127.0.0.1:9527",
        interval_sec=3.0,
        identity=Identity(),
        data_dir=Path(tempfile.mkdtemp()),
        cast_display_url="http://127.0.0.1:9095/endpoint/display",
    )
    base.update(kwargs)
    return Config(**base)


class HeartbeatCloudUsageTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._usage_path = Path(self._tmpdir.name) / "cloud_usage.json"
        self._prev = os.environ.get("MAC_CLOUD_USAGE_PATH")
        os.environ["MAC_CLOUD_USAGE_PATH"] = str(self._usage_path)
        drain()

    def tearDown(self) -> None:
        drain()
        if self._prev is None:
            os.environ.pop("MAC_CLOUD_USAGE_PATH", None)
        else:
            os.environ["MAC_CLOUD_USAGE_PATH"] = self._prev
        self._tmpdir.cleanup()

    def test_brain_client_includes_cloud_usage_delta(self) -> None:
        cfg = _cfg()
        delta = [{"service_id": "ark.query", "ok": 2, "fail": 1}]
        captured: dict = {}

        def fake_post(url: str, *, json: dict) -> MagicMock:
            captured["body"] = json
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"ok": True, "online_status": "online"}
            return resp

        with patch.object(BrainClient, "_post", side_effect=fake_post):
            with patch(
                "mac_edge.brain_client._availability_snapshot",
                return_value=[],
            ):
                client = BrainClient(cfg)
                client.heartbeat("edge-node-test", cloud_usage_delta=delta)

        self.assertEqual(captured["body"]["cloud_usage_delta"], delta)

    def test_brain_client_omits_empty_cloud_usage_delta(self) -> None:
        cfg = _cfg()
        captured: dict = {}

        def fake_post(url: str, *, json: dict) -> MagicMock:
            captured["body"] = json
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"ok": True, "online_status": "online"}
            return resp

        with patch.object(BrainClient, "_post", side_effect=fake_post):
            with patch(
                "mac_edge.brain_client._availability_snapshot",
                return_value=[],
            ):
                client = BrainClient(cfg)
                client.heartbeat("edge-node-test", cloud_usage_delta=[])

        self.assertNotIn("cloud_usage_delta", captured["body"])

    def test_multi_brain_sends_same_delta_and_drains_once(self) -> None:
        drain()
        increment("ark.query", True)
        increment("bing.images", False)
        expected = snapshot()

        cfg = replace(
            _cfg(),
            brain_base_urls=(
                "http://127.0.0.1:9527",
                "http://115.190.153.53:9527",
            ),
        )
        lan = MagicMock()
        cloud = MagicMock()
        lan.heartbeat.return_value = HeartbeatResult(
            edge_id="edge-node-test",
            online_status="online",
            raw={"ok": True},
        )
        cloud.heartbeat.return_value = HeartbeatResult(
            edge_id="edge-node-test",
            online_status="online",
            raw={"ok": True},
        )

        with patch.object(MultiBrainClient, "_open", lambda self: None):
            client = MultiBrainClient(list(cfg.brain_base_urls), config=cfg)
            client._base_urls = list(cfg.brain_base_urls)
            client._clients = [lan, cloud]
            client._by_url = {
                cfg.brain_base_urls[0]: lan,
                cfg.brain_base_urls[1]: cloud,
            }
            client.heartbeat("edge-node-test")

        lan_delta = lan.heartbeat.call_args.kwargs.get("cloud_usage_delta")
        cloud_delta = cloud.heartbeat.call_args.kwargs.get("cloud_usage_delta")
        self.assertEqual(lan_delta, expected)
        self.assertEqual(cloud_delta, expected)
        self.assertIs(lan_delta, cloud_delta)
        self.assertEqual(snapshot(), [])
        self.assertEqual(drain(), [])


if __name__ == "__main__":
    unittest.main()
