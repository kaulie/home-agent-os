"""Mac Edge capability: chat.smalltalk — 简短闲聊/问候，无 LLM.

契约：入参 text=用户的话；产出 reply=回复的话。交付方式不归本能力。
只处理「早啊 / 你好 / 谢谢」这类寒暄。
"""

from __future__ import annotations

import logging
import random
import re
from typing import Any

log = logging.getLogger("mac_edge.chat_smalltalk")


class ChatSmalltalkError(Exception):
    pass


# (compiled pattern, reply candidates) — first match wins
_RULES: list[tuple[re.Pattern[str], tuple[str, ...]]] = [
    (
        re.compile(
            r"(早上好|早安|早啊|早呀|good\s*morning)",
            re.IGNORECASE,
        ),
        ("早啊～", "早上好！", "早呀，今天也顺利～"),
    ),
    (
        re.compile(r"(中午好|午安)", re.IGNORECASE),
        ("中午好～", "午安！"),
    ),
    (
        re.compile(
            r"(晚上好|晚安|晚好|good\s*evening|good\s*night)",
            re.IGNORECASE,
        ),
        ("晚上好～", "晚安，好好休息。", "晚好呀～"),
    ),
    (
        re.compile(
            r"(谢谢|多谢|感谢|thank\s*you|thanks)",
            re.IGNORECASE,
        ),
        ("不客气～", "没事儿～", "应该的。"),
    ),
    (
        re.compile(
            r"(再见|拜拜|回见|bye|goodbye|see\s*you)",
            re.IGNORECASE,
        ),
        ("再见～", "拜拜，有事再叫我。", "回头见～"),
    ),
    (
        re.compile(
            r"(在吗|在不在|你在吗|有人吗)",
            re.IGNORECASE,
        ),
        ("在的～", "我在，有什么事吗？", "在呢。"),
    ),
    (
        re.compile(
            r"(你好吗|你好嘛|怎么样|how\s*are\s*you)",
            re.IGNORECASE,
        ),
        ("挺好的，你呢？", "还不错～你怎么样？"),
    ),
    (
        re.compile(
            r"(你好啊?|您好|嗨|哈喽|嘿|hello|hi\b|hey)",
            re.IGNORECASE,
        ),
        ("你好呀～", "嗨～", "你好！"),
    ),
]


def _pick(candidates: tuple[str, ...]) -> str:
    return random.choice(candidates)


def smalltalk_reply(*, text: str) -> dict[str, str]:
    """Match greeting/smalltalk; raise if not this capability's job."""
    raw = (text or "").strip()
    if not raw:
        raise ChatSmalltalkError("chat.smalltalk 缺少必填 text（用户的话）")
    for pattern, replies in _RULES:
        if pattern.search(raw):
            return {"reply": _pick(replies)}
    raise ChatSmalltalkError(
        "不是简单闲聊/问候（如早啊、你好）。知识问答用 query.content，"
        "报时用 clock.now，算式用 math.calculate。"
    )


def smalltalk_from_params(
    params: dict[str, Any] | None = None,
) -> tuple[str, dict[str, str]]:
    raw = params if isinstance(params, dict) else {}
    text = raw.get("text") or raw.get("message") or raw.get("utterance")
    text_s = str(text).strip() if text is not None else ""
    outputs = smalltalk_reply(text=text_s)
    msg = f"chat.smalltalk {outputs['reply']}"
    log.info("chat.smalltalk text=%r reply=%r", text_s[:80], outputs["reply"])
    return msg, outputs
