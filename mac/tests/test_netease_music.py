"""ncm-cli NetEase plugin: search+play, local ncm_songs cache, transport controls."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mac_edge.ncm_songs import store as ncm_store
from mac_edge.plugins import netease_music as nm

SEARCH_JSON = json.dumps(
    {
        "code": 200,
        "data": {
            "recordCount": 1,
            "records": [
                {
                    "originalId": 66842,
                    "id": "1B8FCF799FD5895F6F0586C7D19A0A3B",
                    "name": "十年",
                    "artists": [{"name": "陈奕迅"}],
                    "visible": False,
                }
            ],
        },
    },
    ensure_ascii=False,
)

PLAY_STDOUT = """[orpheus] orpheus://eyJjbWQiOiJwbGF5IiwidHlwZSI6InNvbmciLCJpZCI6IjY2ODQyIiwiY2hhbm5lbCI6Im5jbWNsaSJ9
{
  "success": true,
  "message": "已唤起云音乐播放歌曲 66842"
}
"""


def _completed(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["ncm-cli"],
        returncode=returncode,
        stdout=stdout,
        stderr="",
    )


class NeteaseMusicTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        ncm_store.reset(path=Path(self._tmp.name) / "ncm_songs.sqlite3")

    def tearDown(self) -> None:
        ncm_store.reset()
        self._tmp.cleanup()

    def test_keyword_one_arg(self) -> None:
        self.assertEqual(nm.search_keyword(song="十年", artist="陈奕迅"), "十年 陈奕迅")
        self.assertEqual(nm.search_keyword(song="十年"), "十年")

    def test_last_json_skips_orpheus_line(self) -> None:
        payload = nm.last_json_object(PLAY_STDOUT)
        self.assertTrue(payload["success"])
        self.assertIn("66842", payload["message"])

    def test_last_json_keeps_search_envelope(self) -> None:
        payload = nm.last_json_object(SEARCH_JSON)
        self.assertEqual(payload.get("code"), 200)
        records = payload["data"]["records"]
        self.assertEqual(records[0]["originalId"], 66842)

    def test_orpheus_only_is_not_success(self) -> None:
        with patch.object(nm, "ncm_cli_bin", return_value="/usr/bin/ncm-cli"):
            with patch.object(
                nm.subprocess,
                "run",
                return_value=_completed(
                    "[orpheus] orpheus://eyJjbWQiOiJwbGF5In0=\n"
                ),
            ):
                with self.assertRaises(nm.NeteaseMusicError) as ctx:
                    nm.play_record(
                        {
                            "id": "1B8FCF799FD5895F6F0586C7D19A0A3B",
                            "originalId": 66842,
                        }
                    )
                self.assertIn("JSON", str(ctx.exception))

    def test_play_requires_song(self) -> None:
        with self.assertRaises(nm.NeteaseMusicError) as ctx:
            nm.play_from_params({"artist": "陈奕迅"})
        self.assertIn("请说出歌名", str(ctx.exception))

    def test_search_then_play_and_cache(self) -> None:
        calls: list[list[str]] = []

        def fake_run(cmd, **_kwargs):
            calls.append(list(cmd))
            if "search" in cmd:
                return _completed(SEARCH_JSON)
            return _completed(PLAY_STDOUT)

        with patch.object(nm, "ncm_cli_bin", return_value="/usr/bin/ncm-cli"):
            with patch.object(nm.subprocess, "run", side_effect=fake_run):
                with patch.object(nm, "enter_music_mode"):
                    msg, outputs = nm.play_from_params({"song": "十年", "artist": "陈奕迅"})
                    self.assertIn("66842", msg)
                    self.assertEqual(outputs, {})
                    self.assertEqual(
                        calls[0][1:5],
                        ["search", "song", "--keyword", "十年 陈奕迅"],
                    )
                    self.assertIn("--encrypted-id", calls[1])
                    got = ncm_store.get_song(66842)
                    assert got is not None
                    self.assertEqual(got["name"], "十年")
                    self.assertIsNotNone(got["played_at"])

                    calls.clear()
                    msg2, _ = nm.play_from_params({"song": "十年", "artist": "陈奕迅"})
                    self.assertIn("66842", msg2)
                    self.assertTrue(any("play" in c for c in calls))
                    self.assertFalse(any("search" in c for c in calls))

    def test_play_failure_does_not_cache(self) -> None:
        def fake_run(cmd, **_kwargs):
            if "search" in cmd:
                return _completed(SEARCH_JSON)
            return _completed('{"success": false, "message": "唤起失败"}')

        with patch.object(nm, "ncm_cli_bin", return_value="/usr/bin/ncm-cli"):
            with patch.object(nm.subprocess, "run", side_effect=fake_run):
                with self.assertRaises(nm.NeteaseMusicError):
                    nm.play_from_params({"song": "十年"})
                self.assertIsNone(ncm_store.get_song(66842))

    def test_pause_resume_stop_next_prev(self) -> None:
        seen: list[str] = []

        def fake_run(cmd, **_kwargs):
            seen.append(cmd[1])
            return _completed('{"success": true, "message": "ok"}')

        with patch.object(nm, "ncm_cli_bin", return_value="/usr/bin/ncm-cli"):
            with patch.object(nm.subprocess, "run", side_effect=fake_run):
                with patch.object(nm, "exit_music_mode"):
                    nm.run_from_params("music.pause", {})
                    nm.run_from_params("music.resume", {})
                    nm.run_from_params("music.stop", {})
                    nm.run_from_params("music.next", {})
                    nm.run_from_params("music.previous", {})
        self.assertEqual(seen, ["pause", "resume", "stop", "next", "prev"])

    def test_unavailable_without_cli(self) -> None:
        with patch.object(nm, "ncm_cli_bin", return_value=None):
            avail = nm.is_available()
            self.assertFalse(avail.ok)


if __name__ == "__main__":
    unittest.main()
