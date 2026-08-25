#!/usr/bin/env python3
"""LAN host for 小花的下雨天. Chromecast must use the printed LAN URL.

  python3 games/rainypig/serve.py

Page polls GET /events every 5s. Switch to the live stream later with ?stream=1.

  curl -s -X POST http://<lan-ip>:8100/splash
  curl -s -X POST http://<lan-ip>:8100/punch
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from queue import Empty, Queue
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
PORT = int((os.environ.get("RAINYPIG_GAME_PORT") or "8100").strip() or "8100")
_CLIENTS: list[Queue] = []
_EVENTS: list[dict] = []
_NEXT_ID = 1
_LOCK = threading.Lock()
_MAX_EVENTS = 200
_STATIC_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}
_POST_PATHS = {
    "/punch", "/punch/", "/action", "/action/",
    "/splash", "/splash/", "/wave", "/wave/",
}


def lan_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.168.3.1", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def latest_id() -> int:
    return _EVENTS[-1]["id"] if _EVENTS else 0


def append_event(event: dict) -> dict:
    global _NEXT_ID
    stored = dict(event)
    with _LOCK:
        stored["id"] = _NEXT_ID
        _NEXT_ID += 1
        if "ts" not in stored:
            stored["ts"] = int(time.time() * 1000)
        _EVENTS.append(stored)
        del _EVENTS[:-_MAX_EVENTS]
        targets = list(_CLIENTS)
    payload = "data: " + json.dumps(stored, ensure_ascii=False) + "\n\n"
    for q in targets:
        q.put(payload)
    return stored


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        sys.stdout.write("%s - %s\n" % (self.address_string(), fmt % args))
        sys.stdout.flush()

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ("/", "", "/index.html"):
            html = (ROOT / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(html)))
            self._cors()
            self.end_headers()
            self.wfile.write(html)
            return
        if path in ("/events", "/events/"):
            self._poll_events(parsed.query)
            return
        if path in ("/events/stream", "/events/stream/"):
            self._sse()
            return
        static = self._static_file(path)
        if static is not None:
            data, ctype = static
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self._cors()
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_response(404)
        self.end_headers()

    def _static_file(self, path: str):
        name = (path or "").lstrip("/")
        if not name or "/" in name or "\\" in name or ".." in name:
            return None
        suffix = Path(name).suffix.lower()
        ctype = _STATIC_TYPES.get(suffix)
        if not ctype:
            return None
        fp = (ROOT / name).resolve()
        if fp.parent != ROOT.resolve() or not fp.is_file():
            return None
        return fp.read_bytes(), ctype

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path not in _POST_PATHS:
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        event: dict = {"type": "splash", "ts": int(time.time() * 1000)}
        if raw.strip():
            try:
                parsed = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                parsed = None
            if isinstance(parsed, dict):
                event.update(parsed)
            if not event.get("type"):
                event["type"] = "splash"
            if "ts" not in event:
                event["ts"] = int(time.time() * 1000)
        stored = append_event(event)
        body = json.dumps({"ok": True, "event": stored}, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _poll_events(self, query: str) -> None:
        qs = parse_qs(query or "")
        raw_since = (qs.get("since") or [None])[0]
        with _LOCK:
            if raw_since is None or str(raw_since).strip() == "":
                items: list[dict] = []
            else:
                try:
                    since = int(raw_since)
                except (TypeError, ValueError):
                    since = 0
                items = [dict(ev) for ev in _EVENTS if int(ev["id"]) > since]
            lid = latest_id()
        payload = json.dumps(
            {"events": items, "latest_id": lid},
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self._cors()
        self.end_headers()
        self.wfile.write(payload)

    def _sse(self) -> None:
        q: Queue = Queue()
        with _LOCK:
            _CLIENTS.append(q)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self._cors()
        self.end_headers()
        try:
            self.wfile.write(b":ok\n\n")
            self.wfile.flush()
            while True:
                try:
                    chunk = q.get(timeout=15)
                    self.wfile.write(chunk.encode("utf-8"))
                    self.wfile.flush()
                except Empty:
                    self.wfile.write(b":ping\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
            pass
        finally:
            with _LOCK:
                if q in _CLIENTS:
                    _CLIENTS.remove(q)


def main() -> None:
    host = "0.0.0.0"
    httpd = ThreadingHTTPServer((host, PORT), Handler)
    ip = lan_ip()
    print("小花的下雨天")
    print("  local  http://127.0.0.1:%s/" % PORT)
    print("  Cast   http://%s:%s/" % (ip, PORT))
    print("  events GET  http://%s:%s/events?since=<id>" % (ip, PORT))
    print("  splash POST http://%s:%s/splash" % (ip, PORT))
    print("  demo   http://%s:%s/?demo=1" % (ip, PORT))
    httpd.serve_forever()


if __name__ == "__main__":
    main()
