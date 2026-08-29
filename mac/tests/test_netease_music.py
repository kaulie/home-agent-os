"""Mac Edge netease.music via ncm-cli + ncm_songs catalog."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mac_edge.ncm_songs import store as ncm_store
from mac_edge.plugins.netease_music import (
    NeteaseMusicError,
    play_from_params,
    run_from_params,
)


class NeteaseMusicTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        ncm_store.reset(path=Path(self._tmp.name) / "ncm_songs.sqlite3")
        os.environ["MAC_EDGE_NCM_CLI"] = "/fake/ncm-cli"

    def tearDown(self) -> None:
        ncm_store.reset()
        os.environ.pop("MAC_EDGE_NCM_CLI", None)
        self._tmp.cleanup()

    def _search_payload(self) -> str:
        return json.dumps(
            {
                "code": 200,
                "data": {
                    "songs": [
                        {
                            "originalId": 18614888,
                            "id": "FDBBB5606444F2B5A6042ED5D40A43CD",
                            "name": "十年",
                            "artists": [{"name": "陈奕迅"}],
                        }
                    ],
                },
            }
        )

    def test_play_searches_and_upserts(self) -> None:
        play_payload = json.dumps({"success": True, "message": "playing"})
        with mock.patch("subprocess.run") as run:
            run.side_effect = [
                mock.Mock(returncode=0, stdout=self._search_payload(), stderr=""),
                mock.Mock(returncode=0, stdout=play_payload, stderr=""),
            ]
            msg, outputs = play_from_params({"song": "十年", "artist": "陈奕迅"})
        self.assertIn("music.play", msg)
        self.assertEqual(outputs["song"], "十年")
        self.assertEqual(outputs["original_id"], 18614888)
        got = ncm_store.get_song(18614888)
        assert got is not None
        self.assertEqual(got["name"], "十年")
        self.assertIsNotNone(got["played_at"])

    def test_play_uses_catalog_cache(self) -> None:
        ncm_store.upsert_record(
            {
                "originalId": 1,
                "id": "enc1",
                "name": "晴天",
                "artists": [{"name": "周杰伦"}],
            }
        )
        play_payload = json.dumps({"success": True, "message": "playing"})
        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(
                returncode=0,
                stdout=play_payload,
                stderr="",
            )
            msg, outputs = play_from_params({"song": "晴天", "artist": "周杰伦"})
        self.assertIn("晴天", msg)
        self.assertEqual(outputs["original_id"], 1)
        run.assert_called_once()

    def test_pause_transport(self) -> None:
        payload = json.dumps({"success": True, "message": "paused"})
        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0, stdout=payload, stderr="")
            msg, outputs = run_from_params("music.pause", {})
        self.assertIn("music.pause", msg)
        self.assertEqual(outputs, {})

    def test_missing_params(self) -> None:
        with self.assertRaises(NeteaseMusicError):
            play_from_params({})


if __name__ == "__main__":
    unittest.main()
