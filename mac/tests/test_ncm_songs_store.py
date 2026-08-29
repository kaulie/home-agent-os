"""Mac Edge ncm_songs catalog."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mac_edge.ncm_songs import store as ncm_store
from mac_edge.ncm_songs.store import NcmSongsError


class NcmSongsStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "ncm_songs.sqlite3"
        ncm_store.reset(path=self.path)

    def tearDown(self) -> None:
        ncm_store.reset()
        self._tmp.cleanup()

    def test_init_and_upsert_by_original_id(self) -> None:
        with mock.patch.dict(os.environ, {"MAC_EDGE_DATA_DIR": self._tmp.name}):
            ncm_store.reset(path=None)
            ncm_store.init_db()
            record = {
                "id": "12345",
                "encrypted_id": "enc_abc",
                "name": "晴天",
                "artists": [{"name": "周杰伦"}],
                "album": "叶惠美",
            }
            oid = ncm_store.upsert_record(record)
            self.assertEqual(oid, "12345")

            got = ncm_store.get_song("12345")
            assert got is not None
            self.assertEqual(got["encrypted_id"], "enc_abc")
            self.assertEqual(got["name_norm"], ncm_store.normalize_text("晴天"))
            self.assertEqual(got["artist_norm"], ncm_store.normalize_text("周杰伦"))
            self.assertEqual(got["record"]["album"], "叶惠美")
            self.assertIsNone(got["played_at"])

            updated = dict(record)
            updated["encrypted_id"] = "enc_new"
            updated["name"] = "晴天 (Live)"
            ncm_store.upsert_record(updated)
            got2 = ncm_store.get_song("12345")
            assert got2 is not None
            self.assertEqual(got2["encrypted_id"], "enc_new")
            self.assertEqual(got2["name_norm"], ncm_store.normalize_text("晴天 (Live)"))

    def test_mark_played_and_recent(self) -> None:
        ncm_store.upsert_record({"id": "1", "name": "A", "artist": "X"})
        ncm_store.upsert_record({"id": "2", "name": "B", "artist": "Y"})
        ncm_store.mark_played("1", at=100.0)
        ncm_store.mark_played("2", at=200.0)
        recent = ncm_store.list_recent_played(limit=5)
        self.assertEqual([row["original_id"] for row in recent], ["2", "1"])

    def test_find_by_norm(self) -> None:
        ncm_store.upsert_record({"songId": "9", "name": "Hello", "artistName": "Adele"})
        hits = ncm_store.find_by_norm(
            name_norm=ncm_store.normalize_text("Hello"),
            artist_norm=ncm_store.normalize_text("Adele"),
        )
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["original_id"], "9")

    def test_missing_original_id_raises(self) -> None:
        with self.assertRaises(NcmSongsError):
            ncm_store.upsert_record({"name": "no id"})

    def test_db_path_under_mac_edge_data_dir(self) -> None:
        with mock.patch.dict(os.environ, {"MAC_EDGE_DATA_DIR": self._tmp.name}):
            ncm_store.reset(path=None)
            self.assertEqual(
                ncm_store.db_path().resolve(),
                (Path(self._tmp.name) / "ncm_songs.sqlite3").resolve(),
            )


if __name__ == "__main__":
    unittest.main()
