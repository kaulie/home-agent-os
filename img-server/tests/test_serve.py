"""img-server HTTP protocol (stdlib, not a capability)."""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import serve  # noqa: E402


class ImgServerHTTPTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.img_dir = Path(self._tmp.name) / "img"
        self.img_dir.mkdir()
        serve.UPLOAD_DIR = self.img_dir
        # Any valid URL shape works here; only the response body echoes it back.
        serve.PUBLIC_BASE = "http://192.168.0.88:8080"
        serve.HOST = "127.0.0.1"
        serve.PORT = 0
        self.server = serve.ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
        self.port = int(self.server.server_address[1])
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        time.sleep(0.05)

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self._tmp.cleanup()

    def _get(self, path: str) -> tuple[int, bytes, str]:
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request("GET", path)
            resp = conn.getresponse()
            body = resp.read()
            ctype = resp.getheader("Content-Type") or ""
            return resp.status, body, ctype
        finally:
            conn.close()

    def test_health(self) -> None:
        status, body, ctype = self._get("/health")
        self.assertEqual(status, 200)
        self.assertIn("json", ctype)
        data = json.loads(body.decode())
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("capability"), False)
        self.assertEqual(data.get("service"), "img-server")

    def test_upload_and_static(self) -> None:
        payload = b"\xff\xd8fake-jpeg"
        boundary = "----ImgTestBoundary"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="a.jpg"\r\n'
            "Content-Type: image/jpeg\r\n\r\n"
        ).encode() + payload + f"\r\n--{boundary}--\r\n".encode()
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request(
                "POST",
                "/api/v1/photos/upload",
                body=body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            )
            resp = conn.getresponse()
            raw = resp.read()
            self.assertEqual(resp.status, 200, raw[:200])
            data = json.loads(raw.decode())
        finally:
            conn.close()
        self.assertTrue(data.get("ok"))
        saved = data["saved_as"]
        self.assertTrue(saved.endswith("_a.jpg") or saved.endswith("a.jpg"))
        self.assertEqual(data["url"], f"{serve.PUBLIC_BASE}/{saved}")

        status, got, ctype = self._get(f"/{saved}")
        self.assertEqual(status, 200)
        self.assertEqual(got, payload)
        self.assertIn("image", ctype)

        status, got, _ = self._get(f"/img/{saved}")
        self.assertEqual(status, 200)
        self.assertEqual(got, payload)

        status, got, _ = self._get("/latest")
        self.assertEqual(status, 200)
        self.assertEqual(got, payload)


class LanPublicBaseTests(unittest.TestCase):
    def test_guess_uses_auto_detected_ip(self) -> None:
        with patch("serve._detect_lan_ipv4", return_value="192.168.3.96"):
            self.assertEqual(
                serve.guess_lan_public_base(8080), "http://192.168.3.96:8080"
            )

    def test_guess_never_returns_stale_fixed_lan_ip(self) -> None:
        base = serve.guess_lan_public_base(8080)
        self.assertNotIn("192.168.3.73", base)

    def test_detect_uses_udp_route(self) -> None:
        class FakeSocket:
            def __init__(self, *_a, **_k) -> None:
                self._ip = None

            def connect(self, _target) -> None:
                self._ip = "192.168.3.96"

            def getsockname(self) -> tuple[str, int]:
                return (self._ip or "0.0.0.0", 0)

            def close(self) -> None:
                pass

        with patch("serve.socket.socket", return_value=FakeSocket()):
            self.assertEqual(serve._detect_lan_ipv4(), "192.168.3.96")

    def test_detect_falls_back_to_ifconfig(self) -> None:
        class FakeFailingSocket:
            def __init__(self, *_a, **_k) -> None:
                pass

            def connect(self, _target) -> None:
                raise OSError("no route to host")

            def getsockname(self) -> tuple[str, int]:
                return ("0.0.0.0", 0)

            def close(self) -> None:
                pass

        from types import SimpleNamespace

        ifconfig_out = (
            "lo0: flags=8049<UP,LOOPBACK,RUNNING> mtu 16384\n"
            "\tinet 127.0.0.1 netmask 0xff000000\n"
            "en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX> mtu 1500\n"
            "\tinet 192.168.3.96 netmask 0xffffff00 broadcast 192.168.3.255\n"
        )
        with patch(
            "serve.socket.socket", return_value=FakeFailingSocket()
        ), patch("serve.socket.getaddrinfo", return_value=[]), patch(
            "subprocess.run",
            return_value=SimpleNamespace(stdout=ifconfig_out, stderr=""),
        ):
            self.assertEqual(serve._detect_lan_ipv4(), "192.168.3.96")

    def test_detect_falls_back_to_hostname_then_loopback(self) -> None:
        class FakeFailingSocket:
            def __init__(self, *_a, **_k) -> None:
                pass

            def connect(self, _target) -> None:
                raise OSError("no route to host")

            def getsockname(self) -> tuple[str, int]:
                return ("0.0.0.0", 0)

            def close(self) -> None:
                pass

        import socket as _socket

        addrinfo = [
            (_socket.AF_INET, _socket.SOCK_STREAM, 6, "", ("192.168.3.96", 0)),
        ]
        with patch(
            "serve.socket.socket", return_value=FakeFailingSocket()
        ), patch("serve.socket.getaddrinfo", return_value=addrinfo):
            self.assertEqual(serve._detect_lan_ipv4(), "192.168.3.96")

        with patch(
            "serve.socket.socket", return_value=FakeFailingSocket()
        ), patch(
            "serve.socket.getaddrinfo", side_effect=OSError("no such host")
        ), patch("subprocess.run", side_effect=OSError("no ifconfig")):
            self.assertEqual(serve._detect_lan_ipv4(), "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
