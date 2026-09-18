"""Brain-side kind=system capabilities: catalog query / inventory.

Not bound to any Runtime. Plugins only see this step's resolved params.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from capability_ads import ADS, attach

log = logging.getLogger("system_capabilities")

SYSTEM_EDGE_ID = "system"
SYSTEM_CAPABILITY_IDS = frozenset(
    {
        "capabilities.summary",
        "asset.inventory",
        "image.ocr",
        "clock.now",
        "map.route.estimate",
    }
)

_SKIP_SUMMARY_IDS = frozenset({"capabilities.summary", "voice_test.run_trial"})
_GROUP_ORDER = (
    "camera",
    "vision",
    "ocr",
    "display",
    "notify",
    "query",
    "math",
    "convert",
    "clock",
    "light",
    "climate",
    "music",
    "asset",
    "meta",
    "map",
)
_MAX_PHRASES = 7
_CAP_ID_RE = re.compile(r"\b[a-z][a-z0-9_]*\.[a-z0-9_.]+\b", re.I)

_SUMMARY_INPUT: dict[str, Any] = {}
_SUMMARY_OUTPUT = {
    "answer_text": {
        "type": "string",
        "required": True,
        "description": "给用户听的简短口语能力介绍（非技术自描述清单）",
    },
    "capability_count": {
        "type": "string",
        "required": False,
        "description": "当前在线可调度 Runtime capability 数量",
    },
}
_INVENTORY_INPUT = {
    "type": {
        "type": "string",
        "required": False,
        "description": "asset 类型：image / video / audio / document 等；问照片填 image，最新 PDF/文档填 document",
    },
    "day": {
        "type": "string",
        "required": False,
        "description": "today / yesterday / YYYY-MM-DD；问「今天拍了几张」填 today，「昨天」填 yesterday",
    },
    "timezone": {
        "type": "string",
        "required": False,
        "description": "IANA 时区，默认 Asia/Shanghai",
    },
    "since": {
        "type": "string",
        "required": False,
        "description": "起始时间 ISO 或 unix；与 day 二选一优先 day",
    },
    "until": {
        "type": "string",
        "required": False,
        "description": "结束时间 ISO 或 unix（不含）",
    },
    "producer_capability": {
        "type": "string",
        "required": False,
        "description": "只统计该生产者产出的 Asset（可选过滤；填生产者标识，不要在口语里念给用户）",
    },
    "limit": {
        "type": "number",
        "required": False,
        "description": "返回 asset_refs 上限，默认 50；取第 N 张时用 index，不要用 limit=N",
    },
    "offset": {
        "type": "number",
        "required": False,
        "description": "跳过前 N 条（0 起）；与 index 二选一，优先 index",
    },
    "index": {
        "type": "number",
        "required": False,
        "description": "1 起：按登记时间取第 N 条（默认 oldest_first）；看「第五张」填 5；最新一份配合 order=newest_first 填 1",
    },
    "order": {
        "type": "string",
        "required": False,
        "description": "newest_first（默认列表/取最新）或 oldest_first（index 默认）",
    },
    "include_refs": {
        "type": "string",
        "required": False,
        "description": "true/false，是否产出 asset_refs；只要数量可 false",
    },
}
_OCR_INPUT = {
    "asset_ref": {
        "type": "string",
        "required": True,
        "description": "图片 AssetRef JSON {asset_id, type, mime_type?} 或 asset_id。禁止 image_url / path / base64。",
    },
    "language": {
        "type": "string",
        "required": False,
        "description": "zh（默认）或 en",
    },
    "return_bbox": {
        "type": "string",
        "required": False,
        "description": "是否返回 bbox，默认 true",
    },
    "return_confidence": {
        "type": "string",
        "required": False,
        "description": "是否返回 confidence，默认 true",
    },
}
_OCR_OUTPUT = {
    "text": {
        "type": "string",
        "required": True,
        "description": "图上全部识别文字（原样拼接，不做理解）",
    },
    "blocks": {
        "type": "string",
        "required": True,
        "description": "OCR 块 JSON 数组 [{text, bbox, confidence}]",
    },
    "language": {
        "type": "string",
        "required": False,
        "description": "识别语言",
    },
    "engine": {
        "type": "string",
        "required": False,
        "description": "OCR 引擎名（如 paddleocr），不是能力 id",
    },
    "model": {
        "type": "string",
        "required": False,
        "description": "模型名",
    },
    "model_version": {
        "type": "string",
        "required": False,
        "description": "模型版本",
    },
    "asset_id": {
        "type": "string",
        "required": True,
        "description": "入参图片的 asset_id",
    },
}
_CLOCK_INPUT: dict[str, Any] = {
    "timezone": {
        "type": "string",
        "required": False,
        "description": "IANA 时区，默认 Asia/Shanghai",
    },
    "appliance": {
        "type": "string",
        "required": False,
        "description": "绑定名（如 Local Clock），仅用于多实例区分，不影响读钟",
    },
}
_CLOCK_OUTPUT = {
    "now_iso": {
        "type": "string",
        "required": True,
        "description": "本机当前时间 ISO 8601（带时区），如 2026-08-27T22:30:00+08:00",
    },
    "time_text": {
        "type": "string",
        "required": True,
        "description": "给人听/看的当前时间中文，如「现在是 22 点 30 分」",
    },
}
_ROUTE_INPUT: dict[str, Any] = {
    "origin": {
        "type": "string",
        "required": True,
        "description": "起点地名或地址，如「望新花园」",
    },
    "destination": {
        "type": "string",
        "required": True,
        "description": "终点地名或地址，如「顺义建邦顺颐府」",
    },
    "mode": {
        "type": "string",
        "required": False,
        "description": "出行方式：driving（驾车，默认）| transit（公交地铁）| walking（步行）",
    },
    "city": {
        "type": "string",
        "required": False,
        "description": "城市名，用于地址消歧与公交规划，默认北京",
    },
}
_ROUTE_OUTPUT = {
    "answer_text": {
        "type": "string",
        "required": True,
        "description": "给人听/看的路线距离与耗时摘要",
    },
    "distance_km": {
        "type": "string",
        "required": True,
        "description": "路线距离（公里，小数）",
    },
    "distance_m": {
        "type": "string",
        "required": False,
        "description": "路线距离（米）",
    },
    "duration_min": {
        "type": "string",
        "required": True,
        "description": "预计耗时（分钟，向上取整）",
    },
    "duration_sec": {
        "type": "string",
        "required": False,
        "description": "预计耗时（秒）",
    },
    "mode": {
        "type": "string",
        "required": False,
        "description": "实际使用的出行方式 driving | transit | walking",
    },
}
_INVENTORY_OUTPUT = {
    "count": {
        "type": "string",
        "required": True,
        "description": "匹配数量",
    },
    "answer_text": {
        "type": "string",
        "required": True,
        "description": "中文盘点结果，如「今天一共登记了 12 张照片。」；取第 N 张时为定位说明",
    },
    "asset_ref": {
        "type": "object",
        "required": False,
        "description": "单张 AssetRef（index 或仅一条时）",
    },
    "asset_refs": {
        "type": "string",
        "required": False,
        "description": "AssetRef JSON 数组（include_refs 时）",
    },
}


class SystemCapabilityError(Exception):
    pass


def is_system_capability(capability_id: str | None) -> bool:
    return str(capability_id or "").strip() in SYSTEM_CAPABILITY_IDS


def catalog_rows() -> list[dict[str, Any]]:
    """Always-available planner rows (kind=system). Not from Runtime heartbeats."""
    summary = attach(
        "capabilities.summary",
        input_schema=_SUMMARY_INPUT,
        output_schema=_SUMMARY_OUTPUT,
    )
    inventory = attach(
        "asset.inventory",
        input_schema=_INVENTORY_INPUT,
        output_schema=_INVENTORY_OUTPUT,
    )
    ocr = attach(
        "image.ocr",
        input_schema=_OCR_INPUT,
        output_schema=_OCR_OUTPUT,
    )
    clock = attach(
        "clock.now",
        input_schema=_CLOCK_INPUT,
        output_schema=_CLOCK_OUTPUT,
    )
    route = attach(
        "map.route.estimate",
        input_schema=_ROUTE_INPUT,
        output_schema=_ROUTE_OUTPUT,
    )
    return [
        _as_schedulable_row(
            summary,
            service_id="system.capabilities",
            group="meta",
        ),
        _as_schedulable_row(
            inventory,
            service_id="system.asset",
            group="asset",
        ),
        _as_schedulable_row(
            ocr,
            service_id="system.ocr",
            group="ocr",
        ),
        _as_schedulable_row(
            clock,
            service_id="system.clock",
            group="clock",
        ),
        _as_schedulable_row(
            route,
            service_id="system.map",
            group="map",
        ),
    ]


def _as_schedulable_row(cap: dict[str, Any], *, service_id: str, group: str) -> dict[str, Any]:
    cid = str(cap.get("capability_id") or "").strip()
    triggers = cap.get("typical_triggers") or []
    if not isinstance(triggers, list):
        triggers = []
    do_not = cap.get("do_not_dispatch") or []
    if not isinstance(do_not, list):
        do_not = []
    return {
        "capability_id": cid,
        "kind": str(cap.get("kind") or "system").strip().lower() or "system",
        "composition": str(cap.get("composition") or "atomic").strip().lower() or "atomic",
        "role": cap.get("role") or "",
        "planner_recognize": cap.get("planner_recognize") or "",
        "typical_triggers": list(triggers),
        "do_not_dispatch": list(do_not),
        "description": cap.get("description") or "",
        "input_schema": cap.get("input_schema") or {},
        "output_schema": cap.get("output_schema") or {},
        "service_id": service_id,
        "group": group,
        "edge_id": SYSTEM_EDGE_ID,
        "edge_name": "Brain",
        "assigned_edge_id": SYSTEM_EDGE_ID,
    }


def run_system_step(
    capability_id: str,
    params: dict[str, Any] | None,
    *,
    capability_rows: list[Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    cid = str(capability_id or "").strip()
    if cid == "capabilities.summary":
        return summary_from_params(params, rows=capability_rows or [])
    if cid == "asset.inventory":
        return inventory_from_params(params)
    if cid == "image.ocr":
        return ocr_from_params(params)
    if cid == "clock.now":
        return clock_from_params(params)
    if cid == "map.route.estimate":
        return route_from_params(params)
    raise SystemCapabilityError(f"unknown system capability {cid}")


def _soft_phrase(raw: str) -> str:
    text = str(raw or "").strip()
    text = _CAP_ID_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    for suffix in (
        "执行器",
        "查询器",
        "回答器",
        "感知器",
        "求值器",
        "读取器",
        "控制器",
        "汇总器",
        "拍摄器",
        "播报器",
        "投屏器",
        "检索器",
    ):
        if text.endswith(suffix) and len(text) > len(suffix):
            text = text[: -len(suffix)]
            break
    if text.endswith("器") and len(text) > 2:
        text = text[:-1]
    for sep in ("；", ";", "。", "，并", "，且", "、", "/"):
        if sep in text and len(text) > 10:
            text = text.split(sep, 1)[0].strip()
            break
    return text.strip(" ，,、")


def _phrase_from_row(row: dict[str, Any]) -> str | None:
    cid = str(row.get("capability_id") or "").strip()
    if not cid or cid in _SKIP_SUMMARY_IDS:
        return None
    phrase = _soft_phrase(str(row.get("planner_recognize") or "")) or _soft_phrase(
        str(row.get("role") or "")
    )
    if not phrase or cid in phrase:
        return None
    return phrase


def _group_key(row: dict[str, Any]) -> str:
    group = str(row.get("group") or "").strip().lower()
    if group:
        return group
    cid = str(row.get("capability_id") or "")
    if "." in cid:
        return cid.split(".", 1)[0]
    return "other"


def build_spoken_summary(rows: list[Any]) -> str:
    """Distill Runtime capability self-descriptions into a short spoken Chinese intro."""
    by_group: dict[str, list[str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        phrase = _phrase_from_row(row)
        if not phrase:
            continue
        by_group.setdefault(_group_key(row), []).append(phrase)

    if not by_group:
        return "这会儿我还帮不上什么忙，稍后再问我一次吧。"

    ordered_keys = [g for g in _GROUP_ORDER if g in by_group]
    ordered_keys.extend(sorted(g for g in by_group if g not in _GROUP_ORDER))

    phrases: list[str] = []
    seen_norm: set[str] = set()
    for group in ordered_keys:
        candidates = sorted(by_group[group], key=lambda p: (len(p), p))
        pick = candidates[0]
        norm = re.sub(r"\s+", "", pick)
        if norm in seen_norm:
            continue
        seen_norm.add(norm)
        phrases.append(pick)
        if len(phrases) >= _MAX_PHRASES:
            break

    if not phrases:
        return "这会儿我还帮不上什么忙，稍后再问我一次吧。"
    if len(phrases) == 1:
        body = phrases[0]
    elif len(phrases) == 2:
        body = f"{phrases[0]}，以及{phrases[1]}"
    else:
        body = "、".join(phrases[:-1]) + f"，以及{phrases[-1]}"
    return f"我现在能帮你：{body}。你直接跟我说想做什么就行。"


def summary_from_params(
    params: dict[str, Any] | None,
    *,
    rows: list[Any],
) -> tuple[str, dict[str, Any]]:
    _ = params
    usable = [
        r
        for r in rows
        if isinstance(r, dict)
        and str(r.get("capability_id") or "").strip()
        and str(r.get("capability_id") or "").strip() not in _SKIP_SUMMARY_IDS
        and str(r.get("kind") or "").strip().lower() != "system"
    ]
    answer = build_spoken_summary(usable)
    for row in usable:
        cid = str(row.get("capability_id") or "")
        if cid and cid in answer:
            raise SystemCapabilityError("summary leaked capability id")
    log.info("capabilities.summary online=%s chars=%s", len(usable), len(answer))
    outputs = {
        "answer_text": answer,
        "capability_count": str(len(usable)),
    }
    return f"capabilities.summary n={len(usable)}", outputs


def clock_from_params(params: dict[str, Any] | None) -> tuple[str, dict[str, Any]]:
    """Read Brain's local wall clock. No LLM, no device I/O, no Runtime."""
    tz_name = str((params or {}).get("timezone") or "").strip() or "Asia/Shanghai"
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("Asia/Shanghai")
    now = datetime.now(tz)
    now_iso = now.isoformat(timespec="seconds")
    hh = now.hour
    mm = now.minute
    if mm == 0:
        time_text = f"现在是 {hh} 点整"
    else:
        time_text = f"现在是 {hh} 点 {mm:02d} 分"
    outputs = {"now_iso": now_iso, "time_text": time_text}
    log.info("clock.now iso=%s text=%s", now_iso, time_text)
    return f"clock.now {now_iso}", outputs


def route_from_params(params: dict[str, Any] | None) -> tuple[str, dict[str, Any]]:
    from map_route import MapRouteError, route_from_params as _route

    try:
        return _route(params)
    except MapRouteError as e:
        raise SystemCapabilityError(str(e)) from e


def _opt_str(raw: Any) -> str | None:
    text = str(raw or "").strip()
    return text or None


def _opt_bool(raw: Any, default: bool = True) -> bool:
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off"):
        return False
    return default


def _opt_limit(raw: Any) -> int | None:
    if raw is None or str(raw).strip() == "":
        return 50
    try:
        return max(0, min(500, int(str(raw).strip())))
    except ValueError as e:
        raise SystemCapabilityError("limit 必须是整数") from e


def _opt_nonneg_int(raw: Any, *, field: str) -> int | None:
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return max(0, int(str(raw).strip()))
    except ValueError as e:
        raise SystemCapabilityError(f"{field} 必须是整数") from e


def _opt_index(raw: Any) -> int | None:
    if raw is None or str(raw).strip() == "":
        return None
    try:
        idx = int(str(raw).strip())
    except ValueError as e:
        raise SystemCapabilityError("index 必须是整数") from e
    if idx < 1:
        raise SystemCapabilityError("index 从 1 开始")
    return idx


def _newest_first(order_raw: Any, *, index: int | None) -> bool:
    text = str(order_raw or "").strip().lower()
    if text in ("oldest_first", "oldest", "asc", "created_asc"):
        return False
    if text in ("newest_first", "newest", "desc", "created_desc"):
        return True
    if index is not None:
        return False
    return True


def parse_asset_day_window(day: str, timezone_name: str | None) -> tuple[float, float] | None:
    """Return [start, end) unix seconds for day=today|yesterday|YYYY-MM-DD in timezone."""
    raw = str(day or "").strip().lower()
    if not raw:
        return None
    tz_name = str(timezone_name or "").strip() or "Asia/Shanghai"
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("Asia/Shanghai")
    now = datetime.now(tz)
    if raw in ("today", "今天"):
        start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif raw in ("yesterday", "昨天"):
        start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    else:
        try:
            y, m, d = [int(p) for p in raw.split("-", 2)]
            start_dt = datetime(y, m, d, tzinfo=tz)
        except (TypeError, ValueError):
            return None
    end_dt = start_dt + timedelta(days=1)
    return start_dt.timestamp(), end_dt.timestamp()


def parse_asset_time_bound(raw: str | None) -> float | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    try:
        if text.endswith("Z"):
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
        return dt.timestamp()
    except ValueError:
        return None


_TYPE_NOUNS: dict[str, tuple[str, str]] = {
    "image": ("照片", "张"),
    "video": ("视频", "段"),
    "audio": ("音频", "条"),
    "document": ("文档", "份"),
    "url": ("链接", "个"),
}


def inventory_answer_text(
    *,
    count: int,
    asset_type: str | None,
    day: str | None,
    index: int | None = None,
    found: bool = True,
) -> str:
    day_raw = (day or "").strip().lower()
    if day_raw in ("today", "今天"):
        day_label = "今天"
    elif day_raw in ("yesterday", "昨天"):
        day_label = "昨天"
    else:
        day_label = (day or "").strip()
    kind = (asset_type or "").strip().lower()
    # 量词按 Asset 类型走：照片「张」、音频「条」、文档「份」、链接「个」。
    # 旧实现一律「第 N 张<noun>」，音频/链接会说成「第 1 张audio」。
    if kind in _TYPE_NOUNS:
        noun, measure = _TYPE_NOUNS[kind]
    elif kind:
        noun, measure = kind, "个"
    else:
        noun, measure = "资源", "个"
    counted = f"{count} {measure}{noun}"
    if index is not None:
        if not found or count <= 0:
            if day_label:
                return f"{day_label}没有第 {index} {measure}{noun}（一共 {count} {measure}）。"
            return f"没有第 {index} {measure}{noun}（一共 {count} {measure}）。"
        if day_label:
            return f"这是{day_label}按登记顺序的第 {index} {measure}{noun}。"
        return f"这是按登记顺序的第 {index} {measure}{noun}。"
    if day_label:
        if count <= 0:
            return f"{day_label}还没有登记过{noun}。"
        return f"{day_label}一共登记了 {counted}。"
    if count <= 0:
        return f"还没有登记过{noun}。"
    return f"一共登记了 {counted}。"


def ocr_from_params(
    params: dict[str, Any] | None,
    **kwargs: Any,
) -> tuple[str, dict[str, Any]]:
    from sdk.image_ocr import ImageOcrError, ocr_from_params as _ocr

    try:
        return _ocr(params, **kwargs)
    except ImageOcrError as e:
        raise SystemCapabilityError(str(e)) from e


def inventory_from_params(
    params: dict[str, Any] | None,
    *,
    db: Any | None = None,
) -> tuple[str, dict[str, Any]]:
    raw = params if isinstance(params, dict) else {}
    asset_type = _opt_str(raw.get("type") or raw.get("asset_type"))
    producer = _opt_str(
        raw.get("producer_capability") or raw.get("producer") or raw.get("capability")
    )
    day = _opt_str(raw.get("day"))
    timezone = _opt_str(raw.get("timezone") or raw.get("tz"))
    since = _opt_str(raw.get("since"))
    until = _opt_str(raw.get("until"))
    include_refs = _opt_bool(raw.get("include_refs"), default=True)
    index = _opt_index(raw.get("index") or raw.get("nth") or raw.get("n"))
    offset = _opt_nonneg_int(raw.get("offset"), field="offset")
    limit = _opt_limit(raw.get("limit"))
    newest_first = _newest_first(raw.get("order"), index=index)

    if index is not None:
        offset = index - 1
        limit = 1
        include_refs = True
    elif offset is None:
        offset = 0

    if include_refs is False:
        limit = 0

    created_since = parse_asset_time_bound(since)
    created_until = parse_asset_time_bound(until)
    if day:
        window = parse_asset_day_window(day, timezone)
        if window is None:
            raise SystemCapabilityError("invalid day (use today, yesterday, or YYYY-MM-DD)")
        created_since, created_until = window

    if db is None:
        import db as brain_db
    else:
        brain_db = db

    filt = dict(
        asset_type=asset_type,
        producer_capability=producer,
        created_since=created_since,
        created_until=created_until,
    )
    try:
        total = int(brain_db.count_assets(**filt))
        rows = brain_db.list_assets(
            **filt, limit=limit, offset=offset or 0, newest_first=newest_first
        )
    except Exception as e:
        raise SystemCapabilityError(f"asset.inventory 查询失败：{e}") from e

    refs: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        ref = row.get("asset_ref")
        if isinstance(ref, dict) and str(ref.get("asset_id") or "").strip():
            refs.append(
                {
                    "asset_id": str(ref["asset_id"]).strip(),
                    "type": str(ref.get("type") or row.get("type") or "other"),
                    **(
                        {"mime_type": str(ref["mime_type"])}
                        if ref.get("mime_type")
                        else {}
                    ),
                }
            )
        else:
            aid = str(row.get("asset_id") or "").strip()
            if aid:
                refs.append(
                    {
                        "asset_id": aid,
                        "type": str(row.get("type") or "other"),
                        **(
                            {"mime_type": str(row["mime_type"])}
                            if row.get("mime_type")
                            else {}
                        ),
                    }
                )

    found = bool(refs) if index is not None else True
    answer = inventory_answer_text(
        count=total,
        asset_type=asset_type,
        day=day,
        index=index,
        found=found,
    )
    outputs: dict[str, Any] = {
        "count": str(total),
        "answer_text": answer,
    }
    if include_refs and refs:
        outputs["asset_refs"] = json.dumps(refs, ensure_ascii=False)
        if len(refs) == 1:
            outputs["asset_ref"] = refs[0]
    if index is not None:
        outputs["asset_index"] = str(index)

    msg = f"asset.inventory count={total}"
    log.info(
        "asset.inventory type=%s day=%s producer=%s index=%s offset=%s count=%s refs=%s",
        asset_type,
        day,
        producer,
        index,
        offset,
        total,
        len(refs),
    )
    return msg, outputs


# Ads must exist for attach(); keep a local check so catalog_rows fails fast.
for _cid in SYSTEM_CAPABILITY_IDS:
    if _cid not in ADS:
        raise RuntimeError(f"missing planner ad for system capability {_cid}")
