"""Capability Candidate Matcher.

Reads the existing planner ads in capability_ads.ADS. Does not create a second
registry. Alias phrases are keyed only by those capability_ids.
"""

from __future__ import annotations

from typing import Any

from capability_ads import ADS

from .patterns import RECOGNIZE_SPLIT_RE

STRENGTH_RANK = {"trigger": 3, "recognize": 2, "alias": 1}

# Spoken-language gaps that typical_triggers do not cover. Keys MUST exist in ADS.
ALIASES: dict[str, tuple[str, ...]] = {
    "light.set": (
        "客厅灯",
        "的灯",
        "照明",
        "亮一点",
        "调亮",
        "调暗",
        "打开灯",
        "关一下灯",
        "开一下灯",
        "打开台灯",
        "关掉台灯",
    ),
    "display.photo": ("投到电视", "丢到电视", "放到电视"),
    "display.audio": (
        "在电视上放出来",
        "电视上放音频",
        "电视上放这段音频",
        "把音频投到电视",
        "电视播放音频",
    ),
    "camera.capture": ("拍照", "拍的照片", "拍张照"),
    "vision.ask": ("照片里", "图里有", "有几个人", "有没有人", "看看照片"),
    "vision.perceive": ("看看客厅", "现在怎样"),
    "notify.speak": ("告诉我", "念给我听"),
    "clock.now": ("几点了", "现在时间", "今天日期", "几月几号", "几号了"),
    "map.route.estimate": ("开车多久", "多远", "多久能到", "坐地铁", "导航", "路线"),
    "climate.set": ("空调", "制冷", "制热"),
    "phone.call": ("打电话", "打给", "拨打", "打个电话"),
    "asset.inventory": (
        "刚才的照片",
        "最后一张照片",
        "最后一张",
        "最近一张照片",
        "最新的PDF",
        "最新的文件",
        "最新的文档",
        "最新的音频",
        "最新音频",
        "最新的录音",
    ),
}


def _ads_catalog() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for capability_id, ad in ADS.items():
        if not isinstance(ad, dict):
            continue
        triggers = ad.get("typical_triggers") or []
        if not isinstance(triggers, list):
            triggers = []
        rows.append(
            {
                "capability_id": str(capability_id),
                "role": str(ad.get("role") or ""),
                "planner_recognize": str(ad.get("planner_recognize") or ""),
                "typical_triggers": [str(t) for t in triggers if str(t).strip()],
            }
        )
    return rows


def _recognize_terms(ad: dict[str, Any]) -> list[str]:
    chunks: list[str] = []
    for raw in (ad.get("planner_recognize") or "", ad.get("role") or ""):
        for part in RECOGNIZE_SPLIT_RE.split(str(raw)):
            term = part.strip()
            if len(term) >= 2:
                chunks.append(term)
    return chunks


def _best_strength(existing: str | None, incoming: str) -> str:
    if existing is None:
        return incoming
    if STRENGTH_RANK.get(incoming, 0) > STRENGTH_RANK.get(existing, 0):
        return incoming
    return existing


def match_candidates(text: str) -> list[dict[str, Any]]:
    """Return unique capability hits: capability_id, strength, terms."""
    src = str(text or "")
    if not src.strip():
        return []
    hits: dict[str, dict[str, Any]] = {}

    def add(capability_id: str, strength: str, term: str) -> None:
        if capability_id not in ADS:
            return
        row = hits.get(capability_id)
        if row is None:
            hits[capability_id] = {
                "capability_id": capability_id,
                "strength": strength,
                "terms": [term],
            }
            return
        row["strength"] = _best_strength(row["strength"], strength)
        if term not in row["terms"]:
            row["terms"].append(term)

    for ad in _ads_catalog():
        cid = ad["capability_id"]
        for trigger in ad["typical_triggers"]:
            if trigger and trigger in src:
                add(cid, "trigger", trigger)
        for term in _recognize_terms(ad):
            if term and term in src:
                add(cid, "recognize", term)
        for alias in ALIASES.get(cid, ()):
            if alias and alias in src:
                add(cid, "alias", alias)

    ordered = sorted(
        hits.values(),
        key=lambda row: (-STRENGTH_RANK.get(row["strength"], 0), row["capability_id"]),
    )
    return ordered
