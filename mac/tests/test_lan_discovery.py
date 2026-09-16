"""lan_discovery — 局域网地址探测层（SSDP / UPnP 描述 / 本机出口 IP）。

不依赖网络与真实设备：socket、HTTP、ioctl 全部 mock；只有纯解析是真的。
"""

from __future__ import annotations

import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mac_edge.plugins import lan_discovery as ld

# 真机抓下来的小度 description.xml（截取需要的部分）
XIAODU_DESC = """<?xml version="1.0"?>
<root xmlns="urn:schemas-upnp-org:device-1-0">
<specVersion><major>1</major><minor>0</minor></specVersion>
<device>
<deviceType>urn:schemas-upnp-org:device:MediaRenderer:1</deviceType>
<friendlyName>小度智能音箱-8432</friendlyName>
<manufacturer>DuerOS</manufacturer>
<modelName>DuerOS-Render</modelName>
<UDN>uuid:6ca6cae6-e861-410b-9e83-f708e4cb89fe</UDN>
<serviceList>
<service>
<serviceType>urn:schemas-upnp-org:service:AVTransport:1</serviceType>
<serviceId>urn:upnp-org:serviceId:AVTransport</serviceId>
<controlURL>/upnp/control/rendertransport1</controlURL>
</service>
<service>
<serviceType>urn:schemas-upnp-org:service:RenderingControl:1</serviceType>
<controlURL>/upnp/control/rendercontrol1</controlURL>
</service>
</serviceList>
</device>
<URLBase>http://192.168.3.47:49494/</URLBase>
</root>
"""

TV_DESC = """<?xml version="1.0"?>
<root xmlns="urn:schemas-upnp-org:device-1-0">
<device>
<friendlyName>客厅电视</friendlyName>
<manufacturer>Xiaomi</manufacturer>
<serviceList><service>
<serviceType>urn:schemas-upnp-org:service:AVTransport:1</serviceType>
<controlURL>/smartshare/render/AVTransport_control</controlURL>
</service></serviceList>
</device>
</root>
"""

SSDP_REPLY = (
    "HTTP/1.1 200 OK\r\n"
    "ST: urn:schemas-upnp-org:device:MediaRenderer:1\r\n"
    "USN: uuid:6ca6cae6-e861-410b-9e83-f708e4cb89fe::urn:schemas-upnp-org:device:MediaRenderer:1\r\n"
    "Location: http://192.168.3.47:49494/description.xml\r\n"
    "SERVER: Linux/4.9.54, UPnP/1.0, Portable SDK for UPnP devices\r\n"
    "\r\n"
).encode("utf-8")


class SsdpTests(unittest.TestCase):
    def test_parses_replies_and_dedupes(self) -> None:
        class FakeSock:
            def __init__(self) -> None:
                self.received = 0
                self.sent: list[tuple[bytes, tuple[str, int]]] = []

            def setsockopt(self, *args: object) -> None:  # noqa: D102
                ...

            def settimeout(self, _t: float) -> None:  # noqa: D102
                ...

            def sendto(self, payload: bytes, addr: tuple[str, int]) -> None:  # noqa: D102
                self.sent.append((payload, addr))

            def recvfrom(self, _n: int):  # noqa: ANN201
                # 同一台设备回两条（真实网络常见）→ 只保留一条
                self.received += 1
                if self.received <= 2:
                    return SSDP_REPLY, ("192.168.3.47", 1900)
                raise socket.timeout()

            def close(self) -> None:  # noqa: D102
                ...

        sock = FakeSock()
        out = ld.ssdp_search(timeout_sec=0.5, socket_fn=lambda: sock)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].ip, "192.168.3.47")
        self.assertEqual(out[0].location, "http://192.168.3.47:49494/description.xml")
        self.assertIn("MediaRenderer", out[0].st)
        self.assertIn(b"M-SEARCH", sock.sent[0][0])
        self.assertIn(b"MAN: \"ssdp:discover\"", sock.sent[0][0])

    def test_multicast_failure_is_explicit(self) -> None:
        class BadSock:
            def setsockopt(self, *args: object) -> None:
                ...

            def settimeout(self, _t: float) -> None:
                ...

            def sendto(self, *_a: object) -> None:
                raise OSError("network is down")

            def close(self) -> None:
                ...

        with self.assertRaises(ld.LanDiscoveryError) as ctx:
            ld.ssdp_search(timeout_sec=0.5, socket_fn=BadSock)
        self.assertIn("SSDP", str(ctx.exception))


class DescriptionTests(unittest.TestCase):
    def test_parses_xiaodu_description(self) -> None:
        d = ld.parse_device_description(XIAODU_DESC, "http://192.168.3.47:49494/description.xml")
        self.assertEqual(d.ip, "192.168.3.47")
        self.assertEqual(d.friendly_name, "小度智能音箱-8432")
        self.assertEqual(d.manufacturer, "DuerOS")
        self.assertEqual(d.model_name, "DuerOS-Render")
        self.assertEqual(d.udn, "uuid:6ca6cae6-e861-410b-9e83-f708e4cb89fe")
        # 相对 controlURL 用 URLBase 拼成绝对地址
        self.assertEqual(
            d.control_url(), "http://192.168.3.47:49494/upnp/control/rendertransport1"
        )
        self.assertIn("dueros", d.identity_text())

    def test_parses_tv_description_without_urlbase(self) -> None:
        d = ld.parse_device_description(TV_DESC, "http://192.168.3.33:49152/description.xml")
        self.assertEqual(
            d.control_url(), "http://192.168.3.33:49152/smartshare/render/AVTransport_control"
        )

    def test_broken_xml_is_explicit(self) -> None:
        with self.assertRaises(ld.LanDiscoveryError) as ctx:
            ld.parse_device_description("<root><device>", "http://x/y.xml")
        self.assertIn("XML", str(ctx.exception))

    def test_description_without_services_is_explicit(self) -> None:
        with self.assertRaises(ld.LanDiscoveryError) as ctx:
            ld.parse_device_description("<root><device></device></root>", "http://x/y.xml")
        self.assertIn("服务", str(ctx.exception))

    def test_fetch_http_error_is_explicit(self) -> None:
        with mock.patch.object(
            ld.urllib.request, "urlopen", side_effect=ld.urllib.error.URLError("boom")
        ):
            with self.assertRaises(ld.LanDiscoveryError) as ctx:
                ld.fetch_device_description("http://192.168.3.47:49494/description.xml")
        self.assertIn("拉取失败", str(ctx.exception))


class LocalAddressTests(unittest.TestCase):
    def test_local_ip_for_uses_route_probe(self) -> None:
        class FakeSock:
            def __init__(self) -> None:
                self.target: tuple[str, int] | None = None

            def connect(self, target: tuple[str, int]) -> None:  # noqa: D102
                self.target = target

            def getsockname(self) -> tuple[str, int]:  # noqa: D102
                return ("192.168.3.84", 51234)

            def close(self) -> None:  # noqa: D102
                ...

        sock = FakeSock()
        with mock.patch.object(ld.socket, "socket", return_value=sock):
            self.assertEqual(ld.local_ip_for("192.168.3.47"), "192.168.3.84")
        self.assertEqual(sock.target, ("192.168.3.47", 9))

    def test_local_ip_for_requires_target(self) -> None:
        with self.assertRaises(ld.LanDiscoveryError):
            ld.local_ip_for("")

    def test_is_local_ip(self) -> None:
        with mock.patch.object(ld, "local_ips", return_value=["192.168.3.84"]):
            self.assertTrue(ld.is_local_ip("192.168.3.84"))
            self.assertFalse(ld.is_local_ip("192.168.3.73"))
            self.assertFalse(ld.is_local_ip(""))

    def test_resolve_public_host_honours_real_local_override(self) -> None:
        with mock.patch.object(ld, "is_local_ip", return_value=True):
            self.assertEqual(
                ld.resolve_public_host("192.168.3.47", "192.168.3.84", what="小度"),
                "192.168.3.84",
            )

    def test_resolve_public_host_ignores_stale_override(self) -> None:
        """写死但过期的本机地址必须被忽略（本机就踩过 .73 → .84 的坑）。"""
        with mock.patch.object(ld, "is_local_ip", return_value=False):
            with mock.patch.object(ld, "local_ips", return_value=["192.168.3.84"]):
                with mock.patch.object(ld, "local_ip_for", return_value="192.168.3.84") as probe:
                    self.assertEqual(
                        ld.resolve_public_host("192.168.3.47", "192.168.3.73", what="小度"),
                        "192.168.3.84",
                    )
        probe.assert_called_once_with("192.168.3.47")

    def test_resolve_public_host_falls_back_without_peer(self) -> None:
        with mock.patch.object(ld, "is_local_ip", return_value=False):
            with mock.patch.object(ld, "lan_host_fallback", return_value="192.168.3.84"):
                self.assertEqual(ld.resolve_public_host(None, "192.168.3.73"), "192.168.3.84")

    def test_local_ips_skips_loopback_and_link_local(self) -> None:
        def fake_ioctl(_fd: int, packed: bytes) -> bytes:
            name = packed.split(b"\x00", 1)[0].decode()
            table = {"lo0": "127.0.0.1", "en0": "192.168.3.84", "en5": "169.254.41.47"}
            ip = table.get(name, "0.0.0.0")
            return packed[:20] + socket.inet_aton(ip) + packed[24:]

        names = [(1, "lo0"), (2, "en0"), (3, "en5")]
        with mock.patch.object(ld.socket, "if_nameindex", return_value=names):
            with mock.patch.object(ld, "_ioctl", side_effect=fake_ioctl):
                self.assertEqual(ld.local_ips(), ["192.168.3.84"])
                self.assertIn("169.254.41.47", ld.local_ips(include_link_local=True))
                self.assertNotIn("127.0.0.1", ld.local_ips(include_link_local=True))



class ProbeTests(unittest.TestCase):
    def test_probe_true_on_2xx(self) -> None:
        url = "http://192.168.3.47:49494/upnp/control/rendertransport1"
        with mock.patch.object(ld, "soap_control", return_value="<ok/>") as post:
            self.assertTrue(ld.probe_av_transport(url))
        self.assertEqual(post.call_args.args[1], "GetTransportInfo")

    def test_probe_false_on_error(self) -> None:
        with mock.patch.object(ld, "soap_control", side_effect=ld.LanDiscoveryError("500")):
            self.assertFalse(ld.probe_av_transport("http://192.168.3.47:49494/x"))

    def test_probe_false_without_url(self) -> None:
        self.assertFalse(ld.probe_av_transport(""))

    def test_soap_control_sets_soapaction_header(self) -> None:
        captured: dict[str, object] = {}

        class FakeResp:
            def read(self) -> bytes:
                return b"<ok/>"

            def __enter__(self) -> "FakeResp":
                return self

            def __exit__(self, *_a: object) -> bool:
                return False

        def fake_urlopen(req, timeout=None):  # noqa: ANN001, ANN202
            captured["url"] = req.full_url
            captured["headers"] = dict(req.headers)
            captured["body"] = req.data
            return FakeResp()

        url = "http://192.168.3.47:49494/upnp/control/rendertransport1"
        with mock.patch.object(ld.urllib.request, "urlopen", side_effect=fake_urlopen):
            out = ld.soap_control(url, "Stop", "")
        self.assertEqual(out, "<ok/>")
        headers = {k.lower(): v for k, v in captured["headers"].items()}  # type: ignore[union-attr]
        self.assertIn("soapaction", headers)
        self.assertIn("Stop", str(headers["soapaction"]))
        self.assertIn(b"Stop", captured["body"])  # type: ignore[operator]


class CacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "xiaodu_renderer.json"

    def test_write_read_drop(self) -> None:
        self.assertIsNone(ld.read_cache(self.path))
        ld.write_cache(self.path, {"ip": "192.168.3.47"})
        data = ld.read_cache(self.path)
        self.assertEqual(data["ip"], "192.168.3.47")
        self.assertIn("saved_at", data)
        ld.drop_cache(self.path)
        self.assertIsNone(ld.read_cache(self.path))

    def test_broken_cache_is_ignored(self) -> None:
        self.path.write_text("{not json", encoding="utf-8")
        self.assertIsNone(ld.read_cache(self.path))
        self.path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        self.assertIsNone(ld.read_cache(self.path))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
