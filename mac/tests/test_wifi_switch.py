"""Parse helpers for Wi-Fi SSID reads (no live radio)."""

from __future__ import annotations

import unittest

from mac_edge.plugins.gopro_camera import humanize_capture_error
from mac_edge.plugins.wifi_switch import _parse_ipconfig_ssid, _parse_networksetup_ssid


class ParseSsidTests(unittest.TestCase):
    def test_ipconfig_ssid(self) -> None:
        blob = (
            "<dictionary> {\n"
            "  BSSID : aa:bb:cc:dd:ee:ff\n"
            "  SSID : 面条_5G\n"
            "  Security : WPA2 Personal\n"
            "}\n"
        )
        self.assertEqual(_parse_ipconfig_ssid(blob), "面条_5G")

    def test_ipconfig_redacted_is_unknown(self) -> None:
        self.assertIsNone(_parse_ipconfig_ssid("  SSID : <redacted>\n"))

    def test_networksetup_current(self) -> None:
        self.assertEqual(
            _parse_networksetup_ssid("Current Wi-Fi Network: 面条_5G\n"),
            "面条_5G",
        )

    def test_networksetup_not_associated(self) -> None:
        self.assertIsNone(
            _parse_networksetup_ssid("You are not associated with an AirPort network.")
        )


class CaptureMsgTests(unittest.TestCase):
    def test_scan_empty_is_readable(self) -> None:
        msg = humanize_capture_error(
            "join 'xuanxuan' failed (rc=1): ERR scan empty ssid=xuanxuan"
        )
        self.assertIn("拍照失败", msg)
        self.assertIn("扫描不到", msg)
        self.assertIn("xuanxuan", msg)

    def test_restore_home_is_readable(self) -> None:
        msg = humanize_capture_error("restore home Wi-Fi failed: timed out waiting for ssid='面条_5G'")
        self.assertIn("切回家里", msg)

    def test_empty_still_readable(self) -> None:
        self.assertIn("拍照失败", humanize_capture_error(""))
