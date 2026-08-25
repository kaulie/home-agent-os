"""kind=system capabilities: catalog injection and Brain-side execution."""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SERVER = Path(__file__).resolve().parents[1]
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

os.environ["BRAIN_SKIP_LLM_WORKER"] = "1"

import db as brain_db  # noqa: E402
from system_capabilities import (  # noqa: E402
    SYSTEM_EDGE_ID,
    build_spoken_summary,
    catalog_rows,
    inventory_answer_text,
    inventory_from_params,
    is_system_capability,
)

try:
    import flask  # noqa: F401
except ImportError:  # pragma: no cover
    flask = None  # type: ignore

if flask is not None:
    import home_brain as hb  # noqa: E402
else:
    hb = None  # type: ignore


def _rows(*items: tuple[str, str, str, str]) -> list[dict]:
    return [
        {
            "capability_id": cid,
            "group": group,
            "role": role,
            "planner_recognize": recognize,
        }
        for cid, group, role, recognize in items
    ]


class SpokenSummaryTests(unittest.TestCase):
    def test_empty(self) -> None:
        text = build_spoken_summary([])
        self.assertIn("帮不上", text)

    def test_from_self_description_not_ids(self) -> None:
        rows = _rows(
            ("camera.capture", "camera", "拍照执行器", "拍一张照片"),
            ("vision.ask", "vision", "看图问答器", "基于图片回答具体问题"),
            ("display.photo", "display", "单图投屏器", "把一张图投到显示端"),
            ("notify.speak", "notify", "语音播报器", "把文本念出来"),
            ("query.content", "query", "文本知识与推理回答器", "回答不依赖本地传感的文本问题"),
            ("math.calculate", "math", "确定性算术求值器", "计算简单、可解析的数学表达式"),
            ("clock.now", "clock", "本机时钟读取器", "读取当前时间"),
            ("capabilities.summary", "meta", "在线能力口语汇总器", "用简短口语介绍当前可调度能力"),
        )
        text = build_spoken_summary(rows)
        self.assertTrue(text.startswith("我现在能帮你："))
        self.assertIn("拍一张照片", text)
        self.assertIn("把文本念出来", text)
        self.assertNotIn("camera.capture", text)
        self.assertNotIn("query.content", text)
        self.assertNotIn("capabilities.summary", text)
        self.assertNotIn("planner_recognize", text)
        self.assertNotIn("capability", text.lower())

    def test_skips_voice_test_and_self(self) -> None:
        rows = _rows(
            ("voice_test.run_trial", "meta", "试音", "跑一轮试音"),
            ("clock.now", "clock", "本机时钟读取器", "读取当前时间"),
        )
        text = build_spoken_summary(rows)
        self.assertIn("读取当前时间", text)
        self.assertNotIn("试音", text)
        self.assertNotIn("voice_test", text)

    def test_one_phrase_per_group(self) -> None:
        rows = _rows(
            ("music.play", "music", "播放器", "按歌名播放"),
            ("music.pause", "music", "暂停器", "暂停播放"),
            ("music.next", "music", "切歌器", "下一首"),
        )
        text = build_spoken_summary(rows)
        self.assertEqual(text.count("以及"), 0)
        self.assertTrue(text.startswith("我现在能帮你："))


class InventoryAnswerTests(unittest.TestCase):
    def test_answer_today_images(self) -> None:
        self.assertEqual(
            inventory_answer_text(count=12, asset_type="image", day="today"),
            "今天一共登记了 12 张照片。",
        )
        self.assertEqual(
            inventory_answer_text(count=0, asset_type="image", day="today"),
            "今天还没有登记过照片。",
        )

    def test_answer_yesterday_images(self) -> None:
        self.assertEqual(
            inventory_answer_text(count=3, asset_type="image", day="yesterday"),
            "昨天一共登记了 3 张照片。",
        )
        self.assertEqual(
            inventory_answer_text(count=0, asset_type="image", day="昨天"),
            "昨天还没有登记过照片。",
        )


class InventoryFromParamsTests(unittest.TestCase):
    def test_maps_db_rows(self) -> None:
        class FakeDb:
            def count_assets(self, **kwargs):
                return 2

            def list_assets(self, **kwargs):
                self.kwargs = kwargs
                return [
                    {
                        "asset_ref": {
                            "asset_id": "asset_a",
                            "type": "image",
                            "mime_type": "image/jpeg",
                        }
                    },
                    {"asset_ref": {"asset_id": "asset_b", "type": "image"}},
                ]

        db = FakeDb()
        msg, out = inventory_from_params({"type": "image", "day": "today"}, db=db)
        self.assertIn("count=2", msg)
        self.assertEqual(out["count"], "2")
        self.assertIn("今天一共登记了 2 张照片", out["answer_text"])
        self.assertIn("asset_a", out["asset_refs"])
        self.assertEqual(db.kwargs["asset_type"], "image")
        self.assertEqual(db.kwargs["offset"], 0)
        self.assertTrue(db.kwargs["newest_first"])

    def test_index_fetches_nth_oldest(self) -> None:
        class FakeDb:
            def count_assets(self, **kwargs):
                return 107

            def list_assets(self, **kwargs):
                self.kwargs = kwargs
                return [
                    {
                        "asset_ref": {
                            "asset_id": "asset_fifth",
                            "type": "image",
                            "mime_type": "image/jpeg",
                        }
                    }
                ]

        db = FakeDb()
        msg, out = inventory_from_params({"type": "image", "index": 5}, db=db)
        self.assertIn("count=107", msg)
        self.assertEqual(out["asset_ref"]["asset_id"], "asset_fifth")
        self.assertEqual(out["asset_index"], "5")
        self.assertIn("第 5 张", out["answer_text"])
        self.assertEqual(db.kwargs["offset"], 4)
        self.assertEqual(db.kwargs["limit"], 1)
        self.assertFalse(db.kwargs["newest_first"])

    def test_db_list_and_count_filters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "brain.sqlite3"
            brain_db.reset(path=db_path)
            brain_db.init_db()
            aid = "asset_inv_filter_1"
            now = datetime.now(ZoneInfo("Asia/Shanghai")).timestamp()
            brain_db.put_asset(
                {
                    "asset_id": aid,
                    "type": "image",
                    "mime_type": "image/jpeg",
                    "status": "available",
                    "producer_capability": "camera.capture",
                    "intent_id": "1",
                    "created_at": now,
                    "storage": {"backend": "img_server", "key": "x.jpg"},
                }
            )
            n = brain_db.count_assets(
                asset_type="image", producer_capability="camera.capture"
            )
            self.assertEqual(n, 1)
            rows = brain_db.list_assets(asset_type="image", limit=5, newest_first=True)
            self.assertEqual(rows[0]["asset_id"], aid)
            brain_db.reset()


class CatalogRowsTests(unittest.TestCase):
    def test_catalog_is_system(self) -> None:
        rows = catalog_rows()
        ids = {r["capability_id"] for r in rows}
        self.assertEqual(ids, {"capabilities.summary", "asset.inventory", "image.ocr"})
        for row in rows:
            self.assertEqual(row["kind"], "system")
            self.assertEqual(row["edge_id"], SYSTEM_EDGE_ID)
            self.assertEqual(row["assigned_edge_id"], SYSTEM_EDGE_ID)
            self.assertTrue(is_system_capability(row["capability_id"]))


@unittest.skipUnless(flask is not None, "flask not installed in this interpreter")
class SystemCapabilityBrainTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "brain.sqlite3"
        brain_db.reset(path=self.path)
        brain_db.init_db()
        hb._REGISTERED_edges = brain_db.registration_ids()
        hb.rebuild_capability_maps()

    def tearDown(self) -> None:
        brain_db.reset()
        self._tmp.cleanup()

    def _heartbeat(self, pid: str) -> None:
        now = time.time()
        brain_db.put_heartbeat(
            pid,
            {
                "online_status": "online",
                "server_received_at": now,
                "reported_at": now,
                "schedule_eligible": True,
            },
        )

    def _register_voice_runtime(self, pid: str) -> None:
        brain_db.put_registration(
            {
                "participant_id": pid,
                "display_name": "Mac Voice",
                "device_type": "mac",
                "roles": ["runtime"],
                "services": [
                    {
                        "service_id": "local.voice",
                        "group": "voice",
                        "capabilities": [
                            {
                                "capability_id": "voice.stream",
                                "kind": "input",
                                "input_schema": {},
                                "output_schema": {},
                            }
                        ],
                    },
                    {
                        "service_id": "local.notify",
                        "group": "notify",
                        "capabilities": [
                            {
                                "capability_id": "notify.speak",
                                "kind": "output",
                                "input_schema": {},
                                "output_schema": {},
                            }
                        ],
                    },
                ],
            }
        )
        now = time.time()
        brain_db.put_heartbeat(
            pid,
            {
                "online_status": "online",
                "server_received_at": now,
                "reported_at": now,
                "schedule_eligible": True,
                "services": [
                    {
                        "service_id": "local.notify",
                        "group": "notify",
                        "capabilities": [
                            {
                                "capability_id": "notify.speak",
                                "kind": "output",
                                "input_schema": {},
                                "output_schema": {},
                            }
                        ],
                    }
                ],
            },
        )
        hb._REGISTERED_edges = brain_db.registration_ids()
        hb.rebuild_capability_maps()

    def test_zero_edge_catalog_includes_system_caps(self) -> None:
        rows = hb._list_schedulable_capabilities()
        by_id = {r["capability_id"]: r for r in rows}
        self.assertIn("capabilities.summary", by_id)
        self.assertIn("asset.inventory", by_id)
        self.assertIn("image.ocr", by_id)
        for cid in ("capabilities.summary", "asset.inventory", "image.ocr"):
            self.assertEqual(by_id[cid]["kind"], "system")
            self.assertEqual(by_id[cid]["assigned_edge_id"], SYSTEM_EDGE_ID)
            self.assertEqual(by_id[cid]["edge_id"], SYSTEM_EDGE_ID)
        listed = hb.app.test_client().get("/api/v1/capabilities")
        self.assertEqual(listed.status_code, 200)
        ids = [c["capability_id"] for c in listed.get_json()["capabilities"]]
        self.assertIn("capabilities.summary", ids)
        self.assertIn("asset.inventory", ids)
        self.assertIn("image.ocr", ids)

    def test_do_execution_plan_assigns_system_even_if_mac_online(self) -> None:
        brain_db.put_registration(
            {
                "participant_id": "mac-online",
                "device_type": "mac",
                "roles": ["runtime"],
                "services": [
                    {
                        "service_id": "local.clock",
                        "capabilities": [{"capability_id": "clock.now"}],
                    }
                ],
            }
        )
        now = time.time()
        brain_db.put_heartbeat(
            "mac-online",
            {
                "online_status": "online",
                "server_received_at": now,
                "reported_at": now,
                "schedule_eligible": True,
                "services": [
                    {
                        "service_id": "local.clock",
                        "capabilities": [{"capability_id": "clock.now"}],
                    },
                    {
                        "service_id": "local.asset",
                        "capabilities": [{"capability_id": "asset.inventory"}],
                    },
                ],
            },
        )
        hb._REGISTERED_edges = brain_db.registration_ids()
        hb.rebuild_capability_maps()
        iid = hb.new_intent(
            {
                "status": "intent_received",
                "text": "昨天拍了几张照片",
                "source": "text",
            }
        )
        hb.do_execution_plan(
            iid,
            [
                {
                    "step": 1,
                    "capability": "asset.inventory",
                    "assigned_edge_id": "mac-online",
                    "input_constrict": {"type": "image", "day": "yesterday"},
                    "output_constrict": {"answer_text": {}},
                }
            ],
        )
        job = hb.get_intent(iid)
        step = job["execution_plan"][0]
        self.assertEqual(step["assigned_edge_id"], SYSTEM_EDGE_ID)
        self.assertEqual(int(step.get("status") or 0), 2)
        self.assertIn("昨天", job.get("ctx_param", {}).get("answer_text") or "")
        self.assertEqual(job["status"], "succeeded")
        self.assertNotIn("asset.inventory", hb.capability_edge_mapping)

    def test_inventory_runs_with_no_mac(self) -> None:
        now = datetime.now(ZoneInfo("Asia/Shanghai")).timestamp()
        brain_db.put_asset(
            {
                "asset_id": "asset_sys_1",
                "type": "image",
                "mime_type": "image/jpeg",
                "status": "available",
                "producer_capability": "camera.capture",
                "intent_id": "1",
                "created_at": now,
                "storage": {"backend": "img_server", "key": "a.jpg"},
            }
        )
        iid = hb.new_intent(
            {
                "status": "intent_received",
                "text": "今天拍了几张照片",
                "source": "text",
            }
        )
        hb.do_execution_plan(
            iid,
            [
                {
                    "step": 1,
                    "capability": "asset.inventory",
                    "input_constrict": {"type": "image", "day": "today"},
                    "output_constrict": {"answer_text": {}, "count": {}},
                }
            ],
        )
        job = hb.get_intent(iid)
        self.assertEqual(job["status"], "succeeded")
        self.assertEqual(job["execution_plan"][0]["assigned_edge_id"], SYSTEM_EDGE_ID)
        self.assertEqual(int(job["execution_plan"][0]["status"]), 2)
        self.assertEqual(job["ctx_param"]["count"], "1")
        self.assertIn("今天一共登记了 1 张照片", job["ctx_param"]["answer_text"])

    def test_summary_runs_with_no_mac(self) -> None:
        iid = hb.new_intent(
            {
                "status": "intent_received",
                "text": "你会什么",
                "source": "text",
            }
        )
        hb.do_execution_plan(
            iid,
            [
                {
                    "step": 1,
                    "capability": "capabilities.summary",
                    "input_constrict": {},
                    "output_constrict": {"answer_text": {}},
                }
            ],
        )
        job = hb.get_intent(iid)
        self.assertEqual(job["status"], "succeeded")
        self.assertEqual(job["execution_plan"][0]["assigned_edge_id"], SYSTEM_EDGE_ID)
        answer = job["ctx_param"]["answer_text"]
        self.assertTrue(answer)
        self.assertNotIn("capabilities.summary", answer)

    def test_mixed_plan_keeps_speak_on_issuer(self) -> None:
        self._register_voice_runtime("mac-voice-plan")
        iid = hb.new_intent(
            {
                "status": "intent_received",
                "text": "你会什么",
                "source": "voice",
                "edge_id": "mac-voice-plan",
                "presentation": {"type": "audio", "from": "answer_text"},
            }
        )
        hb.do_execution_plan(
            iid,
            [
                {
                    "step": 1,
                    "capability": "capabilities.summary",
                    "input_constrict": {},
                    "output_constrict": {"answer_text": {}},
                }
            ],
        )
        job = hb.get_intent(iid)
        plan = job["execution_plan"]
        self.assertEqual(len(plan), 2)
        self.assertEqual(plan[0]["capability"], "capabilities.summary")
        self.assertEqual(plan[0]["assigned_edge_id"], SYSTEM_EDGE_ID)
        self.assertEqual(int(plan[0]["status"]), 2)
        self.assertEqual(plan[1]["capability"], "notify.speak")
        self.assertEqual(plan[1]["assigned_edge_id"], "mac-voice-plan")
        self.assertEqual(int(plan[1].get("status") or 0), 0)
        self.assertNotIn(job["status"], ("succeeded", "failed"))

    def test_planner_prompt_mentions_system_kind_not_ids(self) -> None:
        prompt = hb.compact_prompt()
        self.assertIn("`system`", prompt)
        self.assertIn("not bound to a Runtime", prompt)
        self.assertNotIn("capabilities.summary", prompt)
        self.assertNotIn("asset.inventory", prompt)


if __name__ == "__main__":
    unittest.main()
