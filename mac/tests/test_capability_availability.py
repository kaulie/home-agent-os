"""Tests for capability is_available contract."""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from mac_edge.capability_availability import Availability, is_available, register_checker
from mac_edge.executor import handle_intent, is_available as executor_is_available
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

    def test_capture_and_upload_unavailable_when_capture_is(self) -> None:
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
                    avail = is_available("camera.capture_and_upload")
        self.assertFalse(avail.ok)
        self.assertIn("扫描不到", avail.msg)

    def test_point_to_character_unavailable_when_character_service_is(self) -> None:
        with patch(
            "mac_edge.plugins.point_to_character.is_available",
            return_value=Availability.unavailable("character-service 不可达"),
        ):
            avail = is_available("reading.point_to_character")
        self.assertFalse(avail.ok)
        self.assertIn("character-service", avail.msg)

    def test_detect_finger_follows_character_service(self) -> None:
        with patch(
            "mac_edge.plugins.point_to_character.is_available",
            return_value=Availability.unavailable("character-service 不可达"),
        ):
            avail = is_available("reading.detect_finger")
        self.assertFalse(avail.ok)
        self.assertIn("character-service", avail.msg)

    def test_point_to_character_available_without_camera(self) -> None:
        with patch(
            "mac_edge.plugins.point_to_character.is_available",
            return_value=Availability.available(),
        ):
            avail = is_available("reading.point_to_character")
        self.assertTrue(avail.ok)

    def test_executor_binds_is_available(self) -> None:
        self.assertIs(executor_is_available, is_available)

    def test_handle_intent_unavailable_is_not_nameerror(self) -> None:
        brain = MagicMock()
        brain.begin_running_reports.return_value = (1, 1)
        config = MagicMock()
        intent = {
            "id": 8,
            "status": "running",
            "execution_plan": [
                {
                    "step": 1,
                    "status": 0,
                    "assigned_edge_id": "edge-a",
                    "capability": "clock.now",
                },
            ],
        }
        with patch("mac_edge.local_ledger.active", return_value=None), patch(
            "mac_edge.executor.is_available",
            return_value=Availability.unavailable("blocked for test"),
        ), patch("mac_edge.executor._execute_capability") as exec_mock:
            handle_intent(intent, edge_id="edge-a", config=config, brain=brain)
        exec_mock.assert_not_called()
        intent_calls = brain.post_intent_status.call_args_list
        self.assertTrue(intent_calls)
        last = intent_calls[-1]
        self.assertEqual(last.kwargs.get("status"), "failed")
        self.assertEqual(last.kwargs.get("message"), "blocked for test")
        self.assertNotIn(
            "capability_is_available",
            str(last.kwargs.get("message") or ""),
        )


if __name__ == "__main__":
    unittest.main()
