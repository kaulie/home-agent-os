#!/usr/bin/env python3
"""LAN host for 接金币 (coin-catcher). Chromecast loads the printed LAN URL.

  python3 games/coin-catcher/serve.py

Real-time commands (GameCommand):
  curl -s -X POST http://<lan-ip>:8102/command \\
    -H 'Content-Type: application/json' \\
    -d '{"type":"START","source":"VOICE","timestamp":1730000000123}'

SSE stream: GET /events/stream
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
DIST = ROOT / "dist"
SERVE_ROOT = DIST if DIST.is_dir() and (DIST / "index.html").is_file() else ROOT
PORT = int((os.environ.get("COIN_CATCHER_GAME_PORT") or "8102").strip() or "8102")
_CLIENTS: list[Queue] = []
_EVENTS: list[dict] = []
_NEXT_ID = 1
_LOCK = threading.Lock()
_MAX_EVENTS = 500
_STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".json": "application/json; charset=utf-8",
    ".map": "application/json; charset=utf-8",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
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


def normalize_command(raw: dict) -> dict | None:
    inner = raw.get("command") if isinstance(raw.get("command"), dict) else raw
    if not isinstance(inner, dict):
        return None
    cmd_type = str(inner.get("type") or "").strip().upper()
    valid = {
        "START", "PAUSE", "RESUME", "RESTART",
        "MOVE_LEFT", "MOVE_RIGHT", "JUMP", "SPEED_UP", "SPEED_DOWN",
    }
    if cmd_type not in valid:
        return None
    source = str(inner.get("source") or "SYSTEM").strip().upper()
    if source not in ("VOICE", "GESTURE", "SYSTEM"):
        source = "SYSTEM"
    ts = inner.get("timestamp")
    if ts is None:
        ts = int(time.time() * 1000)
    return {"type": cmd_type, "source": source, "timestamp": int(ts)}


def append_event(event: dict) -> dict:
    global _NEXT_ID
    stored = dict(event)
    with _LOCK:
        stored["id"] = _NEXT_ID
        _NEXT_ID += 1
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
            html = (SERVE_ROOT / "index.html").read_bytes()
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

    def _resolve_static(self, path: str) -> Path | None:
        name = (path or "").lstrip("/")
        if not name or ".." in name or name.startswith("/"):
            return None
        fp = (SERVE_ROOT / name).resolve()
        try:
            fp.relative_to(SERVE_ROOT.resolve())
        except ValueError:
            return None
        if not fp.is_file():
            return None
        return fp

    def _static_file(self, path: str):
        fp = self._resolve_static(path)
        if fp is None:
            return None
        suffix = fp.suffix.lower()
        ctype = _STATIC_TYPES.get(suffix, "application/octet-stream")
        return fp.read_bytes(), ctype

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path not in ("/command", "/command/", "/action", "/action/"):
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        parsed: dict = {}
        if raw.strip():
            try:
                obj = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                obj = None
            if isinstance(obj, dict):
                parsed = obj
        cmd = normalize_command(parsed)
        if cmd is None:
            body = json.dumps({"ok": False, "error": "invalid GameCommand"}, ensure_ascii=False).encode("utf-8")
            self.send_response(400)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self._cors()
            self.end_headers()
            self.wfile.write(body)
            return
        stored = append_event(cmd)
        body = json.dumps({"ok": True, "command": stored}, ensure_ascii=False).encode("utf-8")
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
        payload = json.dumps({"events": items, "latest_id": lid}, ensure_ascii=False).encode("utf-8")
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
    print("接金币 coin-catcher")
    print("  root   %s" % SERVE_ROOT)
    print("  local  http://127.0.0.1:%s/" % PORT)
    print("  Cast   http://%s:%s/" % (ip, PORT))
    print("  SSE    http://%s:%s/events/stream" % (ip, PORT))
    print("  POST   http://%s:%s/command" % (ip, PORT))
    httpd.serve_forever()


if __name__ == "__main__":
    main()
