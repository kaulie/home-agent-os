"""Brain SQLite: schema, persist across reconnect, shared intent id sequence."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

import db as brain_db  # noqa: E402


class BrainDbTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "brain.sqlite3"
        brain_db.reset(path=self.path)
        brain_db.init_db()

    def tearDown(self) -> None:
        brain_db.reset()
        self._tmp.cleanup()

    def _reopen(self) -> None:
        brain_db.reset(path=self.path)

    def test_tables_exist(self) -> None:
        conn = brain_db._connect()
        names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        self.assertTrue(
            {"meta", "jobs", "participants", "intent_reviews", "assets", "asset_grants", "schema_migrations"} <= names
        )
        self.assertNotIn("edges", names)
        self.assertNotIn("intent_queue", names)
        named_indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
            )
        }
        self.assertEqual(named_indexes, set())
        versions = [
            int(row[0])
            for row in conn.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]
        self.assertEqual(versions, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12])
        pcols = {
            row[1] for row in conn.execute("PRAGMA table_info(participants)")
        }
        self.assertIn("location", pcols)
        self.assertNotIn("room", pcols)
        self.assertNotIn("observer_events", pcols)
        cols = {
            row[1] for row in conn.execute("PRAGMA table_info(jobs)")
        }
        self.assertNotIn("payload_json", cols)
        self.assertNotIn("extra_json", cols)
        self.assertNotIn("reply", cols)
        self.assertIn("execution_plan", cols)
        self.assertIn("text", cols)
        rcols = {
            row[1] for row in conn.execute("PRAGMA table_info(intent_reviews)")
        }
        self.assertIn("session_id", rcols)
        acols = {
            row[1] for row in conn.execute("PRAGMA table_info(assets)")
        }
        self.assertIn("asset_id", acols)
        self.assertIn("producer_capability", acols)
        self.assertIn("origin_intent_id", acols)
        self.assertIn("size_bytes", acols)
        self.assertNotIn("url", acols)
        self.assertNotIn("photo_url", acols)
        gcols = {
            row[1] for row in conn.execute("PRAGMA table_info(asset_grants)")
        }
        self.assertEqual({"asset_id", "intent_id", "granted_at"}, gcols)
        nxt = conn.execute(
            "SELECT value FROM meta WHERE key = 'next_intent_id'"
        ).fetchone()
        self.assertEqual(nxt[0], "1")

    def test_connect_does_not_migrate(self) -> None:
        path = Path(self._tmp.name) / "no-migrate.sqlite3"
        brain_db.reset(path=path)
        conn = brain_db._connect()
        names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        self.assertNotIn("jobs", names)
        self.assertNotIn("schema_migrations", names)
        brain_db.reset(path=self.path)
        brain_db.init_db()

    def test_prepare_sql_skips_drop_column_on_sqlite_3_34(self) -> None:
        sql = (
            "-- comment\n"
            "ALTER TABLE jobs DROP COLUMN reply;\n"
            "ALTER TABLE jobs DROP COLUMN extra_json;\n"
        )
        prepared = brain_db._prepare_migration_sql(sql, sqlite_version="3.34.1")
        self.assertNotIn("ALTER TABLE jobs DROP COLUMN", prepared)
        self.assertIn("skipped DROP COLUMN", prepared)
        kept = brain_db._prepare_migration_sql(sql, sqlite_version="3.35.0")
        self.assertIn("DROP COLUMN reply", kept)

    def test_migrate_tolerates_sqlite_without_drop_column(self) -> None:
        path = Path(self._tmp.name) / "sqlite-3.34.sqlite3"
        brain_db.reset(path=path)
        original = brain_db._sqlite_supports_drop_column
        brain_db._sqlite_supports_drop_column = lambda version=None: False
        try:
            brain_db.init_db()
            conn = brain_db._connect()
            jobs_cols = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
            self.assertIn("reply", jobs_cols)
            self.assertIn("extra_json", jobs_cols)
            pcols = {
                row[1] for row in conn.execute("PRAGMA table_info(participants)")
            }
            self.assertIn("observer_events", pcols)
            versions = [
                int(row[0])
                for row in conn.execute(
                    "SELECT version FROM schema_migrations ORDER BY version"
                )
            ]
            self.assertEqual(versions, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12])
            brain_db.put_job(
                {
                    "intent_id": 1,
                    "status": "intent_parsed",
                    "created_at": 1.0,
                    "updated_at": 1.0,
                }
            )
            job = brain_db.get_job(1)
            assert job is not None
            self.assertEqual(job["status"], "intent_parsed")
        finally:
            brain_db._sqlite_supports_drop_column = original
            brain_db.reset(path=self.path)
            brain_db.init_db()

    def test_intent_id_survives_reconnect(self) -> None:
        a = brain_db.next_intent_id()
        b = brain_db.next_intent_id()
        self.assertEqual((a, b), (1, 2))
        self._reopen()
        self.assertEqual(brain_db.next_intent_id(), 3)

    def test_notice_intent_id_bumps_sequence(self) -> None:
        brain_db.notice_intent_id(10)
        self.assertEqual(brain_db.next_intent_id(), 11)

    def test_init_reconciles_sequence_from_existing_jobs(self) -> None:
        brain_db.put_job(
            {
                "intent_id": 7,
                "intent_status": "succeeded",
                "created_at": 1.0,
                "updated_at": 1.0,
            }
        )
        conn = brain_db._connect()
        conn.execute(
            "UPDATE meta SET value = '1' WHERE key = 'next_intent_id'"
        )
        conn.commit()
        brain_db.reset(path=self.path)
        brain_db.init_db()
        self.assertEqual(brain_db.next_intent_id(), 8)
        job = brain_db.get_job(7)
        assert job is not None
        self.assertEqual(job["intent_status"], "succeeded")

    def test_job_survives_reconnect(self) -> None:
        brain_db.put_job(
            {
                "intent_id": 1,
                "intent_status": "intent_parsed",
                "assigned_edge_id": "edge-a",
                "execution_plan": [{"capability": "notify.speak", "step": 1}],
                "created_at": 1.0,
                "updated_at": 1.0,
            }
        )
        self._reopen()
        job = brain_db.get_job(1)
        assert job is not None
        self.assertEqual(job["intent_status"], "intent_parsed")
        self.assertEqual(job["assigned_edge_id"], "edge-a")
        self.assertEqual(job["execution_plan"][0]["capability"], "notify.speak")

    def test_queue_is_jobs_status(self) -> None:
        brain_db.upsert_queue(
            {"id": 1, "status": "intent_parsed", "assigned_edge_id": "a", "text": "hi"}
        )
        brain_db.upsert_queue({"id": 2, "status": "intent_parsed", "assigned_edge_id": "b"})
        ids = [row["id"] for row in brain_db.list_queue()]
        self.assertEqual(ids, [1, 2])
        job = brain_db.get_job(1)
        assert job is not None
        self.assertEqual(job["text"], "hi")
        brain_db.delete_queue_ids(["1"])
        self._reopen()
        still = brain_db.list_queue()
        self.assertEqual([row["id"] for row in still], [1, 2])
        merged = brain_db.upsert_queue({"id": 2, "status": "running"})
        self.assertEqual(merged["status"], "running")
        self.assertEqual(merged.get("assigned_edge_id"), "b")
        self.assertEqual(brain_db.get_job(2)["intent_status"], "running")

    def test_terminal_job_leaves_pull_list(self) -> None:
        brain_db.upsert_queue({"id": 1, "status": "intent_parsed"})
        brain_db.upsert_queue({"id": 2, "status": "intent_parsed"})
        brain_db.remove_queue(1)
        self.assertEqual([row["id"] for row in brain_db.list_queue()], [1, 2])
        brain_db.upsert_queue({"id": 1, "status": "failed"})
        self.assertEqual([row["id"] for row in brain_db.list_queue()], [2])
        self.assertEqual(brain_db.get_job(1)["status"], "failed")
        brain_db.upsert_queue(
            {
                "id": 2,
                "status": "succeeded",
                "pending_delivery": {"edge_id": "mac-1"},
            }
        )
        self.assertEqual([row["id"] for row in brain_db.list_queue()], [2])
        brain_db.upsert_queue({"id": 2, "status": "succeeded", "pending_delivery": None})
        self.assertEqual(brain_db.list_queue(), [])

    def test_intent_waiting_stays_out_of_pull_list(self) -> None:
        brain_db.upsert_queue({"id": 1, "status": "intent_parsed", "msg": "ready"})
        brain_db.upsert_queue(
            {"id": 1, "status": "intent_waiting", "msg": "clock skew, wait"}
        )
        self.assertEqual(brain_db.list_queue(), [])
        job = brain_db.get_job(1)
        assert job is not None
        self.assertEqual(job["status"], "intent_waiting")
        self.assertEqual(job["msg"], "clock skew, wait")
        brain_db.upsert_queue({"id": 1, "status": "assigned"})
        self.assertEqual([row["id"] for row in brain_db.list_queue()], [1])

    def test_intent_reviews_append_only_and_survive_reconnect(self) -> None:
        rid = brain_db.put_intent_review(
            {
                "intent_id": 3,
                "text": "现在几点了",
                "source": "text",
                "edge_id": "phone-1",
                "planner": "ark",
                "model": "ep-test",
                "raw_response": '{"goal":"clock","plan":[]}',
                "parsed_json": {"goal": "clock", "plan": []},
                "execution_plan": [{"capability": "clock.now", "step": 1}],
            }
        )
        brain_db.put_intent_review(
            {
                "intent_id": 3,
                "text": "现在几点了",
                "planner": "ark",
                "error": "retry",
            }
        )
        self._reopen()
        rows = brain_db.list_intent_reviews(3)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["review_id"], rid)
        self.assertEqual(rows[0]["text"], "现在几点了")
        self.assertEqual(rows[0]["parsed_json"]["goal"], "clock")
        self.assertEqual(rows[0]["execution_plan"][0]["capability"], "clock.now")
        self.assertEqual(rows[1]["error"], "retry")
        got = brain_db.get_intent_review(rid)
        assert got is not None
        self.assertEqual(got["planner"], "ark")

    def test_intent_reviews_group_by_session(self) -> None:
        brain_db.put_intent_review(
            {
                "intent_id": 10,
                "session_id": "sess-a",
                "text": "现在几点了",
                "planner": "ark",
            }
        )
        brain_db.put_intent_review(
            {
                "intent_id": 11,
                "session_id": "sess-a",
                "text": "投到电视上",
                "planner": "ark",
            }
        )
        brain_db.put_intent_review(
            {
                "intent_id": 12,
                "session_id": "sess-b",
                "text": "开灯",
                "planner": "heuristic",
            }
        )
        rows = brain_db.list_intent_reviews(session_id="sess-a")
        self.assertEqual([row["intent_id"] for row in rows], [10, 11])
        self.assertEqual(rows[0]["session_id"], "sess-a")
        self.assertEqual(rows[1]["text"], "投到电视上")

    def test_assets_catalog_and_grants(self) -> None:
        aid = brain_db.put_asset(
            {
                "asset_id": "asset_01TEST",
                "type": "image",
                "mime_type": "image/jpeg",
                "size_bytes": 123,
                "status": "available",
                "producer_capability": "camera.capture",
                "producer_edge_id": "mac-1",
                "origin_intent_id": "10",
                "origin_step": 1,
                "metadata": {
                    "width": 1920,
                    "url": "https://example/x.jpg",
                    "photo_url": "http://lan/x.jpg",
                },
                "storage": {
                    "backend": "img_server",
                    "key": "photo_1",
                    "edge_id": "mac-1",
                    "url": "https://should-not-persist",
                },
                "photo_url": "https://should-not-persist",
            }
        )
        self.assertEqual(aid, "asset_01TEST")
        self._reopen()
        got = brain_db.get_asset(aid)
        assert got is not None
        self.assertEqual(got["type"], "image")
        self.assertEqual(got["producer_capability"], "camera.capture")
        self.assertEqual(got["size_bytes"], 123)
        self.assertEqual(got["asset_ref"]["asset_id"], aid)
        self.assertEqual(got["metadata"]["width"], 1920)
        self.assertNotIn("url", got)
        self.assertNotIn("photo_url", got)
        self.assertNotIn("url", got["metadata"])
        self.assertNotIn("photo_url", got["metadata"])
        self.assertNotIn("url", got["storage"])
        self.assertEqual(got["storage"]["key"], "photo_1")
        self.assertTrue(brain_db.has_asset_grant(aid, 10))
        grants = brain_db.list_asset_grants(aid)
        self.assertEqual(len(grants), 1)
        self.assertEqual(grants[0]["intent_id"], 10)
        brain_db.delete_asset(aid)
        self.assertEqual(brain_db.get_asset(aid)["status"], "deleted")
        self.assertEqual(brain_db.list_assets(), [])

    def test_edge_register_and_heartbeat_survive_reconnect(self) -> None:
        brain_db.put_registration(
            {
                "edge_id": "living-room-mac",
                "status": "approved",
                "services": [{"service_id": "local.notify", "capabilities": []}],
            }
        )
        self.assertEqual(brain_db.list_heartbeats(), {})
        brain_db.put_heartbeat(
            "living-room-mac",
            {
                "edge_id": "living-room-mac",
                "online_status": "online",
                "services": [{"service_id": "local.notify", "capabilities": []}],
            },
        )
        self._reopen()
        reg = brain_db.get_registration("living-room-mac")
        beats = brain_db.list_heartbeats()
        assert reg is not None
        self.assertEqual(reg["status"], "approved")
        self.assertEqual(reg["participant_id"], "living-room-mac")
        self.assertEqual(reg["edge_id"], "living-room-mac")
        self.assertIn("runtime", reg["roles"])
        self.assertEqual(reg["services"][0]["service_id"], "local.notify")
        self.assertEqual(beats["living-room-mac"]["online_status"], "online")
        self.assertEqual(beats["living-room-mac"]["edge_id"], "living-room-mac")

    def test_participant_location_accepts_room_alias(self) -> None:
        brain_db.put_registration(
            {"edge_id": "kindle-1", "room": "living-room", "status": "approved"}
        )
        reg = brain_db.get_registration("kindle-1")
        assert reg is not None
        self.assertEqual(reg["location"], "living-room")
        self.assertEqual(reg["room"], "living-room")
        brain_db.put_registration(
            {"edge_id": "kindle-1", "location": "kitchen", "status": "approved"}
        )
        reg = brain_db.get_registration("kindle-1")
        assert reg is not None
        self.assertEqual(reg["location"], "kitchen")
        self.assertEqual(reg["room"], "kitchen")

    def test_participant_roles_inferred_from_contracts(self) -> None:
        brain_db.put_registration(
            {
                "participant_id": "iphone-1",
                "device_type": "iphone",
                "intent_sources": [{"source_id": "microphone", "channel": "voice"}],
                "services": [{"service_id": "gopro.camera", "capabilities": []}],
                "endpoints": [
                    {
                        "endpoint_id": "iphone.display",
                        "supported_presentation": ["image", "text"],
                    },
                    {
                        "endpoint_id": "iphone.speaker",
                        "supported_presentation": ["audio"],
                    },
                ],
                "roles": ["observer"],
                "observer_events": ["intent.created"],
            }
        )
        reg = brain_db.get_registration("iphone-1")
        assert reg is not None
        self.assertEqual(
            set(reg["roles"]),
            {"intent_source", "runtime", "endpoint", "observer"},
        )
        self.assertNotIn("observer_events", reg)
        kindle = {
            "edge_id": "kindle-1",
            "device_type": "kindle",
            "endpoints": [
                {
                    "endpoint_id": "kindle_browser",
                    "supported_presentation": ["html", "text", "image"],
                }
            ],
        }
        brain_db.put_registration(kindle)
        kreg = brain_db.get_registration("kindle-1")
        assert kreg is not None
        self.assertEqual(kreg["roles"], ["endpoint"])
        self.assertFalse(kreg["role_runtime"])
        self.assertEqual(kreg["services"], [])

    def test_registration_does_not_wipe_heartbeat(self) -> None:
        brain_db.put_registration({"edge_id": "n1", "display_name": "one"})
        brain_db.put_heartbeat(
            "n1",
            {"online_status": "online", "health": {"status": "healthy"}},
        )
        brain_db.put_registration({"edge_id": "n1", "display_name": "two"})
        beats = brain_db.list_heartbeats()
        self.assertEqual(beats["n1"]["online_status"], "online")
        self.assertEqual(beats["n1"]["health"]["status"], "healthy")
        self.assertEqual(brain_db.get_registration("n1")["display_name"], "two")

    def test_heartbeat_requires_existing_participant(self) -> None:
        with self.assertRaises(KeyError):
            brain_db.put_heartbeat("missing", {"online_status": "online"})

    def test_004_migrates_edges_json_blobs(self) -> None:
        import json
        import sqlite3

        sql_dir = SERVER / "sql"
        path = Path(self._tmp.name) / "from-edges.sqlite3"
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        for name in (
            "001_init.sql",
            "002_flatten_jobs.sql",
            "003_drop_jobs_reply_extra.sql",
        ):
            conn.executescript((sql_dir / name).read_text(encoding="utf-8"))
        conn.execute(
            "INSERT INTO edges(edge_id, registration_json, heartbeat_json, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (
                "living-room-mac",
                json.dumps(
                    {
                        "edge_id": "living-room-mac",
                        "client_hint": "living-room-mac",
                        "device_type": "mac",
                        "status": "approved",
                        "registered_at": 1.0,
                        "services": [{"service_id": "local.notify", "capabilities": []}],
                    }
                ),
                json.dumps(
                    {
                        "online_status": "online",
                        "server_received_at": 2.0,
                        "health": {"status": "healthy"},
                    }
                ),
                3.0,
            ),
        )
        conn.executescript((sql_dir / "004_participants.sql").read_text(encoding="utf-8"))
        names = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        self.assertIn("participants", names)
        self.assertNotIn("edges", names)
        row = conn.execute(
            "SELECT * FROM participants WHERE participant_id = 'living-room-mac'"
        ).fetchone()
        assert row is not None
        self.assertEqual(row["role_runtime"], 1)
        self.assertEqual(row["online_status"], "online")
        self.assertEqual(row["client_hint"], "living-room-mac")
        services = json.loads(row["services"])
        self.assertEqual(services[0]["service_id"], "local.notify")
        conn.close()

    def test_005_copies_queue_only_rows_into_jobs(self) -> None:
        import json
        import sqlite3

        sql_dir = SERVER / "sql"
        path = Path(self._tmp.name) / "from-queue.sqlite3"
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        for name in (
            "001_init.sql",
            "002_flatten_jobs.sql",
            "003_drop_jobs_reply_extra.sql",
            "004_participants.sql",
        ):
            conn.executescript((sql_dir / name).read_text(encoding="utf-8"))
        conn.execute(
            "INSERT INTO intent_queue(intent_id, position, status, assigned_edge_id, payload_json, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                "9",
                1,
                "intent_parsed",
                "edge-a",
                json.dumps(
                    {
                        "id": 9,
                        "status": "intent_parsed",
                        "text": "queue only",
                        "execution_plan": [{"capability": "notify.speak", "step": 1}],
                    }
                ),
                4.0,
            ),
        )
        conn.executescript((sql_dir / "005_drop_intent_queue.sql").read_text(encoding="utf-8"))
        names = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        self.assertIn("jobs", names)
        self.assertNotIn("intent_queue", names)
        row = conn.execute("SELECT * FROM jobs WHERE intent_id = '9'").fetchone()
        assert row is not None
        self.assertEqual(row["status"], "intent_parsed")
        self.assertEqual(row["assigned_edge_id"], "edge-a")
        self.assertEqual(row["text"], "queue only")
        plan = json.loads(row["execution_plan"])
        self.assertEqual(plan[0]["capability"], "notify.speak")
        conn.close()

    def test_backup_roundtrip(self) -> None:
        brain_db.put_job(
            {
                "intent_id": 7,
                "status": "failed",
                "created_at": 1.0,
                "updated_at": 1.0,
            }
        )
        dest = Path(self._tmp.name) / "brain.bak.sqlite3"
        brain_db.backup(dest)
        self.assertTrue(dest.is_file())
        brain_db.reset(path=dest)
        job = brain_db.get_job(7)
        assert job is not None
        self.assertEqual(job["status"], "failed")


if __name__ == "__main__":
    unittest.main()
