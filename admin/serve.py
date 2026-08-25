#!/usr/bin/env python3
"""Local-only Home Agent admin page. Not Brain. Do not deploy to cloud.

  python3 admin/serve.py
  open http://127.0.0.1:8788/

Proxies /api/v1/admin/* to BRAIN_URL (default http://127.0.0.1:9527).
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
HOST = (os.environ.get("ADMIN_HOST") or "127.0.0.1").strip() or "127.0.0.1"
PORT = int((os.environ.get("ADMIN_PORT") or "8788").strip() or "8788")
BRAIN_URL = (os.environ.get("BRAIN_URL") or "http://127.0.0.1:9527").strip().rstrip("/")


def _json_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


class AdminHandler(BaseHTTPRequestHandler):
    server_version = "HomeAdmin/1"

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.log_date_time_string(), fmt % args))

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path in ("/", "/admin"):
            page = STATIC_DIR / "index.html"
            if not page.is_file():
                self._send(404, _json_bytes({"error": "admin page missing"}), "application/json; charset=utf-8")
                return
            self._send(200, page.read_bytes(), "text/html; charset=utf-8")
            return
        if path == "/api/v1/admin/local_config":
            self._send(
                200,
                _json_bytes({"ok": True, "brain": BRAIN_URL, "local": True}),
                "application/json; charset=utf-8",
            )
            return
        if path.startswith("/api/v1/admin/"):
            self._proxy()
            return
        self._send(404, _json_bytes({"error": "not found"}), "application/json; charset=utf-8")

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path.startswith("/api/v1/admin/"):
            self._proxy()
            return
        self._send(404, _json_bytes({"error": "not found"}), "application/json; charset=utf-8")

    def do_PUT(self) -> None:  # noqa: N802
        self.do_POST()

    def _proxy(self) -> None:
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/v1/admin/"):
            self._send(404, _json_bytes({"error": "not found"}), "application/json; charset=utf-8")
            return
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length > 0 else b""
        url = BRAIN_URL + parsed.path
        if parsed.query:
            url += "?" + parsed.query
        headers = {"Content-Type": self.headers.get("Content-Type") or "application/json"}
        token = (self.headers.get("X-Admin-Token") or "").strip()
        if token:
            headers["X-Admin-Token"] = token
        auth = (self.headers.get("Authorization") or "").strip()
        if auth:
            headers["Authorization"] = auth
        req = Request(url, data=raw or None, headers=headers, method=self.command)
        try:
            with urlopen(req, timeout=20) as resp:
                body = resp.read()
                content_type = resp.headers.get("Content-Type") or "application/json; charset=utf-8"
                self._send(resp.status, body, content_type)
        except HTTPError as exc:
            body = exc.read() or _json_bytes({"error": str(exc.reason)})
            content_type = exc.headers.get("Content-Type") if exc.headers else "application/json; charset=utf-8"
            self._send(exc.code, body, content_type or "application/json; charset=utf-8")
        except URLError as exc:
            self._send(
                502,
                _json_bytes({"error": f"brain unreachable: {exc.reason}", "brain": BRAIN_URL}),
                "application/json; charset=utf-8",
            )


def main() -> None:
    httpd = ThreadingHTTPServer((HOST, PORT), AdminHandler)
    sys.stderr.write("home admin http://%s:%s/  brain=%s\n" % (HOST, PORT, BRAIN_URL))
    httpd.serve_forever()


if __name__ == "__main__":
    main()
