"""Parse @mentions and compute message audience."""

from __future__ import annotations

import re

HANDLES: tuple[str, ...] = (
    "coordinator",
    "brain",
    "runtime",
    "intent",
    "capability",
    "endpoint",
    "quality",
    "dba",
)

HANDLE_SET = frozenset(HANDLES)

ALL_ALIASES = frozenset({"all", "所有人", "everyone"})
HANDLE_ALIASES = {"observer": "coordinator", "user": "boss", "owner": "boss"}
OWNER = "boss"

SENDERS = HANDLE_SET | {OWNER}

DISPLAY_NAMES = {
    "boss": "boss",
    "owner": "boss",
    "coordinator": "system coordinator agent",
    "brain": "brain agent",
    "runtime": "runtime dev agent",
    "intent": "Intent dev agent",
    "capability": "capability dev agent",
    "endpoint": "endpoint agent",
    "quality": "quality agent",
    "dba": "dba agent",
}

# @all / @everyone / @brain / @所有人
_MENTION_RE = re.compile(r"@([A-Za-z_]+|所有人)")


def normalize_handle(raw: str | None) -> str:
    text = (raw or "").strip()
    if text.startswith("@"):
        text = text[1:]
    if text == "所有人":
        return "all"
    key = text.lower()
    if key in ALL_ALIASES:
        return "all"
    mapped = HANDLE_ALIASES.get(key, key)
    return mapped


def parse_mentions(body: str) -> list[str]:
    """Return ['all'] or a de-duplicated list of registered handles."""
    found: list[str] = []
    saw_all = False
    for match in _MENTION_RE.finditer(body or ""):
        token = match.group(1)
        if token == "所有人" or token.lower() in ALL_ALIASES:
            saw_all = True
            continue
        handle = normalize_handle(token)
        if handle == "all":
            saw_all = True
            continue
        if handle in SENDERS and handle not in found:
            found.append(handle)
    if saw_all:
        return ["all"]
    return found


def audience_for(from_handle: str, mentions: list[str]) -> list[str]:
    sender = normalize_handle(from_handle)
    if "all" in mentions:
        return ["all"]
    if mentions:
        return list(mentions)
    if sender == OWNER:
        return []
    return ["all"]


def visible_to(audience: list[str], handle: str) -> bool:
    if not audience:
        return False
    if "all" in audience:
        return True
    return handle in audience


def recipients_for(from_handle: str, audience: list[str]) -> list[str]:
    """Who has a read/unread row. Sender is included only for boss notes."""
    sender = normalize_handle(from_handle)
    if sender == "all":
        sender = OWNER
    if not audience:
        return [OWNER]
    recips: list[str] = []
    if "all" in audience:
        recips.extend(HANDLES)
    else:
        for item in audience:
            handle = normalize_handle(item)
            if handle in SENDERS and handle not in recips:
                recips.append(handle)
    if sender != OWNER and OWNER not in recips:
        recips.append(OWNER)
    return recips
