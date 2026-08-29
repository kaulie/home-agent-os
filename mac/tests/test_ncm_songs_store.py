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
            "duration": 269000,
            "artists": [{"name": "周杰伦"}],
            "album": {
                "originalId": 18625,
                "id": "ALBUM_ENC_YEHUIMEI",
                "name": "叶惠美",
            },
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
            idx_cols = {row[1] for row in conn.execute("PRAGMA table_info(ncm_song_index)")}
            self.assertEqual(
                idx_cols,
                {
                    "song_original_id",
                    "song_name",
                    "song_name_norm",
                    "song_encrypted_id",
                    "duration",
                    "artist",
                    "artist_norm",
                    "album_original_id",
                    "album_name",
                    "album_encrypted_id",
                },
            )
            idx_indexes = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master"
                    " WHERE type='index' AND tbl_name='ncm_song_index'"
                )
            }
            self.assertIn("idx_ncm_song_index_song_name", idx_indexes)
            self.assertIn("idx_ncm_song_index_artist", idx_indexes)
            self.assertIn("idx_ncm_song_index_album_original_id", idx_indexes)
            self.assertIn("idx_ncm_song_index_name_artist", idx_indexes)
            versions = {
                int(row[0])
                for row in conn.execute("SELECT version FROM schema_migrations")
            }
            self.assertIn(3, versions)
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
        self.assertEqual(got["record"]["album"]["name"], "叶惠美")
        self.assertIsNone(got["played_at"])

        indexed = ncm_store.get_index_song(12345)
        assert indexed is not None
        self.assertEqual(indexed["song_encrypted_id"], "ncm_enc_id_abc")
        self.assertEqual(indexed["song_name"], "晴天")
        self.assertEqual(indexed["duration"], 269000)
        self.assertEqual(indexed["artist"], "周杰伦")
        self.assertEqual(indexed["album_original_id"], 18625)
        self.assertEqual(indexed["album_name"], "叶惠美")
        self.assertEqual(indexed["album_encrypted_id"], "ALBUM_ENC_YEHUIMEI")

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

    def test_index_missing_album_and_duration_are_null(self) -> None:
        ncm_store.upsert_record(
            {
                "originalId": 9,
                "id": "enc9",
                "name": "无名",
                "artists": [{"name": "佚名"}],
            }
        )
        indexed = ncm_store.get_index_song(9)
        assert indexed is not None
        self.assertIsNone(indexed["duration"])
        self.assertIsNone(indexed["album_original_id"])
        self.assertIsNone(indexed["album_name"])
        self.assertIsNone(indexed["album_encrypted_id"])

    def test_index_string_album_maps_name_only(self) -> None:
        ncm_store.upsert_record(
            self._record(album="叶惠美", duration=None)
        )
        indexed = ncm_store.get_index_song(12345)
        assert indexed is not None
        self.assertEqual(indexed["album_name"], "叶惠美")
        self.assertIsNone(indexed["album_original_id"])
        self.assertIsNone(indexed["album_encrypted_id"])
        self.assertIsNone(indexed["duration"])

    def test_find_prefers_index_table(self) -> None:
        ncm_store.upsert_record(self._record())
        hits = ncm_store.find_index_by_name_artist(name="晴天", artist="周杰伦")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["song_original_id"], 12345)
        self.assertEqual(hits[0]["duration"], 269000)

        via_legacy = ncm_store.find_by_name_artist(name="晴天", artist="周杰伦")
        self.assertEqual(len(via_legacy), 1)
        self.assertEqual(via_legacy[0]["original_id"], 12345)
        self.assertEqual(via_legacy[0]["record"]["album"]["name"], "叶惠美")

    def test_find_falls_back_to_ncm_songs(self) -> None:
        ncm_store.init_db()
        conn = ncm_store.connect()
        conn.execute(
            """
            INSERT INTO ncm_songs (
              original_id, encrypted_id, name, name_norm, artist, artist_norm,
              record_json, played_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                77,
                "enc77",
                "孤勇者",
                ncm_store.normalize_text("孤勇者"),
                "陈奕迅",
                ncm_store.normalize_text("陈奕迅"),
                '{"originalId":77,"id":"enc77","name":"孤勇者"}',
                None,
            ),
        )
        hits = ncm_store.find_by_name_artist(name="孤勇者", artist="陈奕迅")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["original_id"], 77)
        self.assertEqual(ncm_store.find_index_by_name_artist(name="孤勇者"), [])

    def test_index_upsert_does_not_null_overwrite(self) -> None:
        ncm_store.upsert_record(self._record())
        ncm_store.upsert_record(
            {
                "originalId": 12345,
                "id": "ncm_new",
                "name": "晴天 (Live)",
                "artists": [{"name": "周杰伦"}],
            }
        )
        indexed = ncm_store.get_index_song(12345)
        assert indexed is not None
        self.assertEqual(indexed["song_encrypted_id"], "ncm_new")
        self.assertEqual(indexed["song_name"], "晴天 (Live)")
        self.assertEqual(indexed["duration"], 269000)
        self.assertEqual(indexed["album_original_id"], 18625)

    def test_migrate_backfills_index_from_ncm_songs(self) -> None:
        ncm_store.init_db()
        conn = ncm_store.connect()
        conn.execute("DELETE FROM ncm_song_index")
        conn.execute("DELETE FROM schema_migrations WHERE version = 3")
        conn.execute(
            """
            INSERT INTO ncm_songs (
              original_id, encrypted_id, name, name_norm, artist, artist_norm,
              record_json, played_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                66842,
                "1B8FCF799FD5895F6F0586C7D19A0A3B",
                "十年",
                ncm_store.normalize_text("十年"),
                "陈奕迅",
                ncm_store.normalize_text("陈奕迅"),
                (
                    '{"originalId":66842,"id":"1B8FCF799FD5895F6F0586C7D19A0A3B",'
                    '"name":"十年","duration":205423,'
                    '"artists":[{"name":"陈奕迅"}],'
                    '"album":{"originalId":6548,'
                    '"id":"6AF3D73514E9BBA48FC1B1F0AA0A5D75","name":"黑白灰"}}'
                ),
                None,
            ),
        )
        ncm_store.reset(path=self.path)
        ncm_store.init_db()
        indexed = ncm_store.get_index_song(66842)
        assert indexed is not None
        self.assertEqual(indexed["duration"], 205423)
        self.assertEqual(indexed["album_original_id"], 6548)
        self.assertEqual(indexed["album_name"], "黑白灰")
        self.assertEqual(indexed["album_encrypted_id"], "6AF3D73514E9BBA48FC1B1F0AA0A5D75")

    def test_db_path_under_mac_edge_data_dir(self) -> None:
        with mock.patch.dict(os.environ, {"MAC_EDGE_DATA_DIR": self._tmp.name}):
            ncm_store.reset(path=None)
            self.assertEqual(
                ncm_store.db_path().resolve(),
                (Path(self._tmp.name) / "ncm_songs.sqlite3").resolve(),
            )


if __name__ == "__main__":
    unittest.main()
