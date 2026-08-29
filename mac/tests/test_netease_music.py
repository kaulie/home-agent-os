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
                    "duration": 205423,
                    "artists": [{"name": "陈奕迅"}],
                    "album": {
                        "originalId": 6548,
                        "id": "6AF3D73514E9BBA48FC1B1F0AA0A5D75",
                        "name": "黑白灰",
                    },
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

    def test_play_requires_song_or_artist(self) -> None:
        with self.assertRaises(nm.NeteaseMusicError) as ctx:
            nm.play_from_params({})
        self.assertIn("请说出歌名", str(ctx.exception))

    def test_play_artist_only_searches_keyword_artist(self) -> None:
        records = [
            {
                "originalId": 1,
                "id": "encA",
                "name": "十年",
                "artists": [{"name": "路人"}],
            },
            {
                "originalId": 66842,
                "id": "1B8FCF799FD5895F6F0586C7D19A0A3B",
                "name": "浮夸",
                "artists": [{"name": "陈奕迅"}],
            },
        ]
        payload = json.dumps({"code": 200, "data": {"records": records}}, ensure_ascii=False)
        calls: list[list[str]] = []

        def fake_run(cmd, **_kwargs):
            calls.append(list(cmd))
            if "search" in cmd:
                return _completed(payload)
            return _completed(PLAY_STDOUT)

        with patch.object(nm, "ncm_cli_bin", return_value="/usr/bin/ncm-cli"):
            with patch.object(nm.subprocess, "run", side_effect=fake_run):
                with patch.object(nm, "enter_music_mode"):
                    nm.play_from_params({"artist": "陈奕迅"})
        keywords = [c[c.index("--keyword") + 1] for c in calls if "search" in c]
        self.assertEqual(keywords, ["陈奕迅"])
        self.assertEqual(ncm_store.get_song(66842)["name"], "浮夸")

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
                    self.assertEqual(
                        set(outputs.get("timing") or {}),
                        {"cache", "search", "play", "total"},
                    )
                    self.assertGreaterEqual(outputs["timing"]["search"], 0)
                    self.assertEqual(
                        calls[0][1:7],
                        ["search", "song", "--keyword", "十年 陈奕迅", "--limit", "10"],
                    )
                    self.assertIn("--encrypted-id", calls[1])
                    got = ncm_store.get_song(66842)
                    assert got is not None
                    self.assertEqual(got["name"], "十年")
                    self.assertIsNotNone(got["played_at"])
                    indexed = ncm_store.get_index_song(66842)
                    assert indexed is not None
                    self.assertEqual(indexed["song_encrypted_id"], "1B8FCF799FD5895F6F0586C7D19A0A3B")
                    self.assertEqual(indexed["duration"], 205423)
                    self.assertEqual(indexed["album_original_id"], 6548)
                    self.assertEqual(indexed["album_name"], "黑白灰")
                    self.assertEqual(indexed["album_encrypted_id"], "6AF3D73514E9BBA48FC1B1F0AA0A5D75")

                    calls.clear()
                    msg2, outputs2 = nm.play_from_params({"song": "十年", "artist": "陈奕迅"})
                    self.assertIn("66842", msg2)
                    self.assertEqual(outputs2["timing"]["search"], 0)
                    self.assertTrue(any("play" in c for c in calls))
                    self.assertFalse(any("search" in c for c in calls))

    def test_play_failure_still_caches_search_hits(self) -> None:
        def fake_run(cmd, **_kwargs):
            if "search" in cmd:
                return _completed(SEARCH_JSON)
            return _completed('{"success": false, "message": "唤起失败"}')

        with patch.object(nm, "ncm_cli_bin", return_value="/usr/bin/ncm-cli"):
            with patch.object(nm.subprocess, "run", side_effect=fake_run):
                with self.assertRaises(nm.NeteaseMusicError):
                    nm.play_from_params({"song": "十年"})
                got = ncm_store.get_song(66842)
                assert got is not None
                self.assertEqual(got["name"], "十年")
                self.assertIsNone(got["played_at"])
                self.assertIsNotNone(ncm_store.get_index_song(66842))

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

    def test_search_user_input_and_keyword_argv(self) -> None:
        calls: list[list[str]] = []

        def fake_run(cmd, **_kwargs):
            calls.append(list(cmd))
            if "search" in cmd:
                return _completed(SEARCH_JSON)
            return _completed(PLAY_STDOUT)

        with patch.object(nm, "ncm_cli_bin", return_value="/usr/bin/ncm-cli"):
            with patch.object(nm.subprocess, "run", side_effect=fake_run):
                with patch.object(nm, "enter_music_mode"):
                    nm.play_from_params(
                        {
                            "song": "陈奕迅的十年",
                            "user_input": "播放陈奕迅的十年",
                        }
                    )
        search = calls[0]
        self.assertEqual(
            search[1:],
            [
                "search",
                "song",
                "--userInput",
                "播放陈奕迅的十年",
                "--keyword",
                "陈奕迅的十年",
                "--limit",
                "10",
            ],
        )

    def test_search_user_input_falls_back_to_keyword(self) -> None:
        calls: list[list[str]] = []

        def fake_run(cmd, **_kwargs):
            calls.append(list(cmd))
            if "--userInput" in cmd:
                return _completed(
                    '{"success": false, "message": "unknown option \'--userInput\'"}',
                    returncode=1,
                )
            if "search" in cmd:
                return _completed(SEARCH_JSON)
            return _completed(PLAY_STDOUT)

        with patch.object(nm, "ncm_cli_bin", return_value="/usr/bin/ncm-cli"):
            with patch.object(nm.subprocess, "run", side_effect=fake_run):
                with patch.object(nm, "enter_music_mode"):
                    nm.play_from_params(
                        {"song": "十年", "user_input": "播放十年"}
                    )
        self.assertTrue(any("--userInput" in c for c in calls))
        keyword_only = next(
            c for c in calls if "search" in c and "--userInput" not in c
        )
        self.assertEqual(
            keyword_only[1:],
            ["search", "song", "--keyword", "十年", "--limit", "10"],
        )

    def test_pick_exact_name_over_earlier_partial(self) -> None:
        records = [
            {"originalId": 1, "id": "a", "name": "披荆斩棘的夏天"},
            {"originalId": 2, "id": "b", "name": "披荆斩棘"},
            {"originalId": 3, "id": "c", "name": "斩棘"},
        ]
        picked = nm.pick_search_record(records, keyword="披荆斩棘", song="披荆斩棘")
        self.assertEqual(picked["originalId"], 2)

    def test_pick_highest_char_overlap(self) -> None:
        records = [
            {"originalId": 1, "id": "a", "name": "hello"},
            {"originalId": 2, "id": "b", "name": "斩棘"},
            {"originalId": 3, "id": "c", "name": "披荆斩棘之歌"},
        ]
        picked = nm.pick_search_record(records, keyword="披荆斩棘", song="披荆斩棘")
        self.assertEqual(picked["originalId"], 3)
        self.assertEqual(nm.char_overlap_score("披荆斩棘之歌", "披荆斩棘"), 4)
        self.assertEqual(nm.char_overlap_score("斩棘", "披荆斩棘"), 2)

    def test_search_limit_10_caches_all_hits(self) -> None:
        records = [
            {
                "originalId": 100 + i,
                "id": f"enc{i}",
                "name": "披荆斩棘" if i == 7 else f"披荆斩棘{i}",
                "artists": [{"name": "歌手"}],
            }
            for i in range(10)
        ]
        payload = json.dumps({"code": 200, "data": {"records": records}}, ensure_ascii=False)
        calls: list[list[str]] = []

        def fake_run(cmd, **_kwargs):
            calls.append(list(cmd))
            if "search" in cmd:
                self.assertEqual(cmd[-1], "10")
                return _completed(payload)
            return _completed(PLAY_STDOUT)

        with patch.object(nm, "ncm_cli_bin", return_value="/usr/bin/ncm-cli"):
            with patch.object(nm.subprocess, "run", side_effect=fake_run):
                with patch.object(nm, "enter_music_mode"):
                    nm.play_from_params({"song": "披荆斩棘"})
        self.assertEqual(ncm_store.get_song(107)["name"], "披荆斩棘")
        self.assertEqual(len(ncm_store.list_library(limit=20)), 10)
        self.assertIsNotNone(ncm_store.get_song(107)["played_at"])
        self.assertIsNone(ncm_store.get_song(100)["played_at"])

    def test_unavailable_without_cli(self) -> None:
        with patch.object(nm, "ncm_cli_bin", return_value=None):
            avail = nm.is_available()
            self.assertFalse(avail.ok)

    def test_artist_from_playlist_remainder(self) -> None:
        self.assertEqual(nm.artist_from_playlist_remainder("张三的歌"), "张三")
        self.assertEqual(nm.artist_from_playlist_remainder("周杰伦的歌曲"), "周杰伦")
        self.assertEqual(nm.artist_from_playlist_remainder("陈奕迅的十年"), "")
        self.assertEqual(nm.artist_from_playlist_remainder("我的歌声里"), "")
        self.assertEqual(nm.artist_from_playlist_remainder("的歌"), "")
        self.assertEqual(nm.artist_from_playlist_remainder("的歌曲"), "")

    def test_pick_search_record_by_artist_first_exact(self) -> None:
        records = [
            {"originalId": 1, "id": "a", "name": "十年", "artists": [{"name": "路人"}]},
            {"originalId": 2, "id": "b", "name": "浮夸", "artists": [{"name": "陈奕迅"}]},
            {"originalId": 3, "id": "c", "name": "K歌之王", "artists": [{"name": "陈奕迅"}]},
        ]
        picked = nm.pick_search_record_by_artist(records, artist="陈奕迅")
        self.assertEqual(picked["originalId"], 2)

    def test_pick_search_record_by_artist_overlap_then_title(self) -> None:
        records = [
            {"originalId": 1, "id": "a", "name": "hello", "artists": [{"name": "abc"}]},
            {"originalId": 2, "id": "b", "name": "周杰伦精选", "artists": [{"name": "周杰"}]},
        ]
        picked = nm.pick_search_record_by_artist(records, artist="周杰伦")
        self.assertEqual(picked["originalId"], 2)

    def test_play_exact_title_xxx_de_ge_skips_artist_search(self) -> None:
        records = [
            {
                "originalId": 200 + i,
                "id": f"encT{i}",
                "name": "张三的歌" if i == 4 else f"张三的歌谣{i}",
                "artists": [{"name": "路人" if i == 4 else "张三"}],
            }
            for i in range(10)
        ]
        payload = json.dumps({"code": 200, "data": {"records": records}}, ensure_ascii=False)
        calls: list[list[str]] = []

        def fake_run(cmd, **_kwargs):
            calls.append(list(cmd))
            if "search" in cmd:
                kw = cmd[cmd.index("--keyword") + 1]
                self.assertEqual(kw, "张三的歌")
                return _completed(payload)
            return _completed(PLAY_STDOUT)

        with patch.object(nm, "ncm_cli_bin", return_value="/usr/bin/ncm-cli"):
            with patch.object(nm.subprocess, "run", side_effect=fake_run):
                with patch.object(nm, "enter_music_mode"):
                    nm.play_from_params({"song": "张三的歌", "user_input": "播放张三的歌"})
        search_calls = [c for c in calls if "search" in c]
        self.assertEqual(len(search_calls), 1)
        self.assertEqual(ncm_store.get_song(204)["name"], "张三的歌")
        self.assertIsNotNone(ncm_store.get_song(204)["played_at"])
        self.assertEqual(len(ncm_store.list_library(limit=20)), 10)

    def test_play_xxx_de_ge_falls_back_to_artist(self) -> None:
        title_records = [
            {
                "originalId": 300 + i,
                "id": f"encA{i}",
                "name": f"无关歌名{i}",
                "artists": [{"name": "路人"}],
            }
            for i in range(10)
        ]
        artist_records = [
            {
                "originalId": 400 + i,
                "id": f"encB{i}",
                "name": f"艺人歌{i}",
                "artists": [{"name": "张三" if i == 1 else "路人"}],
            }
            for i in range(10)
        ]
        title_json = json.dumps(
            {"code": 200, "data": {"records": title_records}}, ensure_ascii=False
        )
        artist_json = json.dumps(
            {"code": 200, "data": {"records": artist_records}}, ensure_ascii=False
        )
        calls: list[list[str]] = []

        def fake_run(cmd, **_kwargs):
            calls.append(list(cmd))
            if "search" in cmd:
                kw = cmd[cmd.index("--keyword") + 1]
                if kw == "张三的歌":
                    return _completed(title_json)
                if kw == "张三":
                    return _completed(artist_json)
                self.fail(f"unexpected keyword {kw}")
            return _completed(PLAY_STDOUT)

        with patch.object(nm, "ncm_cli_bin", return_value="/usr/bin/ncm-cli"):
            with patch.object(nm.subprocess, "run", side_effect=fake_run):
                with patch.object(nm, "enter_music_mode"):
                    nm.play_from_params({"song": "张三的歌"})
        keywords = [
            c[c.index("--keyword") + 1] for c in calls if "search" in c
        ]
        self.assertEqual(keywords, ["张三的歌", "张三"])
        self.assertEqual(ncm_store.get_song(401)["name"], "艺人歌1")
        self.assertIsNotNone(ncm_store.get_song(401)["played_at"])
        self.assertIsNone(ncm_store.get_song(400)["played_at"])
        self.assertEqual(len(ncm_store.list_library(limit=40)), 20)

    def test_eason_de_shinian_is_title_search_not_playlist(self) -> None:
        calls: list[list[str]] = []

        def fake_run(cmd, **_kwargs):
            calls.append(list(cmd))
            if "search" in cmd:
                return _completed(SEARCH_JSON)
            return _completed(PLAY_STDOUT)

        with patch.object(nm, "ncm_cli_bin", return_value="/usr/bin/ncm-cli"):
            with patch.object(nm.subprocess, "run", side_effect=fake_run):
                with patch.object(nm, "enter_music_mode"):
                    nm.play_from_params({"song": "陈奕迅的十年"})
        search_calls = [c for c in calls if "search" in c]
        self.assertEqual(len(search_calls), 1)
        self.assertEqual(
            search_calls[0][search_calls[0].index("--keyword") + 1],
            "陈奕迅的十年",
        )


if __name__ == "__main__":
    unittest.main()
