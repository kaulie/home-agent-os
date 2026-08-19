"""Heartbeat capability descriptions must tell the planner can / cannot."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from mac_edge.services import default_services


def _caps(services: list[dict]) -> list[dict]:
    out: list[dict] = []
    for svc in services:
        for cap in svc.get("capabilities") or []:
            out.append(cap)
    return out


class PlannerDescriptionTests(unittest.TestCase):
    def test_laptop_caps_state_can_and_cannot(self) -> None:
        env = {
            "MAC_EDGE_ROLE": "laptop",
            "MAC_EDGE_SERVICE_WHITELIST": "",
            "MAC_EDGE_GOPRO_SSID": "",
            "MAC_EDGE_ADVERTISE_CAST": "1",
        }
        with patch.dict(os.environ, env, clear=False):
            caps = _caps(default_services())
        ids = {c["capability_id"] for c in caps}
        self.assertGreaterEqual(
            ids,
            {
                "display.photo",
                "display.slideshow",
                "notify.speak",
                "query.content",
                "clock.now",
                "vision.perceive",
                "vision.ask",
            },
        )
        for cap in caps:
            desc = str(cap.get("description") or "")
            cid = cap["capability_id"]
            self.assertIn("能：", desc, cid)
            self.assertIn("不能：", desc, cid)
            if cid == "query.content":
                self.assertIn("文生图", desc)
                self.assertIn("投屏", desc)
                self.assertIn("不生图", desc)

    def test_home_server_caps_state_can_and_cannot(self) -> None:
        env = {
            "MAC_EDGE_ROLE": "home-server",
            "MAC_EDGE_SERVICE_WHITELIST": "",
            "MAC_EDGE_GOPRO_SSID": "xuanxuan",
            "MAC_EDGE_ADVERTISE_CAST": "0",
        }
        with patch.dict(os.environ, env, clear=False):
            caps = _caps(default_services())
        ids = {c["capability_id"] for c in caps}
        self.assertEqual(ids, {"camera.capture", "light.set"})
        for cap in caps:
            desc = str(cap.get("description") or "")
            self.assertIn("能：", desc, cap["capability_id"])
            self.assertIn("不能：", desc, cap["capability_id"])


if __name__ == "__main__":
    unittest.main()
