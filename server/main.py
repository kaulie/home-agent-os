#!/usr/bin/env python3
"""Living-room control-center command API (stdlib only).

Chromecast TV client polls:
  GET /api/v1/devices/{device_id}/commands
and acknowledges with:
  POST /api/v1/devices/{device_id}/commands/{command_id}/ack
"""

from __future__ import annotations

import itertools
import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

HOST = "0.0.0.0"
PORT = 8000

ALLOWED_ACTIONS = {
    "launch",
    "play",
    "pause",
    "play_pause",
    "next",
    "previous",
    "stop",
    "play_song",
}
ALLOWED_APPS = {"spotify", "netease"}

_id_counter = itertools.count(1)
_lock = threading.Lock()
_pending: dict[str, list[dict]] = {}
_history: list[dict] = []


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict | list) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(body)


def _read_json(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0"))
    raw = handler.rfile.read(length) if length > 0 else b"{}"
    if not raw:
        return {}
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("JSON body must be an object")
    return data


def _device_queue(device_id: str) -> list[dict]:
    if device_id not in _pending:
        _pending[device_id] = []
    return _pending[device_id]


def _parse_song_artist(song: str | None, artist: str | None) -> tuple[str, str | None]:
    """Accept play_song as song name only, or '歌曲名 歌手' (artist optional)."""
    explicit_artist = (artist or "").strip() or None
    raw = (song or "").strip()
    if explicit_artist or not raw:
        return raw, explicit_artist
    if " " in raw:
        name, _, rest = raw.partition(" ")
        name = name.strip()
        rest = rest.strip()
        if name and rest:
            return name, rest
    return raw, None


def _parse_device_path(path: str) -> tuple[str, str | None] | None:
    """
    Match:
      /api/v1/devices/{device_id}/commands
      /api/v1/devices/{device_id}/commands/{command_id}/ack
      /api/v1/devices/{device_id}/history
    """
    parts = [p for p in path.split("/") if p]
    if len(parts) < 4 or parts[0:3] != ["api", "v1", "devices"]:
        return None
    device_id = parts[3]
    rest = parts[4:]
    if rest == ["commands"]:
        return device_id, None
    if len(rest) == 3 and rest[0] == "commands" and rest[2] == "ack":
        return device_id, rest[1]
    if rest == ["history"]:
        return device_id, "__history__"
    return None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        print(f"[{self.log_date_time_string()}] {self.address_string()} {fmt % args}")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/health":
            _json_response(self, 200, {"status": "ok"})
            return

        matched = _parse_device_path(path)
        if matched is None:
            _json_response(self, 404, {"detail": "not found"})
            return

        device_id, special = matched
        if special == "__history__":
            with _lock:
                items = [h for h in _history if h["device_id"] == device_id]
            _json_response(self, 200, {"history": items[-50:]})
            return

        if special is None:
            with _lock:
                commands = list(_device_queue(device_id))
            _json_response(self, 200, {"commands": commands})
            return

        _json_response(self, 404, {"detail": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        matched = _parse_device_path(path)
        if matched is None:
            _json_response(self, 404, {"detail": "not found"})
            return

        device_id, command_id = matched
        try:
            body = _read_json(self)
        except (ValueError, json.JSONDecodeError) as exc:
            _json_response(self, 400, {"detail": str(exc)})
            return

        if command_id is None:
            action = str(body.get("action", "")).strip()
            app = str(body.get("app", "netease")).strip()
            uri = body.get("uri")
            song = body.get("song")
            artist = body.get("artist")
            if action not in ALLOWED_ACTIONS:
                _json_response(self, 400, {"detail": f"invalid action: {action}"})
                return
            if app not in ALLOWED_APPS:
                _json_response(self, 400, {"detail": f"invalid app: {app}"})
                return
            if uri is not None and not isinstance(uri, str):
                _json_response(self, 400, {"detail": "uri must be a string"})
                return
            if song is not None and not isinstance(song, str):
                _json_response(self, 400, {"detail": "song must be a string"})
                return
            if artist is not None and not isinstance(artist, str):
                _json_response(self, 400, {"detail": "artist must be a string"})
                return
            if action == "play_song":
                if not (isinstance(song, str) and song.strip()) and not (isinstance(uri, str) and uri.strip()):
                    _json_response(self, 400, {"detail": "play_song requires song (歌名；可选: 歌名 歌手)"})
                    return
                if isinstance(song, str) and song.strip():
                    song, artist = _parse_song_artist(song, artist if isinstance(artist, str) else None)

            cmd = {
                "id": f"cmd-{next(_id_counter)}-{uuid.uuid4().hex[:8]}",
                "action": action,
                "app": app,
                "uri": uri,
                "song": song,
                "artist": artist,
                "created_at": time.time(),
            }
            with _lock:
                _device_queue(device_id).append(cmd)
            _json_response(self, 200, cmd)
            return

        if command_id == "__history__":
            _json_response(self, 405, {"detail": "method not allowed"})
            return

        status = str(body.get("status", "")).strip() or "ok"
        message = body.get("message")
        with _lock:
            queue = _device_queue(device_id)
            match = next((c for c in queue if c["id"] == command_id), None)
            if match is None:
                _json_response(self, 404, {"detail": "command not found or already acked"})
                return
            queue.remove(match)
            _history.append(
                {
                    "device_id": device_id,
                    "command": match,
                    "ack": {"status": status, "message": message},
                    "acked_at": time.time(),
                }
            )
            if len(_history) > 200:
                del _history[:-200]
        _json_response(self, 200, {"status": "acked"})

    def do_DELETE(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        matched = _parse_device_path(path)
        if matched is None or matched[1] is not None:
            _json_response(self, 404, {"detail": "not found"})
            return
        device_id, _ = matched
        with _lock:
            n = len(_device_queue(device_id))
            _pending[device_id] = []
        _json_response(self, 200, {"cleared": n})


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Smart Home Control API listening on http://{HOST}:{PORT}", flush=True)
    print("Health: GET /health", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down", flush=True)
        server.server_close()


if __name__ == "__main__":
    main()
