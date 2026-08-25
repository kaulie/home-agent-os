"""Xiaomi TV DLNA adapter: parse description and SOAP play."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from mac_edge.plugins.xiaomi_tv_display import (
    XiaomiTvError,
    display_backend,
    parse_device_description,
    play_photo,
    tv_configured,
)
from mac_edge.services import default_services

_DESC = """<?xml version="1.0"?>
<root xmlns="urn:schemas-upnp-org:device-1-0">
  <device>
    <friendlyName>小米电视 S Pro</friendlyName>
    <serviceList>
      <service>
        <serviceType>urn:schemas-upnp-org:service:AVTransport:1</serviceType>
        <controlURL>/upnp/control/AVTransport1</controlURL>
      </service>
    </serviceList>
  </device>
</root>
"""


class TvConfigTests(unittest.TestCase):
    def test_backend_defaults_cast(self) -> None:
        env = {
            "MAC_EDGE_DISPLAY_BACKEND": "",
            "MAC_EDGE_XIAOMI_TV": "",
            "MAC_EDGE_XIAOMI_TV_HOST": "",
            "MAC_EDGE_XIAOMI_TV_NAME": "",
        }
        with patch.dict(os.environ, env, clear=False):
            self.assertEqual(display_backend(), "cast")
            self.assertFalse(tv_configured())

    def test_backend_xiaomi_when_host_set(self) -> None:
        env = {
            "MAC_EDGE_DISPLAY_BACKEND": "",
            "MAC_EDGE_XIAOMI_TV": "",
            "MAC_EDGE_XIAOMI_TV_HOST": "192.168.3.20",
            "MAC_EDGE_XIAOMI_TV_NAME": "",
        }
        with patch.dict(os.environ, env, clear=False):
            self.assertEqual(display_backend(), "xiaomi")
            self.assertTrue(tv_configured())


class DlnaParseTests(unittest.TestCase):
    def test_parse_control_url(self) -> None:
        parsed = parse_device_description(
            _DESC, "http://192.168.3.20:49152/description.xml"
        )
        assert parsed is not None
        self.assertEqual(parsed["friendly_name"], "小米电视 S Pro")
        self.assertEqual(
            parsed["control_url"],
            "http://192.168.3.20:49152/upnp/control/AVTransport1",
        )

    def test_play_photo_sends_set_and_play(self) -> None:
        posts: list[str] = []

        def post_fn(_url: str, envelope: str, _headers: dict[str, str]) -> int:
            posts.append(envelope)
            return 200

        msg = play_photo(
            "http://192.168.3.65:8080/p.jpg",
            renderer={
                "friendly_name": "小米电视 S Pro",
                "control_url": "http://192.168.3.20/av",
            },
            post_fn=post_fn,
        )
        self.assertIn("dlna ok", msg)
        self.assertEqual(len(posts), 2)
        self.assertIn("SetAVTransportURI", posts[0])
        self.assertIn("http://192.168.3.65:8080/p.jpg", posts[0])
        self.assertIn("Play", posts[1])

    def test_empty_url_fails(self) -> None:
        with self.assertRaises(XiaomiTvError):
            play_photo("")


class AdvertiseTvTests(unittest.TestCase):
    def test_xiaomi_backend_advertises_tv_not_cast(self) -> None:
        env = {
            "MAC_EDGE_ROLE": "laptop",
            "MAC_EDGE_SERVICE_WHITELIST": "",
            "MAC_EDGE_GOPRO_SSID": "",
            "MAC_EDGE_ADVERTISE_CAST": "1",
            "MAC_EDGE_HISENSE_USERNAME": "",
            "MAC_EDGE_HISENSE_PASSWORD": "",
            "MAC_EDGE_XIAOMI_USERNAME": "",
            "MAC_EDGE_XIAOMI_PASSWORD": "",
            "MAC_EDGE_DISPLAY_BACKEND": "xiaomi",
            "MAC_EDGE_XIAOMI_TV": "1",
            "MAC_EDGE_XIAOMI_TV_HOST": "",
        }
        with patch.dict(os.environ, env, clear=False):
            ids = [s["service_id"] for s in default_services()]
        self.assertIn("xiaomi.tv.display", ids)
        self.assertNotIn("chromecast.display", ids)


if __name__ == "__main__":
    unittest.main()
