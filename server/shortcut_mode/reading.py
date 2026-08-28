"""Reading Mode: triggers and hard-coded execution plans."""

from __future__ import annotations

from copy import deepcopy

from .matcher import matches_any

# Runtime hydrate only loads outputs marked data_dest=context (Mac/iOS executor).
_CTX_REF = {"type": "object", "data_dest": "context", "required": True}
_CTX_TEXT = {"type": "string", "data_dest": "context", "required": True}

READING_ENTER_TRIGGERS = (
    "开启阅读模式",
    "进入阅读模式",
    "阅读模式",
)
READING_EXIT_TRIGGERS = (
    "退出阅读模式",
    "关闭阅读模式",
    "结束阅读模式",
)
READING_PIPELINE_TRIGGERS = (
    "这个字",
    "那个字",
    "这是什么字",
    "怎么读",
    "怎么念",
    "认识一下这个字",
    "这个字是什么字",
    "这个读什么",
    "这个字读啥",
    "指的这个字怎么读",
    "这个字念什么",
    "指着这个字",
    "认一下这个字",
)

# 已有登记照片（asset.inventory），不再 camera.capture_and_upload。
READING_EXISTING_PHOTO_TRIGGERS = (
    "最新的一张照片",
    "最新一张照片",
    "最新照片",
    "最后一张照片",
    "最后一张",
    "刚才的照片",
    "刚才那张",
    "最近一张照片",
    "最近一张",
    "上一张照片",
    "上一张",
    "最新的照片",
    "刚拍的照片",
    "刚才拍的那张",
    "之前拍的照片",
    "之前那张",
)

READING_LIVE_CAPTURE_HINTS = (
    "拍一张",
    "拍照",
    "现在拍",
    "重新拍",
    "再拍",
    "拍张",
    "拍一下",
)

READING_ENTER_PLAN = [
    {
        "step": 1,
        "capability": "notify.speak",
        "input_constrict": {"text": "好的，已进入阅读模式。"},
        "output_constrict": {},
    },
]

READING_EXIT_PLAN = [
    {
        "step": 1,
        "capability": "notify.speak",
        "input_constrict": {"text": "好的，已退出阅读模式。"},
        "output_constrict": {},
    },
]

READING_PIPELINE_PLAN = [
    {
        "step": 1,
        "capability": "camera.capture_and_upload",
        "input_constrict": {},
        "output_constrict": {"asset_ref": dict(_CTX_REF)},
    },
    {
        "step": 2,
        "capability": "reading.point_to_character",
        "input_constrict": {"asset_ref": "$asset_ref"},
        "output_constrict": {
            "character": dict(_CTX_TEXT),
            "answer_text": dict(_CTX_TEXT),
        },
    },
    {
        "step": 3,
        "capability": "notify.speak",
        "input_constrict": {"text": "$answer_text"},
        "output_constrict": {},
    },
]

READING_EXISTING_PHOTO_PIPELINE_PLAN = [
    {
        "step": 1,
        "capability": "asset.inventory",
        "input_constrict": {
            "type": "image",
            "index": 1,
            "order": "newest_first",
            "include_refs": "true",
        },
        "output_constrict": {
            "asset_ref": dict(_CTX_REF),
            "answer_text": dict(_CTX_TEXT),
        },
    },
    {
        "step": 2,
        "capability": "reading.point_to_character",
        "input_constrict": {"asset_ref": "$asset_ref"},
        "output_constrict": {
            "character": dict(_CTX_TEXT),
            "answer_text": dict(_CTX_TEXT),
        },
    },
    {
        "step": 3,
        "capability": "notify.speak",
        "input_constrict": {"text": "$answer_text"},
        "output_constrict": {},
    },
]

READING_ENTER_PRESENTATION = {"type": "audio", "text": "好的，已进入阅读模式。"}
READING_EXIT_PRESENTATION = {"type": "audio", "text": "好的，已退出阅读模式。"}
READING_PIPELINE_PRESENTATION = {"type": "audio", "from": "answer_text"}


def match_enter(text: str) -> bool:
    return matches_any(text, READING_ENTER_TRIGGERS)


def match_exit(text: str) -> bool:
    return matches_any(text, READING_EXIT_TRIGGERS)


def match_pipeline(text: str) -> bool:
    return matches_any(text, READING_PIPELINE_TRIGGERS)


def match_existing_photo(text: str) -> bool:
    """Referring to a catalogued photo — inventory, not live capture."""
    if not matches_any(text, READING_EXISTING_PHOTO_TRIGGERS):
        return False
    if matches_any(text, READING_LIVE_CAPTURE_HINTS):
        return False
    return matches_any(text, READING_PIPELINE_TRIGGERS) or matches_any(
        text, ("手指", "指着")
    )


def copy_plan(plan: list[dict]) -> list[dict]:
    return deepcopy(plan)
