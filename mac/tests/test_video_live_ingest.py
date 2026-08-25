"""video.live_stream plan-step refuse + MPEG-TS ingest control HTTP."""

from __future__ import annotations

import json
import socket
import tempfile
import time
import unittest
from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
