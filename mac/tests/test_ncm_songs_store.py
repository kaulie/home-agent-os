"""Mac Edge ncm_songs catalog."""

from __future__ import annotations

import os
import sqlite3
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

    def _record(self, **overrides: object) -> dict:
        base = {
            "originalId": 12345,
            "id": "ncm_enc_id_abc",
            "name": "晴天",
            "artists": [{"name": "周杰伦"}],
            "album": "叶惠美",
        }
        base.update(overrides)
        return base

    def test_init_creates_table_and_indexes(self) -> None:
        ncm_store.init_db()
        conn = sqlite3.connect(str(self.path))
        try:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(ncm_songs)")}
            self.assertEqual(
                cols,
                {
                    "original_id",
                    "encrypted_id",
                    "name",
                    "name_norm",
                    "artist",
                    "artist_norm",
                    "record_json",
                    "played_at",
                },
            )
            indexes = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='ncm_songs'"
                )
            }
            self.assertIn("idx_ncm_songs_name_norm", indexes)
            self.assertIn("idx_ncm_songs_artist_norm", indexes)
        finally:
            conn.close()

    def test_upsert_by_original_id(self) -> None:
        oid = ncm_store.upsert_record(self._record())
        self.assertEqual(oid, 12345)

        got = ncm_store.get_song(12345)
        assert got is not None
        self.assertEqual(got["encrypted_id"], "ncm_enc_id_abc")
        self.assertEqual(got["name"], "晴天")
        self.assertEqual(got["artist"], "周杰伦")
        self.assertEqual(got["name_norm"], ncm_store.normalize_text("晴天"))
        self.assertEqual(got["record"]["album"], "叶惠美")
        self.assertIsNone(got["played_at"])

        ncm_store.upsert_record(self._record(id="ncm_new", name="晴天 (Live)"))
        got2 = ncm_store.get_song(12345)
        assert got2 is not None
        self.assertEqual(got2["encrypted_id"], "ncm_new")
        self.assertEqual(got2["name"], "晴天 (Live)")

    def test_mark_played_and_find_by_norm(self) -> None:
        ncm_store.upsert_record(
            self._record(originalId=1, id="a", name="Hello", artists=[{"name": "Adele"}])
        )
        ncm_store.upsert_record(
            self._record(originalId=2, id="b", name="World", artists=[{"name": "Someone"}])
        )
        ncm_store.mark_played(1, at=100.0)

        hits = ncm_store.find_by_name_artist(name="Hello", artist="Adele")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["original_id"], 1)
        self.assertEqual(hits[0]["played_at"], 100.0)

        only_name = ncm_store.find_by_norm(name_norm=ncm_store.normalize_text("World"))
        self.assertEqual(len(only_name), 1)
        self.assertEqual(only_name[0]["original_id"], 2)

    def test_missing_fields_raise(self) -> None:
        with self.assertRaises(NcmSongsError):
            ncm_store.upsert_record({"name": "no originalId"})
        with self.assertRaises(NcmSongsError):
            ncm_store.upsert_record({"originalId": 9, "name": "x"})

    def test_db_path_under_mac_edge_data_dir(self) -> None:
        with mock.patch.dict(os.environ, {"MAC_EDGE_DATA_DIR": self._tmp.name}):
            ncm_store.reset(path=None)
            self.assertEqual(
                ncm_store.db_path().resolve(),
                (Path(self._tmp.name) / "ncm_songs.sqlite3").resolve(),
            )


if __name__ == "__main__":
    unittest.main()
