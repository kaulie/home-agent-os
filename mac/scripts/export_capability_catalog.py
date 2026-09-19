#!/usr/bin/env python3
"""导出 mac edge 的能力目录（给 capability-marketplace 用）。

只读、可重复、**无副作用** —— 刻意不调用 `services.default_services()`：
它会 `ensure_running()` 起 game host、探测网络与设备。目录导出必须能安全地随时重跑。

数据来源（逐层合并，缺哪层都能出目录）：

  1. 定义层  mac_edge.capability_ads.ADS —— 规划器广告（kind/composition/role/触发语/不要派给谁）
  2. 声明层  mac_edge.services 的 `*_SERVICE` 常量 —— service_id → capabilities（含 input/output schema）
  3. 可用性  mac_edge.capability_availability —— 该能力有没有执行前探测（有无 checker）
  4. 文档层  plugins/*/manifest.yaml + capability.md —— 能力包（display_name/group/entry/config/文档）

产物（写进 --out 指向的仓库，通常是 capability-marketplace 的检出目录）：

  catalog/capabilities.json   机器可读全量目录（含 source/summary/capabilities）
  catalog/capabilities.md     人读总表（按 group 分组）
  schema/catalog.schema.json  catalog 结构约束（由本脚本生成，避免手写漂移）
  capabilities/<id>.md        每个能力一页（触发语/参数表/不要派给谁/在哪台设备/文档链接）

用法：

  # 生成（只出声明层：集市是「能力展示与技能介绍」，不登记实时状态）
  python3 mac/scripts/export_capability_catalog.py --out ../home-agent-capabilty-marketplace

  # CI：代码改了但目录没更新 → 非零退出（忽略 generated_at/commit 这类易变字段）
  python3 mac/scripts/export_capability_catalog.py --out ../home-agent-capabilty-marketplace --check
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

SCHEMA_ID = "home-agent.capability-catalog/v1"
GENERATED_BY = "mac/scripts/export_capability_catalog.py"
# --check 比对时忽略的易变字段（每次生成都会变，不代表能力变了）
VOLATILE_KEYS = ("generated_at",)


def mac_src() -> Path:
    return Path(__file__).resolve().parents[1] / "src"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _import_mac_edge():
    src = str(mac_src())
    if src not in sys.path:
        sys.path.insert(0, src)
    from mac_edge import capability_ads, capability_availability  # noqa: PLC0415

    return capability_ads, capability_availability


def _service_constants() -> dict[str, dict[str, Any]]:
    """services.py 里静态声明的服务（`*_SERVICE` 且是 dict）。动态生成的（如按设备 label 的空调）不在其中。"""
    src = str(mac_src())
    if src not in sys.path:
        sys.path.insert(0, src)
    from mac_edge import services  # noqa: PLC0415

    out: dict[str, dict[str, Any]] = {}
    for name in dir(services):
        if not name.endswith("_SERVICE"):
            continue
        value = getattr(services, name)
        if isinstance(value, dict) and value.get("service_id"):
            out[name] = value
    return out


def _manifest_packages(root: Path) -> list[dict[str, Any]]:
    """读 plugins/*/manifest.yaml（轻量解析：id/service_id/group/platforms/entry/config/capabilities）。

    `platforms:` 与 `entry:` 的键就是**适用宿主**（capability 跑在哪：`mac` = Mac Edge、`brain` = 服务端…），
    是代码层面的事实 —— 集市据此给出「代码认为它该跑在哪」，人工可以再改（集市字段 `hosts`）。
    """
    packages: list[dict[str, Any]] = []
    plugins = root / "plugins"
    if not plugins.is_dir():
        return packages
    for manifest in sorted(plugins.glob("*/manifest.yaml")):
        text = manifest.read_text(encoding="utf-8")
        pkg: dict[str, Any] = {
            "package": manifest.parent.name,
            "docs": f"plugins/{manifest.parent.name}/capability.md",
            "capability_ids": [],
            "config_keys": [],
        }
        for key in ("id", "service_id", "group", "version", "display_name", "description"):
            m = re.search(rf"^{key}:\s*(.+)$", text, re.M)
            if m:
                pkg[key] = m.group(1).strip().strip('"').strip("'")
        pkg["entry"] = {}
        entry_block = re.search(r"^entry:\s*\n((?:\s{2,}\S.*\n|\s*\n)*)", text, re.M)
        if entry_block:
            for m in re.finditer(r"^\s{2}([A-Za-z_][\w]*):\s*(.+)$", entry_block.group(1), re.M):
                value = m.group(2).strip().strip('"').strip("'")
                if value.endswith("/"):
                    continue  # 目录聚合（如 providers/ 一堆实现），不是宿主
                pkg["entry"][m.group(1).strip()] = value
        pkg["platforms"] = []
        plat_block = re.search(r"^platforms:\s*\n((?:\s*-\s*\S.*\n?)+)", text, re.M)
        if plat_block:
            pkg["platforms"] = [m.group(1).strip() for m in re.finditer(r"-\s*([\w.\-]+)", plat_block.group(1))]
        caps_block = re.search(r"^capabilities:\s*\n((?:\s+.*\n|\s*\n)*)", text, re.M)
        if caps_block:
            for m in re.finditer(r"^\s+-\s*(?:capability_id:\s*)?([A-Za-z][\w.\-]*)\s*$", caps_block.group(1), re.M):
                cid = m.group(1).strip()
                if cid not in pkg["capability_ids"]:
                    pkg["capability_ids"].append(cid)
        for m in re.finditer(r"^\s+-\s+key:\s*([A-Za-z0-9_]+)", text, re.M):
            if m.group(1) not in pkg["config_keys"]:
                pkg["config_keys"].append(m.group(1))
        packages.append(pkg)
    return packages


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(repo_root()),
            capture_output=True,
            text=True,
            timeout=5,
        )
        return (out.stdout or "").strip()
    except Exception:  # noqa: BLE001 - 不在 git 里也能导出
        return ""


DEFINITION_FIELDS = (
    "kind",
    "composition",
    "role",
    "planner_recognize",
    "typical_triggers",
    "do_not_dispatch",
    "decomposes_to",
    "prefer_when",
    "group",
    "display_name",
    "input_schema",
    "output_schema",
)


def _blank_layer() -> dict[str, Any]:
    return {
        "kind": "",
        "composition": "atomic",
        "role": "",
        "planner_recognize": "",
        "typical_triggers": [],
        "do_not_dispatch": [],
        "decomposes_to": [],
        "prefer_when": "",
        "group": "",
        "display_name": "",
        "input_schema": {},
        "output_schema": {},
    }


def _new_entry(cid: str) -> dict[str, Any]:
    """一条能力（**声明视图**：完全由代码决定，稳定，可 `--check` 比对）。

    定义层（definition）来自 ADS / services 声明 / 能力包；顶层那几个便捷字段
    （kind/group/display_name/role…）是它的投影，供排序/筛选/链接用。
    """
    return {
        "capability_id": cid,
        "kind": "",
        "composition": "atomic",
        "role": "",
        "group": "",
        "display_name": "",
        "definition": _blank_layer(),
        "declared_by": [],
        "declared_lists": [],
        "packages": [],
        "docs": [],
        "entry": {},
        "runs_on": [],
        "config_keys": [],
        "availability": {"has_checker": False},
        "in_ads": False,
    }


def _write_layer(e: dict[str, Any], layer: str, fields: dict[str, Any], source: str) -> None:
    """把定义层字段写进 entry["definition"]，并记下来源（sources）。"""
    dst = e.setdefault(layer, {})
    for field in DEFINITION_FIELDS:
        if field not in fields or fields[field] in (None, "", [], {}):
            continue
        value = fields[field]
        dst[field] = list(value) if isinstance(value, (list, tuple)) else value
    if layer == "definition":
        sources = dst.setdefault("sources", [])
        if source and source not in sources:
            sources.append(source)


def _merge_ads(by_id: dict[str, dict[str, Any]], ads: dict[str, dict[str, Any]]) -> None:
    for cid, ad in ads.items():
        e = by_id.setdefault(cid, _new_entry(cid))
        e["in_ads"] = True
        _write_layer(e, "definition", {k: ad.get(k) for k in DEFINITION_FIELDS}, "ads")


def _merge_services(
    by_id: dict[str, dict[str, Any]], services_raw: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """合并 services.py 静态声明（service_id → capabilities，含 input/output schema）。"""
    services: list[dict[str, Any]] = []
    for const_name, svc in sorted(services_raw.items()):
        sid = str(svc.get("service_id") or "")
        cap_ids: list[str] = []
        for cap in svc.get("capabilities") or []:
            if not isinstance(cap, dict):
                continue
            cid = str(cap.get("capability_id") or "").strip()
            if not cid:
                continue
            cap_ids.append(cid)
            e = by_id.setdefault(cid, _new_entry(cid))
            if sid and sid not in e["declared_by"]:
                e["declared_by"].append(sid)
            # attach() 会按服务覆盖广告（例如 display 的 role/触发语与 ADS 不同）→ 也算「定义层」
            _write_layer(e, "definition", {k: cap.get(k) for k in DEFINITION_FIELDS}, f"service:{sid}")
        services.append(
            {
                "constant": const_name,
                "service_id": sid,
                "display_name": str(svc.get("display_name") or ""),
                "group": str(svc.get("group") or ""),
                "version": str(svc.get("version") or ""),
                "capabilities": sorted(cap_ids),
            }
        )
    return services


def _merge_packages(by_id: dict[str, dict[str, Any]], packages: list[dict[str, Any]]) -> None:
    """合并 plugins/*/manifest.yaml：能力包、开发者文档、entry（适用宿主）、config 旋钮。"""
    for pkg in packages:
        for cid in pkg["capability_ids"]:
            e = by_id.setdefault(cid, _new_entry(cid))
            if pkg["package"] not in e["packages"]:
                e["packages"].append(pkg["package"])
            if pkg.get("docs") and pkg["docs"] not in e["docs"]:
                e["docs"].append(pkg["docs"])
            for host, path in (pkg.get("entry") or {}).items():
                e["entry"][host] = path
                if host not in e["runs_on"]:
                    e["runs_on"].append(host)
            for host in pkg.get("platforms") or []:
                if host not in e["runs_on"]:
                    e["runs_on"].append(host)
            for key in pkg["config_keys"]:
                if key not in e["config_keys"]:
                    e["config_keys"].append(key)
            _write_layer(
                e,
                "definition",
                {"group": pkg.get("group"), "display_name": pkg.get("display_name")},
                f"package:{pkg['package']}",
            )


def _capability_constants() -> dict[str, list[dict[str, Any]]]:
    """services.py 里**声明但按条件挂**的能力列表常量（如 PDF 投屏、电视音频）。

    为什么单独收：它们不在任何 `*_SERVICE` 的静态 capabilities 里（`_display_capabilities()`
    按依赖/后端动态 extend），但确实是「声明过的能力」—— 正是「声明未上线」那笔账的来源。
    这里只读常量、不做可用性探测，保证定义层与机器环境无关。
    """
    src = str(mac_src())
    if src not in sys.path:
        sys.path.insert(0, src)
    from mac_edge import services  # noqa: PLC0415

    out: dict[str, list[dict[str, Any]]] = {}
    for name in sorted(dir(services)):
        if not name.endswith("_CAPABILITIES"):
            continue
        value = getattr(services, name)
        if isinstance(value, (list, tuple)):
            caps = [dict(c) for c in value if isinstance(c, dict) and c.get("capability_id")]
            if caps:
                out[name] = caps
    return out


# 「条件声明」的能力列表常量 → 会在哪些服务上按条件挂上（小表，配 test_ 钉住不许腐烂）：
# 这些常量是 `_display_capabilities()` 动态 extend 进显示服务的，静态读不到归属关系。
CONDITIONAL_OWNERS: dict[str, list[str]] = {
    "AUDIO_DISPLAY_CAPABILITIES": ["xiaomi.tv.display"],
    "PDF_DISPLAY_CAPABILITIES": ["xiaomi.tv.display", "chromecast.display"],
}


def _merge_declared_caps(
    by_id: dict[str, dict[str, Any]], caps_consts: dict[str, list[dict[str, Any]]]
) -> None:
    for const_name, caps in caps_consts.items():
        owners = CONDITIONAL_OWNERS.get(const_name, [])
        for cap in caps:
            cid = str(cap.get("capability_id") or "").strip()
            if not cid:
                continue
            e = by_id.setdefault(cid, _new_entry(cid))
            lists = e.setdefault("declared_lists", [])
            if const_name not in lists:
                lists.append(const_name)
            for owner in owners:
                if owner not in e["declared_by"]:
                    e["declared_by"].append(owner)
            _write_layer(e, "definition", {k: cap.get(k) for k in DEFINITION_FIELDS}, f"caps:{const_name}")


def build_catalog() -> dict[str, Any]:
    """合并四层来源，返回 catalog（除 generated_at 外是纯函数：同输入必得同输出）。

    只出**声明层**（由代码决定）：集市是能力展示与技能介绍，不登记实时状态。
    """
    capability_ads, capability_availability = _import_mac_edge()
    ads: dict[str, dict[str, Any]] = dict(capability_ads.ADS)
    services_raw = _service_constants()
    packages = _manifest_packages(repo_root())

    by_id: dict[str, dict[str, Any]] = {}
    _merge_ads(by_id, ads)
    services = _merge_services(by_id, services_raw)
    _merge_declared_caps(by_id, _capability_constants())
    _merge_packages(by_id, packages)

    # 可用性探测：执行前 checker（本身无副作用，这里只记录「有没有这道闸」）
    checkers = getattr(capability_availability, "_CHECKERS", {}) or {}
    for cid in checkers:
        by_id.setdefault(cid, _new_entry(cid))["availability"]["has_checker"] = True

    capabilities: list[dict[str, Any]] = []
    for e in by_id.values():
        for field in ("declared_by", "declared_lists", "packages", "docs", "config_keys", "runs_on"):
            e[field] = sorted(dict.fromkeys(e[field]))
        definition = e.get("definition") or {}
        for field in ("typical_triggers", "do_not_dispatch", "decomposes_to"):
            if definition.get(field):
                definition[field] = sorted(dict.fromkeys(definition[field]))
        if definition.get("sources"):
            definition["sources"] = sorted(dict.fromkeys(definition["sources"]))
        # 便捷字段：以定义层为准（稳定排序/筛选用）
        for field, fallback in (("kind", ""), ("composition", "atomic"), ("role", ""),
                                ("group", ""), ("display_name", "")):
            e[field] = str(definition.get(field) or fallback)
        if not e["group"]:
            # 都没给 group 时按 id 前缀归属（display.audio.control → display），保证 UI 分组不漏
            e["group"] = cid.split(".", 1)[0] if "." in (cid := e["capability_id"]) else "(未分类)"
        capabilities.append(e)
    capabilities.sort(key=lambda x: x["capability_id"])


    groups: dict[str, int] = {}
    kinds: dict[str, int] = {}
    for e in capabilities:
        groups[e["group"] or "(未分类)"] = groups.get(e["group"] or "(未分类)", 0) + 1
        kinds[e["kind"] or "(未标注)"] = kinds.get(e["kind"] or "(未标注)", 0) + 1

    return {
        "schema": SCHEMA_ID,
        "generated_by": GENERATED_BY,
        "generated_at": _now_iso(),
        "source": {"repo": "home-agent-os", "commit": _git_commit(), "edge": "mac_edge"},
        "summary": {
            "capabilities": len(capabilities),
            "ads_definitions": len(ads),
            "declared_capabilities": sum(len(s["capabilities"]) for s in services),
            "services": len(services),
            "extensions": len(packages),
            "with_checker": sum(1 for e in capabilities if e["availability"]["has_checker"]),
            "groups": dict(sorted(groups.items())),
            "kinds": dict(sorted(kinds.items())),
        },
        "services": sorted(services, key=lambda s: s["service_id"]),
        "capabilities": capabilities,
    }


def catalog_schema() -> dict[str, Any]:
    """catalog 的结构约束（由导出器生成 → 不会与产物漂移）。"""
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "$id": SCHEMA_ID,
        "title": "Home Agent capability catalog",
        "type": "object",
        "required": ["schema", "source", "summary", "capabilities"],
        "properties": {
            "schema": {"const": SCHEMA_ID},
            "generated_by": {"type": "string"},
            "generated_at": {"type": "string"},
            "source": {
                "type": "object",
                "required": ["repo", "edge"],
                "properties": {
                    "repo": {"type": "string"},
                    "commit": {"type": "string"},
                    "edge": {"type": "string"},
                },
            },
            "summary": {"type": "object"},
            "services": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["service_id"],
                    "properties": {
                        "service_id": {"type": "string"},
                        "display_name": {"type": "string"},
                        "group": {"type": "string"},
                        "version": {"type": "string"},
                        "constant": {"type": "string"},
                        "capabilities": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "capabilities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["capability_id", "kind", "composition", "group"],
                    "properties": {
                        "capability_id": {"type": "string"},
                        "kind": {"type": "string", "enum": ["input", "action", "output", "system", ""]},
                        "composition": {"type": "string", "enum": ["atomic", "composite"]},
                        "role": {"type": "string"},
                        "definition": {"type": "object", "description": "代码决定的定义层（稳定）"},
                        "planner_recognize": {"type": "string"},
                        "typical_triggers": {"type": "array", "items": {"type": "string"}},
                        "do_not_dispatch": {"type": "array", "items": {"type": "string"}},
                        "decomposes_to": {"type": "array", "items": {"type": "string"}},
                        "prefer_when": {"type": "string"},
                        "group": {"type": "string"},
                        "display_name": {"type": "string"},
                        "input_schema": {"type": "object"},
                        "output_schema": {"type": "object"},
                        "declared_by": {"type": "array", "items": {"type": "string"}},
                        "packages": {"type": "array", "items": {"type": "string"}},
                        "docs": {"type": "array", "items": {"type": "string"}},
                        "entry": {"type": "object"},
                        "runs_on": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "代码层面的适用宿主（manifest 的 platforms/entry 键，如 mac/brain）",
                        },
                        "config_keys": {"type": "array", "items": {"type": "string"}},
                        "availability": {
                            "type": "object",
                            "properties": {"has_checker": {"type": "boolean"}},
                        },
                        "in_ads": {"type": "boolean"},
                    },
                },
            },
        },
    }


def _md_escape(text: Any) -> str:
    return str(text or "").replace("|", "\\|").replace("\n", " ").strip()


def _param_rows(schema: dict[str, Any]) -> list[str]:
    rows: list[str] = []
    for name in sorted(schema or {}):
        spec = schema.get(name) or {}
        if not isinstance(spec, dict):
            continue
        req = "是" if spec.get("required") else "否"
        rows.append(
            f"| `{name}` | {_md_escape(spec.get('type') or '')} | {req} | {_md_escape(spec.get('description'))} |"
        )
    return rows


def effective_view(cap: dict[str, Any]) -> dict[str, Any]:
    """展示视图：定义层（声明）投影 + 来源。集市不掺实时状态。"""
    view: dict[str, Any] = {}
    definition = cap.get("definition") or {}
    for field in DEFINITION_FIELDS:
        value = definition.get(field)
        view[field] = value if value is not None else ([] if field.endswith("s") and field != "prefer_when" else "")
    view["sources"] = definition.get("sources") or []
    return view


def render_capability_md(cap: dict[str, Any], catalog: dict[str, Any]) -> str:
    cid = cap["capability_id"]
    view = effective_view(cap)
    lines: list[str] = [f"# `{cid}`", ""]
    headline = " · ".join(x for x in (view.get("display_name"), view.get("role")) if x)
    if headline:
        lines += [headline, ""]
    flags = [
        f"kind=`{view.get('kind') or '-'}`",
        f"composition=`{view.get('composition') or '-'}`",
        f"group=`{view.get('group') or '-'}`",
        f"声明=`{'是' if cap.get('in_ads') or cap.get('declared_by') or cap.get('declared_lists') else '否'}`",
        f"执行前自检=`{'有' if cap.get('availability', {}).get('has_checker') else '无'}`",
    ]
    lines += [" · ".join(flags), ""]

    if view.get("planner_recognize"):
        lines += ["## 规划器怎么认它", "", view["planner_recognize"], ""]
    if view.get("prefer_when"):
        lines += [f"> 优先本能力：{view['prefer_when']}", ""]
    if view.get("typical_triggers"):
        lines += ["## 典型触发语", ""] + [f"- {t}" for t in view["typical_triggers"]] + [""]
    if view.get("do_not_dispatch"):
        lines += ["## 不要派给它", ""] + [f"- {t}" for t in view["do_not_dispatch"]] + [""]
    if view.get("decomposes_to"):
        lines += ["## 分解为（接线图）", ""] + [f"- `{t}`" for t in view["decomposes_to"]] + [""]

    rows = _param_rows(view.get("input_schema") or {})
    lines += ["## 入参", ""]
    lines += (["| 参数 | 类型 | 必填 | 说明 |", "|---|---|---|---|"] + rows) if rows else ["（无）"]
    lines += [""]
    out_rows = _param_rows(view.get("output_schema") or {})
    lines += ["## 出参", ""]
    lines += (["| 参数 | 类型 | 必填 | 说明 |", "|---|---|---|---|"] + out_rows) if out_rows else ["（无）"]
    lines += [""]

    if cap.get("runs_on"):
        lines += ["## 适用宿主（代码事实）", ""] + [f"- `{h}`" for h in cap["runs_on"]] + [""]
    declared = cap.get("declared_by") or []
    if declared:
        lines += ["## 服务声明", ""] + [f"- `{s}`" for s in declared] + [""]
    lists = cap.get("declared_lists") or []
    if lists:
        lines += ["## 条件声明", ""] + [
            f"- `{name}`（按依赖/后端决定是否挂上）" for name in lists
        ] + [""]
    if cap.get("packages"):
        lines += ["## 能力包", ""] + [f"- `plugins/{p}/`" for p in cap["packages"]] + [""]
    if cap.get("docs"):
        lines += ["## 文档", ""] + [
            f"- [home-agent-os/{d}](https://github.com/kaulie/home-agent-os/blob/main/{d})" for d in cap["docs"]
        ] + [""]
    if cap.get("entry"):
        lines += ["## 入口", ""]
        for platform, path in sorted(cap["entry"].items()):
            lines.append(f"- {platform}: `{path}`")
        lines += [""]
    if cap.get("config_keys"):
        lines += ["## 相关配置", ""] + [f"- `{k}`" for k in cap["config_keys"]] + [""]
    if view.get("sources"):
        lines += ["", f"- 定义层来源：{'、'.join(f'`{s}`' for s in view['sources'])}"]
    lines += [
        "",
        "---",
        "",
        f"<sub>由 `{catalog.get('generated_by')}` 生成（home-agent-os `{catalog.get('source', {}).get('commit')}`）"
        f"，请勿手改。</sub>",
        "",
    ]
    return "\n".join(lines)



def render_catalog_md(catalog: dict[str, Any]) -> str:
    """人读总表：概览 + 按 group 分组 + 两节「账不平」。"""
    s = catalog["summary"]
    src = catalog["source"]
    caps = catalog["capabilities"]
    lines: list[str] = [
        "# 能力总表（mac edge）",
        "",
        f"> 由 `{catalog['generated_by']}` 从 home-agent-os `{src.get('commit') or '-'}` 生成"
        f"（{catalog['generated_at']}）；**请勿手改** —— 改能力请改 home-agent-os 再跑 `scripts/sync.sh`。",
        "",
        "## 概览",
        "",
        "| 项 | 数 |",
        "|---|---|",
        f"| 能力总数（并集） | {s['capabilities']} |",
        f"| 规划器广告定义（ADS） | {s['ads_definitions']} |",
        f"| 服务声明（services.py 静态） | {s['declared_capabilities']}（{s['services']} 个 service） |",
        f"| 能力包（plugins/*/manifest.yaml） | {s['extensions']} |",
        f"| 有执行前探测（checker） | {s['with_checker']} |",
        "",
        "### 按 group",
        "",
        "| group | 能力数 |",
        "|---|---|",
    ]
    for group, count in sorted(s["groups"].items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"| `{group}` | {count} |")
    lines += ["", "### 按 kind", "", "| kind | 能力数 |", "|---|---|"]
    for kind, count in sorted(s["kinds"].items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"| `{kind}` | {count} |")

    lines += ["", "## 能力清单（按 group）", ""]
    def _anchor(cid: str) -> str:
        return f"capabilities/{cid}.md"

    by_group: dict[str, list[dict[str, Any]]] = {}
    for cap in caps:
        by_group.setdefault(cap.get("group") or "(未分类)", []).append(cap)
    for group in sorted(by_group):
        lines += [f"### `{group}`", "", "| 能力 | kind | 角色 | 触发语（示例） |", "|---|---|---|---|"]
        for cap in by_group[group]:
            role = cap.get("role") or cap.get("display_name") or ""
            trigger = ((cap.get("definition") or {}).get("typical_triggers") or [""])[0]
            lines.append(
                f"| [`{cap['capability_id']}`]({_anchor(cap['capability_id'])}) | {cap.get('kind') or '-'} | "
                f"{_md_escape(role)} | {_md_escape(trigger)} |"
            )
        lines += [""]

    lines += ["", "---", "", f"`{catalog['schema']}`", ""]
    return "\n".join(lines)


# --- 写入 / 漂移检查 -------------------------------------------------------


def _dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2) + "\n"


def write_catalog(catalog: dict[str, Any], out: Path) -> list[str]:
    """把 catalog 写进仓库（catalog/ + capabilities/ + schema/），返回写入的相对路径。"""
    out = Path(out)
    (out / "catalog").mkdir(parents=True, exist_ok=True)
    (out / "capabilities").mkdir(parents=True, exist_ok=True)
    (out / "schema").mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    files = {
        "catalog/capabilities.json": _dump(catalog),
        "catalog/capabilities.md": render_catalog_md(catalog) + "\n",
        "schema/catalog.schema.json": _dump(catalog_schema()),
    }
    for rel, text in files.items():
        (out / rel).write_text(text, encoding="utf-8")
        written.append(rel)

    wanted: set[str] = set()
    for cap in catalog["capabilities"]:
        rel = f"capabilities/{cap['capability_id']}.md"
        (out / rel).write_text(render_capability_md(cap, catalog), encoding="utf-8")
        wanted.add(rel)
        written.append(rel)

    # 清掉已不存在的能力页（否则仓库里会留过期页面）
    for old in (out / "capabilities").glob("*.md"):
        rel = f"capabilities/{old.name}"
        if rel not in wanted:
            old.unlink()
            written.append(f"-{rel}")
    return sorted(written)


def normalize_for_check(catalog: dict[str, Any]) -> dict[str, Any]:
    """比对用的归一化：只丢易变字段（每次生成都会变，不代表能力变了）。"""
    import copy

    data = copy.deepcopy(catalog)
    data.pop("generated_at", None)
    data.get("source", {}).pop("commit", None)
    return data


def check_catalog(catalog: dict[str, Any], out: Path) -> list[str]:
    """与仓库里已有的 catalog 比对，返回漂移描述（空 = 一致）。"""
    existing_path = Path(out) / "catalog/capabilities.json"
    if not existing_path.is_file():
        return [f"{existing_path} 不存在：先跑一次导出（去掉 --check）"]
    try:
        existing = json.loads(existing_path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return [f"{existing_path} 不是合法 JSON：{e}"]

    a, b = normalize_for_check(existing), normalize_for_check(catalog)
    if a == b:
        return []

    problems: list[str] = []
    for key in ("schema", "source", "summary", "services"):
        if a.get(key) != b.get(key):
            problems.append(f"{key} 不同")
    old_caps = {c["capability_id"]: c for c in a.get("capabilities", [])}
    new_caps = {c["capability_id"]: c for c in b.get("capabilities", [])}
    for cid in sorted(set(old_caps) - set(new_caps)):
        problems.append(f"仓库里有、代码里没了：{cid}")
    for cid in sorted(set(new_caps) - set(old_caps)):
        problems.append(f"代码里有、仓库里没有：{cid}")
    for cid in sorted(set(old_caps) & set(new_caps)):
        if old_caps[cid] != new_caps[cid]:
            fields = sorted(
                k
                for k in set(old_caps[cid]) | set(new_caps[cid])
                if old_caps[cid].get(k) != new_caps[cid].get(k)
            )
            problems.append(f"{cid} 字段变了：{', '.join(fields)}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="导出 mac edge 能力目录（capability marketplace）")
    parser.add_argument("--out", required=True, help="目标目录（marketplace 仓库检出目录）")
    parser.add_argument("--check", action="store_true", help="只比对不写文件；有漂移则退出码 1")
    args = parser.parse_args(argv)

    catalog = build_catalog()
    out = Path(args.out)

    if args.check:
        problems = check_catalog(catalog, out)
        if problems:
            print(f"[check] 目录与代码不一致（{len(problems)} 处）：", file=sys.stderr)
            for p in problems[:40]:
                print(f"  - {p}", file=sys.stderr)
            return 1
        print("[check] 一致 ✓")
        return 0

    written = write_catalog(catalog, out)
    s = catalog["summary"]
    print(
        f"[ok] 写 {len(written)} 个文件 → {out}\n"
        f"     能力 {s['capabilities']}（ADS {s['ads_definitions']} / 声明 {s['declared_capabilities']} / "
        f"能力包 {s['extensions']} / 有执行前探测 {s['with_checker']}）"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())







