"""Tests for Participant Model registration wire."""

from __future__ import annotations

import unittest

from mac_edge.participant import registration_payload, runtime_roles


class ParticipantWireTests(unittest.TestCase):
    def test_runtime_roles(self) -> None:
        self.assertEqual(runtime_roles(), ["runtime"])

    def test_registration_payload_runtime_only(self) -> None:
        body = registration_payload(
            display_name="客厅 · Mac Edge",
            device_type="mac",
            location="living-room",
            app_version="0.3.0",
            services=[{"service_id": "local.clock", "capabilities": []}],
            client_hint="living-room-mac",
        )
        self.assertEqual(body["roles"], ["runtime"])
        self.assertTrue(body["role_runtime"])
        self.assertEqual(body["location"], "living-room")
        self.assertEqual(body["room"], "living-room")
        self.assertEqual(body["client_hint"], "living-room-mac")
        self.assertNotIn("intent_sources", body)
        self.assertNotIn("endpoints", body)

    def test_heartbeat_includes_edge_id(self) -> None:
        body = registration_payload(
            display_name="Home Server",
            device_type="mac",
            location="living-room",
            app_version="0.3.0",
            services=[],
            edge_id="edge-node-abc",
            online_status="online",
        )
        self.assertEqual(body["edge_id"], "edge-node-abc")
        self.assertEqual(body["online_status"], "online")


if __name__ == "__main__":
    unittest.main()
