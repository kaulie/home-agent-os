"""P0 keyword rule routing: clock, climate, latest photo — same intercept chain as reading/music."""

from __future__ import annotations

import re
import time
from copy import deepcopy
from dataclasses import dataclass

from .matcher import matches_any, normalize_text

_CTX_REF = {"type": "object", "data_dest": "context", "required": True}

_CLOCK_TRIGGERS = (
    "现在几点了",
    "现在几点",
    "几点钟了",
    "几点钟",
    "几点了",
    "报时",
)
_CLOCK_EXCLUDE = ("明天", "后天", "几点开", "几点到", "几点见", "几点出发")

_CLIMATE_ON = ("打开", "开启")
_CLIMATE_OFF = ("关闭", "关掉")
_CLIMATE_COMPLEX = ("风速", "温度", "制冷", "制热", "除湿", "调为", "调到", "调成")
_CLIMATE_ROOMS = ("客厅", "儿童房", "卧室", "主卧", "次卧", "书房", "餐厅")
_APPLIANCE_RE = re.compile(r"([\u4e00-\u9fff]{2,6})空调")

_PHOTO_LATEST_HINTS = (
    "最新照片",
    "最新的一张照片",
    "最新一张照片",
    "最后一张照片",
    "刚才的照片",
    "上一张照片",
    "最近一张照片",
    "最新的照片",
    "最新一张",
    "最后一张",
    "上一张",
    "最近一张",
)
_PHOTO_CAST_HINTS = ("投到电视", "丢到电视", "放到电视", "电视上", "投屏", "投")
_PHOTO_VIEW_HINTS = ("看", "显示", "打开", "我要看", "瞧", "浏览")
_PHOTO_EXCLUDE = (
    "轮播",
    "幻灯",
    "拍一张",
    "拍照",
    "几张",
    "多少张",
    "这个字",
    "怎么读",
    "怎么念",
    "读啥",
    "念什么",
    "手指",
    "指着",
    "什么字",
    "视频",
)

_COURTESY_PREFIXES = (
    "请帮我",
    "请给我",
    "麻烦帮我",
    "帮我",
    "给我",
    "麻烦",
    "请",
)
_TRAILING_PUNCT = "。．.！!？?，,、；;：:…~～"


@dataclass(frozen=True)
class RuleHit:
    rule: str
    goal: str
    plan: list[dict]
    presentation: dict
    match_ms: int


def copy_plan(plan: list[dict]) -> list[dict]:
    return deepcopy(plan)


def _lstrip_courtesy(text: str) -> str:
    rest = str(text or "").strip()
    while True:
        nxt = rest
        for prefix in _COURTESY_PREFIXES:
            if prefix and rest.startswith(prefix):
                nxt = rest[len(prefix) :].lstrip()
                break
        if nxt == rest:
            return rest
        rest = nxt


def _rstrip_punct(text: str) -> str:
    return str(text or "").strip().rstrip(_TRAILING_PUNCT).strip()


def _inventory_step() -> dict:
    return {
        "step": 1,
        "capability": "asset.inventory",
        "input_constrict": {
            "type": "image",
            "index": 1,
            "order": "newest_first",
            "include_refs": "true",
        },
        "output_constrict": {"asset_ref": dict(_CTX_REF)},
    }


def _extract_climate_appliance(text: str) -> str | None:
    utterance = str(text or "")
    for room in _CLIMATE_ROOMS:
        if room in utterance:
            return f"{room}空调"
    matched = _APPLIANCE_RE.search(utterance)
    if matched:
        return matched.group(0)
    return None


def match_clock(text: str) -> RuleHit | None:
    t0 = time.perf_counter()
    utterance = _rstrip_punct(_lstrip_courtesy(str(text or "").strip()))
    if not utterance:
        return None
    if matches_any(utterance, _CLOCK_EXCLUDE):
        return None
    if not matches_any(utterance, _CLOCK_TRIGGERS):
        return None
    match_ms = int(round((time.perf_counter() - t0) * 1000))
    return RuleHit(
        rule="clock_now",
        goal="clock.now",
        plan=[
            {
                "step": 1,
                "capability": "clock.now",
                "input_constrict": {},
                "output_constrict": {"time_text": {}},
            }
        ],
        presentation={"type": "audio", "from": "time_text"},
        match_ms=match_ms,
    )


def match_climate(text: str) -> RuleHit | None:
    t0 = time.perf_counter()
    utterance = _rstrip_punct(_lstrip_courtesy(str(text or "").strip()))
    if not utterance or "空调" not in utterance:
        return None
    if matches_any(utterance, _CLIMATE_COMPLEX):
        return None

    norm = normalize_text(utterance)
    power = ""
    if any(normalize_text(v) in norm for v in _CLIMATE_OFF):
        power = "off"
    elif any(normalize_text(v) in norm for v in _CLIMATE_ON):
        power = "on"
    elif re.search(r"(^|.)关.{0,4}空调", utterance):
        power = "off"
    elif re.search(r"(^|.)开.{0,4}空调", utterance):
        power = "on"
    if not power:
        return None

    constrict: dict[str, str] = {"power": power}
    appliance = _extract_climate_appliance(utterance)
    if appliance:
        constrict["appliance"] = appliance

    match_ms = int(round((time.perf_counter() - t0) * 1000))
    return RuleHit(
        rule="climate_off_on" if power == "off" else "climate_on",
        goal="climate.set",
        plan=[
            {
                "step": 1,
                "capability": "climate.set",
                "input_constrict": constrict,
                "output_constrict": {},
            }
        ],
        presentation={"type": "text"},
        match_ms=match_ms,
    )


def match_photo_latest(text: str) -> RuleHit | None:
    t0 = time.perf_counter()
    utterance = _rstrip_punct(_lstrip_courtesy(str(text or "").strip()))
    if not utterance or "照片" not in utterance:
        return None
    if matches_any(utterance, _PHOTO_EXCLUDE):
        return None
    if not matches_any(utterance, _PHOTO_LATEST_HINTS):
        return None

    want_cast = matches_any(utterance, _PHOTO_CAST_HINTS)
    want_view = want_cast or matches_any(utterance, _PHOTO_VIEW_HINTS)
    if not want_view:
        return None

    inv = _inventory_step()
    if want_cast:
        plan = [
            inv,
            {
                "step": 2,
                "capability": "display.photo",
                "input_constrict": {"asset_ref": "$asset_ref"},
                "output_constrict": {},
            },
        ]
    else:
        plan = [inv]

    match_ms = int(round((time.perf_counter() - t0) * 1000))
    return RuleHit(
        rule="photo_latest_cast" if want_cast else "photo_latest",
        goal="latest photo",
        plan=plan,
        presentation={"type": "image", "from": "asset_ref"},
        match_ms=match_ms,
    )


_TV_PDF_HINT = "电视"
_TV_PDF_PREV = ("上一页", "上页", "往前翻", "向前翻")
_TV_PDF_NEXT = ("下一页", "下页", "往后翻", "向后翻")
_TV_PDF_EXCLUDE = (
    "第几页",
    "哪一页",
    "什么",
    "啥",
    "多少页",
    "几页",
)


def match_tv_pdf_page(text: str) -> RuleHit | None:
    """「电视上一页 / 电视下一页」→ display.pdf.page 翻页（电视前缀消歧，不带前缀不拦截）。"""
    t0 = time.perf_counter()
    utterance = _rstrip_punct(_lstrip_courtesy(str(text or "").strip()))
    if not utterance or _TV_PDF_HINT not in utterance:
        return None
    if matches_any(utterance, _TV_PDF_EXCLUDE):
        return None
    action = ""
    if matches_any(utterance, _TV_PDF_PREV):
        action = "prev"
    elif matches_any(utterance, _TV_PDF_NEXT):
        action = "next"
    if not action:
        return None

    match_ms = int(round((time.perf_counter() - t0) * 1000))
    return RuleHit(
        rule="tv_pdf_page",
        goal="display.pdf.page",
        plan=[
            {
                "step": 1,
                "capability": "display.pdf.page",
                "input_constrict": {"action": action},
                "output_constrict": {"status_text": {}},
            }
        ],
        # 语音发起时由 TTS 注入步朗读 status_text（如「已翻到第 2 页 / 共 3 页」）
        presentation={"type": "audio", "from": "status_text"},
        match_ms=match_ms,
    )


_TV_PDF_ZOOM_IN = ("放大",)
_TV_PDF_ZOOM_OUT = ("缩小",)
_TV_PDF_ZOOM_RESET = ("还原", "恢复原图", "原图大小")
# 「把电视声音放大」绝不能误触图片缩放
_TV_PDF_ZOOM_EXCLUDE = _TV_PDF_EXCLUDE + (
    "声音",
    "音量",
    "几倍",
)


def match_tv_pdf_zoom(text: str) -> RuleHit | None:
    """「电视放大 / 电视缩小 / 电视还原」→ display.pdf.zoom（电视前缀消歧，音量类排除）。"""
    t0 = time.perf_counter()
    utterance = _rstrip_punct(_lstrip_courtesy(str(text or "").strip()))
    if not utterance or _TV_PDF_HINT not in utterance:
        return None
    if matches_any(utterance, _TV_PDF_ZOOM_EXCLUDE):
        return None
    action = ""
    if matches_any(utterance, _TV_PDF_ZOOM_RESET):
        action = "reset"
    elif matches_any(utterance, _TV_PDF_ZOOM_OUT):
        action = "out"
    elif matches_any(utterance, _TV_PDF_ZOOM_IN):
        action = "in"
    if not action:
        return None

    match_ms = int(round((time.perf_counter() - t0) * 1000))
    return RuleHit(
        rule="tv_pdf_zoom",
        goal="display.pdf.zoom",
        plan=[
            {
                "step": 1,
                "capability": "display.pdf.zoom",
                "input_constrict": {"action": action},
                "output_constrict": {"status_text": {}},
            }
        ],
        # 语音发起时由 TTS 注入步朗读 status_text（如「已放大到 2 倍」）
        presentation={"type": "audio", "from": "status_text"},
        match_ms=match_ms,
    )


def match_rules(text: str) -> RuleHit | None:
    """Run P0 rules in priority order; uncertain → None."""
    for matcher in (
        match_clock,
        match_climate,
        match_photo_latest,
        match_tv_pdf_page,
        match_tv_pdf_zoom,
    ):
        hit = matcher(text)
        if hit is not None:
            return hit
    return None
