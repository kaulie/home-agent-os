"""能力目录导出器：ADS / 服务声明 / 可用性 / 能力包 四层合并。

重点钉三件事：
1. **无副作用**：导出绝不能调用 `services.default_services()`（它会起 game host、探测设备）；
2. **确定性**：同输入两次导出除 generated_at 外逐字一致；
3. **只出声明**：产物里不许出现任何实时状态字段（在线/设备/providers/reconcile）。

漂移对账不在这里做（产物结构 ≠ 集市仓库里的库导出）：
由集市侧 `scripts/sync.sh <home-agent-os> --check` 负责。
"""

from __future__ import annotations

import importlib.util
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

# 集市定位：能力展示与技能介绍（静态声明）。这些实时概念一律不该出现在产物里。
LIVE_FIELDS = ("live", "in_live", "providers", "reconcile", "registered_ids")


class ExportCatalogTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / "marketplace"

    def _build(self):
        return exporter.build_catalog()

    def test_definition_layer_comes_from_ads_and_services(self) -> None:
        catalog = self._build()
        by_id = {c["capability_id"]: c for c in catalog["capabilities"]}
        cap = by_id["display.audio"]
        self.assertTrue(cap["in_ads"])
        self.assertEqual(cap["definition"]["kind"], "output")
        self.assertIn("asset_ref", cap["definition"]["input_schema"])
        self.assertIn("xiaomi.tv.display", cap["declared_by"])
        self.assertTrue(cap["definition"]["sources"])
        self.assertTrue(cap["availability"]["has_checker"] in (True, False))

    def test_catalog_has_no_realtime_fields(self) -> None:
        catalog = self._build()
        self.assertEqual(set(catalog["source"]) & set(LIVE_FIELDS), set())
        self.assertEqual(set(catalog["summary"]) & set(LIVE_FIELDS), set())
        for cap in catalog["capabilities"]:
            self.assertEqual(set(cap) & set(LIVE_FIELDS), set(), cap["capability_id"])

    def test_export_does_not_call_default_services(self) -> None:
        """导出必须是纯读：default_services() 会 ensure_running() 起进程/探测设备。"""
        import mac_edge.services as real_services

        called: list[str] = []
        original = real_services.default_services
        real_services.default_services = lambda *a, **k: called.append("boom")  # type: ignore[assignment]
        try:
            self._build()
        finally:
            real_services.default_services = original  # type: ignore[assignment]
        self.assertEqual(called, [], "导出过程不允许调用 default_services()")

    def test_brain_layer_fills_declaration_gaps(self) -> None:
        """Brain 侧声明**只补**本机没说的：新能力 / 服务归属 / kind=system → 宿主 brain。"""
        catalog = self._build()
        by_id = {c["capability_id"]: c for c in catalog["capabilities"]}
        # 1) 只在 Brain 侧声明的能力进了目录：算「在 ADS 里」、宿主含 brain、有服务归属
        route = by_id["map.route.estimate"]
        self.assertTrue(route["in_ads"])
        self.assertIn("brain", route["runs_on"])
        self.assertIn("system.map", route["declared_by"])
        self.assertTrue(route["definition"]["planner_recognize"])
        # 2) 本机 ADS 没给服务归属的，用 wire 规格补上
        self.assertIn("system.asset", by_id["asset.inventory"]["declared_by"])
        self.assertIn("marshall.willen", by_id["bluetooth.connect"]["declared_by"])
        # 3) 定义层不覆盖本机 ADS（gap-fill）
        self.assertIn("ads", by_id["display.audio"]["definition"]["sources"])
        # 4) mac 侧没声明过的服务进了目录，并标明来源
        brain_svcs = [s for s in catalog["services"] if s.get("source") == "brain.wire"]
        self.assertTrue(brain_svcs)
        self.assertIn("system.map", {s["service_id"] for s in brain_svcs})

    def test_services_have_unique_ids(self) -> None:
        catalog = self._build()
        sids = [s["service_id"] for s in catalog["services"]]
        self.assertEqual(len(sids), len(set(sids)), "服务 id 不许重复（本机 + Brain 合并后）")

    def test_deterministic_except_generated_at(self) -> None:
        a, b = self._build(), self._build()
        a.pop("generated_at"), b.pop("generated_at")
        self.assertEqual(a, b)

    def test_write_and_removes_stale_pages(self) -> None:
        catalog = self._build()
        exporter.write_catalog(catalog, self.out)
        self.assertTrue((self.out / "catalog/capabilities.json").is_file())
        self.assertTrue((self.out / "capabilities/display.audio.md").is_file())
        self.assertTrue((self.out / "schema/catalog.schema.json").is_file())
        # 代码里删掉一个能力 → 仓库里的旧页要清掉
        stale = self.out / "capabilities/gone.away.md"
        stale.write_text("stale", encoding="utf-8")
        exporter.write_catalog(catalog, self.out)
        self.assertFalse(stale.exists(), "已不存在的能力页必须被清掉")

    def test_markdown_sections_and_params(self) -> None:
        catalog = self._build()
        md = exporter.render_catalog_md(catalog)
        for section in ("# 能力总表", "## 概览", "## 能力清单（按 group）"):
            self.assertIn(section, md)
        for gone in ("当前在线", "声明未上线", "线上未声明"):
            self.assertNotIn(gone, md)
        cap = next(c for c in catalog["capabilities"] if c["capability_id"] == "display.audio")
        cap_md = exporter.render_capability_md(cap, catalog)
        for section in ("## 规划器怎么认它", "## 典型触发语", "## 入参", "## 服务声明", "## 能力包"):
            self.assertIn(section, cap_md)
        self.assertIn("asset_ref", cap_md)
        self.assertIn("执行前自检=`", cap_md)
        for gone in ("谁提供", "当前在线"):
            self.assertNotIn(gone, cap_md)

    def test_schema_is_declaration_only(self) -> None:
        schema = exporter.catalog_schema()
        props = schema["properties"]["capabilities"]["items"]["properties"]
        self.assertIn("definition", props)
        for gone in LIVE_FIELDS:
            self.assertNotIn(gone, props)
        self.assertEqual(schema["properties"]["schema"]["const"], exporter.SCHEMA_ID)

    def test_conditional_owner_map_still_matches_code(self) -> None:
        """CONDITIONAL_OWNERS 里点到的常量必须真的存在（否则小表会悄悄腐烂）。"""
        consts = exporter._capability_constants()
        for name, owners in exporter.CONDITIONAL_OWNERS.items():
            self.assertIn(name, consts, f"{name} 已不在 services.py 里，请更新 CONDITIONAL_OWNERS")
            self.assertTrue(owners)


if __name__ == "__main__":
    unittest.main()
