"""TTS playback flag: mute mic while Runtime is speaking."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from mac_edge.tts_playback import PlaybackMute, is_playing, playback_session


class TtsPlaybackTests(unittest.TestCase):
    def test_session_sets_and_clears_flag(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            flag = Path(td) / "tts_playing"
            with patch("mac_edge.tts_playback.flag_path", return_value=flag):
                self.assertFalse(is_playing(flag))
                with playback_session():
                    self.assertTrue(flag.is_file())
                    self.assertTrue(is_playing(flag))
                self.assertFalse(flag.is_file())
                self.assertFalse(is_playing(flag))

    def test_nested_sessions_keep_flag_until_outer_exits(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            flag = Path(td) / "tts_playing"
            with patch("mac_edge.tts_playback.flag_path", return_value=flag):
                with playback_session():
                    self.assertTrue(flag.is_file())
                    with playback_session():
                        self.assertTrue(flag.is_file())
                    self.assertTrue(flag.is_file())
                self.assertFalse(flag.is_file())

    def test_stale_flag_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            flag = Path(td) / "tts_playing"
            flag.write_text("1\n", encoding="utf-8")
            past = time.time() - 500
            os_utime = __import__("os").utime
            os_utime(flag, (past, past))
            self.assertFalse(is_playing(flag, stale_s=180.0))

    def test_mute_hangover_after_flag_clears(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            flag = Path(td) / "tts_playing"
            now = [10.0]

            def clock() -> float:
                return now[0]

            mute = PlaybackMute(flag, hangover_s=0.5, clock=clock)
            self.assertFalse(mute())
            flag.write_text("1\n", encoding="utf-8")
            self.assertTrue(mute())
            flag.unlink()
            self.assertTrue(mute())  # hangover starts
            now[0] = 10.4
            self.assertTrue(mute())
            now[0] = 10.6
            self.assertFalse(mute())


if __name__ == "__main__":
    unittest.main()
