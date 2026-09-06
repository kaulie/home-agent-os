"""img_server locator: prefer original key, fallback to preview."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from mac_edge.asset.backends.img_server import (
    brain_content_http_url,
    default_lan_public_base,
    detect_lan_ipv4,
    http_url_from_storage,
    lan_facing_brain_base,
)
from mac_edge.asset.types import AssetStorageError


class ImgServerResolveTests(unittest.TestCase):
    def test_prefers_original_key(self) -> None:
        # A stored private-LAN public_base is DHCP-volatile and possibly stale,
        # so the current LAN base is resolved at use time instead.
        with patch.dict(
            os.environ,
            {"MAC_EDGE_LAN_PUBLIC_BASE": "http://192.168.3.96:8080"},
            clear=False,
        ):
            rep = http_url_from_storage(
                {
                    "backend": "img_server",
                    "key": "orig.jpg",
                    "preview_key": "prev.jpg",
                    "public_base": "http://192.168.3.65:8080",
                }
            )
        self.assertEqual(rep.url, "http://192.168.3.96:8080/orig.jpg")

    def test_fallback_preview_when_original_pending(self) -> None:
        rep = http_url_from_storage(
            {
                "backend": "img_server",
                "preview_key": "56a6b3fa_preview.JPG",
                "cloud_preview_key": "56a6b3fa_preview.JPG",
                "public_base": "http://115.190.153.53:8080",
                "cloud_public_base": "http://115.190.153.53:8080",
            }
        )
        self.assertEqual(
            rep.url, "http://115.190.153.53:8080/56a6b3fa_preview.JPG"
        )

    def test_cloud_key_when_lan_key_absent(self) -> None:
        rep = http_url_from_storage(
            {
                "backend": "img_server",
                "cloud_key": "cloud_orig.jpg",
                "cloud_preview_key": "cloud_prev.jpg",
                "cloud_public_base": "http://115.190.153.53:8080",
            }
        )
        self.assertEqual(rep.url, "http://115.190.153.53:8080/cloud_orig.jpg")

    def test_missing_all_keys_fails(self) -> None:
        with self.assertRaises(AssetStorageError) as ctx:
            http_url_from_storage({"backend": "img_server", "public_base": "http://x"})
        self.assertIn("missing key", str(ctx.exception))

    def test_percent_encodes_non_ascii_keys(self) -> None:
        """id=641: Chinese PDF keys must be quoted for urllib on Mac Edge."""
        with patch.dict(
            os.environ,
            {"MAC_EDGE_LAN_PUBLIC_BASE": "http://192.168.3.96:8080"},
            clear=False,
        ):
            rep = http_url_from_storage(
                {
                    "backend": "img_server",
                    "key": "f1103a10_当前Agent编排平台现状分析和创业空间.pdf",
                    "public_base": "http://192.168.3.65:8080",
                }
            )
        self.assertIn("%E5%BD%93%E5%89%8D", rep.url)
        self.assertNotIn("当前", rep.url)
        self.assertTrue(rep.url.startswith("http://192.168.3.96:8080/f1103a10_"))

    def test_lan_facing_brain_rewrites_loopback(self) -> None:
        with patch.dict(
            os.environ,
            {"MAC_EDGE_LAN_PUBLIC_BASE": "http://192.168.3.96:8080"},
            clear=False,
        ):
            self.assertEqual(
                lan_facing_brain_base("http://127.0.0.1:9527"),
                "http://192.168.3.96:9527",
            )
        # An already-LAN brain base is returned unchanged (host is not loopback).
        self.assertEqual(
            lan_facing_brain_base("http://192.168.3.96:9527"),
            "http://192.168.3.96:9527",
        )

    def test_lan_facing_brain_uses_auto_detected_host(self) -> None:
        with patch(
            "mac_edge.asset.backends.img_server.default_lan_public_base",
            return_value="http://192.168.3.96:8080",
        ):
            self.assertEqual(
                lan_facing_brain_base("http://127.0.0.1:9527"),
                "http://192.168.3.96:9527",
            )

    def test_brain_content_http_url(self) -> None:
        with patch.dict(
            os.environ,
            {"MAC_EDGE_LAN_PUBLIC_BASE": "http://192.168.3.96:8080"},
            clear=False,
        ):
            url = brain_content_http_url(
                "http://127.0.0.1:9527",
                "asset_4747c813a26f8ba5d1a99a28",
                "168",
            )
        self.assertEqual(
            url,
            "http://192.168.3.96:9527/api/v1/assets/"
            "asset_4747c813a26f8ba5d1a99a28/content"
            "?intent_id=168&representation=original",
        )


class LanPublicBaseTests(unittest.TestCase):
    def test_default_lan_public_base_shape(self) -> None:
        base = default_lan_public_base()
        self.assertTrue(base.startswith("http://"))
        self.assertTrue(base.endswith(":8080"))
        self.assertNotIn("192.168.3.73", base)

    def test_detect_lan_ipv4_uses_udp_route(self) -> None:
        class FakeSocket:
            def __init__(self, *_a, **_k) -> None:
                self._ip = None

            def connect(self, _target) -> None:
                self._ip = "192.168.3.96"

            def getsockname(self) -> tuple[str, int]:
                return (self._ip or "0.0.0.0", 0)

            def close(self) -> None:
                pass

        with patch(
            "mac_edge.asset.backends.img_server.socket.socket",
            return_value=FakeSocket(),
        ):
            self.assertEqual(detect_lan_ipv4(), "192.168.3.96")

    def test_detect_lan_ipv4_ifconfig_fallback(self) -> None:
        from types import SimpleNamespace

        class FakeFailingSocket:
            def __init__(self, *_a, **_k) -> None:
                pass

            def connect(self, _target) -> None:
                raise OSError("no route to host")

            def getsockname(self) -> tuple[str, int]:
                return ("0.0.0.0", 0)

            def close(self) -> None:
                pass

        ifconfig_out = (
            "lo0: flags=8049<UP,LOOPBACK,RUNNING> mtu 16384\n"
            "\tinet 127.0.0.1 netmask 0xff000000\n"
            "en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX> mtu 1500\n"
            "\tinet 192.168.3.96 netmask 0xffffff00 broadcast 192.168.3.255\n"
        )
        with patch(
            "mac_edge.asset.backends.img_server.socket.socket",
            return_value=FakeFailingSocket(),
        ), patch(
            "mac_edge.asset.backends.img_server.socket.getaddrinfo", return_value=[]
        ), patch(
            "subprocess.run",
            return_value=SimpleNamespace(stdout=ifconfig_out, stderr=""),
        ):
            self.assertEqual(detect_lan_ipv4(), "192.168.3.96")

    def test_detect_lan_ipv4_hostname_fallback(self) -> None:
        import socket as _socket

        class FakeFailingSocket:
            def __init__(self, *_a, **_k) -> None:
                pass

            def connect(self, _target) -> None:
                raise OSError("no route to host")

            def getsockname(self) -> tuple[str, int]:
                return ("0.0.0.0", 0)

            def close(self) -> None:
                pass

        addrinfo = [
            (_socket.AF_INET, _socket.SOCK_STREAM, 6, "", ("192.168.3.96", 0)),
        ]
        with patch(
            "mac_edge.asset.backends.img_server.socket.socket",
            return_value=FakeFailingSocket(),
        ), patch(
            "mac_edge.asset.backends.img_server.socket.getaddrinfo",
            return_value=addrinfo,
        ):
            self.assertEqual(detect_lan_ipv4(), "192.168.3.96")

    def test_detect_lan_ipv4_last_resort_loopback(self) -> None:
        class FakeFailingSocket:
            def __init__(self, *_a, **_k) -> None:
                pass

            def connect(self, _target) -> None:
                raise OSError("no route to host")

            def getsockname(self) -> tuple[str, int]:
                return ("0.0.0.0", 0)

            def close(self) -> None:
                pass

        with patch(
            "mac_edge.asset.backends.img_server.socket.socket",
            return_value=FakeFailingSocket(),
        ), patch(
            "mac_edge.asset.backends.img_server.socket.getaddrinfo",
            side_effect=OSError("no such host"),
        ), patch("subprocess.run", side_effect=OSError("no ifconfig")):
            self.assertEqual(detect_lan_ipv4(), "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
