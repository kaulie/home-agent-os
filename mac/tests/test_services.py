"""Laptop registers general Mac caps; home-server is GoPro + living-room light."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from mac_edge.services import default_services


def _ids(services: list[dict]) -> list[str]:
    return [str(s["service_id"]) for s in services]


class ServiceAdvertiseTests(unittest.TestCase):
    def test_laptop_registers_query_not_gopro_even_with_ssid(self) -> None:
        env = {
            "MAC_EDGE_ROLE": "laptop",
            "MAC_EDGE_SERVICE_WHITELIST": "",
            "MAC_EDGE_GOPRO_SSID": "xuanxuan",
            "MAC_EDGE_ADVERTISE_CAST": "0",
            "MAC_EDGE_HISENSE_USERNAME": "",
            "MAC_EDGE_HISENSE_PASSWORD": "",
            "MAC_EDGE_XIAOMI_USERNAME": "",
            "MAC_EDGE_XIAOMI_PASSWORD": "",
            "MAC_EDGE_XIAOMI_TV": "",
            "MAC_EDGE_DISPLAY_BACKEND": "",
            "MAC_EDGE_XIAOMI_TV_HOST": "",
        }
        with patch.dict(os.environ, env, clear=False):
            services = default_services()
        ids = _ids(services)
        self.assertIn("local.query", ids)
        self.assertIn("local.notify", ids)
        self.assertIn("local.vision", ids)
        self.assertIn("local.clock", ids)
        self.assertIn("local.math", ids)
        self.assertIn("local.voice_test", ids)
        clock_caps = []
        for svc in services:
            if svc["service_id"] == "local.clock":
                clock_caps = [c["capability_id"] for c in svc["capabilities"]]
        self.assertIn("clock.now", clock_caps)
        self.assertIn("livingroom.ceiling_light", ids)
        light_caps = []
        for svc in services:
            if svc["service_id"] == "livingroom.ceiling_light":
                light_caps = [c["capability_id"] for c in svc["capabilities"]]
        self.assertIn("light.set", light_caps)
        self.assertNotIn("livingroom.climate", ids)
        self.assertNotIn("livingroom.aquarium", ids)
        self.assertNotIn("entry.lock", ids)
        self.assertNotIn("xiaomi.tv.display", ids)
        self.assertNotIn("local.endpoint", ids)
        caps = []
        for svc in services:
            if svc["service_id"] == "local.vision":
                caps = [c["capability_id"] for c in svc["capabilities"]]
        self.assertIn("vision.perceive", caps)
        self.assertIn("vision.ask", caps)
        self.assertNotIn("gopro.camera", ids)
        self.assertNotIn("chromecast.display", ids)
        self.assertNotIn("local.capabilities", ids)

    def test_default_role_is_laptop(self) -> None:
        env = {
            "MAC_EDGE_ROLE": "",
            "MAC_EDGE_SERVICE_WHITELIST": "",
            "MAC_EDGE_GOPRO_SSID": "",
            "MAC_EDGE_ADVERTISE_CAST": "1",
            "MAC_EDGE_HISENSE_USERNAME": "",
            "MAC_EDGE_HISENSE_PASSWORD": "",
            "MAC_EDGE_XIAOMI_USERNAME": "",
            "MAC_EDGE_XIAOMI_PASSWORD": "",
            "MAC_EDGE_XIAOMI_TV": "",
            "MAC_EDGE_DISPLAY_BACKEND": "",
            "MAC_EDGE_XIAOMI_TV_HOST": "",
        }
        with patch.dict(os.environ, env, clear=False):
            ids = _ids(default_services())
        self.assertIn("local.query", ids)
        self.assertIn("chromecast.display", ids)
        self.assertIn("local.clock", ids)
        self.assertIn("local.voice_test", ids)
        self.assertIn("livingroom.ceiling_light", ids)
        self.assertNotIn("livingroom.climate", ids)
        self.assertNotIn("livingroom.aquarium", ids)
        self.assertNotIn("entry.lock", ids)
        self.assertNotIn("xiaomi.tv.display", ids)
        self.assertNotIn("local.endpoint", ids)
        self.assertNotIn("gopro.camera", ids)

    def test_home_server_role_gopro_and_light(self) -> None:
        env = {
            "MAC_EDGE_ROLE": "home-server",
            "MAC_EDGE_SERVICE_WHITELIST": "",
            "MAC_EDGE_GOPRO_SSID": "xuanxuan",
            "MAC_EDGE_ADVERTISE_CAST": "1",
            "MAC_EDGE_HISENSE_USERNAME": "",
            "MAC_EDGE_HISENSE_PASSWORD": "",
            "MAC_EDGE_XIAOMI_USERNAME": "",
            "MAC_EDGE_XIAOMI_PASSWORD": "",
            "MAC_EDGE_XIAOMI_TV": "",
            "MAC_EDGE_DISPLAY_BACKEND": "",
            "MAC_EDGE_XIAOMI_TV_HOST": "",
        }
        with patch.dict(os.environ, env, clear=False):
            services = default_services()
        ids = _ids(services)
        self.assertCountEqual(
            ids, ["gopro.camera", "livingroom.ceiling_light", "local.asset"]
        )
        light_caps = []
        for svc in services:
            if svc["service_id"] == "livingroom.ceiling_light":
                light_caps = [c["capability_id"] for c in svc["capabilities"]]
        self.assertIn("light.set", light_caps)

    def test_whitelist_gopro_implies_home_server(self) -> None:
        env = {
            "MAC_EDGE_ROLE": "",
            "MAC_EDGE_SERVICE_WHITELIST": "gopro.camera",
            "MAC_EDGE_GOPRO_SSID": "xuanxuan",
            "MAC_EDGE_ADVERTISE_CAST": "1",
            "MAC_EDGE_HISENSE_USERNAME": "",
            "MAC_EDGE_HISENSE_PASSWORD": "",
            "MAC_EDGE_XIAOMI_USERNAME": "",
            "MAC_EDGE_XIAOMI_PASSWORD": "",
            "MAC_EDGE_XIAOMI_TV": "",
            "MAC_EDGE_DISPLAY_BACKEND": "",
            "MAC_EDGE_XIAOMI_TV_HOST": "",
        }
        with patch.dict(os.environ, env, clear=False):
            self.assertEqual(_ids(default_services()), ["gopro.camera"])

    def test_home_server_without_ssid_still_light(self) -> None:
        env = {
            "MAC_EDGE_ROLE": "home-server",
            "MAC_EDGE_SERVICE_WHITELIST": "",
            "MAC_EDGE_GOPRO_SSID": "",
            "MAC_EDGE_ADVERTISE_CAST": "0",
            "MAC_EDGE_HISENSE_USERNAME": "",
            "MAC_EDGE_HISENSE_PASSWORD": "",
            "MAC_EDGE_XIAOMI_USERNAME": "",
            "MAC_EDGE_XIAOMI_PASSWORD": "",
            "MAC_EDGE_XIAOMI_TV": "",
            "MAC_EDGE_DISPLAY_BACKEND": "",
            "MAC_EDGE_XIAOMI_TV_HOST": "",
        }
        with patch.dict(os.environ, env, clear=False):
            self.assertCountEqual(
                _ids(default_services()),
                ["livingroom.ceiling_light", "local.asset"],
            )

    def test_home_server_whitelist_gopro_without_ssid_is_empty(self) -> None:
        env = {
            "MAC_EDGE_ROLE": "home-server",
            "MAC_EDGE_SERVICE_WHITELIST": "gopro.camera",
            "MAC_EDGE_GOPRO_SSID": "",
            "MAC_EDGE_ADVERTISE_CAST": "0",
            "MAC_EDGE_HISENSE_USERNAME": "",
            "MAC_EDGE_HISENSE_PASSWORD": "",
            "MAC_EDGE_XIAOMI_USERNAME": "",
            "MAC_EDGE_XIAOMI_PASSWORD": "",
            "MAC_EDGE_XIAOMI_TV": "",
            "MAC_EDGE_DISPLAY_BACKEND": "",
            "MAC_EDGE_XIAOMI_TV_HOST": "",
        }
        with patch.dict(os.environ, env, clear=False):
            self.assertEqual(_ids(default_services()), [])


if __name__ == "__main__":
    unittest.main()
