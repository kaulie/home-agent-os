"""Xiaomi TV DLNA adapter: parse description and SOAP play."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx

from mac_edge.asset.types import AssetError, AssetRef
from mac_edge.plugins.xiaomi_tv_display import (
    XiaomiTvError,
    _send_wol,
    audio_current_uri_metadata,
    audio_from_params,
    discover_renderer,
    display_backend,
    parse_device_description,
    play_audio,
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


_AUDIO_REF = AssetRef(asset_id="asset_a0c4", type="audio", mime_type="audio/mpeg")
_AUDIO_URL = (
    "http://192.168.3.84:9527/api/v1/assets/asset_a0c4/content"
    "?intent_id=781&representation=original"
)


class AudioMetadataTests(unittest.TestCase):
    def test_didl_marks_audio_item_with_mime(self) -> None:
        didl = audio_current_uri_metadata(_AUDIO_URL, "audio/mpeg")
        self.assertIn("object.item.audioItem.musicTrack", didl)
        self.assertIn("http-get:*:audio/mpeg:*", didl)
        # DIDL 里的 URL 必须 XML 转义（& → &amp;）
        self.assertIn(_AUDIO_URL.replace("&", "&amp;"), didl)

    def test_didl_defaults_to_mp3(self) -> None:
        self.assertIn(
            "http-get:*:audio/mpeg:*",
            audio_current_uri_metadata("http://192.168.3.84:9527/a"),
        )

    def test_didl_keeps_m4a_mime(self) -> None:
        self.assertIn(
            "http-get:*:audio/mp4:*",
            audio_current_uri_metadata("http://192.168.3.84:9527/a", "audio/mp4"),
        )


class AudioPlayTests(unittest.TestCase):
    def test_play_audio_sends_set_and_play_with_metadata(self) -> None:
        posts: list[str] = []

        def post_fn(_url: str, envelope: str, _headers: dict[str, str]) -> int:
            posts.append(envelope)
            return 200

        msg = play_audio(
            _AUDIO_URL,
            mime_type="audio/mpeg",
            renderer={
                "friendly_name": "小米电视 S Pro",
                "control_url": "http://192.168.3.20/av",
            },
            post_fn=post_fn,
        )
        self.assertIn("dlna audio ok", msg)
        self.assertEqual(len(posts), 2)
        self.assertIn("SetAVTransportURI", posts[0])
        self.assertIn("audioItem", posts[0])
        self.assertIn("Play", posts[1])

    def test_play_audio_empty_url_fails(self) -> None:
        with self.assertRaises(XiaomiTvError):
            play_audio("   ")

    def test_play_audio_requires_http(self) -> None:
        with self.assertRaises(XiaomiTvError):
            play_audio("/tmp/a.mp3")


class AudioFromParamsTests(unittest.TestCase):
    def _asset(self) -> MagicMock:
        asset = MagicMock()
        asset.require_ref.return_value = _AUDIO_REF
        asset.http_url.return_value = _AUDIO_URL
        return asset

    def test_plays_audio_asset_on_tv(self) -> None:
        played: list[str] = []

        def play_fn(url: str, **_kwargs: object) -> str:
            played.append(url)
            return "dlna audio ok → 小米电视 S Pro"

        msg, outputs = audio_from_params(
            {"asset_ref": _AUDIO_REF.to_dict()},
            asset=self._asset(),
            play_fn=play_fn,
        )
        self.assertEqual(played, [_AUDIO_URL])
        self.assertIn("cast_status=accepted", msg)
        self.assertEqual(outputs["cast_transport"], "xiaomi_dlna")
        self.assertEqual(outputs["asset_id"], "asset_a0c4")
        self.assertIn("播放", outputs["status_text"])

    def test_rejects_non_audio_asset(self) -> None:
        asset = self._asset()
        asset.require_ref.return_value = AssetRef(
            asset_id="img_1", type="image", mime_type="image/jpeg"
        )
        with self.assertRaises(XiaomiTvError) as ctx:
            audio_from_params(
                {"asset_ref": "{}"}, asset=asset, play_fn=lambda *a, **k: "x"
            )
        self.assertIn("audio", str(ctx.exception))

    def test_missing_asset_ref_fails(self) -> None:
        asset = self._asset()
        asset.require_ref.side_effect = AssetError(
            "missing or invalid asset_ref (AssetRef required)"
        )
        with self.assertRaises(XiaomiTvError):
            audio_from_params({}, asset=asset, play_fn=lambda *a, **k: "x")


class AudioAdvertiseTests(unittest.TestCase):
    _XIAOMI_ENV = {
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
    _CAST_ENV = {
        **_XIAOMI_ENV,
        "MAC_EDGE_DISPLAY_BACKEND": "",
        "MAC_EDGE_XIAOMI_TV": "",
        "MAC_EDGE_XIAOMI_TV_HOST": "",
        "MAC_EDGE_XIAOMI_TV_NAME": "",
    }

    def _ids(self, env: dict[str, str]) -> set[str]:
        with patch.dict(os.environ, env, clear=False):
            services = default_services()
        return {
            str(c["capability_id"])
            for s in services
            for c in (s.get("capabilities") or [])
        }

    def test_xiaomi_backend_advertises_display_audio(self) -> None:
        self.assertIn("display.audio", self._ids(self._XIAOMI_ENV))

    def test_cast_backend_does_not_advertise_display_audio(self) -> None:
        self.assertNotIn("display.audio", self._ids(self._CAST_ENV))


class AudioExecutorDispatchTests(unittest.TestCase):
    def test_executor_dispatches_audio_on_xiaomi_backend(self) -> None:
        from mac_edge.executor import _execute_capability

        config = MagicMock()
        config.display_http_timeout_sec = 5.0
        with patch.dict(os.environ, {"MAC_EDGE_DISPLAY_BACKEND": "xiaomi"}, clear=False):
            with patch(
                "mac_edge.executor.xiaomi_audio_from_params",
                return_value=("ok", {"status_text": "已在小米电视播放最新音频"}),
            ) as fn:
                ok, _msg, outputs = _execute_capability(
                    "display.audio",
                    MagicMock(),
                    params={"asset_ref": _AUDIO_REF.to_dict()},
                    config=config,
                )
        self.assertTrue(ok)
        self.assertEqual(outputs["status_text"], "已在小米电视播放最新音频")
        fn.assert_called_once()

    def test_executor_rejects_audio_on_cast_backend(self) -> None:
        from mac_edge.executor import _execute_capability

        env = {
            "MAC_EDGE_DISPLAY_BACKEND": "cast",
            "MAC_EDGE_XIAOMI_TV": "",
            "MAC_EDGE_XIAOMI_TV_HOST": "",
            "MAC_EDGE_XIAOMI_TV_NAME": "",
        }
        with patch.dict(os.environ, env, clear=False):
            ok, msg, _outputs = _execute_capability(
                "display.audio", MagicMock(), params={}, config=MagicMock()
            )
        self.assertFalse(ok)
        self.assertIn("DLNA", msg)


if __name__ == "__main__":
    unittest.main()
