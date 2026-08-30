"""Structured Chat message kinds (distinct from free-text chat)."""

from __future__ import annotations

KIND_CHAT = "chat"
KIND_COMPLETE = "complete"

VALID_KINDS = frozenset({KIND_CHAT, KIND_COMPLETE})

# Feishu-style reaction on a message (stored in message_acks, not as a message row).
# One handle → one ack_type per message (upsert).
ACK_RECV = "recv"  # 收到 — formal @ 派活签收（可先不写聊天行）
ACK_GOT = "got"  # 知道了 — cc @ 周知知情
ACK_OK = "ok"  # legacy alias; UI treats like 知道了 (got)
VALID_ACK_TYPES = frozenset({ACK_RECV, ACK_GOT, ACK_OK})

ACK_LABELS = {
    ACK_RECV: "收到",
    ACK_GOT: "知道了",
    ACK_OK: "知道了",
}


def normalize_ack_type(raw: str | None) -> str:
    key = str(raw or "").strip().lower() or ACK_GOT
    if key in ("received", "receive", "ack", "recv"):
        return ACK_RECV
    if key in ("got", "know", "fyi"):
        return ACK_GOT
    if key == ACK_OK:
        return ACK_OK
    if key in VALID_ACK_TYPES:
        return key
    raise ValueError(f"invalid ack_type: {raw}")
