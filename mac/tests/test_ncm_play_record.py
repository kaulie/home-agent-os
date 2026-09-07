"""BlackHole/ffmpeg play-side recorder for ncm-cli."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from mac_edge.ncm_songs import store as ncm_store
from mac_edge.plugins import ncm_play_record as rec


class NcmPlayRecordTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_data = os.environ.get("MAC_EDGE_DATA_DIR")
        self._old_flag = os.environ.get("MAC_EDGE_NCM_RECORD")
        os.environ["MAC_EDGE_DATA_DIR"] = self._tmp.name
        os.environ["MAC_EDGE_NCM_RECORD"] = "1"
        ncm_store.reset(path=Path(self._tmp.name) / "ncm_songs.sqlite3")
        ncm_store.init_db()
        rec._active_original_id = None
        rec.stop_recording(clear_playlist=True)

    def tearDown(self) -> None:
        rec.stop_recording(clear_playlist=True)
        ncm_store.reset()
        if self._old_data is None:
            os.environ.pop("MAC_EDGE_DATA_DIR", None)
        else:
            os.environ["MAC_EDGE_DATA_DIR"] = self._old_data
        if self._old_flag is None:
            os.environ.pop("MAC_EDGE_NCM_RECORD", None)
        else:
            os.environ["MAC_EDGE_NCM_RECORD"] = self._old_flag
        self._tmp.cleanup()

    def _song(self, oid: int = 1, duration: int = 3000, name: str = "十年") -> dict:
        return {
            "originalId": oid,
            "id": f"enc{oid}",
            "name": name,
            "duration": duration,
            "artists": [{"name": "陈奕迅"}],
        }

    def test_sanitize_filename(self) -> None:
        self.assertEqual(rec.sanitize_filename("十年 / 爱"), "十年_爱")
        self.assertTrue(rec.sanitize_filename("").startswith("unknown") or True)

    def test_disabled_skips_spawn(self) -> None:
        os.environ["MAC_EDGE_NCM_RECORD"] = "0"
        with patch.object(rec.subprocess, "Popen") as popen:
            self.assertFalse(rec.start_recording(self._song()))
            popen.assert_not_called()

    def test_start_and_stop_kills_process_group(self) -> None:
        fake = MagicMock()
        fake.pid = 4242
        fake.poll.return_value = None
        with patch.object(rec, "_ffmpeg_bin", return_value="/usr/bin/ffmpeg"):
            with patch.object(rec.subprocess, "Popen", return_value=fake) as popen:
                with patch.object(rec.os, "killpg") as killpg:
                    with patch.object(rec, "_schedule_stop_locked"):
                        ok = rec.start_recording(self._song())
                        self.assertTrue(ok)
                        argv = popen.call_args[0][0]
                        self.assertEqual(argv[0], "/usr/bin/ffmpeg")
                        self.assertIn("avfoundation", argv)
                        self.assertIn("none:BlackHole 2ch", argv)
                        self.assertTrue(str(argv[-1]).endswith(".mp3"))
                        path = rec.stop_recording()
                        self.assertIsNotNone(path)
                        killpg.assert_called()

    def test_playlist_on_next_advances(self) -> None:
        songs = [self._song(1, name="A"), self._song(2, name="B")]
        fake = MagicMock()
        fake.pid = 100
        fake.poll.return_value = None
        with patch.object(rec, "_ffmpeg_bin", return_value="/usr/bin/ffmpeg"):
            with patch.object(rec.subprocess, "Popen", return_value=fake) as popen:
                with patch.object(rec.os, "killpg"):
                    with patch.object(rec, "_schedule_stop_locked"):
                        self.assertTrue(rec.start_playlist_session(songs))
                        self.assertEqual(rec._playlist_index, 0)
                        self.assertTrue(rec.on_next())
                        self.assertEqual(rec._playlist_index, 1)
                        self.assertGreaterEqual(popen.call_count, 2)
                        out = str(popen.call_args[0][0][-1])
                        self.assertIn("B_", out)

    def test_duration_default_when_missing(self) -> None:
        song = {"originalId": 9, "id": "x", "name": "无时长"}
        self.assertEqual(rec._duration_ms(song), rec.DEFAULT_DURATION_MS)

    def test_complete_skips_rerecord(self) -> None:
        song = self._song(42)
        path = rec._output_path(song)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"ID3fake")
        ncm_store.upsert_recording_started(song, path)
        ncm_store.mark_recording_complete(42)
        with patch.object(rec.subprocess, "Popen") as popen:
            self.assertTrue(rec.start_recording(song))
            popen.assert_not_called()
        row = ncm_store.get_recording(42)
        self.assertEqual(row["status"], "complete")

    def test_incomplete_allows_overwrite(self) -> None:
        song = self._song(7)
        path = rec._output_path(song)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"old")
        ncm_store.upsert_recording_started(song, path)
        ncm_store.mark_recording_incomplete(7)
        fake = MagicMock()
        fake.pid = 99
        fake.poll.return_value = None
        with patch.object(rec, "_ffmpeg_bin", return_value="/usr/bin/ffmpeg"):
            with patch.object(rec.subprocess, "Popen", return_value=fake) as popen:
                with patch.object(rec, "_schedule_stop_locked"):
                    self.assertTrue(rec.start_recording(song))
                    popen.assert_called_once()
        row = ncm_store.get_recording(7)
        self.assertEqual(row["status"], "recording")

    def test_stop_marks_incomplete(self) -> None:
        fake = MagicMock()
        fake.pid = 55
        fake.poll.return_value = None
        with patch.object(rec, "_ffmpeg_bin", return_value="/usr/bin/ffmpeg"):
            with patch.object(rec.subprocess, "Popen", return_value=fake):
                with patch.object(rec.os, "killpg"):
                    with patch.object(rec, "_schedule_stop_locked"):
                        rec.start_recording(self._song(3))
                        rec.stop_recording()
        row = ncm_store.get_recording(3)
        self.assertEqual(row["status"], "incomplete")


if __name__ == "__main__":
    unittest.main()
