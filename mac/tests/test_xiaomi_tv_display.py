"""Xiaomi TV DLNA adapter: parse description and SOAP play."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from mac_edge.plugins.xiaomi_tv_display import (
    XiaomiTvError,
    _send_wol,
    discover_renderer,
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


_XIAODU_DESC = """<?xml version="1.0"?>
<root xmlns="urn:schemas-upnp-org:device-1-0">
  <device>
    <friendlyName>小度智能音箱-8432</friendlyName>
    <serviceList>
      <service>
        <serviceType>urn:schemas-upnp-org:service:AVTransport:1</serviceType>
        <controlURL>/upnp/control/AVTransport1</controlURL>
      </service>
    </serviceList>
  </device>
</root>
"""

_TV_LOC = "http://192.168.3.20:49152/description.xml"


class DiscoverCacheWolTests(unittest.TestCase):
    """发现链路：缓存直连 / SSDP 多轮 / WoL 唤醒。"""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = {
            "MAC_EDGE_DATA_DIR": self.tmp.name,
            "MAC_EDGE_XIAOMI_TV_HOST": "",
            "MAC_EDGE_XIAOMI_TV_NAME": "",
            "MAC_EDGE_XIAOMI_TV_MAC": "",
            "MAC_EDGE_XIAOMI_TV_SSDP_ROUNDS": "",
        }
        self.patcher = patch.dict(os.environ, env, clear=False)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    @property
    def cache_file(self) -> Path:
        return Path(self.tmp.name) / "xiaomi_tv_renderer.json"

    def _seed_cache(self, location: str) -> None:
        self.cache_file.write_text(
            json.dumps({"location": location, "friendly_name": "小米电视 S Pro"}),
            encoding="utf-8",
        )

    def test_cache_hit_skips_ssdp(self) -> None:
        self._seed_cache(_TV_LOC)

        def search_fn() -> list[str]:
            raise AssertionError("SSDP should not run on cache hit")

        msg = discover_renderer(
            search_fn=search_fn, fetch_fn=lambda url: _DESC
        )
        self.assertEqual(msg["friendly_name"], "小米电视 S Pro")

    def test_stale_cache_falls_back_to_ssdp_and_rewrites(self) -> None:
        stale_loc = "http://192.168.3.99:49152/description.xml"
        self._seed_cache(stale_loc)

        def fetch_fn(url: str) -> str:
            if url == stale_loc:
                raise httpx.RequestError("conn refused")
            return _DESC

        out = discover_renderer(search_fn=lambda: [_TV_LOC], fetch_fn=fetch_fn)
        self.assertEqual(out["friendly_name"], "小米电视 S Pro")
        cached = json.loads(self.cache_file.read_text(encoding="utf-8"))
        self.assertEqual(cached["location"], _TV_LOC)

    def test_cache_name_mismatch_falls_back(self) -> None:
        self._seed_cache(_TV_LOC)

        def fetch_fn(url: str) -> str:
            # 缓存地址如今指向一台非电视设备（如 IP 被重新分配）
            return _XIAODU_DESC if "3.20" in url else _DESC

        with self.assertRaises(XiaomiTvError) as ctx:
            discover_renderer(search_fn=lambda: [], fetch_fn=fetch_fn)
        self.assertIn("没有发现 DLNA 电视", str(ctx.exception))

    def test_ssdp_second_round_after_empty_first(self) -> None:
        calls = {"n": 0}

        def search_fn() -> list[str]:
            calls["n"] += 1
            return [_TV_LOC] if calls["n"] >= 2 else []

        out = discover_renderer(search_fn=search_fn, fetch_fn=lambda url: _DESC)
        self.assertEqual(out["friendly_name"], "小米电视 S Pro")
        self.assertEqual(calls["n"], 2)

    def test_wol_sent_when_configured_and_nothing_found(self) -> None:
        wols: list[str] = []
        searches = {"n": 0}

        def search_fn() -> list[str]:
            searches["n"] += 1
            return []

        with patch.dict(os.environ, {"MAC_EDGE_XIAOMI_TV_MAC": "aa:bb:cc:dd:ee:ff"}):
            with self.assertRaises(XiaomiTvError):
                discover_renderer(
                    search_fn=search_fn,
                    fetch_fn=lambda url: _DESC,
                    wol_fn=wols.append,
                    sleep_fn=lambda _s: None,
                )
        self.assertEqual(wols, ["aa:bb:cc:dd:ee:ff"])
        # 2 轮常规 + WoL 后补 1 轮
        self.assertEqual(searches["n"], 3)

    def test_wol_wake_then_found(self) -> None:
        searches = {"n": 0}

        def search_fn() -> list[str]:
            searches["n"] += 1
            # 前 2 轮空手，WoL 后第 3 轮发现
            return [_TV_LOC] if searches["n"] >= 3 else []

        with patch.dict(os.environ, {"MAC_EDGE_XIAOMI_TV_MAC": "aa-bb-cc-dd-ee-ff"}):
            out = discover_renderer(
                search_fn=search_fn,
                fetch_fn=lambda url: _DESC,
                wol_fn=lambda _mac: None,
                sleep_fn=lambda _s: None,
            )
        self.assertEqual(out["friendly_name"], "小米电视 S Pro")

    def test_send_wol_rejects_bad_mac(self) -> None:
        with self.assertRaises(XiaomiTvError):
            _send_wol("not-a-mac")


if __name__ == "__main__":
    unittest.main()
