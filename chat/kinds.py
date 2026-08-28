"""Structured Chat message kinds (distinct from free-text chat)."""

from __future__ import annotations

KIND_CHAT = "chat"
KIND_COMPLETE = "complete"

VALID_KINDS = frozenset({KIND_CHAT, KIND_COMPLETE})

# Feishu-style reaction on a message (stored in message_acks, not as a message row).
ACK_OK = "ok"
ACK_GOT = "got"
VALID_ACK_TYPES = frozenset({ACK_OK, ACK_GOT})
