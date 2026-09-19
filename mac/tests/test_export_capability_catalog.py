"""能力目录导出器：定义/声明/能力包/实况四层合并 + 漂移检查。

重点钉三件事：
1. **无副作用**：导出绝不能调用 `services.default_services()`（它会起 game host、探测设备）；
2. **确定性**：同输入两次导出除 generated_at 外逐字一致（否则 --check 没法用）；
3. **该抓的漂移要抓到**：能力增删、契约字段变化；而实况（谁在线）变化不该算漂移。
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

MAC = Path(__file__).resolve().parents[1]
SRC = MAC / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

EXPORTER = MAC / "scripts" / "export_capability_catalog.py"
_spec = importlib.util.spec_from_file_location("export_capability_catalog", EXPORTER)
assert _spec and _spec.loader
exporter = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(exporter)


LIVE_FIXTURE = {
    "ok": True,
    "count": 2,
    "capabilities": [
        {
            "capability_id": "display.audio",
            "kind": "output",
            "composition": "atomic",
            "role": "音频投电视播放器",
            "planner_recognize": "实况版：把 audio Asset 交给电视 DLNA",
            "typical_triggers": ["把最新的音频在小米电视上放出来"],
            "do_not_dispatch": ["投图", "点歌放歌"],
            "group": "display",
            "display_name": "小米电视 DLNA",
            "input_schema": {"asset_ref": {"type": "object", "required": True, "description": "必填"}},
            "output_schema": {"status_text": {"type": "string", "description": "确认语"}},
            "edge_id": "edge-node-TEST",
            "edge_name": "客厅 · Mac Edge",
            "assigned_edge_id": "edge-node-TEST",
            "service_id": "xiaomi.tv.display",
        },
        {
            # 只在线、不在 ADS：验证「线上未声明」记账
            "capability_id": "xiaodu.control",
            "kind": "action",
            "composition": "atomic",
            "role": "小度控制器",
            "group": "voice",
            "display_name": "小度音箱",
            "edge_id": "edge-node-TEST",
            "edge_name": "客厅 · Mac Edge",
            "service_id": "xiaodu.speaker",
        },
    ],
}


class ExportCatalogTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.live_path = Path(self.tmp.name) / "live.json"
        self.live_path.write_text(json.dumps(LIVE_FIXTURE, ensure_ascii=False), encoding="utf-8")
        self.out = Path(self.tmp.name) / "marketplace"

    def _build(self):
        return exporter.build_catalog(live_json=str(self.live_path))

    def test_definition_layer_comes_from_ads_and_services(self) -> None:
        catalog = self._build()
        by_id = {c["capability_id"]: c for c in catalog["capabilities"]}
        cap = by_id["display.audio"]
        self.assertTrue(cap["in_ads"])
        self.assertTrue(cap["in_live"])
        self.assertEqual(cap["definition"]["kind"], "output")
        self.assertIn("asset_ref", cap["definition"]["input_schema"])
        self.assertIn("xiaomi.tv.display", cap["declared_by"])
        # 实况层单存一份（原文覆盖不污染定义层）
        self.assertEqual(cap["live"]["role"], "音频投电视播放器")
        self.assertEqual(cap["live"]["providers"][0]["edge_name"], "客厅 · Mac Edge")
        self.assertTrue(cap["definition"]["sources"])

    def test_reconcile_bookkeeping(self) -> None:
        catalog = self._build()
        by_id = {c["capability_id"]: c for c in catalog["capabilities"]}
        self.assertTrue(by_id["xiaodu.control"]["reconcile"]["live_not_declared"])
        self.assertTrue(by_id["camera.capture"]["reconcile"]["declared_not_live"])
        self.assertGreaterEqual(catalog["summary"]["declared_not_live"], 1)
        self.assertEqual(catalog["summary"]["live_not_declared"], 1)

    def test_no_side_effects_no_default_services(self) -> None:
        """导出绝不能碰 default_services()（它会 ensure_running 起 game host）。"""
        from mac_edge import services as real_services

        called: list[str] = []
        original = real_services.default_services
        real_services.default_services = lambda *a, **k: called.append("boom")  # type: ignore[assignment]
        try:
            self._build()
        finally:
            real_services.default_services = original  # type: ignore[assignment]
        self.assertEqual(called, [], "导出过程不允许调用 default_services()")

    def test_deterministic_except_generated_at(self) -> None:
        a, b = self._build(), self._build()
        a.pop("generated_at"), b.pop("generated_at")
        self.assertEqual(a, b)

    def test_write_then_check_passes_and_removes_stale_pages(self) -> None:
        catalog = self._build()
        exporter.write_catalog(catalog, self.out)
        self.assertTrue((self.out / "catalog/capabilities.json").is_file())
        self.assertTrue((self.out / "capabilities/display.audio.md").is_file())
        self.assertTrue((self.out / "schema/catalog.schema.json").is_file())
        # 离线 check 也要一致（实况差异不算漂移）
        self.assertEqual(exporter.check_catalog(exporter.build_catalog(), self.out), [])
        self.assertEqual(exporter.check_catalog(catalog, self.out), [])
        # 代码里删掉一个能力 → 仓库里的旧页要清掉
        stale = self.out / "capabilities/gone.away.md"
        stale.write_text("stale", encoding="utf-8")
        exporter.write_catalog(catalog, self.out)
        self.assertFalse(stale.exists(), "已不存在的能力页必须被清掉")

    def test_check_reports_drift(self) -> None:
        catalog = self._build()
        exporter.write_catalog(catalog, self.out)
        path = self.out / "catalog/capabilities.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        for cap in data["capabilities"]:
            if cap["capability_id"] == "display.audio":
                cap["definition"]["typical_triggers"] = ["被篡改"]
        data["capabilities"] = [c for c in data["capabilities"] if c["capability_id"] != "clock.now"]
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        joined = "\n".join(exporter.check_catalog(catalog, self.out))
        self.assertIn("display.audio", joined)
        self.assertIn("clock.now", joined)

    def test_markdown_sections_and_params(self) -> None:
        catalog = self._build()
        md = exporter.render_catalog_md(catalog)
        for section in ("# 能力总表", "## 概览", "## 能力清单（按 group）", "声明未上线", "线上未声明"):
            self.assertIn(section, md)
        cap = next(c for c in catalog["capabilities"] if c["capability_id"] == "display.audio")
        cap_md = exporter.render_capability_md(cap, catalog)
        for section in ("## 规划器怎么认它", "## 典型触发语", "## 入参", "## 谁提供", "## 文档"):
            self.assertIn(section, cap_md)
        self.assertIn("asset_ref", cap_md)

    def test_schema_lists_definition_and_live(self) -> None:
        props = exporter.catalog_schema()["properties"]["capabilities"]["items"]["properties"]
        self.assertIn("definition", props)
        self.assertIn("live", props)
        self.assertEqual(exporter.catalog_schema()["properties"]["schema"]["const"], exporter.SCHEMA_ID)

    def test_conditional_owner_map_still_matches_code(self) -> None:
        """CONDITIONAL_OWNERS 里点到的常量必须真的存在（否则小表会悄悄腐烂）。"""
        consts = exporter._capability_constants()
        for name, owners in exporter.CONDITIONAL_OWNERS.items():
            self.assertIn(name, consts, f"{name} 已不在 services.py 里，请更新 CONDITIONAL_OWNERS")
            self.assertTrue(owners)


if __name__ == "__main__":
    unittest.main()

