#!/usr/bin/env python3
"""Temporary LAN host for the Kindle intent page. Does not change Brain.

  python3 kindle/serve.py

Kindle / laptop: http://<lan-ip>:8088/?intent_id=<id>
Proxies GET /api/v1/intent_detail and GET /api/v1/assets/*/content to BRAIN_URL.
"""

from __future__ import annotations

import json
import os
import re
import socket
import sys
import threading
from datetime import datetime
from html import escape
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
LOG_PATH = ROOT / "serve.log"
PORT = int((os.environ.get("KINDLE_PAGE_PORT") or "8088").strip() or "8088")
BRAIN_URL = (
    os.environ.get("KINDLE_BRAIN_URL") or "http://127.0.0.1:9527"
).strip().rstrip("/")
_ASSET_CONTENT_RE = re.compile(r"^/api/v1/assets/([^/]+)/content/?$")
_LOG_LOCK = threading.Lock()
_LOG_FP = None


def lan_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.168.3.1", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def _open_log() -> None:
    global _LOG_FP
    _LOG_FP = open(LOG_PATH, "a", encoding="utf-8", buffering=1)


def write_log(text: str) -> None:
    if not text.endswith("\n"):
        text += "\n"
    with _LOG_LOCK:
        if _LOG_FP is not None:
            _LOG_FP.write(text)
            _LOG_FP.flush()
        sys.stdout.write(text)
        sys.stdout.flush()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt: str, *args) -> None:
        write_log("%s - %s" % (self.address_string(), fmt % args))

    def do_GET(self) -> None:
        self._log_client_access()
        parsed = urlparse(self.path)
        if parsed.path in ("/api/v1/intent_detail", "/api/v1/intent_detail/"):
            self._proxy_detail(parsed.query)
            return
        asset_match = _ASSET_CONTENT_RE.match(parsed.path)
        if asset_match:
            self._proxy_asset_content(asset_match.group(1), parsed.query)
            return
        if parsed.path in ("/", "", "/index.html"):
            self._serve_index(parsed.query)
            return
        super().do_GET()

    def do_POST(self) -> None:
        self._log_client_access()
        self._json(405, {"ok": False, "error": "POST not supported"})

    def do_PUT(self) -> None:
        self._log_client_access()
        self._json(405, {"ok": False, "error": "PUT not supported"})

    def do_HEAD(self) -> None:
        self._log_client_access()
        super().do_HEAD()

    def _log_client_access(self) -> None:
        host = (self.headers.get("Host") or "").strip()
        path = self.path or "/"
        if host:
            full_url = "http://%s%s" % (host, path)
        else:
            full_url = path
        ip = self.client_address[0] if self.client_address else ""
        port = self.client_address[1] if self.client_address else ""
        forwarded = (self.headers.get("X-Forwarded-For") or "").strip()
        header_lines = []
        for key, value in self.headers.items():
            header_lines.append("  %s: %s" % (key, value))
        payload = self._read_payload()
        parsed = urlparse(path)
        lines = [
            "----- %s -----" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "ip: %s" % ip,
            "port: %s" % port,
            "forwarded_for: %s" % (forwarded or "-"),
            "method: %s" % self.command,
            "url: %s" % full_url,
            "path: %s" % parsed.path,
            "query: %s" % (parsed.query or "-"),
            "http_version: %s" % self.request_version,
            "headers:",
        ]
        lines.extend(header_lines or ["  (none)"])
        lines.append("payload:")
        lines.append(payload if payload else "  (empty)")
        lines.append("")
        write_log("\n".join(lines))

    def _read_payload(self) -> str:
        raw_len = (self.headers.get("Content-Length") or "").strip()
        if not raw_len:
            return ""
        try:
            length = int(raw_len)
        except ValueError:
            return ""
        if length <= 0:
            return ""
        cap = min(length, 65536)
        try:
            body = self.rfile.read(cap)
        except OSError:
            return "  (read failed)"
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            text = repr(body)
        if length > cap:
            text += "\n  … truncated, content-length=%s" % length
        return text

    def _serve_index(self, query: str) -> None:
        endpoint = (parse_qs(query).get("endpoint") or [""])[0].strip() or "未知"
        ua = (self.headers.get("User-Agent") or self.headers.get("user-agent") or "").strip() or "未知"
        cls = "unknown"
        if endpoint != "未知":
            cls = endpoint.lower()
        if not re.fullmatch(r"[a-z0-9_-]+", cls or ""):
            cls = "unknown"
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        html = (
            html.replace("{{ENDPOINT}}", escape(endpoint, quote=True))
            .replace("{{USER_AGENT}}", escape(ua, quote=True))
            .replace("{{ENDPOINT_CLASS}}", escape(cls, quote=True))
        )
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _proxy_detail(self, query: str) -> None:
        intent_id = (parse_qs(query).get("intent_id") or parse_qs(query).get("id") or [""])[0]
        intent_id = str(intent_id).strip()
        if not intent_id:
            self._json(400, {"ok": False, "error": "intent_id is required"})
            return
        url = f"{BRAIN_URL}/api/v1/intent_detail?intent_id={intent_id}"
        req = Request(url, method="GET")
        try:
            with urlopen(req, timeout=20) as resp:
                body = resp.read()
                status = getattr(resp, "status", 200)
                ctype = resp.headers.get("Content-Type") or "application/json; charset=utf-8"
        except HTTPError as exc:
            body = exc.read() or json.dumps({"ok": False, "error": str(exc)}).encode("utf-8")
            status = exc.code
            ctype = "application/json; charset=utf-8"
        except URLError as exc:
            self._json(502, {"ok": False, "error": f"brain unreachable: {exc.reason}"})
            return
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _proxy_asset_content(self, asset_id: str, query: str) -> None:
        intent_id = (parse_qs(query).get("intent_id") or [""])[0]
        intent_id = str(intent_id).strip()
        if not intent_id:
            self._json(400, {"ok": False, "error": "intent_id is required"})
            return
        extra = parse_qs(query)
        rep = (extra.get("representation") or [""])[0]
        rep = str(rep).strip()
        qs_parts = ["intent_id=" + intent_id]
        if rep:
            qs_parts.append("representation=" + rep)
        url = "%s/api/v1/assets/%s/content?%s" % (
            BRAIN_URL,
            asset_id,
            "&".join(qs_parts),
        )
        req = Request(url, method="GET")
        try:
            resp = urlopen(req, timeout=30)
        except HTTPError as exc:
            body = exc.read() or json.dumps({"ok": False, "error": str(exc)}).encode("utf-8")
            self.send_response(exc.code)
            self.send_header("Content-Type", exc.headers.get("Content-Type") or "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        except URLError as exc:
            self._json(502, {"ok": False, "error": "brain unreachable: %s" % exc.reason})
            return
        status = getattr(resp, "status", 200)
        ctype = resp.headers.get("Content-Type") or "application/octet-stream"
        clen = resp.headers.get("Content-Length")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        if clen:
            self.send_header("Content-Length", clen)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)
        finally:
            resp.close()

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    os.chdir(ROOT)
    _open_log()
    httpd = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    ip = lan_ip()
    write_log("Kindle page  http://%s:%s/?intent_id=<id>" % (ip, PORT))
    write_log("Brain proxy  %s/api/v1/intent_detail" % BRAIN_URL)
    write_log("Asset stream %s/api/v1/assets/{id}/content" % BRAIN_URL)
    write_log("access log   %s" % LOG_PATH)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
