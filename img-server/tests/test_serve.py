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
        serve.PUBLIC_BASE = "http://192.168.3.73:8080"
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
        self.assertEqual(data["url"], f"http://192.168.3.73:8080/{saved}")

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


if __name__ == "__main__":
    unittest.main()
