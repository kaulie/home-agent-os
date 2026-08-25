"""Tests for capability is_available contract."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from mac_edge.capability_availability import Availability, is_available, register_checker
from mac_edge.plugins.gopro_camera import is_available as gopro_is_available


class AvailabilityContractTests(unittest.TestCase):
    def test_unknown_capability_defaults_available(self) -> None:
        avail = is_available("math.calculate")
        self.assertTrue(avail.ok)

    def test_empty_capability_unavailable(self) -> None:
        avail = is_available("")
        self.assertFalse(avail.ok)

    def test_register_checker(self) -> None:
        register_checker(
            "test.probe",
            lambda _cfg: Availability.unavailable("blocked"),
        )
        avail = is_available("test.probe")
        self.assertFalse(avail.ok)
        self.assertIn("blocked", avail.msg)

    def test_gopro_missing_ssid(self) -> None:
        env = {
            "MAC_EDGE_GOPRO_SSID": "",
            "MAC_EDGE_GOPRO_PASSWORD": "x",
        }
        with patch.dict(os.environ, env, clear=False):
            avail = gopro_is_available()
        self.assertFalse(avail.ok)
        self.assertIn("MAC_EDGE_GOPRO_SSID", avail.msg)

    def test_gopro_visible_hotspot(self) -> None:
        env = {
            "MAC_EDGE_GOPRO_SSID": "GoProTest",
            "MAC_EDGE_GOPRO_PASSWORD": "secret",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch(
                "mac_edge.plugins.gopro_camera.current_ssid", return_value="HomeWifi"
            ):
                with patch(
                    "mac_edge.plugins.gopro_camera.ssid_visible", return_value=True
                ):
                    avail = gopro_is_available()
        self.assertTrue(avail.ok)

    def test_gopro_hotspot_missing(self) -> None:
        env = {
            "MAC_EDGE_GOPRO_SSID": "GoProTest",
            "MAC_EDGE_GOPRO_PASSWORD": "secret",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch(
                "mac_edge.plugins.gopro_camera.current_ssid", return_value="HomeWifi"
            ):
                with patch(
                    "mac_edge.plugins.gopro_camera.ssid_visible", return_value=False
                ):
                    avail = gopro_is_available()
        self.assertFalse(avail.ok)
        self.assertIn("扫描不到", avail.msg)


if __name__ == "__main__":
    unittest.main()
