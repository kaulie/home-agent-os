"""LAN MPEG-TS ingest for video.live_stream (Console + Larix Broadcaster).

Control HTTP (default :8790, LAN only):
  POST /api/v1/video-live/prepare
  GET  /api/v1/video-live/status?stream_id=
  POST /api/v1/video-live/stop
  GET  /api/v1/video-live/hls/<stream_id>/<file>   (playlist.m3u8 / .ts segments)

HLS relay: while streaming, MPEG-TS is teed into ffmpeg which writes a rolling
HLS playlist under <data>/video-live/hls/<stream_id>/. Snapshot exposes
"playback_url" so a second LAN phone can watch via AVPlayer (HLS, ~2s segments).

Event mode (default, HLS_LIST_SIZE=0): every segment is kept and completed
sessions are registered as replays (`status.replays[]`) and stay playable until
RETENTION_MINUTES (0 = keep forever) / MAX_SESSIONS prune them.

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
        hls: bool = False,
        http_port: int = DEFAULT_HTTP_PORT,
        hls_list_size: int = 0,
        server: VideoLiveIngestServer | None = None,
    ) -> None:
        self.stream_id = stream_id
        self.source = source
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.dump_path = dump_path
        self.preview = preview
        self.hls = hls
        self.http_port = http_port
        self.hls_list_size = int(hls_list_size)
        self._server = server
        self.started_at = time.time()
        self.bytes_received = 0
        self.status = "starting"
        self.error: str | None = None
        self.endpoint = f"tcp://{lan_ipv4()}:{listen_port}"
        self.hls_dir = dump_path.parent / "hls" / stream_id
        self.hls_ready = False
        self._stop = threading.Event()
        self._sock: socket.socket | None = None
        self._ffplay: subprocess.Popen[bytes] | None = None
        self._ffmpeg_hls: subprocess.Popen[bytes] | None = None
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
        if self._ffmpeg_hls is not None:
            try:
                self._ffmpeg_hls.terminate()
                try:
                    self._ffmpeg_hls.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._ffmpeg_hls.kill()
                    self._ffmpeg_hls.wait(timeout=5)
            except OSError:
                pass
        self.status = "idle"

    def snapshot(self) -> dict[str, Any]:
        snap: dict[str, Any] = {
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
        if self.hls and self.status == "streaming" and self.hls_ready:
            snap["playback_url"] = (
                f"http://{lan_ipv4()}:{self.http_port}"
                f"/api/v1/video-live/hls/{self.stream_id}/playlist.m3u8"
            )
        return snap

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
        if self.hls:
            # Reset any content from a previous push on this session (Larix reuses
            # the same stream_id) and drop its stale replay/cleanup timer.
            shutil.rmtree(self.hls_dir, ignore_errors=True)
            if self._server is not None:
                self._server._hls_session_started(self.stream_id)
            ffmpeg_bin = shutil.which("ffmpeg")
            if ffmpeg_bin:
                try:
                    self.hls_dir.mkdir(parents=True, exist_ok=True)
                    # list_size 0 = Event mode: keep every segment (full replay).
                    # list_size > 0 = sliding window: delete segments that fall out.
                    hls_flags = "append_list" if self.hls_list_size == 0 else "delete_segments"
                    self._ffmpeg_hls = subprocess.Popen(
                        [
                            ffmpeg_bin,
                            "-hide_banner",
                            "-loglevel",
                            "error",
                            "-f",
                            "mpegts",
                            "-i",
                            "pipe:0",
                            "-c",
                            "copy",
                            "-f",
                            "hls",
                            "-hls_time",
                            "2",
                            "-hls_list_size",
                            str(self.hls_list_size),
                            "-hls_flags",
                            hls_flags,
                            "-hls_segment_filename",
                            str(self.hls_dir / "seg_%05d.ts"),
                            str(self.hls_dir / "playlist.m3u8"),
                        ],
                        stdin=subprocess.PIPE,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                except OSError:
                    self._ffmpeg_hls = None
                if self._ffmpeg_hls is not None and self._ffmpeg_hls.stdin is not None:
                    try:
                        os.set_blocking(self._ffmpeg_hls.stdin.fileno(), False)
                    except OSError:
                        pass
            else:
                log.info("hls relay: install ffmpeg on PATH to expose playback_url")
        try:
            with conn, self.dump_path.open("ab") as dump:
                conn.settimeout(1.0)
                while not self._stop.is_set():
                    try:
                        chunk = conn.recv(64 * 1024)
                    except socket.timeout:
                        self._maybe_mark_hls_ready()
                        continue
                    except OSError:
                        break
                    if not chunk:
                        break
                    self.bytes_received += len(chunk)
                    dump.write(chunk)
                    dump.flush()
                    self._maybe_open_viewer()
                    self._maybe_mark_hls_ready()
                    for proc in (self._ffplay, self._ffmpeg_hls):
                        if proc is None:
                            continue
                        stdin = proc.stdin
                        if stdin is None:
                            continue
                        try:
                            stdin.write(chunk)
                        except BlockingIOError:
                            pass
                        except BrokenPipeError:
                            if proc is self._ffmpeg_hls:
                                # Keep the reference: the finally block must still be
                                # able to kill/reap it even if the pipe broke early.
                                self.hls_ready = False
                            else:
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
            if self._ffmpeg_hls is not None:
                try:
                    if self._ffmpeg_hls.stdin is not None:
                        self._ffmpeg_hls.stdin.close()
                    self._ffmpeg_hls.terminate()
                    try:
                        self._ffmpeg_hls.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        self._ffmpeg_hls.kill()
                        self._ffmpeg_hls.wait(timeout=5)
                except OSError:
                    pass
                self._ffmpeg_hls = None
            self.hls_ready = False
            if self.hls:
                if self.hls_list_size == 0 and self._server is not None:
                    # Event mode: keep the directory (replay stays available); the
                    # server registers the replay and owns retention/pruning.
                    self._server._hls_session_ended(self)
                else:
                    # Window mode: sweep late writes then remove the directory.
                    for _attempt in range(5):
                        shutil.rmtree(self.hls_dir, ignore_errors=True)
                        if not self.hls_dir.exists():
                            break
                        time.sleep(0.3)
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

    def _maybe_mark_hls_ready(self) -> None:
        if self.hls_ready or not self.hls or self._ffmpeg_hls is None:
            return
        playlist = self.hls_dir / "playlist.m3u8"
        if playlist.is_file() and playlist.stat().st_size > 0:
            self.hls_ready = True
            log.info("hls relay ready stream_id=%s dir=%s", self.stream_id, self.hls_dir)


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
        hls: bool = True,
        hls_list_size: int = 0,
        hls_retention_minutes: int = 0,
        hls_max_sessions: int = 0,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.http_host = http_host
        self.http_port = int(http_port)
        self.larix_port = int(larix_port)
        self.preview = preview
        self.enable_larix = enable_larix
        self.hls = hls
        self.hls_list_size = int(hls_list_size)
        self.hls_retention_seconds = int(hls_retention_minutes) * 60
        self.hls_max_sessions = int(hls_max_sessions)
        self._lock = threading.Lock()
        self._sessions: dict[str, StreamSession] = {}
        self._archives: dict[str, dict[str, Any]] = {}
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
        hls = _env_bool("MAC_EDGE_VIDEO_INGEST_HLS", True)
        hls_list_size = int(os.environ.get("MAC_EDGE_VIDEO_INGEST_HLS_LIST_SIZE") or "0")
        hls_retention = int(os.environ.get("MAC_EDGE_VIDEO_INGEST_HLS_RETENTION_MINUTES") or "0")
        hls_max_sessions = int(os.environ.get("MAC_EDGE_VIDEO_INGEST_HLS_MAX_SESSIONS") or "0")
        return cls(
            data_dir=data_dir,
            http_port=http_port,
            larix_port=larix_port,
            preview=preview,
            hls=hls,
            hls_list_size=hls_list_size,
            hls_retention_minutes=hls_retention,
            hls_max_sessions=hls_max_sessions,
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
            hls=self.hls,
            http_port=self.http_port,
            hls_list_size=self.hls_list_size,
            server=self,
        )
        with self._lock:
            self._sessions[stream_id] = session
        session.start()
        return session.snapshot()

    def status(self, stream_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            sessions = list(self._sessions.values())
            larix = self._larix
            replays = sorted(
                (dict(r) for r in self._archives.values()),
                key=lambda r: r["ended_at"],
                reverse=True,
            )
            for r in replays:
                r.pop("hls_dir", None)
                r.pop("timer", None)
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
        return {"status": "streaming" if active else "idle", "streams": live, "replays": replays}

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
            hls=self.hls,
            http_port=self.http_port,
            hls_list_size=self.hls_list_size,
            server=self,
        )
        self._larix = session
        session.start()
        log.info("Larix MPEG-TS standing port %s stream_id=%s", self.larix_port, stream_id)

    def serve_hls(self, handler: BaseHTTPRequestHandler, path: str) -> None:
        prefix = "/api/v1/video-live/hls/"
        rest = path[len(prefix):].strip("/")
        stream_id, _, filename = rest.partition("/")
        if not stream_id or not filename:
            handler._send(404, {"error": "not found"})
            return
        with self._lock:
            sessions = list(self._sessions.values())
            larix = self._larix
            archive = self._archives.get(stream_id)
        session = next((s for s in sessions if s.stream_id == stream_id), None)
        if session is None and larix is not None and larix.stream_id == stream_id:
            session = larix
        if session is not None:
            if not session.hls:
                handler._send(404, {"error": "hls disabled"})
                return
            hls_root = session.hls_dir
        elif archive is not None:
            # Completed replay: files stay on disk under the archive record.
            hls_root = Path(archive["hls_dir"])
        else:
            handler._send(404, {"error": "unknown stream_id"})
            return
        target = hls_root / filename
        try:
            target.resolve().relative_to(hls_root.resolve())
        except ValueError:
            handler._send(404, {"error": "not found"})
            return
        if not target.is_file():
            handler._send(404, {"error": "not found"})
            return
        content_type = (
            "application/vnd.apple.mpegurl"
            if filename.endswith(".m3u8")
            else "video/mp2t"
        )
        handler.send_response(200)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(target.stat().st_size))
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        with target.open("rb") as fh:
            shutil.copyfileobj(fh, handler.wfile)

    def _archive_record(self, session: StreamSession) -> dict[str, Any] | None:
        playlist = session.hls_dir / "playlist.m3u8"
        if not playlist.is_file():
            return None
        segments = len(list(session.hls_dir.glob("seg_*.ts")))
        return {
            "stream_id": session.stream_id,
            "capability_id": CAPABILITY_ID,
            "source": session.source,
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(session.started_at)),
            "ended_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time())),
            "bytes_received": session.bytes_received,
            "segments": segments,
            "playback_url": (
                f"http://{lan_ipv4()}:{self.http_port}"
                f"/api/v1/video-live/hls/{session.stream_id}/playlist.m3u8"
            ),
            "hls_dir": str(session.hls_dir),
            "timer": None,
        }

    def _hls_session_started(self, stream_id: str) -> None:
        """A push is starting on `stream_id` (possibly reusing a previous session's
        directory, e.g. the standing Larix port): drop any stale replay + timer."""
        with self._lock:
            old = self._archives.pop(stream_id, None)
        if old is not None and old.get("timer") is not None:
            old["timer"].cancel()

    def _hls_session_ended(self, session: StreamSession) -> None:
        """Event-mode stream ended: keep the files and register a replay."""
        if self.hls_list_size > 0:
            return
        record = self._archive_record(session)
        if record is None:
            return
        with self._lock:
            old = self._archives.get(session.stream_id)
            if old is not None and old.get("timer") is not None:
                old["timer"].cancel()
            if self.hls_retention_seconds > 0:
                timer = threading.Timer(
                    self.hls_retention_seconds,
                    self._expire_archive,
                    (session.stream_id,),
                )
                timer.daemon = True
                record["timer"] = timer
                timer.start()
            self._archives[session.stream_id] = record
            self._prune_archives_locked()
        log.info(
            "hls replay archived stream_id=%s segments=%s bytes=%s",
            session.stream_id,
            record["segments"],
            record["bytes_received"],
        )

    def _expire_archive(self, stream_id: str) -> None:
        with self._lock:
            record = self._archives.pop(stream_id, None)
        if record is not None:
            shutil.rmtree(record["hls_dir"], ignore_errors=True)
            log.info("hls replay expired stream_id=%s", stream_id)

    def _prune_archives_locked(self) -> None:
        maxn = self.hls_max_sessions
        if maxn <= 0:
            return
        ordered = sorted(self._archives.values(), key=lambda r: r["ended_at"])
        while len(self._archives) > maxn and ordered:
            oldest = ordered.pop(0)
            self._archives.pop(oldest["stream_id"], None)
            if oldest.get("timer") is not None:
                oldest["timer"].cancel()
            shutil.rmtree(oldest["hls_dir"], ignore_errors=True)
            log.info("hls replay pruned stream_id=%s", oldest["stream_id"])

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
                path = parsed.path.rstrip("/") or "/"
                if path == "/api/v1/video-live/status":
                    q = parse_qs(parsed.query or "")
                    stream_id = (q.get("stream_id") or [""])[0].strip() or None
                    self._send(200, server.status(stream_id))
                    return
                if path.startswith("/api/v1/video-live/hls/"):
                    server.serve_hls(self, path)
                    return
                self._send(404, {"error": "not found"})

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
