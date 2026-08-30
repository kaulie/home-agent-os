"""video.live_stream plan-step refuse + MPEG-TS ingest control HTTP."""

from __future__ import annotations

import json
import shutil
import socket
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from mac_edge.plugins.video_live_ingest import VideoLiveIngestServer
from mac_edge.plugins.video_live_stream import VideoLiveStreamError, run_from_params
from mac_edge.capability_ads import ADS, attach


class VideoLiveStreamTests(unittest.TestCase):
    def test_plan_step_refused(self) -> None:
        with self.assertRaises(VideoLiveStreamError) as ctx:
            run_from_params({})
        self.assertIn("计划", str(ctx.exception))
        self.assertIn("video.live_stream", str(ctx.exception))

    def test_planner_ad_is_input_and_not_a_plan_step(self) -> None:
        self.assertIn("video.live_stream", ADS)
        ad = attach("video.live_stream")
        self.assertEqual(ad["kind"], "input")
        self.assertTrue(any("计划" in x or "逐步" in x for x in ad["do_not_dispatch"]))
        self.assertIn("看图理解", ad["do_not_dispatch"])
        self.assertIn("抽帧上传", ad["do_not_dispatch"])
        self.assertIn("投屏", ad["do_not_dispatch"])


class VideoLiveIngestHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.server = VideoLiveIngestServer(
            data_dir=self.root,
            http_host="127.0.0.1",
            http_port=0,
            larix_port=0,
            preview=False,
            enable_larix=False,
            hls=False,
        )
        self.server.start()
        self.base = f"http://127.0.0.1:{self.server.http_port}"

    def tearDown(self) -> None:
        self.server.stop()

    def _json(self, method: str, path: str, body: dict | None = None) -> dict:
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = Request(
            self.base + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"} if data else {},
        )
        with urlopen(req, timeout=3) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def test_idle_status(self) -> None:
        body = self._json("GET", "/api/v1/video-live/status")
        self.assertEqual(body["status"], "idle")

    def test_prepare_listen_and_stop(self) -> None:
        prepared = self._json("POST", "/api/v1/video-live/prepare")
        stream_id = prepared["stream_id"]
        self.assertTrue(stream_id.startswith("video_stream_"))
        self.assertEqual(prepared["transport"], "mpegts_tcp")
        self.assertEqual(prepared["encoding"], "h264")
        self.assertEqual(prepared["capability_id"], "video.live_stream")
        self.assertTrue(str(prepared["endpoint"]).startswith("tcp://"))
        endpoint = str(prepared["endpoint"])
        port = int(endpoint.rsplit(":", 1)[-1])
        deadline = time.time() + 2.0
        last = prepared
        while time.time() < deadline:
            last = self._json("GET", f"/api/v1/video-live/status?stream_id={stream_id}")
            if last.get("status") in ("listening", "streaming"):
                break
            time.sleep(0.05)
        self.assertIn(last.get("status"), ("listening", "streaming", "starting"))
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        try:
            sock.connect(("127.0.0.1", port))
            sock.sendall(b"\x47" + b"\x00" * 187)
        finally:
            sock.close()
        deadline = time.time() + 2.0
        while time.time() < deadline:
            last = self._json("GET", f"/api/v1/video-live/status?stream_id={stream_id}")
            if int(last.get("bytes_received") or 0) > 0:
                break
            time.sleep(0.05)
        self.assertGreater(int(last.get("bytes_received") or 0), 0)
        stopped = self._json("POST", "/api/v1/video-live/stop", {"stream_id": stream_id})
        self.assertEqual(stopped["status"], "idle")

    def test_stop_requires_stream_id(self) -> None:
        req = Request(
            self.base + "/api/v1/video-live/stop",
            data=b"{}",
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with self.assertRaises(HTTPError) as ctx:
            urlopen(req, timeout=3)
        self.assertEqual(ctx.exception.code, 400)


class VideoLiveIngestHlsTests(unittest.TestCase):
    """HLS relay: fake ffmpeg writes playlist+segment; playback_url + route."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.server = VideoLiveIngestServer(
            data_dir=self.root,
            http_host="127.0.0.1",
            http_port=0,
            larix_port=0,
            preview=False,
            enable_larix=False,
            hls=True,
        )
        self.server.start()
        self.base = f"http://127.0.0.1:{self.server.http_port}"
        self._real_which = shutil.which
        self._fake_ffmpeg = self._install_fake_ffmpeg()

    def tearDown(self) -> None:
        self.server.stop()

    def _install_fake_ffmpeg(self) -> Path:
        fake = self.root / "fake_ffmpeg"
        fake.write_text(
            "#!/bin/bash\n"
            'out="${@: -1}"\n'
            'dir="$(dirname "$out")"\n'
            'mkdir -p "$dir"\n'
            'printf "seg_00000.ts\\n" > "$dir/playlist.m3u8"\n'
            'printf "FAKETS" > "$dir/seg_00000.ts"\n'
            "cat > /dev/null\n"
        )
        fake.chmod(0o755)
        return fake

    def _fake_which(self, name: str) -> str | None:
        if name == "ffmpeg":
            return str(self._fake_ffmpeg)
        return self._real_which(name)

    def _make_server(self, **kw: Any) -> VideoLiveIngestServer:
        server = VideoLiveIngestServer(
            data_dir=Path(tempfile.mkdtemp()),
            http_host="127.0.0.1",
            http_port=0,
            larix_port=0,
            preview=False,
            enable_larix=False,
            hls=True,
            **kw,
        )
        server.start()
        return server

    def _json(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        base: str | None = None,
    ) -> dict:
        root = base or self.base
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = Request(
            root + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"} if data else {},
        )
        with urlopen(req, timeout=3) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _open_stream(self, base: str | None = None) -> tuple[str, socket.socket]:
        prepared = self._json("POST", "/api/v1/video-live/prepare", base=base)
        stream_id = prepared["stream_id"]
        port = int(str(prepared["endpoint"]).rsplit(":", 1)[-1])
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        sock.connect(("127.0.0.1", port))
        sock.sendall(b"\x47" + b"\x00" * 187)
        return stream_id, sock

    def _wait_for(self, predicate, timeout: float = 6.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            result = predicate()
            if result:
                return result
            time.sleep(0.1)
        return None


    def test_hls_ready_exposes_playback_url_and_route(self) -> None:
        with mock.patch.object(shutil, "which", self._fake_which):
            stream_id, sock = self._open_stream()
            try:
                deadline = time.time() + 5.0
                last: dict = {}
                while time.time() < deadline:
                    last = self._json("GET", f"/api/v1/video-live/status?stream_id={stream_id}")
                    if last.get("playback_url"):
                        break
                    time.sleep(0.1)
                self.assertEqual(last.get("status"), "streaming")
                playback = str(last.get("playback_url") or "")
                self.assertIn(f"/api/v1/video-live/hls/{stream_id}/playlist.m3u8", playback)
                # playlist served 200 + references the segment
                with urlopen(self.base + f"/api/v1/video-live/hls/{stream_id}/playlist.m3u8", timeout=3) as resp:
                    self.assertEqual(resp.status, 200)
                    playlist = resp.read().decode("utf-8")
                self.assertIn("seg_00000.ts", playlist)
                # segment served 200 + exact bytes
                with urlopen(self.base + f"/api/v1/video-live/hls/{stream_id}/seg_00000.ts", timeout=3) as resp:
                    self.assertEqual(resp.status, 200)
                    self.assertEqual(resp.read(), b"FAKETS")
                # unknown file -> 404
                with self.assertRaises(HTTPError) as ctx:
                    urlopen(self.base + f"/api/v1/video-live/hls/{stream_id}/nope.ts", timeout=3)
                self.assertEqual(ctx.exception.code, 404)
                # unknown stream -> 404
                with self.assertRaises(HTTPError) as ctx:
                    urlopen(self.base + "/api/v1/video-live/hls/video_stream_deadbeef/playlist.m3u8", timeout=3)
                self.assertEqual(ctx.exception.code, 404)
                # traversal -> 404
                with self.assertRaises(HTTPError) as ctx:
                    urlopen(self.base + f"/api/v1/video-live/hls/{stream_id}/../playlist.m3u8", timeout=3)
                self.assertEqual(ctx.exception.code, 404)
            finally:
                sock.close()
        # after disconnect: event mode keeps the files and registers a replay
        self._wait_for(lambda: self._json("GET", "/api/v1/video-live/status")["status"] == "idle")
        full = self._json("GET", "/api/v1/video-live/status")
        replay = next((r for r in full.get("replays", []) if r["stream_id"] == stream_id), None)
        self.assertIsNotNone(replay, "replay not registered after stream end")
        self.assertEqual(replay["source"], "console")
        self.assertGreaterEqual(replay["segments"], 1)
        self.assertIn(f"/api/v1/video-live/hls/{stream_id}/playlist.m3u8", replay["playback_url"])
        # archived playlist is still served
        with urlopen(self.base + f"/api/v1/video-live/hls/{stream_id}/playlist.m3u8", timeout=3) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("seg_00000.ts", resp.read().decode("utf-8"))


    def test_hls_not_exposed_before_streaming(self) -> None:
        with mock.patch.object(shutil, "which", self._fake_which):
            prepared = self._json("POST", "/api/v1/video-live/prepare")
            stream_id = prepared["stream_id"]
            deadline = time.time() + 2.0
            last: dict = {}
            while time.time() < deadline:
                last = self._json("GET", f"/api/v1/video-live/status?stream_id={stream_id}")
                if last.get("status") in ("listening", "streaming"):
                    break
                time.sleep(0.05)
            self.assertIn(last.get("status"), ("listening", "streaming"))
            self.assertNotIn("playback_url", last)

    def test_hls_disabled_has_no_playback_url(self) -> None:
        server = VideoLiveIngestServer(
            data_dir=Path(tempfile.mkdtemp()),
            http_host="127.0.0.1",
            http_port=0,
            larix_port=0,
            preview=False,
            enable_larix=False,
            hls=False,
        )
        server.start()
        base = f"http://127.0.0.1:{server.http_port}"
        try:
            prepared = self._json("POST", "/api/v1/video-live/prepare", base=base)
            stream_id = prepared["stream_id"]
            port = int(str(prepared["endpoint"]).rsplit(":", 1)[-1])
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            sock.connect(("127.0.0.1", port))
            sock.sendall(b"\x47" + b"\x00" * 187)
            deadline = time.time() + 5.0
            last: dict = {}
            while time.time() < deadline:
                last = self._json("GET", f"/api/v1/video-live/status?stream_id={stream_id}", base=base)
                if last.get("status") == "streaming":
                    break
                time.sleep(0.1)
            self.assertEqual(last.get("status"), "streaming")
            self.assertNotIn("playback_url", last)
            with self.assertRaises(HTTPError) as ctx:
                urlopen(base + f"/api/v1/video-live/hls/{stream_id}/playlist.m3u8", timeout=3)
            self.assertEqual(ctx.exception.code, 404)
            sock.close()
        finally:
            server.stop()


    def test_window_mode_deletes_on_stop(self) -> None:
        server = self._make_server(hls_list_size=6)
        base = f"http://127.0.0.1:{server.http_port}"
        try:
            with mock.patch.object(shutil, "which", self._fake_which):
                stream_id, sock = self._open_stream(base=base)
                self._wait_for(
                    lambda: self._json("GET", f"/api/v1/video-live/status?stream_id={stream_id}", base=base).get("playback_url")
                )
                sock.close()
                self._wait_for(
                    lambda: self._json("GET", f"/api/v1/video-live/status?stream_id={stream_id}", base=base).get("status") == "idle"
                )
            # sliding window mode: dir removed -> 404, and no replay registered
            with self.assertRaises(HTTPError) as ctx:
                urlopen(base + f"/api/v1/video-live/hls/{stream_id}/playlist.m3u8", timeout=3)
            self.assertEqual(ctx.exception.code, 404)
            full = self._json("GET", "/api/v1/video-live/status", base=base)
            self.assertEqual(full.get("replays"), [])
        finally:
            server.stop()

    def test_ffmpeg_args_event_vs_window(self) -> None:
        with mock.patch.object(shutil, "which", self._fake_which):
            stream_id, sock = self._open_stream()
            session = self.server._sessions[stream_id]
            self._wait_for(lambda: session._ffmpeg_hls is not None)
            args = list(session._ffmpeg_hls.args)  # type: ignore[union-attr]
            self.assertEqual(args[args.index("-hls_list_size") + 1], "0")
            self.assertEqual(args[args.index("-hls_flags") + 1], "append_list")
            sock.close()

        server = self._make_server(hls_list_size=6)
        base = f"http://127.0.0.1:{server.http_port}"
        try:
            with mock.patch.object(shutil, "which", self._fake_which):
                stream_id, sock = self._open_stream(base=base)
                session = server._sessions[stream_id]
                self._wait_for(lambda: session._ffmpeg_hls is not None)
                args = list(session._ffmpeg_hls.args)  # type: ignore[union-attr]
                self.assertEqual(args[args.index("-hls_list_size") + 1], "6")
                self.assertEqual(args[args.index("-hls_flags") + 1], "delete_segments")
                sock.close()
        finally:
            server.stop()

    def test_replay_expires_when_retention_configured(self) -> None:
        server = self._make_server(hls_retention_minutes=1)
        base = f"http://127.0.0.1:{server.http_port}"
        try:
            with mock.patch.object(shutil, "which", self._fake_which):
                stream_id, sock = self._open_stream(base=base)
                self._wait_for(
                    lambda: self._json("GET", f"/api/v1/video-live/status?stream_id={stream_id}", base=base).get("playback_url")
                )
                sock.close()
                self._wait_for(
                    lambda: any(
                        r["stream_id"] == stream_id
                        for r in self._json("GET", "/api/v1/video-live/status", base=base).get("replays", [])
                    )
                )
            self.assertEqual(len(server._archives), 1)
            server._expire_archive(stream_id)
            self.assertEqual(len(server._archives), 0)
            with self.assertRaises(HTTPError) as ctx:
                urlopen(base + f"/api/v1/video-live/hls/{stream_id}/playlist.m3u8", timeout=3)
            self.assertEqual(ctx.exception.code, 404)
        finally:
            server.stop()

    def test_max_sessions_prunes_oldest(self) -> None:
        server = self._make_server(hls_max_sessions=1)
        base = f"http://127.0.0.1:{server.http_port}"
        try:
            with mock.patch.object(shutil, "which", self._fake_which):
                stream_ids: list[str] = []
                for _ in range(2):
                    stream_id, sock = self._open_stream(base=base)
                    self._wait_for(
                        lambda sid=stream_id: self._json(
                            "GET", f"/api/v1/video-live/status?stream_id={sid}", base=base
                        ).get("playback_url")
                    )
                    sock.close()
                    self._wait_for(
                        lambda sid=stream_id: any(
                            r["stream_id"] == sid
                            for r in self._json("GET", "/api/v1/video-live/status", base=base).get("replays", [])
                        )
                    )
                    stream_ids.append(stream_id)
            full = self._json("GET", "/api/v1/video-live/status", base=base)
            replay_ids = [r["stream_id"] for r in full["replays"]]
            self.assertEqual(replay_ids, [stream_ids[1]])
            old_dir = server.data_dir / "video-live" / "hls" / stream_ids[0]
            self.assertFalse(old_dir.exists(), "pruned oldest replay dir still on disk")
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
