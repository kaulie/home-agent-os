"""Heartbeat capability ads must expose structured planner fields (not 「能：/不能：」)."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from mac_edge.services import default_services

REQUIRED_PLANNER_KEYS = (
    "kind",
    "composition",
    "role",
    "planner_recognize",
    "typical_triggers",
    "do_not_dispatch",
)


def _caps(services: list[dict]) -> list[dict]:
    out: list[dict] = []
    for svc in services:
        for cap in svc.get("capabilities") or []:
            out.append(cap)
    return out


class PlannerAdTests(unittest.TestCase):
    def test_laptop_caps_have_structured_planner_fields(self) -> None:
        env = {
            "MAC_EDGE_ROLE": "laptop",
            "MAC_EDGE_SERVICE_WHITELIST": "",
            "MAC_EDGE_GOPRO_SSID": "",
            "MAC_EDGE_ADVERTISE_CAST": "1",
            "MAC_EDGE_HISENSE_USERNAME": "",
            "MAC_EDGE_HISENSE_PASSWORD": "",
            "MAC_EDGE_XIAOMI_USERNAME": "",
            "MAC_EDGE_XIAOMI_PASSWORD": "",
            "MAC_EDGE_XIAOMI_TV": "",
            "MAC_EDGE_DISPLAY_BACKEND": "",
            "MAC_EDGE_XIAOMI_TV_HOST": "",
        }
        with patch.dict(os.environ, env, clear=False):
            caps = _caps(default_services())
        ids = {c["capability_id"] for c in caps}
        self.assertNotIn("asset.inventory", ids)
        self.assertNotIn("capabilities.summary", ids)
        self.assertGreaterEqual(
            ids,
            {
                "display.photo",
                "display.slideshow",
                "notify.speak",
                "query.content",
                "search.images",
                "clock.now",
                "math.calculate",
                "chat.smalltalk",
                "asset.upload",
                "voice.stream",
                "voicewakeup.echo",
                "vision.perceive",
                "vision.ask",
                "voice_test.run_trial",
            },
        )
        for cap in caps:
            cid = cap["capability_id"]
            for key in REQUIRED_PLANNER_KEYS:
                self.assertIn(key, cap, f"{cid} missing {key}")
            self.assertIn(cap["kind"], {"input", "action", "output"}, cid)
            self.assertIn(cap["composition"], {"atomic", "composite"}, cid)
            self.assertTrue(str(cap["role"]).strip(), cid)
            self.assertTrue(str(cap["planner_recognize"]).strip(), cid)
            self.assertIsInstance(cap["typical_triggers"], list, cid)
            self.assertIsInstance(cap["do_not_dispatch"], list, cid)
            self.assertTrue(cap["typical_triggers"], cid)
            self.assertTrue(cap["do_not_dispatch"], cid)
            # Prose 「能：/不能：」 is no longer the planning contract.
            self.assertNotIn("能：", str(cap.get("description") or ""), cid)
            self.assertNotIn("不能：", str(cap.get("description") or ""), cid)
            if cid == "asset.upload":
                self.assertEqual(cap["kind"], "action")
                self.assertIn("asset_ref", cap.get("input_schema") or {})
                self.assertTrue(
                    any("传到云上" in t or "图床" in t for t in cap["typical_triggers"]),
                    cap["typical_triggers"],
                )
                self.assertIn("拍照", cap["do_not_dispatch"])
            if cid == "math.calculate":
                self.assertEqual(cap["kind"], "action")
                self.assertIn("应用题", cap["do_not_dispatch"])
                self.assertTrue(
                    any("根号" in t or "1+1" in t for t in cap["typical_triggers"]),
                    cap["typical_triggers"],
                )
            if cid == "query.content":
                self.assertEqual(cap["kind"], "action")
                self.assertIn("报时", cap["do_not_dispatch"])
                self.assertIn("控制设备", cap["do_not_dispatch"])
                self.assertIn("你可以做什么", cap["do_not_dispatch"])
                self.assertIn("文搜图", cap["do_not_dispatch"])
                self.assertIn("搜网上实拍图", cap["do_not_dispatch"])
                self.assertTrue(
                    any("画" in t or "生成" in t for t in cap["typical_triggers"]),
                    cap["typical_triggers"],
                )
                self.assertIn("生图", cap["planner_recognize"])
            if cid == "search.images":
                self.assertEqual(cap["kind"], "action")
                self.assertIn("AI文生图", cap["do_not_dispatch"])
                self.assertIn("画一张", cap["do_not_dispatch"])
                self.assertIn("生成图片", cap["do_not_dispatch"])
                self.assertTrue(
                    any("搜一张" in t or "实拍" in t for t in cap["typical_triggers"]),
                    cap["typical_triggers"],
                )
                self.assertIn("存量实拍", cap["planner_recognize"])
                self.assertIn("asset_refs", cap.get("output_schema") or {})
                self.assertNotIn("photo_url", cap.get("output_schema") or {})
            if cid == "voice.stream":
                self.assertEqual(cap["kind"], "input")
                self.assertTrue(
                    any("计划" in x or "逐步" in x for x in cap["do_not_dispatch"]),
                    cap["do_not_dispatch"],
                )
            if cid == "voicewakeup.echo":
                self.assertEqual(cap["kind"], "output")
                self.assertTrue(
                    any("计划" in x or "逐步" in x for x in cap["do_not_dispatch"]),
                    cap["do_not_dispatch"],
                )
                self.assertFalse(
                    any("又咋了" in t or "唤醒回应" in t for t in cap["typical_triggers"]),
                    cap["typical_triggers"],
                )
            if cid == "notify.speak":
                self.assertEqual(cap["kind"], "output")
            if cid == "camera.capture":
                self.assertEqual(cap["kind"], "input")
                self.assertTrue(
                    any("上传" in x or "图床" in x for x in cap["do_not_dispatch"]),
                    cap["do_not_dispatch"],
                )
                self.assertNotIn("upload_dest", cap.get("input_schema") or {})
    def test_home_server_caps_have_structured_planner_fields(self) -> None:
        env = {
            "MAC_EDGE_ROLE": "home-server",
            "MAC_EDGE_SERVICE_WHITELIST": "",
            "MAC_EDGE_GOPRO_SSID": "xuanxuan",
            "MAC_EDGE_ADVERTISE_CAST": "0",
            "MAC_EDGE_HISENSE_USERNAME": "",
            "MAC_EDGE_HISENSE_PASSWORD": "",
            "MAC_EDGE_XIAOMI_USERNAME": "",
            "MAC_EDGE_XIAOMI_PASSWORD": "",
            "MAC_EDGE_XIAOMI_TV": "",
            "MAC_EDGE_DISPLAY_BACKEND": "",
            "MAC_EDGE_XIAOMI_TV_HOST": "",
        }
        with patch.dict(os.environ, env, clear=False):
            caps = _caps(default_services())
        ids = {c["capability_id"] for c in caps}
        self.assertEqual(
            ids, {"camera.capture", "camera.capture_and_upload", "light.set", "asset.upload"}
        )
        for cap in caps:
            for key in REQUIRED_PLANNER_KEYS:
                self.assertIn(key, cap, cap["capability_id"])
            self.assertTrue(cap["role"])
            self.assertTrue(cap["planner_recognize"])
            self.assertTrue(cap["do_not_dispatch"])
        capture = next(c for c in caps if c["capability_id"] == "camera.capture")
        self.assertTrue(
            any("上传" in x or "图床" in x for x in capture["do_not_dispatch"]),
            capture["do_not_dispatch"],
        )
        self.assertNotIn("upload_dest", capture.get("input_schema") or {})
        self.assertIn("capture_ref", capture.get("output_schema") or {})
        self.assertNotIn("asset_ref", capture.get("output_schema") or {})
        self.assertIn("capture_ref", capture["planner_recognize"])
        composite = next(c for c in caps if c["capability_id"] == "camera.capture_and_upload")
        self.assertEqual(composite["composition"], "composite")
        self.assertEqual(composite["decomposes_to"], ["camera.capture", "asset.upload"])
        self.assertTrue(str(composite.get("prefer_when") or "").strip())
        self.assertIn("asset_ref", composite.get("output_schema") or {})
        upload = next(c for c in caps if c["capability_id"] == "asset.upload")
        self.assertIn("asset_ref", upload.get("input_schema") or {})
        self.assertTrue(
            any("传到云上" in t or "图床" in t for t in upload["typical_triggers"]),
            upload["typical_triggers"],
        )

    def test_laptop_climate_ads_are_structured(self) -> None:
        env = {
            "MAC_EDGE_ROLE": "laptop",
            "MAC_EDGE_SERVICE_WHITELIST": "",
            "MAC_EDGE_GOPRO_SSID": "",
            "MAC_EDGE_ADVERTISE_CAST": "0",
            "MAC_EDGE_HISENSE_USERNAME": "13800000000",
            "MAC_EDGE_HISENSE_PASSWORD": "secret",
            "MAC_EDGE_HISENSE_LABEL": "客厅空调",
            "MAC_EDGE_XIAOMI_USERNAME": "",
            "MAC_EDGE_XIAOMI_PASSWORD": "",
            "MAC_EDGE_DISPLAY_BACKEND": "",
            "MAC_EDGE_XIAOMI_TV": "",
        }
        with patch.dict(os.environ, env, clear=False):
            services = default_services()
            caps = _caps(services)
        climate_svc = next(s for s in services if s["group"] == "climate")
        self.assertEqual(climate_svc["service_id"], "climate.living_room")
        self.assertEqual(climate_svc["display_name"], "客厅空调")
        climate = next(c for c in caps if c["capability_id"] == "climate.set")
        for key in REQUIRED_PLANNER_KEYS:
            self.assertIn(key, climate)
        self.assertEqual(climate["role"], "客厅空调控制器")
        self.assertIn("客厅空调", climate["planner_recognize"])
        self.assertEqual(climate["typical_triggers"][0], "打开客厅空调")
        self.assertIn("关掉客厅空调", climate["typical_triggers"])
        if "打开空调" in climate["typical_triggers"]:
            self.assertGreater(
                climate["typical_triggers"].index("打开空调"),
                climate["typical_triggers"].index("打开客厅空调"),
            )
        self.assertIn("风速高", climate["typical_triggers"])
        self.assertIn("新风", climate["do_not_dispatch"])
        self.assertNotIn("风速/扫风/新风", climate["do_not_dispatch"])
        self.assertNotIn("能：", str(climate.get("description") or ""))

    def test_kids_room_climate_ads_differ_from_living_room(self) -> None:
        env = {
            "MAC_EDGE_ROLE": "laptop",
            "MAC_EDGE_SERVICE_WHITELIST": "",
            "MAC_EDGE_GOPRO_SSID": "",
            "MAC_EDGE_ADVERTISE_CAST": "0",
            "MAC_EDGE_HISENSE_USERNAME": "13800000000",
            "MAC_EDGE_HISENSE_PASSWORD": "secret",
            "MAC_EDGE_HISENSE_LABEL": "儿童房空调",
            "MAC_EDGE_XIAOMI_USERNAME": "",
            "MAC_EDGE_XIAOMI_PASSWORD": "",
            "MAC_EDGE_DISPLAY_BACKEND": "",
            "MAC_EDGE_XIAOMI_TV": "",
        }
        with patch.dict(os.environ, env, clear=False):
            services = default_services()
        climate_svc = next(s for s in services if s["group"] == "climate")
        self.assertEqual(climate_svc["service_id"], "climate.kids_room")
        self.assertEqual(climate_svc["display_name"], "儿童房空调")
        climate = climate_svc["capabilities"][0]
        self.assertEqual(climate["role"], "儿童房空调控制器")
        self.assertEqual(climate["typical_triggers"][0], "打开儿童房空调")
        self.assertNotEqual(climate["typical_triggers"][0], "打开空调")

    def test_two_bound_units_advertise_two_named_climate_ads(self) -> None:
        env = {
            "MAC_EDGE_ROLE": "laptop",
            "MAC_EDGE_SERVICE_WHITELIST": "",
            "MAC_EDGE_GOPRO_SSID": "",
            "MAC_EDGE_ADVERTISE_CAST": "0",
            "MAC_EDGE_HISENSE_USERNAME": "13800000000",
            "MAC_EDGE_HISENSE_PASSWORD": "secret",
            "MAC_EDGE_HISENSE_DEVICES": (
                '[{"device_id":"a","label":"客厅空调"},'
                '{"device_id":"b","label":"儿童房空调"}]'
            ),
            "MAC_EDGE_HISENSE_LABEL": "",
            "MAC_EDGE_XIAOMI_USERNAME": "",
            "MAC_EDGE_XIAOMI_PASSWORD": "",
            "MAC_EDGE_DISPLAY_BACKEND": "",
            "MAC_EDGE_XIAOMI_TV": "",
        }
        with patch.dict(os.environ, env, clear=False):
            services = default_services()
        climate = [s for s in services if s.get("group") == "climate"]
        self.assertEqual(len(climate), 2)
        by_id = {s["service_id"]: s for s in climate}
        self.assertEqual(by_id["climate.living_room"]["display_name"], "客厅空调")
        self.assertEqual(by_id["climate.kids_room"]["display_name"], "儿童房空调")

    def test_character_service_ads_mark_point_to_character_composite(self) -> None:
        env = {
            "MAC_EDGE_ROLE": "laptop",
            "MAC_EDGE_SERVICE_WHITELIST": "",
            "MAC_EDGE_GOPRO_SSID": "",
            "MAC_EDGE_ADVERTISE_CAST": "0",
            "MAC_EDGE_HISENSE_USERNAME": "",
            "MAC_EDGE_HISENSE_PASSWORD": "",
            "MAC_EDGE_XIAOMI_USERNAME": "",
            "MAC_EDGE_XIAOMI_PASSWORD": "",
            "MAC_EDGE_DISPLAY_BACKEND": "",
            "MAC_EDGE_XIAOMI_TV": "",
        }
        with patch.dict(os.environ, env, clear=False), patch(
            "mac_edge.services._character_service_listening", return_value=True
        ):
            caps = {c["capability_id"]: c for c in _caps(default_services())}
        composite = caps["reading.point_to_character"]
        self.assertEqual(composite["composition"], "composite")
        self.assertEqual(
            composite["decomposes_to"],
            ["reading.detect_finger", "reading.ocr_at_finger", "reading.rank_pointed"],
        )
        self.assertTrue(str(composite.get("prefer_when") or "").strip())
        schema = composite.get("input_schema") or {}
        self.assertIn("asset_ref", schema)
        self.assertTrue((schema.get("asset_ref") or {}).get("required"))
        self.assertNotIn("dest", schema)
        for atomic_id in (
            "reading.detect_finger",
            "reading.ocr_at_finger",
            "reading.rank_pointed",
        ):
            atomic = caps[atomic_id]
            self.assertEqual(atomic["composition"], "atomic")
            self.assertNotIn("decomposes_to", atomic)
            self.assertIn("asset_ref", atomic.get("input_schema") or {})


if __name__ == "__main__":
    unittest.main()
