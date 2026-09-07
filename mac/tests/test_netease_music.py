"""ncm-cli NetEase plugin: search+play, local ncm_songs cache, transport controls."""

from __future__ import annotations

import json
import os
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

QUEUE_CLEAR_JSON = json.dumps({"success": True, "message": "cleared"})
QUEUE_ADD_JSON = json.dumps({"success": True, "message": "added"})
QUEUE_ADD_NOOP_JSON = json.dumps(
    {"success": True, "message": "云音乐播放队列为空（或无法读取）"}
)
PLAYLIST_CREATE_JSON = json.dumps(
    {
        "code": 200,
        "data": {
            "originalId": 18355129161,
            "id": "6F2F27DAB2DAF7F4DF9ACEFA18A5F212",
        },
    },
    ensure_ascii=False,
)
PLAYLIST_TRACKS_EMPTY_JSON = json.dumps({"code": 200, "data": []}, ensure_ascii=False)
PLAYLIST_ADD_OK_JSON = json.dumps({"code": 200, "data": ["x"]}, ensure_ascii=False)
PLAYLIST_REMOVE_OK_JSON = json.dumps({"code": 200, "data": True}, ensure_ascii=False)
PLAY_PLAYLIST_ORPHEUS = (
    "[orpheus] orpheus://eyJjbWQiOiJwbGF5IiwidHlwZSI6InBsYXlsaXN0IiwiaWQiOiIxODM1NTEyOTE2MSJ9\n"
)

PLAY_ISSUER = "iphone-origin"


def _completed(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["ncm-cli"],
        returncode=returncode,
        stdout=stdout,
        stderr="",
    )


def _ncm_action(cmd: list[str]) -> str:
    if len(cmd) < 2:
        return ""
    if cmd[1] == "search":
        return "search"
    if cmd[1] == "recommend":
        return "recommend"
    if cmd[1] == "queue" and len(cmd) > 2:
        return cmd[2]
    if cmd[1] == "playlist" and len(cmd) > 2:
        return f"playlist_{cmd[2]}"
    if cmd[1] == "play":
        return "play"
    return cmd[1]


def _playlist_play_response(cmd: list[str]) -> subprocess.CompletedProcess[str] | None:
    """Handle playlist CRUD + play --playlist used by artist/daily continuous play."""
    action = _ncm_action(cmd)
    if action == "playlist_create":
        return _completed(PLAYLIST_CREATE_JSON)
    if action == "playlist_tracks":
        return _completed(PLAYLIST_TRACKS_EMPTY_JSON)
    if action == "playlist_remove":
        return _completed(PLAYLIST_REMOVE_OK_JSON)
    if action == "playlist_add":
        return _completed(PLAYLIST_ADD_OK_JSON)
    if action == "play" and "--playlist" in cmd:
        return _completed(PLAY_PLAYLIST_ORPHEUS)
    return None


DAILY_JSON = json.dumps(
    {
        "code": 200,
        "data": [
            {
                "originalId": 4132379,
                "id": "C03EEFFC1E4FADF72D5EEB5894F720DF",
                "name": "I Hate Myself for Loving You",
                "artists": [{"name": "Joan Jett & the Blackhearts"}],
            },
            {
                "originalId": 1315441719,
                "id": "227DD9269B88C743F96B825D3B9B8D1D",
                "name": "Always Remember Us This Way",
                "artists": [{"name": "Lady Gaga"}],
            },
        ],
    },
    ensure_ascii=False,
)


class NeteaseMusicTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_data_dir = os.environ.get("MAC_EDGE_DATA_DIR")
        self._old_record = os.environ.get("MAC_EDGE_NCM_RECORD")
        os.environ["MAC_EDGE_DATA_DIR"] = self._tmp.name
        os.environ["MAC_EDGE_NCM_RECORD"] = "0"
        ncm_store.reset(path=Path(self._tmp.name) / "ncm_songs.sqlite3")

    def tearDown(self) -> None:
        ncm_store.reset()
        if self._old_data_dir is None:
            os.environ.pop("MAC_EDGE_DATA_DIR", None)
        else:
            os.environ["MAC_EDGE_DATA_DIR"] = self._old_data_dir
        if self._old_record is None:
            os.environ.pop("MAC_EDGE_NCM_RECORD", None)
        else:
            os.environ["MAC_EDGE_NCM_RECORD"] = self._old_record
        self._tmp.cleanup()

    def _with_issuer(self, params: dict) -> dict:
        out = {"participant_id": PLAY_ISSUER, "intent_id": "intent-test"}
        out.update(params)
        return out

    def _play_oids(self) -> list[int]:
        return [
            int(p["song_original_id"])
            for p in ncm_store.list_recent_played(limit=50)
        ]

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

    def test_play_bare_resume_when_possible(self) -> None:
        calls: list[list[str]] = []

        def fake_run(cmd, **_kwargs):
            calls.append(list(cmd))
            if cmd[1] == "resume":
                return _completed('{"success": true, "message": "已继续播放"}')
            self.fail(f"unexpected ncm-cli {cmd}")

        with patch.object(nm, "ncm_cli_bin", return_value="/usr/bin/ncm-cli"):
            with patch.object(nm.subprocess, "run", side_effect=fake_run):
                with patch.object(nm, "enter_music_mode") as enter:
                    msg, outputs = nm.play_from_params(
                        self._with_issuer({"user_input": "播放音乐"})
                    )
        self.assertEqual(msg, "已继续播放")
        self.assertEqual(outputs.get("bare_mode"), "resume")
        self.assertEqual([c[1] for c in calls], ["resume"])
        enter.assert_called_once()

    def test_play_bare_daily_when_resume_fails(self) -> None:
        calls: list[list[str]] = []

        def fake_run(cmd, **_kwargs):
            calls.append(list(cmd))
            action = _ncm_action(cmd)
            if action == "resume":
                return _completed(
                    '{"success": false, "message": "播放列表为空，请先使用 play 命令播放歌曲"}'
                )
            if action == "recommend":
                return _completed(DAILY_JSON)
            pl = _playlist_play_response(cmd)
            if pl is not None:
                return pl
            self.fail(f"unexpected ncm-cli {cmd}")

        with patch.object(nm, "ncm_cli_bin", return_value="/usr/bin/ncm-cli"):
            with patch.object(nm.subprocess, "run", side_effect=fake_run):
                with patch.object(nm, "enter_music_mode"):
                    msg, outputs = nm.play_from_params(
                        self._with_issuer({"user_input": "播放音乐"})
                    )
        self.assertIn("歌单", msg)
        self.assertEqual(outputs.get("bare_mode"), "daily")
        self.assertEqual(outputs.get("queue_count"), 2)
        self.assertEqual(outputs.get("queue_added"), 1)
        self.assertEqual(calls[0][1], "resume")
        self.assertEqual(calls[1][1:], ["recommend", "daily", "--limit", "20"])
        actions = [_ncm_action(c) for c in calls]
        self.assertIn("playlist_create", actions)
        self.assertIn("playlist_add", actions)
        self.assertTrue(any("--playlist" in c for c in calls if c[1] == "play"))
        self.assertEqual(self._play_oids(), [4132379])

    def test_play_bare_fails_when_resume_and_daily_fail(self) -> None:
        def fake_run(cmd, **_kwargs):
            if cmd[1] == "resume":
                return _completed(
                    '{"success": false, "message": "播放列表为空"}'
                )
            if cmd[1] == "recommend":
                return _completed('{"code": 500, "message": "fail", "data": []}')
            self.fail(f"unexpected ncm-cli {cmd}")

        with patch.object(nm, "ncm_cli_bin", return_value="/usr/bin/ncm-cli"):
            with patch.object(nm.subprocess, "run", side_effect=fake_run):
                with self.assertRaises(nm.NeteaseMusicError) as ctx:
                    nm.play_from_params({})
        self.assertIn("无法开播", str(ctx.exception))

    def test_queue_add_rejects_orpheus_noop(self) -> None:
        def fake_run(cmd, **_kwargs):
            if _ncm_action(cmd) == "add":
                return _completed(QUEUE_ADD_NOOP_JSON)
            self.fail(f"unexpected ncm-cli {cmd}")

        with patch.object(nm, "ncm_cli_bin", return_value="/usr/bin/ncm-cli"):
            with patch.object(nm.subprocess, "run", side_effect=fake_run):
                with self.assertRaises(nm.NeteaseMusicError) as ctx:
                    nm.queue_add(
                        {
                            "id": "1B8FCF799FD5895F6F0586C7D19A0A3B",
                            "originalId": 66842,
                        }
                    )
        self.assertIn("无法读取", str(ctx.exception))

    def test_play_artist_only_artist_queue(self) -> None:
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
            {
                "originalId": 66843,
                "id": "encC",
                "name": "K歌之王",
                "artists": [{"name": "陈奕迅"}],
            },
        ]
        payload = json.dumps({"code": 200, "data": {"records": records}}, ensure_ascii=False)
        calls: list[list[str]] = []

        def fake_run(cmd, **_kwargs):
            calls.append(list(cmd))
            if _ncm_action(cmd) == "search":
                return _completed(payload)
            pl = _playlist_play_response(cmd)
            if pl is not None:
                return pl
            self.fail(f"unexpected ncm-cli {cmd}")

        with patch.object(nm, "ncm_cli_bin", return_value="/usr/bin/ncm-cli"):
            with patch.object(nm.subprocess, "run", side_effect=fake_run):
                with patch.object(nm, "enter_music_mode"):
                    msg, outputs = nm.play_from_params({"artist": "陈奕迅"})
        keywords = [
            c[c.index("--keyword") + 1] for c in calls if _ncm_action(c) == "search"
        ]
        self.assertEqual(keywords, ["陈奕迅"])
        actions = [_ncm_action(c) for c in calls]
        self.assertEqual(actions[0], "search")
        self.assertIn("playlist_create", actions)
        self.assertIn("playlist_add", actions)
        self.assertTrue(any("--playlist" in c for c in calls if c[1] == "play"))
        self.assertNotIn("add", actions)  # desktop queue add unused
        self.assertEqual(outputs.get("queue_count"), 2)
        self.assertEqual(outputs.get("queue_added"), 1)
        self.assertIn("歌单", msg)
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
                    msg, outputs = nm.play_from_params(
                        self._with_issuer({"song": "十年", "artist": "陈奕迅"})
                    )
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
                    self.assertIsNone(got["played_at"])
                    self.assertEqual(self._play_oids(), [66842])
                    self.assertEqual(
                        ncm_store.list_recent_played()[0]["participant_id"],
                        PLAY_ISSUER,
                    )
                    indexed = ncm_store.get_index_song(66842)
                    assert indexed is not None
                    self.assertEqual(indexed["song_encrypted_id"], "1B8FCF799FD5895F6F0586C7D19A0A3B")
                    self.assertEqual(indexed["duration"], 205423)
                    self.assertEqual(indexed["album_original_id"], 6548)
                    self.assertEqual(indexed["album_name"], "黑白灰")
                    self.assertEqual(indexed["album_encrypted_id"], "6AF3D73514E9BBA48FC1B1F0AA0A5D75")

                    calls.clear()
                    msg2, outputs2 = nm.play_from_params(
                        self._with_issuer({"song": "十年", "artist": "陈奕迅"})
                    )
                    self.assertIn("66842", msg2)
                    self.assertEqual(outputs2["timing"]["search"], 0)
                    self.assertTrue(any("play" in c for c in calls))
                    self.assertFalse(any("search" in c for c in calls))
                    self.assertEqual(self._play_oids(), [66842, 66842])
                    nm.run_from_params("music.next", {})
                    self.assertEqual(self._play_oids(), [66842, 66842])
                    nm.play_from_params({"song": "十年", "artist": "陈奕迅"})
                    self.assertEqual(self._play_oids(), [66842, 66842])

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
                self.assertEqual(self._play_oids(), [])
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

    def test_resume_empty_queue_falls_back_to_daily(self) -> None:
        calls: list[list[str]] = []

        def fake_run(cmd, **_kwargs):
            calls.append(list(cmd))
            action = _ncm_action(cmd)
            if action == "resume":
                return _completed(
                    '{"success": false, "message": "播放列表为空，请先使用 play 命令播放歌曲"}'
                )
            if action == "recommend":
                return _completed(DAILY_JSON)
            pl = _playlist_play_response(cmd)
            if pl is not None:
                return pl
            self.fail(f"unexpected ncm-cli {cmd}")

        with patch.object(nm, "ncm_cli_bin", return_value="/usr/bin/ncm-cli"):
            with patch.object(nm.subprocess, "run", side_effect=fake_run):
                with patch.object(nm, "enter_music_mode"):
                    msg, outputs = nm.run_from_params(
                        "music.resume",
                        self._with_issuer({}),
                    )
        self.assertEqual(msg, "无可继续，已改播每日推荐")
        self.assertEqual(outputs.get("resume_fallback"), "daily")
        self.assertEqual(outputs.get("bare_mode"), "daily")
        self.assertEqual(outputs.get("queue_count"), 2)
        self.assertEqual(calls[0][1], "resume")
        self.assertEqual(calls[1][1:], ["recommend", "daily", "--limit", "20"])
        self.assertTrue(any("--playlist" in c for c in calls if c[1] == "play"))

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
                    nm.play_from_params(self._with_issuer({"song": "披荆斩棘"}))
        self.assertEqual(ncm_store.get_song(107)["name"], "披荆斩棘")
        self.assertEqual(len(ncm_store.list_library(limit=20)), 10)
        self.assertIsNone(ncm_store.get_song(107)["played_at"])
        self.assertIsNone(ncm_store.get_song(100)["played_at"])
        self.assertEqual(self._play_oids(), [107])

    def test_unavailable_without_cli(self) -> None:
        with patch.object(nm, "ncm_cli_bin", return_value=None):
            avail = nm.is_available()
            self.assertFalse(avail.ok)

    def test_artist_from_playlist_remainder(self) -> None:
        self.assertEqual(nm.artist_from_playlist_remainder("张三的歌"), "张三")
        self.assertEqual(nm.artist_from_playlist_remainder("周杰伦的歌曲"), "周杰伦")
        self.assertEqual(nm.artist_from_playlist_remainder("几首周杰伦的歌"), "周杰伦")
        self.assertEqual(nm.artist_from_playlist_remainder("3首周杰伦的歌"), "周杰伦")
        self.assertEqual(nm.artist_from_playlist_remainder("陈奕迅的十年"), "")
        self.assertEqual(nm.artist_from_playlist_remainder("我的歌声里"), "")
        self.assertEqual(nm.artist_from_playlist_remainder("的歌"), "")
        self.assertEqual(nm.artist_from_playlist_remainder("的歌曲"), "")

    def test_strip_leading_quantity(self) -> None:
        self.assertEqual(
            nm.strip_leading_quantity("几首周杰伦的歌"),
            ("周杰伦的歌", 5),
        )
        self.assertEqual(
            nm.strip_leading_quantity("3首五月天的歌"),
            ("五月天的歌", 3),
        )
        self.assertEqual(nm.strip_leading_quantity("周杰伦的歌"), ("周杰伦的歌", None))

    def test_play_ji_shou_artist_queue_limit_5(self) -> None:
        records = [
            {
                "originalId": 100 + i,
                "id": f"enc{i}",
                "name": f"song{i}",
                "artists": [{"name": "周杰伦"}],
            }
            for i in range(10)
        ]
        payload = json.dumps({"code": 200, "data": {"records": records}}, ensure_ascii=False)
        calls: list[list[str]] = []

        def fake_run(cmd, **_kwargs):
            calls.append(list(cmd))
            if _ncm_action(cmd) == "search":
                return _completed(payload)
            pl = _playlist_play_response(cmd)
            if pl is not None:
                return pl
            self.fail(f"unexpected ncm-cli {cmd}")

        with patch.object(nm, "ncm_cli_bin", return_value="/usr/bin/ncm-cli"):
            with patch.object(nm.subprocess, "run", side_effect=fake_run):
                with patch.object(nm, "enter_music_mode"):
                    msg, outputs = nm.play_from_params(
                        self._with_issuer(
                            {
                                "song": "几首周杰伦的歌",
                                "user_input": "放几首周杰伦的歌",
                            }
                        )
                    )
        self.assertEqual(outputs.get("queue_count"), 5)
        self.assertEqual(outputs.get("queue_added"), 4)
        search = next(c for c in calls if _ncm_action(c) == "search")
        # keyword must be artist only (not 「几首周杰伦」); no --userInput
        kw_idx = search.index("--keyword")
        self.assertEqual(search[kw_idx + 1], "周杰伦")
        self.assertNotIn("--userInput", search)
        self.assertEqual(search[search.index("--limit") + 1], "20")
        self.assertTrue(any("--playlist" in c for c in calls if c[1] == "play"))

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

    def test_play_xxx_de_ge_artist_queue(self) -> None:
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
            action = _ncm_action(cmd)
            if action == "search":
                kw = cmd[cmd.index("--keyword") + 1]
                self.assertEqual(kw, "张三")
                self.assertEqual(cmd[cmd.index("--limit") + 1], "20")
                self.assertNotIn("--userInput", cmd)
                return _completed(payload)
            pl = _playlist_play_response(cmd)
            if pl is not None:
                return pl
            self.fail(f"unexpected ncm-cli {cmd}")

        with patch.object(nm, "ncm_cli_bin", return_value="/usr/bin/ncm-cli"):
            with patch.object(nm.subprocess, "run", side_effect=fake_run):
                with patch.object(nm, "enter_music_mode"):
                    msg, outputs = nm.play_from_params(
                        self._with_issuer(
                            {"song": "张三的歌", "user_input": "播放张三的歌"}
                        )
                    )
        search_calls = [c for c in calls if _ncm_action(c) == "search"]
        self.assertEqual(len(search_calls), 1)
        actions = [_ncm_action(c) for c in calls]
        self.assertEqual(actions[0], "search")
        self.assertIn("playlist_create", actions)
        self.assertIn("playlist_add", actions)
        self.assertTrue(any("--playlist" in c for c in calls if c[1] == "play"))
        self.assertEqual(outputs.get("queue_count"), 9)
        self.assertEqual(outputs.get("queue_added"), 8)
        self.assertIn("歌单", msg)
        self.assertEqual(ncm_store.get_song(200)["name"], "张三的歌谣0")
        self.assertEqual(self._play_oids(), [200])

    def test_play_title_only_skips_queue_clear(self) -> None:
        calls: list[list[str]] = []

        def fake_run(cmd, **_kwargs):
            calls.append(list(cmd))
            if _ncm_action(cmd) == "search":
                return _completed(SEARCH_JSON)
            return _completed(PLAY_STDOUT)

        with patch.object(nm, "ncm_cli_bin", return_value="/usr/bin/ncm-cli"):
            with patch.object(nm.subprocess, "run", side_effect=fake_run):
                with patch.object(nm, "enter_music_mode"):
                    nm.play_from_params(
                        self._with_issuer({"song": "十年", "artist": "陈奕迅"})
                    )
        actions = [_ncm_action(c) for c in calls]
        self.assertEqual(actions, ["search", "play"])
        self.assertNotIn("clear", actions)
        self.assertNotIn("add", actions)
        self.assertFalse(any("--playlist" in c for c in calls))

    def test_play_xxx_de_ge_single_artist_match(self) -> None:
        artist_records = [
            {
                "originalId": 400 + i,
                "id": f"encB{i}",
                "name": f"艺人歌{i}",
                "artists": [{"name": "张三" if i == 1 else "路人"}],
            }
            for i in range(10)
        ]
        artist_json = json.dumps(
            {"code": 200, "data": {"records": artist_records}}, ensure_ascii=False
        )
        calls: list[list[str]] = []

        def fake_run(cmd, **_kwargs):
            calls.append(list(cmd))
            action = _ncm_action(cmd)
            if action == "search":
                kw = cmd[cmd.index("--keyword") + 1]
                self.assertEqual(kw, "张三")
                return _completed(artist_json)
            if action == "clear":
                return _completed(QUEUE_CLEAR_JSON)
            if action == "play" and "--song" in cmd:
                return _completed(PLAY_STDOUT)
            self.fail(f"unexpected ncm-cli {cmd}")

        with patch.object(nm, "ncm_cli_bin", return_value="/usr/bin/ncm-cli"):
            with patch.object(nm.subprocess, "run", side_effect=fake_run):
                with patch.object(nm, "enter_music_mode"):
                    nm.play_from_params(self._with_issuer({"song": "张三的歌"}))
        keywords = [
            c[c.index("--keyword") + 1] for c in calls if _ncm_action(c) == "search"
        ]
        self.assertEqual(keywords, ["张三"])
        actions = [_ncm_action(c) for c in calls]
        self.assertEqual(actions, ["search", "clear", "play"])
        self.assertFalse(any("--playlist" in c for c in calls))
        self.assertEqual(ncm_store.get_song(401)["name"], "艺人歌1")
        self.assertEqual(self._play_oids(), [401])
        self.assertIsNone(ncm_store.get_song(400)["played_at"])
        self.assertEqual(len(ncm_store.list_library(limit=40)), 10)

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

    def test_clamp_cache_count(self) -> None:
        self.assertEqual(nm.clamp_cache_count(None), 100)
        self.assertEqual(nm.clamp_cache_count(""), 100)
        self.assertEqual(nm.clamp_cache_count("x"), 100)
        self.assertEqual(nm.clamp_cache_count(50), 50)
        self.assertEqual(nm.clamp_cache_count("50"), 50)
        self.assertEqual(nm.clamp_cache_count(0), 1)
        self.assertEqual(nm.clamp_cache_count(500), 200)

    def _cache_page_json(self, offset: int, *, artist: str, n: int = 20) -> str:
        records = [
            {
                "originalId": 5000 + offset + i,
                "id": f"encC{offset + i}",
                "name": f"冰雨{offset + i}",
                "artists": [{"name": artist}],
            }
            for i in range(n)
        ]
        return json.dumps({"code": 200, "data": {"records": records}}, ensure_ascii=False)

    def test_cache_pages_limit_20_no_play(self) -> None:
        sleeps: list[float] = []
        calls: list[list[str]] = []

        def fake_run(cmd, **_kwargs):
            calls.append(list(cmd))
            if "play" in cmd:
                self.fail("music.cache must not play")
            self.assertEqual(cmd[cmd.index("--limit") + 1], "20")
            offset = int(cmd[cmd.index("--offset") + 1])
            return _completed(self._cache_page_json(offset, artist="刘德华"))

        with patch.object(nm, "ncm_cli_bin", return_value="/usr/bin/ncm-cli"):
            with patch.object(nm.subprocess, "run", side_effect=fake_run):
                with patch.object(nm.time, "sleep", side_effect=lambda s: sleeps.append(s)):
                    msg, outputs = nm.run_from_params(
                        "music.cache",
                        {"song": "冰雨", "count": 50},
                    )
        self.assertIn("未下载音频", msg)
        self.assertEqual(outputs.get("cached"), 50)
        search_calls = [c for c in calls if "search" in c]
        self.assertEqual(len(search_calls), 3)
        self.assertEqual(
            [int(c[c.index("--offset") + 1]) for c in search_calls],
            [0, 20, 40],
        )
        self.assertEqual(sleeps, [10.0, 10.0])
        # Last page is fully upserted (20) even though count stops at 50.
        self.assertEqual(len(ncm_store.list_library(limit=80)), 60)
        self.assertIsNone(ncm_store.get_song(5000)["played_at"])
        self.assertEqual(self._play_oids(), [])

    def test_cache_fetch_audio_still_index_only(self) -> None:
        calls: list[list[str]] = []

        def fake_run(cmd, **_kwargs):
            calls.append(list(cmd))
            if "play" in cmd:
                self.fail("music.cache must not play")
            return _completed(self._cache_page_json(0, artist="刘德华", n=1))

        with patch.object(nm, "ncm_cli_bin", return_value="/usr/bin/ncm-cli"):
            with patch.object(nm.subprocess, "run", side_effect=fake_run):
                with patch.object(nm.time, "sleep"):
                    msg, outputs = nm.cache_from_params(
                        {"song": "冰雨", "count": 1, "fetch_audio": True}
                    )
        self.assertIn("未下载音频", msg)
        self.assertEqual(outputs.get("fetch_audio"), False)
        self.assertFalse(any("play" in c for c in calls))

    def test_cache_playlist_then_play_hits_artist_without_search(self) -> None:
        title_records = [
            {
                "originalId": 7000 + i,
                "id": f"encT{i}",
                "name": f"无关歌名{i}",
                "artists": [{"name": "路人"}],
            }
            for i in range(20)
        ]
        artist_records = [
            {
                "originalId": 8000 + i,
                "id": f"encL{i}",
                "name": f"天意{i}",
                "artists": [{"name": "刘德华"}],
            }
            for i in range(20)
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
            action = _ncm_action(cmd)
            if action == "search":
                kw = cmd[cmd.index("--keyword") + 1]
                self.assertEqual(cmd[cmd.index("--limit") + 1], "20")
                if kw == "刘德华的歌":
                    return _completed(title_json)
                if kw == "刘德华":
                    return _completed(artist_json)
                self.fail(f"unexpected keyword {kw}")
            pl = _playlist_play_response(cmd)
            if pl is not None:
                return pl
            self.fail(f"unexpected ncm cmd {cmd}")

        with patch.object(nm, "ncm_cli_bin", return_value="/usr/bin/ncm-cli"):
            with patch.object(nm.subprocess, "run", side_effect=fake_run):
                with patch.object(nm.time, "sleep"):
                    with patch.object(nm, "enter_music_mode"):
                        cache_msg, cache_out = nm.cache_from_params(
                            {"song": "刘德华的歌", "count": 20}
                        )
                        self.assertIn("未下载音频", cache_msg)
                        self.assertEqual(cache_out.get("cached"), 20)
                        self.assertFalse(any("play" in c for c in calls))
                        calls.clear()
                        _msg, outputs = nm.play_from_params(
                            self._with_issuer({"song": "刘德华的歌"})
                        )
        search_calls = [c for c in calls if _ncm_action(c) == "search"]
        self.assertEqual(len(search_calls), 0)
        self.assertTrue(any("--playlist" in c for c in calls if c[1] == "play"))
        self.assertIn("playlist_add", [_ncm_action(c) for c in calls])
        self.assertEqual(outputs.get("queue_count"), 20)
        plays = ncm_store.list_recent_played()
        self.assertEqual(len(plays), 1)
        hit = int(plays[0]["song_original_id"])
        self.assertTrue(8000 <= hit < 8020)
        self.assertEqual(plays[0]["participant_id"], PLAY_ISSUER)
        self.assertIsNone(ncm_store.get_song(hit)["played_at"])
        self.assertIsNone(ncm_store.get_song(7000)["played_at"])

    def test_solo_first_ranks_collabs_after_solos(self) -> None:
        records = [
            {
                "originalId": 1,
                "id": "c1",
                "name": "合唱A",
                "artists": [{"name": "王力宏"}, {"name": "谭维维"}],
            },
            {
                "originalId": 2,
                "id": "s1",
                "name": "单曲A",
                "artists": [{"name": "王力宏"}],
            },
            {
                "originalId": 3,
                "id": "c2",
                "name": "三人",
                "artists": [
                    {"name": "李荣浩"},
                    {"name": "王力宏"},
                    {"name": "某人"},
                ],
            },
            {
                "originalId": 4,
                "id": "s2",
                "name": "单曲B",
                "artists": [{"name": "王力宏"}],
            },
            {
                "originalId": 5,
                "id": "d2",
                "name": "合唱B",
                "artists": [{"name": "王力宏"}, {"name": "某人"}],
            },
        ]
        ranked = nm.apply_artist_queue_strategy(
            records, artist="王力宏", strategy="solo_first"
        )
        # fewer artists first; stable within same count → 2,4 then 1,5 then 3
        self.assertEqual([r["originalId"] for r in ranked], [2, 4, 1, 5, 3])
        api = nm.apply_artist_queue_strategy(
            records, artist="王力宏", strategy="api_order"
        )
        self.assertEqual([r["originalId"] for r in api], [1, 2, 3, 4, 5])

    def test_collect_artist_queue_solo_first_default(self) -> None:
        page = [
            {
                "originalId": 10,
                "id": "c",
                "name": "合唱",
                "artists": [{"name": "王力宏"}, {"name": "某人"}],
            },
            {
                "originalId": 11,
                "id": "s",
                "name": "单人",
                "artists": [{"name": "王力宏"}],
            },
        ]
        payload = json.dumps({"code": 200, "data": {"records": page}}, ensure_ascii=False)

        def fake_run(cmd, **_kwargs):
            if _ncm_action(cmd) == "search":
                return _completed(payload)
            self.fail(f"unexpected {cmd}")

        with patch.object(nm, "ncm_cli_bin", return_value="/usr/bin/ncm-cli"):
            with patch.object(nm.subprocess, "run", side_effect=fake_run):
                got = nm.collect_artist_queue_records(artist="王力宏", limit=2)
        self.assertEqual([r["originalId"] for r in got], [11, 10])
        self.assertTrue(nm.is_solo_for_artist(got[0], artist="王力宏"))

    def test_collect_artist_queue_pages_until_full_max_5(self) -> None:
        """Sparse per-page matches → keep paging; cap at 5 pages; rank by count."""

        def page_records(page_i: int) -> list[dict[str, Any]]:
            # Each search page has 20 hits; only 3 match 王力宏 (mix of solo/duet).
            out: list[dict[str, Any]] = []
            for j in range(20):
                oid = page_i * 100 + j
                if j < 3:
                    artists: list[dict[str, str]] = [{"name": "王力宏"}]
                    if j == 0:
                        artists.append({"name": "合唱"})
                    out.append(
                        {
                            "originalId": oid,
                            "id": f"e{oid}",
                            "name": f"歌{oid}",
                            "artists": artists,
                        }
                    )
                else:
                    out.append(
                        {
                            "originalId": oid,
                            "id": f"x{oid}",
                            "name": f"其他{oid}",
                            "artists": [{"name": "路人"}],
                        }
                    )
            return out

        offsets: list[int] = []

        def fake_run(cmd, **_kwargs):
            if _ncm_action(cmd) != "search":
                self.fail(f"unexpected {cmd}")
            off = int(cmd[cmd.index("--offset") + 1]) if "--offset" in cmd else 0
            offsets.append(off)
            page_i = off // 20
            payload = json.dumps(
                {"code": 200, "data": {"records": page_records(page_i)}},
                ensure_ascii=False,
            )
            return _completed(payload)

        with patch.object(nm, "ncm_cli_bin", return_value="/usr/bin/ncm-cli"):
            with patch.object(nm.subprocess, "run", side_effect=fake_run):
                got = nm.collect_artist_queue_records(artist="王力宏", limit=20)
        # 3 matches/page → need 7 pages for 20, but cap is 5 → 15 songs
        self.assertEqual(len(offsets), 5)
        self.assertEqual(offsets, [0, 20, 40, 60, 80])
        self.assertEqual(len(got), 15)
        # solos (j=1,2 per page) before duets (j=0)
        self.assertTrue(all(nm.is_solo_for_artist(r, artist="王力宏") for r in got[:10]))
        self.assertFalse(nm.is_solo_for_artist(got[10], artist="王力宏"))


if __name__ == "__main__":
    unittest.main()
