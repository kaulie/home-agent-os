"""Brain-persisted voice wake reply (唤醒应答) settings."""

from __future__ import annotations

import re
from typing import Any

import db as brain_db

DEFAULT_WAKE_ACK = "我在呢"
META_WAKE_ACK = "voice_wake_ack"
_LEGACY_WAKE_ACK_UTTERANCES = frozenset({"又咋了", "又咋啦", "我在呢", "在呢", "咋了"})
_WAKE_ACK_MAX_LEN = 32


def _compact(text: str) -> str:
    return re.sub(r"[\s，。！？,.!?\"'“”‘’]", "", str(text or ""))


def get_wake_ack() -> str:
    getter = getattr(brain_db, "meta_get", None)
    if not callable(getter):
        return DEFAULT_WAKE_ACK
    raw = str(getter(META_WAKE_ACK, "") or "").strip()
    return raw or DEFAULT_WAKE_ACK


def set_wake_ack(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        raise ValueError("wake_ack must not be empty")
    if len(value) > _WAKE_ACK_MAX_LEN:
        raise ValueError(f"wake_ack must be at most {_WAKE_ACK_MAX_LEN} characters")
    setter = getattr(brain_db, "meta_set", None)
    if not callable(setter):
        raise RuntimeError("meta_set not available on Brain db")
    setter(META_WAKE_ACK, value)
    return value


def wake_ack_utterances(ack: str | None = None) -> frozenset[str]:
    """Utterances that must not be posted as user intents (STT echo of wake reply)."""
    variants: set[str] = set(_LEGACY_WAKE_ACK_UTTERANCES)
    compact = _compact(ack if ack is not None else get_wake_ack())
    if compact:
        variants.add(compact)
        if compact.startswith("我") and len(compact) > 1:
            variants.add(compact[1:])
        if compact.endswith("呢") and len(compact) > 1:
            variants.add(compact[:-1])
    return frozenset(v for v in variants if v)


def public_settings() -> dict[str, Any]:
    ack = get_wake_ack()
    return {"ok": True, "wake_ack": ack}
