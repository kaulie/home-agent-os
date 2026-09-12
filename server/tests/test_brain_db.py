"""Brain SQLite: schema, persist across reconnect, shared intent id sequence."""

from __future__ import annotations

import json
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
            {"meta", "jobs", "participants", "intent_reviews", "intent_classification_events", "global_events", "assets", "asset_grants", "edge_control_policy", "admin_op_log", "cloud_api_calls", "playback_sessions", "schema_migrations"} <= names
        )
        self.assertNotIn("edges", names)
        self.assertNotIn("intent_queue", names)
        named_indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
            )
        }
        self.assertEqual(
            named_indexes,
            {
                "idx_cloud_api_calls_occurred_service",
                "idx_cloud_api_calls_service_occurred",
            },
        )
        versions = [
            int(row[0])
            for row in conn.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]
        self.assertEqual(
            versions,
            list(range(1, 28)),
        )
        job_cols = {
            row[1]: row[2]
            for row in conn.execute("PRAGMA table_info(jobs)")
        }
        self.assertEqual(job_cols["intent_id"], "INTEGER")
        self.assertIn("available_capabilities", job_cols)
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
        self.assertIn("intent_origin", cols)
        self.assertNotIn("assigned_edge_id", cols)
        self.assertNotIn("scheduler_node", cols)
        rcols = {
            row[1] for row in conn.execute("PRAGMA table_info(intent_reviews)")
        }
        self.assertIn("session_id", rcols)
        self.assertIn("cost_ms", rcols)
        self.assertIn("request_payload", rcols)
        self.assertIn("response_json", rcols)
        self.assertIn("raw_response", rcols)
        ccols = {
            row[1] for row in conn.execute("PRAGMA table_info(intent_classification_events)")
        }
        self.assertEqual(
            {
                "event_id",
                "intent_id",
                "text",
                "classifier_version",
                "score",
                "classification",
                "features",
                "candidates",
                "created_at",
            },
            ccols,
        )
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
            job_types = {
                row[1]: row[2]
                for row in conn.execute("PRAGMA table_info(jobs)")
            }
            self.assertNotIn("reply", jobs_cols)
            self.assertNotIn("extra_json", jobs_cols)
            self.assertEqual(job_types["intent_id"], "INTEGER")
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
            self.assertEqual(
                versions,
                [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25],
            )
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

    def test_create_job_autoincrement_intent_id(self) -> None:
        iid = brain_db.create_job(
            {
                "status": "intent_received",
                "text": "auto",
                "created_at": 1.0,
                "updated_at": 1.0,
            }
        )
        self.assertEqual(iid, 1)
        job = brain_db.get_job(iid)
        assert job is not None
        self.assertEqual(job["intent_id"], 1)
        self.assertEqual(job["job_id"], "1")
        iid2 = brain_db.create_job(
            {
                "status": "intent_received",
                "created_at": 2.0,
                "updated_at": 2.0,
            }
        )
        self.assertEqual(iid2, 2)
        self._reopen()
        self.assertEqual(brain_db.get_job(2)["status"], "intent_received")

    def test_put_job_without_id_uses_autoincrement(self) -> None:
        brain_db.put_job(
            {
                "status": "intent_parsed",
                "created_at": 1.0,
                "updated_at": 1.0,
            }
        )
        jobs = brain_db.list_jobs()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["intent_id"], 1)

    def test_put_job_roundtrips_available_capabilities(self) -> None:
        catalog = [
            {"capability_id": "clock.now", "edge_id": "sys", "composition": "atomic"},
            {
                "capability_id": "scanner.scan",
                "edge_id": "mac-1",
                "prefer_when": "scan docs",
            },
        ]
        brain_db.put_job(
            {
                "intent_id": 1,
                "status": "intent_parsed",
                "available_capabilities": catalog,
                "created_at": 1.0,
                "updated_at": 1.0,
            }
        )
        job = brain_db.get_job(1)
        assert job is not None
        self.assertEqual(job["available_capabilities"], catalog)
        brain_db.put_job(
            {
                "intent_id": 1,
                "status": "succeeded",
                "created_at": 1.0,
                "updated_at": 2.0,
            }
        )
        kept = brain_db.get_job(1)
        assert kept is not None
        self.assertEqual(kept["available_capabilities"], catalog)
        self.assertEqual(kept["status"], "succeeded")

    def test_list_jobs_page_newest_first(self) -> None:
        for i in range(1, 6):
            brain_db.put_job(
                {
                    "intent_id": i,
                    "status": "succeeded",
                    "text": f"t{i}",
                    "created_at": float(i),
                    "updated_at": float(i),
                }
            )
        page = brain_db.list_jobs_page(limit=2)
        self.assertEqual([job["intent_id"] for job in page], [5, 4])
        page2 = brain_db.list_jobs_page(before_id=4, limit=2)
        self.assertEqual([job["intent_id"] for job in page2], [3, 2])
        page3 = brain_db.list_jobs_page(before_id=2, limit=2)
        self.assertEqual([job["intent_id"] for job in page3], [1])

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
                "scheduler_node": "edge-a",
                "execution_plan": [
                    {
                        "capability": "notify.speak",
                        "step": 1,
                        "assigned_edge_id": "edge-a",
                    }
                ],
                "created_at": 1.0,
                "updated_at": 1.0,
            }
        )
        self._reopen()
        job = brain_db.get_job(1)
        assert job is not None
        self.assertEqual(job["intent_status"], "intent_parsed")
        self.assertNotIn("assigned_edge_id", job)
        self.assertNotIn("scheduler_node", job)
        self.assertEqual(job["execution_plan"][0]["capability"], "notify.speak")
        self.assertEqual(job["execution_plan"][0]["assigned_edge_id"], "edge-a")

    def test_job_persists_intent_origin(self) -> None:
        brain_db.put_job(
            {
                "intent_id": 1,
                "status": "intent_received",
                "text": "hi",
                "source": "voice",
                "intent_origin": "cloud",
                "created_at": 1.0,
                "updated_at": 1.0,
            }
        )
        job = brain_db.get_job(1)
        assert job is not None
        self.assertEqual(job["intent_origin"], "cloud")
        brain_db.put_job(
            {
                "intent_id": 2,
                "status": "intent_received",
                "intent_origin": "not-a-slot",
                "created_at": 1.0,
                "updated_at": 1.0,
            }
        )
        missing = brain_db.get_job(2)
        assert missing is not None
        self.assertNotIn("intent_origin", missing)
        self._reopen()
        again = brain_db.get_job(1)
        assert again is not None
        self.assertEqual(again["intent_origin"], "cloud")

    def test_queue_is_jobs_status(self) -> None:
        brain_db.upsert_queue(
            {"id": 1, "status": "intent_parsed", "text": "hi"}
        )
        brain_db.upsert_queue({"id": 2, "status": "intent_parsed"})
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
        self.assertNotIn("assigned_edge_id", merged)
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

    def test_put_job_does_not_wipe_existing_text(self) -> None:
        brain_db.put_job(
            {
                "intent_id": 7,
                "status": "intent_received",
                "text": "播放歌曲十年",
                "source": "voice",
                "edge_id": "edge-a",
            }
        )
        brain_db.put_job({"intent_id": 7, "status": "running"})
        job = brain_db.get_job(7)
        assert job is not None
        self.assertEqual(job["text"], "播放歌曲十年")
        self.assertEqual(job["source"], "voice")
        self.assertEqual(job["edge_id"], "edge-a")
        self.assertEqual(job["status"], "running")

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
                "cost_ms": 1842,
                "raw_response": '{"goal":"clock","plan":[]}',
                "parsed_json": {"goal": "clock", "plan": []},
                "execution_plan": [{"capability": "clock.now", "step": 1}],
                "request_payload": {
                    "model": "ep-test",
                    "messages": [
                        {"role": "system", "content": "planner rules"},
                        {"role": "user", "content": "现在几点了"},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 4096,
                    "response_format": {"type": "json_object"},
                    "extra_body": {"thinking": {"type": "enabled"}},
                },
                "response_json": {
                    "choices": [{"message": {"content": '{"goal":"clock","plan":[]}'}}],
                    "usage": {"total_tokens": 88},
                },
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
        self.assertEqual(rows[0]["cost_ms"], 1842)
        self.assertEqual(rows[0]["request_payload"]["model"], "ep-test")
        self.assertEqual(rows[0]["request_payload"]["messages"][0]["content"], "planner rules")
        self.assertEqual(rows[0]["raw_response"], '{"goal":"clock","plan":[]}')
        self.assertEqual(rows[0]["response_json"]["usage"]["total_tokens"], 88)
        self.assertEqual(rows[1]["error"], "retry")
        got = brain_db.get_intent_review(rid)
        assert got is not None
        self.assertEqual(got["planner"], "ark")
        self.assertEqual(got["cost_ms"], 1842)
        self.assertNotIn("Authorization", json.dumps(got["request_payload"]))

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

    def test_intent_classification_events_append_only_and_stats(self) -> None:
        first = brain_db.put_intent_classification_event(
            {
                "intent_id": 21,
                "text": "打开客厅灯。",
                "classifier_version": "v1-rule",
                "score": 2.0,
                "classification": "SIMPLE",
                "features": {
                    "capability_candidate_count": 1,
                    "action_count": 1,
                    "condition_count": 0,
                    "sequence_count": 0,
                    "parallel_count": 0,
                    "temporal_count": 0,
                    "context_reference_count": 0,
                    "ambiguity": 0,
                    "character_count": 6,
                    "token_count": 5,
                    "text_length_factor": 0.0,
                },
                "candidates": [{"capability_id": "light.set", "strength": "alias"}],
            }
        )
        brain_db.put_intent_classification_event(
            {
                "text": "dry-run",
                "classifier_version": "v1-rule",
                "score": 9.0,
                "classification": "COMPLEX",
                "features": {"capability_candidate_count": 3, "action_count": 2},
                "candidates": [],
            }
        )
        brain_db.put_job(
            {
                "intent_id": 21,
                "status": "intent_parsed",
                "text": "打开客厅灯。",
                "execution_plan": [
                    {"step": 1, "capability": "light.set"},
                ],
            }
        )
        self._reopen()
        rows = brain_db.list_intent_classification_events(21)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event_id"], first)
        self.assertEqual(rows[0]["classification"], "SIMPLE")
        self.assertEqual(rows[0]["features"]["action_count"], 1)
        all_rows = brain_db.list_intent_classification_events()
        self.assertEqual(len(all_rows), 2)
        stats = brain_db.list_intent_classification_stats()
        self.assertEqual(stats["n"], 2)
        self.assertEqual(stats["simple_count"], 1)
        self.assertEqual(stats["complex_count"], 1)
        self.assertEqual(stats["simple_rate"], 0.5)
        self.assertEqual(stats["mean_plan_steps_by_class"]["SIMPLE"], 1.0)
        self.assertIsNone(stats["mean_plan_steps_by_class"]["COMPLEX"])
        with self.assertRaises(ValueError):
            brain_db.put_intent_classification_event({"classification": "WEIRD", "score": 1})

    def test_intent_user_feedback_upsert(self) -> None:
        row = brain_db.upsert_intent_user_feedback(
            {
                "intent_id": 7,
                "participant_id": "phone-1",
                "understanding": "accurate",
                "response_speed": "fast",
            }
        )
        self.assertEqual(row["intent_id"], 7)
        self.assertEqual(row["understanding"], "accurate")
        self.assertEqual(row["response_speed"], "fast")
        updated = brain_db.upsert_intent_user_feedback(
            {
                "intent_id": 7,
                "participant_id": "phone-1",
                "understanding": "inaccurate",
                "response_speed": "slow",
            }
        )
        self.assertEqual(updated["feedback_id"], row["feedback_id"])
        self.assertEqual(updated["understanding"], "inaccurate")
        got = brain_db.get_intent_user_feedback(7, "phone-1")
        assert got is not None
        self.assertEqual(got["response_speed"], "slow")
        self._reopen()
        again = brain_db.get_intent_user_feedback(7, "phone-1")
        assert again is not None
        self.assertEqual(again["understanding"], "inaccurate")

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

    def test_edge_control_policy_independent_of_heartbeat(self) -> None:
        brain_db.put_registration(
            {
                "participant_id": "mac-1",
                "roles": ["runtime"],
                "services": [
                    {
                        "service_id": "gopro.camera",
                        "group": "camera",
                        "capabilities": [
                            {
                                "capability_id": "camera.capture",
                                "input_schema": {},
                                "output_schema": {},
                            }
                        ],
                    }
                ],
            }
        )
        brain_db.put_edge_control_policy(
            participant_id="mac-1",
            target_kind="capability",
            target_id="camera.capture",
            enabled=False,
        )
        brain_db.put_heartbeat(
            "mac-1",
            {
                "online_status": "online",
                "server_received_at": 100.0,
                "services": [
                    {
                        "service_id": "gopro.camera",
                        "group": "camera",
                        "capabilities": [
                            {
                                "capability_id": "camera.capture",
                                "input_schema": {},
                                "output_schema": {},
                            }
                        ],
                    }
                ],
            },
        )
        beats = brain_db.list_heartbeats()
        self.assertEqual(beats["mac-1"]["online_status"], "online")
        self.assertEqual(
            beats["mac-1"]["services"][0]["capabilities"][0]["capability_id"],
            "camera.capture",
        )
        self.assertFalse(
            brain_db.control_policy_allows("mac-1", "capability", "camera.capture")
        )
        self.assertTrue(brain_db.control_policy_allows("mac-1", "role", "runtime"))
        rows = brain_db.list_participants()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["participant_id"], "mac-1")

    def test_admin_op_log_insert_and_newest_first(self) -> None:
        first = brain_db.insert_admin_op_log(
            actor="admin",
            action="policy_disable",
            participant_id="mac-1",
            target_kind="capability",
            target_id="camera.capture",
            result="ok",
            summary="关掉 客厅 Mac 的 camera.capture",
        )
        second = brain_db.insert_admin_op_log(
            actor="",
            action="policy_enable",
            participant_id="mac-1",
            target_kind="capability",
            target_id="camera.capture",
            extra={"note": "reenable"},
            result="ok",
            summary="打开 客厅 Mac 的 camera.capture",
        )
        listed = brain_db.list_admin_op_logs(limit=10)
        self.assertEqual(listed[0]["id"], second["id"])
        self.assertEqual(listed[1]["id"], first["id"])
        self.assertEqual(listed[0]["extra"], {"note": "reenable"})
        capped = brain_db.list_admin_op_logs(limit=1)
        self.assertEqual(len(capped), 1)
        self.assertEqual(capped[0]["action"], "policy_enable")

    def test_entities_v1_seed_and_upsert(self) -> None:
        rows = brain_db.list_entities(entity_type="device")
        ids = {r["entity_id"] for r in rows}
        self.assertIn("ent_dev_livingroom_ac", ids)
        self.assertIn("ent_dev_livingroom_ceiling_light", ids)
        self.assertIn("ent_dev_livingroom_gopro", ids)
        self.assertIn("ent_dev_livingroom_tv", ids)
        ac = brain_db.get_entity("ent_dev_livingroom_ac")
        assert ac is not None
        self.assertEqual(ac["type"], "device")
        self.assertEqual(ac["name"], "客厅空调")
        self.assertEqual(ac["metadata"].get("room"), "living-room")
        self.assertEqual(ac["state"], {})
        updated = brain_db.upsert_entity(
            {
                "entity_id": "ent_dev_livingroom_ac",
                "type": "device",
                "name": "客厅空调",
                "metadata": {"room": "living-room", "vendor": "hisense"},
                "state": {"power": True, "temperature": 26},
                "references": {"capability_ids": ["climate.set"]},
            }
        )
        self.assertEqual(updated["state"].get("temperature"), 26)
        with self.assertRaises(ValueError):
            brain_db.upsert_entity(
                {
                    "entity_id": "ent_recipe_x",
                    "type": "recipe",
                    "name": "红烧肉",
                }
            )


class GlobalEventsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "brain.sqlite3"
        brain_db.reset(path=self.path)
        brain_db.init_db()

    def tearDown(self) -> None:
        brain_db.reset()
        self._tmp.cleanup()

    def test_mode_activate_deactivate_and_switch(self) -> None:
        self.assertIsNone(brain_db.resolve_active_mode())
        brain_db.append_global_event(
            {"kind": "mode", "action": "activate", "subject": "reading"}
        )
        self.assertEqual(brain_db.resolve_active_mode(), "reading")
        brain_db.append_global_event(
            {"kind": "mode", "action": "deactivate", "subject": "reading"}
        )
        self.assertIsNone(brain_db.resolve_active_mode())
        brain_db.append_global_event(
            {"kind": "mode", "action": "activate", "subject": "game"}
        )
        self.assertEqual(brain_db.resolve_active_mode(), "game")

    def test_list_global_events_filters_kind(self) -> None:
        brain_db.append_global_event(
            {"kind": "mode", "action": "activate", "subject": "reading"}
        )
        brain_db.append_global_event(
            {"kind": "scene", "action": "activate", "subject": "movie"}
        )
        mode_events = brain_db.list_global_events(kind="mode", limit=10)
        self.assertEqual(len(mode_events), 1)
        self.assertEqual(mode_events[0]["subject"], "reading")


class CloudApiCallsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "brain.sqlite3"
        brain_db.reset(path=self.path)
        brain_db.init_db()

    def tearDown(self) -> None:
        brain_db.reset()
        self._tmp.cleanup()

    def test_record_and_aggregate(self) -> None:
        t0 = 1_700_000_000.0
        brain_db.record_cloud_call("ark.planner", 1, "brain", occurred_at=t0)
        brain_db.record_cloud_call("ark.planner", 0, "brain", occurred_at=t0 + 1)
        brain_db.record_cloud_call("ark.vision", 1, "edge:laptop-1", occurred_at=t0 + 2)

        all_rows = brain_db.aggregate_cloud_calls()
        self.assertEqual(
            all_rows,
            [
                {"service_id": "ark.planner", "count": 2, "ok": 1, "fail": 1},
                {"service_id": "ark.vision", "count": 1, "ok": 1, "fail": 0},
            ],
        )

        window = brain_db.aggregate_cloud_calls(since=t0, until=t0 + 1)
        self.assertEqual(
            window,
            [{"service_id": "ark.planner", "count": 2, "ok": 1, "fail": 1}],
        )

    def test_ingest_cloud_usage_delta(self) -> None:
        t0 = 1_700_000_100.0
        n = brain_db.ingest_cloud_usage_delta(
            "edge:mac-1",
            [
                {"service_id": "volc.stt", "ok": 3, "fail": 1},
                {"service_id": "bing.images", "ok": 2, "fail": 0},
            ],
            occurred_at=t0,
        )
        self.assertEqual(n, 6)
        rows = brain_db.aggregate_cloud_calls(since=t0, until=t0)
        self.assertEqual(
            rows,
            [
                {"service_id": "bing.images", "count": 2, "ok": 2, "fail": 0},
                {"service_id": "volc.stt", "count": 4, "ok": 3, "fail": 1},
            ],
        )

    def test_invalid_source_raises(self) -> None:
        with self.assertRaises(ValueError):
            brain_db.record_cloud_call("ark.planner", 1, "laptop")


class UrlAssetDbTests(unittest.TestCase):
    """url 资产类型：归一化保留 url，metadata.url_target 持久化（非剥离键）。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "brain.sqlite3"
        brain_db.reset(path=self.path)
        brain_db.init_db()

    def tearDown(self) -> None:
        brain_db.reset()
        self._tmp.cleanup()

    def test_type_url_is_kept(self) -> None:
        self.assertEqual(brain_db._norm_asset_type("url"), "url")

    def test_url_asset_round_trip_keeps_url_target(self) -> None:
        target = "https://example.com/article?a=1&b=2"
        aid = brain_db.put_asset(
            {
                "asset_id": "asset_urltest01",
                "type": "url",
                "mime_type": "text/uri-list",
                "status": "ready",
                "metadata": {"url_target": target, "title": "示例"},
                "storage": None,
            }
        )
        got = brain_db.get_asset(aid)
        self.assertEqual(got["type"], "url")
        self.assertEqual(got["metadata"]["url_target"], target)
        self.assertEqual(got["metadata"]["title"], "示例")

    def test_unknown_type_still_falls_back_to_other(self) -> None:
        self.assertEqual(brain_db._norm_asset_type("whatever"), "other")


if __name__ == "__main__":
    unittest.main()
