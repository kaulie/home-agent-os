"""LAN MPEG-TS ingest for video.live_stream (Console + Larix Broadcaster).

Control HTTP (default :8790, LAN only):
  POST /api/v1/video-live/prepare
  GET  /api/v1/video-live/status?stream_id=
  POST /api/v1/video-live/stop

Media: MPEG-TS over TCP. prepare() opens a short-lived listen port.
A standing Larix port (default 5004) accepts the same TS without prepare.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import shutil
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

log = logging.getLogger("mac_edge.video_live_ingest")

DEFAULT_HTTP_PORT = 8790
DEFAULT_LARIX_PORT = 5004
CAPABILITY_ID = "video.live_stream"
TRANSPORT = "mpegts_tcp"
ENCODING = "h264"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def lan_ipv4() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def _new_stream_id() -> str:
    return "video_stream_" + secrets.token_hex(4)


def _parse_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length") or "0")
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    if not raw:
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


class StreamSession:
    def __init__(
        self,
        *,
        stream_id: str,
        source: str,
        listen_host: str,
        listen_port: int,
        dump_path: Path,
        preview: bool,
    ) -> None:
        self.stream_id = stream_id
        self.source = source
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.dump_path = dump_path
        self.preview = preview
        self.started_at = time.time()
        self.bytes_received = 0
        self.status = "starting"
        self.error: str | None = None
        self.endpoint = f"tcp://{lan_ipv4()}:{listen_port}"
        self._stop = threading.Event()
        self._sock: socket.socket | None = None
        self._ffplay: subprocess.Popen[bytes] | None = None
        self._viewer_opened = False
        self._thread = threading.Thread(
            target=self._run,
            name=f"video-live-{stream_id}",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        if self._ffplay is not None:
            try:
                self._ffplay.terminate()
            except OSError:
                pass
        self.status = "idle"

    def snapshot(self) -> dict[str, Any]:
        return {
            "stream_id": self.stream_id,
            "capability_id": CAPABILITY_ID,
            "input_type": "video",
            "encoding": ENCODING,
            "transport": TRANSPORT,
            "source": self.source,
            "status": self.status,
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.started_at)),
            "endpoint": self.endpoint,
            "bytes_received": self.bytes_received,
            "error": self.error,
        }

    def _run(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(1.0)
        try:
            sock.bind((self.listen_host, self.listen_port))
            sock.listen(1)
            self._sock = sock
            self.status = "listening"
            log.info(
                "MPEG-TS listen stream_id=%s source=%s %s",
                self.stream_id,
                self.source,
                self.endpoint,
            )
            while not self._stop.is_set():
                try:
                    conn, addr = sock.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                self._recv(conn, addr)
                if self.source != "larix":
                    break
        except OSError as e:
            self.status = "error"
            self.error = str(e)
            log.exception("ingest listen failed stream_id=%s", self.stream_id)
        finally:
            try:
                sock.close()
            except OSError:
                pass
            if self.status not in ("error",):
                self.status = "idle"

    def _recv(self, conn: socket.socket, addr: tuple[str, int]) -> None:
        self.status = "streaming"
        log.info("ingest connected stream_id=%s from=%s", self.stream_id, addr)
        self.dump_path.parent.mkdir(parents=True, exist_ok=True)
        ffplay_bin = shutil.which("ffplay")
        if self.preview and ffplay_bin:
            try:
                self._ffplay = subprocess.Popen(
                    [
                        ffplay_bin,
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-fflags",
                        "nobuffer",
                        "-flags",
                        "low_delay",
                        "-alwaysontop",
                        "-left",
                        "80",
                        "-top",
                        "80",
                        "-x",
                        "960",
                        "-y",
                        "540",
                        "-f",
                        "mpegts",
                        "-i",
                        "pipe:0",
                        "-window_title",
                        f"HomeAgent {self.stream_id}",
                    ],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except OSError:
                self._ffplay = None
            if self._ffplay is not None and self._ffplay.stdin is not None:
                try:
                    os.set_blocking(self._ffplay.stdin.fileno(), False)
                except OSError:
                    pass
        try:
            with conn, self.dump_path.open("ab") as dump:
                conn.settimeout(1.0)
                while not self._stop.is_set():
                    try:
                        chunk = conn.recv(64 * 1024)
                    except socket.timeout:
                        continue
                    except OSError:
                        break
                    if not chunk:
                        break
                    self.bytes_received += len(chunk)
                    dump.write(chunk)
                    dump.flush()
                    self._maybe_open_viewer()
                    stdin = self._ffplay.stdin if self._ffplay is not None else None
                    if stdin is not None:
                        try:
                            stdin.write(chunk)
                        except BlockingIOError:
                            pass
                        except BrokenPipeError:
                            self._ffplay = None
        finally:
            if self._ffplay is not None:
                try:
                    if self._ffplay.stdin is not None:
                        self._ffplay.stdin.close()
                    self._ffplay.terminate()
                except OSError:
                    pass
                self._ffplay = None
            if self.source == "larix" and not self._stop.is_set():
                self.status = "listening"
            else:
                self.status = "idle"
            log.info(
                "ingest closed stream_id=%s bytes=%s",
                self.stream_id,
                self.bytes_received,
            )

    def _maybe_open_viewer(self) -> None:
        if self._viewer_opened or not self.preview:
            return
        if self._ffplay is not None:
            self._viewer_opened = True
            return
        # Wait for a real GOP, not the first 64KB (QuickTime would flash one frame and freeze).
        if self.bytes_received < 512 * 1024:
            return
        self._viewer_opened = True
        ffplay_bin = shutil.which("ffplay")
        if ffplay_bin:
            try:
                subprocess.Popen(
                    [
                        ffplay_bin,
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-follow",
                        "1",
                        "-fflags",
                        "nobuffer+discardcorrupt+genpts",
                        "-framedrop",
                        "-alwaysontop",
                        "-left",
                        "80",
                        "-top",
                        "80",
                        "-x",
                        "960",
                        "-y",
                        "540",
                        "-window_title",
                        f"HomeAgent {self.stream_id}",
                        str(self.dump_path),
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                log.info("ffplay -follow %s", self.dump_path)
                return
            except OSError:
                pass
        log.info("preview: install ffmpeg (ffplay) or run ./preview_video_live.sh after Stop")


class VideoLiveIngestServer:
    def __init__(
        self,
        *,
        data_dir: Path,
        http_host: str = "0.0.0.0",
        http_port: int = DEFAULT_HTTP_PORT,
        larix_port: int = DEFAULT_LARIX_PORT,
        preview: bool = False,
        enable_larix: bool = True,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.http_host = http_host
        self.http_port = int(http_port)
        self.larix_port = int(larix_port)
        self.preview = preview
        self.enable_larix = enable_larix
        self._lock = threading.Lock()
        self._sessions: dict[str, StreamSession] = {}
        self._httpd: ThreadingHTTPServer | None = None
        self._http_thread: threading.Thread | None = None
        self._larix: StreamSession | None = None

    @classmethod
    def from_env(cls, data_dir: Path) -> VideoLiveIngestServer | None:
        if not _env_bool("MAC_EDGE_VIDEO_INGEST", True):
            log.info("video live ingest off (MAC_EDGE_VIDEO_INGEST=0)")
            return None
        http_port = int(os.environ.get("MAC_EDGE_VIDEO_INGEST_HTTP_PORT") or DEFAULT_HTTP_PORT)
        larix_port = int(os.environ.get("MAC_EDGE_VIDEO_INGEST_LARIX_PORT") or DEFAULT_LARIX_PORT)
        preview = _env_bool("MAC_EDGE_VIDEO_INGEST_PREVIEW", False)
        return cls(
            data_dir=data_dir,
            http_port=http_port,
            larix_port=larix_port,
            preview=preview,
        )

    @property
    def dump_dir(self) -> Path:
        return self.data_dir / "video-live"

    def start(self) -> None:
        handler = self._make_handler()
        httpd = ThreadingHTTPServer((self.http_host, self.http_port), handler)
        self.http_port = int(httpd.server_address[1])
        self._httpd = httpd
        self._http_thread = threading.Thread(
            target=httpd.serve_forever,
            name="video-live-http",
            daemon=True,
        )
        self._http_thread.start()
        log.info("video-live control http://%s:%s", self.http_host, self.http_port)
        if self.enable_larix and self.larix_port > 0:
            self._start_larix()

    def stop(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
            larix = self._larix
            self._larix = None
        for session in sessions:
            session.stop()
        if larix is not None:
            larix.stop()
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    def prepare(self) -> dict[str, Any]:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("0.0.0.0", 0))
        port = int(sock.getsockname()[1])
        sock.close()
        stream_id = _new_stream_id()
        session = StreamSession(
            stream_id=stream_id,
            source="console",
            listen_host="0.0.0.0",
            listen_port=port,
            dump_path=self.dump_dir / f"{stream_id}.ts",
            preview=self.preview,
        )
        with self._lock:
            self._sessions[stream_id] = session
        session.start()
        return session.snapshot()

    def status(self, stream_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            sessions = list(self._sessions.values())
            larix = self._larix
        if stream_id:
            for session in sessions:
                if session.stream_id == stream_id:
                    return session.snapshot()
            if larix is not None and larix.stream_id == stream_id:
                return larix.snapshot()
            return {"status": "idle", "stream_id": stream_id, "error": "unknown stream_id"}
        live = [s.snapshot() for s in sessions]
        if larix is not None:
            live.append(larix.snapshot())
        active = [s for s in live if s.get("status") in ("listening", "streaming", "starting")]
        if not active:
            return {"status": "idle", "streams": live}
        return {"status": "streaming", "streams": live}

    def stop_stream(self, stream_id: str) -> dict[str, Any]:
        with self._lock:
            session = self._sessions.pop(stream_id, None)
            larix = self._larix
        if session is not None:
            session.stop()
            return {"status": "idle", "stream_id": stream_id}
        if larix is not None and larix.stream_id == stream_id:
            larix.stop()
            self._larix = None
            self._start_larix()
            return {"status": "idle", "stream_id": stream_id}
        return {"status": "idle", "stream_id": stream_id, "error": "unknown stream_id"}

    def _start_larix(self) -> None:
        stream_id = _new_stream_id()
        session = StreamSession(
            stream_id=stream_id,
            source="larix",
            listen_host="0.0.0.0",
            listen_port=self.larix_port,
            dump_path=self.dump_dir / f"{stream_id}.ts",
            preview=self.preview,
        )
        self._larix = session
        session.start()
        log.info("Larix MPEG-TS standing port %s stream_id=%s", self.larix_port, stream_id)

    def _make_handler(self) -> type[BaseHTTPRequestHandler]:
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: Any) -> None:
                log.debug("%s - " + fmt, self.address_string(), *args)

            def _send(self, code: int, body: dict[str, Any]) -> None:
                raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                if parsed.path.rstrip("/") != "/api/v1/video-live/status":
                    self._send(404, {"error": "not found"})
                    return
                q = parse_qs(parsed.query or "")
                stream_id = (q.get("stream_id") or [""])[0].strip() or None
                self._send(200, server.status(stream_id))

            def do_POST(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                path = parsed.path.rstrip("/")
                body = _parse_body(self)
                if path == "/api/v1/video-live/prepare":
                    self._send(200, server.prepare())
                    return
                if path == "/api/v1/video-live/stop":
                    stream_id = str(body.get("stream_id") or "").strip()
                    if not stream_id:
                        q = parse_qs(parsed.query or "")
                        stream_id = (q.get("stream_id") or [""])[0].strip()
                    if not stream_id:
                        self._send(400, {"error": "stream_id required"})
                        return
                    self._send(200, server.stop_stream(stream_id))
                    return
                self._send(404, {"error": "not found"})

        return Handler
