"""Unit tests for xiaodu.speaker plugin."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mac_edge.plugins import xiaodu_speaker as xs


class XiaoduSpeakerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        # 缓存指到临时目录：单测绝不读/写仓库里的 mac/data
        self._env = mock.patch.dict(
            os.environ,
            {
                "MAC_EDGE_XIAODU_CACHE": str(Path(self._tmp.name) / "xiaodu_renderer.json"),
                "MAC_EDGE_XIAODU_IP": "",
                "MAC_EDGE_XIAODU_DISCOVER": "0",
            },
            clear=False,
        )
        self._env.start()
        xs.bind_server(None)

    def tearDown(self) -> None:
        xs.bind_server(None)
        self._env.stop()

    def test_speak_from_params_requires_text(self) -> None:
        with self.assertRaises(xs.XiaoduSpeakerError) as ctx:
            xs.speak_from_params({})
        self.assertIn("text", str(ctx.exception).lower())

    def test_play_uri_sends_stop_seturi_play(self) -> None:
        calls: list[tuple[str, str, float]] = []

        def fake_post(
            du_ip: str,
            action: str,
            body: str,
            *,
            timeout_sec: float = 8.0,
        ) -> None:
            calls.append((action, body, timeout_sec))

        with mock.patch.object(xs, "_upnp_post", side_effect=fake_post):
            xs.play_uri("192.168.3.47", "http://192.168.3.73:8000/tts_1.mp3")

        self.assertEqual(len(calls), 3)
        self.assertIn("Stop", calls[0][0])
        self.assertEqual(calls[0][2], xs.UPNP_STOP_TIMEOUT_SEC)
        self.assertIn("SetAVTransportURI", calls[1][0])
        self.assertIn("http://192.168.3.73:8000/tts_1.mp3", calls[1][1])
        self.assertIn("Play", calls[2][0])

    def test_play_uri_continues_when_stop_times_out(self) -> None:
        calls: list[str] = []

        def fake_post(
            du_ip: str,
            action: str,
            body: str,
            *,
            timeout_sec: float = 8.0,
        ) -> None:
            calls.append(action)
            if "Stop" in action:
                raise xs.XiaoduSpeakerError("UPnP request failed (Stop): timed out")

        with mock.patch.object(xs, "_upnp_post", side_effect=fake_post):
            xs.play_uri("192.168.3.47", "http://192.168.3.73:8000/tts_2.mp3")

        self.assertEqual(len(calls), 3)
        self.assertIn("Stop", calls[0])
        self.assertIn("SetAVTransportURI", calls[1])
        self.assertIn("Play", calls[2])

    def test_speak_synthesizes_and_plays(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            server = xs.XiaoduTtsHttpServer(data_dir=data_dir, http_port=0)
            server.start()
            xs.bind_server(server)
            self.addCleanup(server.stop)
            self.addCleanup(lambda: xs.bind_server(None))

            async def fake_synthesize(text: str, voice: str, path: Path) -> None:
                path.write_bytes(b"\xff" * 128)

            upnp_calls: list[str] = []

            def fake_post(
                du_ip: str,
                action: str,
                body: str,
                *,
                timeout_sec: float = 8.0,
            ) -> None:
                upnp_calls.append(action)

            with mock.patch.dict(
                os.environ,
                {"MAC_EDGE_XIAODU_IP": "192.168.3.47", "MAC_EDGE_XIAODU_PUBLIC_HOST": "192.168.3.73"},
                clear=False,
            ):
                with mock.patch.object(xs, "_synthesize", side_effect=fake_synthesize):
                    with mock.patch.object(xs, "_upnp_post", side_effect=fake_post):
                        msg = xs.speak("欢迎回家")

            self.assertTrue(msg.startswith("xiaodu spoke:"))
            self.assertIn("欢迎回家", msg)
            self.assertEqual(len(upnp_calls), 3)
            mp3_files = list(server.serve_dir.glob("tts_*.mp3"))
            self.assertEqual(len(mp3_files), 1)
            self.assertGreaterEqual(mp3_files[0].stat().st_size, 64)

    def test_xiaodu_configured(self) -> None:
        # 没覆盖、没缓存、探测关掉 → 不广告
        with mock.patch.dict(
            os.environ, {"MAC_EDGE_XIAODU_DISCOVER": "0", "MAC_EDGE_XIAODU_IP": ""}, clear=False
        ):
            self.assertFalse(xs.xiaodu_configured())
        # 显式覆盖 → 广告（老行为）
        with mock.patch.dict(os.environ, {"MAC_EDGE_XIAODU_IP": "192.168.3.47"}, clear=False):
            self.assertTrue(xs.xiaodu_configured())
        # 显式关闭 → 不广告（即使有覆盖）
        with mock.patch.dict(
            os.environ,
            {"MAC_EDGE_XIAODU_IP": "192.168.3.47", "MAC_EDGE_XIAODU": "0"},
            clear=False,
        ):
            self.assertFalse(xs.xiaodu_configured())

    def test_xiaodu_configured_by_discovery(self) -> None:
        """不写死地址也能广告：SSDP 现场探测到就广告。"""
        with mock.patch.dict(
            os.environ,
            {"MAC_EDGE_XIAODU_IP": "", "MAC_EDGE_XIAODU": "", "MAC_EDGE_XIAODU_DISCOVER": ""},
            clear=False,
        ):
            with mock.patch.object(
                xs, "discover_xiaodu", return_value=xs.XiaoduDevice(ip="192.168.3.47")
            ):
                self.assertTrue(xs.xiaodu_configured())

    def test_from_env_returns_none_without_ip(self) -> None:
        with mock.patch.dict(
            os.environ, {"MAC_EDGE_XIAODU_IP": "", "MAC_EDGE_XIAODU_DISCOVER": "0"}, clear=False
        ):
            self.assertIsNone(xs.XiaoduTtsHttpServer.from_env(Path("/tmp/xiaodu_test")))

    def test_public_url_uses_override_host(self) -> None:
        server = xs.XiaoduTtsHttpServer(data_dir=Path("/tmp/xiaodu_test2"), http_port=8000)
        with mock.patch.dict(
            os.environ, {"MAC_EDGE_XIAODU_PUBLIC_HOST": "192.168.3.84"}, clear=False
        ):
            with mock.patch.object(xs.lan, "is_local_ip", return_value=True):
                url = server.public_url("tts_99.mp3")
        self.assertEqual(url, "http://192.168.3.84:8000/tts_99.mp3")

    def test_public_url_ignores_stale_override(self) -> None:
        """写死但过期的本机地址（.73）不能再用 —— 按目标设备探测（.84）。"""
        server = xs.XiaoduTtsHttpServer(data_dir=Path("/tmp/xiaodu_test3"), http_port=8000)
        with mock.patch.dict(
            os.environ, {"MAC_EDGE_XIAODU_PUBLIC_HOST": "192.168.3.73"}, clear=False
        ):
            with mock.patch.object(xs.lan, "is_local_ip", return_value=False):
                with mock.patch.object(xs.lan, "local_ips", return_value=["192.168.3.84"]):
                    with mock.patch.object(xs.lan, "local_ip_for", return_value="192.168.3.84"):
                        host = xs.public_host("192.168.3.47")
                        url = server.public_url("tts_99.mp3", host=host)
        self.assertEqual(url, "http://192.168.3.84:8000/tts_99.mp3")


class XiaoduDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cache = Path(self._tmp.name) / "xiaodu_renderer.json"
        self._env = mock.patch.dict(
            os.environ,
            {
                "MAC_EDGE_XIAODU_CACHE": str(self.cache),
                "MAC_EDGE_XIAODU_IP": "",
                "MAC_EDGE_XIAODU_NAME": "",
                "MAC_EDGE_XIAODU": "",
                "MAC_EDGE_XIAODU_DISCOVER": "",
                "MAC_EDGE_XIAODU_PUBLIC_HOST": "",
            },
            clear=False,
        )
        self._env.start()
        xs.bind_server(None)

    def tearDown(self) -> None:
        xs.bind_server(None)
        self._env.stop()

    def _desc(
        self,
        ip: str,
        name: str = "小度智能音箱-8432",
        manufacturer: str = "DuerOS",
        model: str = "DuerOS-Render",
    ):
        from mac_edge.plugins.lan_discovery import DeviceDescription

        return DeviceDescription(
            location=f"http://{ip}:49494/description.xml",
            ip=ip,
            friendly_name=name,
            manufacturer=manufacturer,
            model_name=model,
            services={xs.lan.AV_TRANSPORT: f"http://{ip}:49494/upnp/control/rendertransport1"},
        )

    def _resp(self, ip: str):
        return xs.lan.SsdpResponse(ip=ip, location=f"http://{ip}:49494/description.xml")

    def test_discover_returns_probed_device(self) -> None:
        with mock.patch.object(xs.lan, "ssdp_search", return_value=[self._resp("192.168.3.47")]):
            with mock.patch.object(
                xs.lan, "fetch_device_description", return_value=self._desc("192.168.3.47")
            ):
                with mock.patch.object(xs.lan, "probe_av_transport", return_value=True) as probe:
                    device = xs.discover_xiaodu(timeout_sec=0.1)
        self.assertIsNotNone(device)
        self.assertEqual(device.ip, "192.168.3.47")
        self.assertEqual(
            device.control_url, "http://192.168.3.47:49494/upnp/control/rendertransport1"
        )
        probe.assert_called_once()

    def test_discover_skips_unprobeable_device(self) -> None:
        """探活不通 = 不采信（同网段可能还有别的 DuerOS/休眠设备）。"""
        with mock.patch.object(xs.lan, "ssdp_search", return_value=[self._resp("192.168.3.99")]):
            with mock.patch.object(
                xs.lan, "fetch_device_description", return_value=self._desc("192.168.3.99")
            ):
                with mock.patch.object(xs.lan, "probe_av_transport", return_value=False):
                    self.assertIsNone(xs.discover_xiaodu(timeout_sec=0.1))

    def test_discover_skips_foreign_devices(self) -> None:
        with mock.patch.object(xs.lan, "ssdp_search", return_value=[self._resp("192.168.3.59")]):
            with mock.patch.object(
                xs.lan,
                "fetch_device_description",
                return_value=self._desc(
                    "192.168.3.59", name="客厅电视", manufacturer="Xiaomi", model="MiTV"
                ),
            ):
                with mock.patch.object(xs.lan, "probe_av_transport", return_value=True):
                    self.assertIsNone(xs.discover_xiaodu(timeout_sec=0.1))



if __name__ == "__main__":
    unittest.main()


    def test_resolve_prefers_override_then_discovers_and_caches(self) -> None:
        # 显式覆盖优先，且不探测
        with mock.patch.object(xs.lan, "ssdp_search") as ssdp:
            device = xs.resolve_device(override_ip="192.168.3.50")
        self.assertEqual(device.source, "override")
        self.assertEqual(device.ip, "192.168.3.50")
        ssdp.assert_not_called()

        # 没覆盖 → SSDP 探测 → 落缓存
        with mock.patch.object(xs.lan, "ssdp_search", return_value=[self._resp("192.168.3.47")]):
            with mock.patch.object(
                xs.lan, "fetch_device_description", return_value=self._desc("192.168.3.47")
            ):
                with mock.patch.object(xs.lan, "probe_av_transport", return_value=True):
                    found = xs.resolve_device()
        self.assertEqual(found.source, "discovered")
        cached = json.loads(self.cache.read_text(encoding="utf-8"))
        self.assertEqual(cached["ip"], "192.168.3.47")
        self.assertEqual(cached["control_url"], found.control_url)

        # 有缓存 → 先缓存（但仍要探活通过）
        with mock.patch.object(xs.lan, "ssdp_search") as ssdp2:
            with mock.patch.object(
                xs.lan, "fetch_device_description", return_value=self._desc("192.168.3.47")
            ):
                with mock.patch.object(xs.lan, "probe_av_transport", return_value=True):
                    again = xs.resolve_device()
        self.assertEqual(again.source, "cache")
        ssdp2.assert_not_called()

    def test_resolve_drops_stale_cache_and_rediscovers(self) -> None:
        xs.lan.write_cache(
            self.cache,
            {"ip": "192.168.3.47", "location": "http://192.168.3.47:49494/description.xml"},
        )
        fetches = [xs.lan.LanDiscoveryError("timeout"), self._desc("192.168.3.48")]
        with mock.patch.object(xs.lan, "fetch_device_description", side_effect=fetches):
            with mock.patch.object(xs.lan, "ssdp_search", return_value=[self._resp("192.168.3.48")]):
                with mock.patch.object(xs.lan, "probe_av_transport", return_value=True):
                    device = xs.resolve_device()
        self.assertEqual(device.ip, "192.168.3.48")
        self.assertEqual(device.source, "discovered")
        self.assertEqual(json.loads(self.cache.read_text(encoding="utf-8"))["ip"], "192.168.3.48")

    def test_resolve_without_any_device_is_explicit(self) -> None:
        with mock.patch.object(xs.lan, "ssdp_search", return_value=[]):
            with self.assertRaises(xs.XiaoduSpeakerError) as ctx:
                xs.resolve_device()
        self.assertIn("没有找到小度音箱", str(ctx.exception))

    def test_speak_heals_when_cached_device_is_gone(self) -> None:
        """缓存地址播放失败 → 丢缓存重新探测 → 用新地址重试一次。"""
        with tempfile.TemporaryDirectory() as tmp:
            server = xs.XiaoduTtsHttpServer(data_dir=Path(tmp), http_port=0)
            server.start()
            xs.bind_server(server)
            self.addCleanup(server.stop)

            async def fake_synthesize(text: str, voice: str, path: Path) -> None:
                path.write_bytes(b"\xff" * 128)

            played: list[tuple[str, str]] = []

            def fake_play(device: xs.XiaoduDevice, uri: str) -> None:
                played.append((device.ip, uri))
                if len(played) == 1:
                    raise xs.XiaoduSpeakerError("UPnP request failed (Play): timeout")

            devices = [
                xs.XiaoduDevice(ip="192.168.3.47", source="cache"),
                xs.XiaoduDevice(ip="192.168.3.48", source="discovered"),
            ]
            with mock.patch.object(xs, "resolve_device", side_effect=devices):
                with mock.patch.object(xs, "_synthesize", side_effect=fake_synthesize):
                    with mock.patch.object(xs, "play_device", side_effect=fake_play):
                        msg = xs.speak("欢迎回家")
        self.assertTrue(msg.startswith("xiaodu spoke:"))
        self.assertEqual([ip for ip, _uri in played], ["192.168.3.47", "192.168.3.48"])
        self.assertTrue(all("tts_" in uri for _ip, uri in played))
