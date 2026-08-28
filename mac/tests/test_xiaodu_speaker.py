"""Unit tests for xiaodu.speaker plugin."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest import mock

from mac_edge.plugins import xiaodu_speaker as xs


class XiaoduSpeakerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._env = mock.patch.dict(os.environ, {}, clear=False)
        self._env.start()
        xs.bind_server(None)

    def tearDown(self) -> None:
        xs.bind_server(None)
        self._env.stop()

    def test_speak_from_params_requires_text(self) -> None:
        with self.assertRaises(xs.XiaoduSpeakerError) as ctx:
            xs.speak_from_params({})
        self.assertIn("text", str(ctx.exception).lower())

    def test_play_uri_sends_stop_seturi_play(self) -> None:
        calls: list[tuple[str, str]] = []

        def fake_post(du_ip: str, action: str, body: str, *, timeout_sec: float = 8.0) -> None:
            calls.append((action, body))

        with mock.patch.object(xs, "_upnp_post", side_effect=fake_post):
            xs.play_uri("192.168.3.47", "http://192.168.3.73:8000/tts_1.mp3")

        self.assertEqual(len(calls), 3)
        self.assertIn("Stop", calls[0][0])
        self.assertIn("SetAVTransportURI", calls[1][0])
        self.assertIn("http://192.168.3.73:8000/tts_1.mp3", calls[1][1])
        self.assertIn("Play", calls[2][0])

    def test_speak_synthesizes_and_plays(self) -> None:
        data_dir = Path(os.environ.get("TMPDIR", "/tmp")) / "xiaodu_speaker_test"
        data_dir.mkdir(parents=True, exist_ok=True)
        server = xs.XiaoduTtsHttpServer(data_dir=data_dir, http_port=0)
        server.start()
        xs.bind_server(server)
        self.addCleanup(server.stop)
        self.addCleanup(lambda: xs.bind_server(None))

        async def fake_synthesize(text: str, voice: str, path: Path) -> None:
            path.write_bytes(b"\xff" * 128)

        upnp_calls: list[str] = []

        def fake_post(du_ip: str, action: str, body: str, *, timeout_sec: float = 8.0) -> None:
            upnp_calls.append(action)

        with mock.patch.dict(
            os.environ,
            {"MAC_EDGE_XIAODU_IP": "192.168.3.47", "MAC_EDGE_XIAODU_PUBLIC_HOST": "192.168.3.73"},
            clear=False,
        ):
            with mock.patch.object(xs, "_synthesize", side_effect=fake_synthesize):
                with mock.patch.object(xs, "_upnp_post", side_effect=fake_post):
                    msg = xs.speak("欢迎回家")

        self.assertTrue(msg.startswith("xiaodu spoke:"))
        self.assertIn("欢迎回家", msg)
        self.assertEqual(len(upnp_calls), 3)
        mp3_files = list(server.serve_dir.glob("tts_*.mp3"))
        self.assertEqual(len(mp3_files), 1)
        self.assertGreaterEqual(mp3_files[0].stat().st_size, 64)

    def test_xiaodu_configured(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(xs.xiaodu_configured())
        with mock.patch.dict(os.environ, {"MAC_EDGE_XIAODU_IP": "192.168.3.47"}, clear=False):
            self.assertTrue(xs.xiaodu_configured())

    def test_from_env_returns_none_without_ip(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(xs.XiaoduTtsHttpServer.from_env(Path("/tmp/xiaodu_test")))

    def test_public_url_uses_override_host(self) -> None:
        server = xs.XiaoduTtsHttpServer(data_dir=Path("/tmp/xiaodu_test2"), http_port=8000)
        with mock.patch.dict(
            os.environ,
            {"MAC_EDGE_XIAODU_PUBLIC_HOST": "192.168.3.73"},
            clear=False,
        ):
            url = server.public_url("tts_99.mp3")
        self.assertEqual(url, "http://192.168.3.73:8000/tts_99.mp3")


if __name__ == "__main__":
    unittest.main()
