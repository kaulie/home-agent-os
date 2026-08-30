"""Parse @mentions and compute message audience.

Formal @ (action / 主送) vs cc @ (周知):
  `@quality 请验收。cc @ui @boss`
  - action: ack_msg ack_type=recv (✅ 收到), then do work; push_msg later when done/need to talk
  - cc: ack_msg ack_type=got (👌 知道了) only; no chat reply line; no work

See docs/agent-coordination.md §4 and .cursor/rules/agent-chat-mentions.mdc.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

HANDLES: tuple[str, ...] = (
    "coordinator",
    "controller",
    "brain",
    "runtime",
    "ui",
    "capability",
    "quality",
    "deploy",
    "sre",
    "dba",
)

HANDLE_SET = frozenset(HANDLES)

ALL_ALIASES = frozenset({"all", "所有人", "everyone"})
HANDLE_ALIASES = {
    "observer": "coordinator",
    "user": "boss",
    "owner": "boss",
    "intent": "ui",
    "endpoint": "ui",
}
OWNER = "boss"

SENDERS = HANDLE_SET | {OWNER}

DISPLAY_NAMES = {
    "boss": "boss",
    "owner": "boss",
    "coordinator": "system coordinator agent",
    "controller": "dev controller agent",
    "brain": "brain agent",
    "runtime": "runtime dev agent",
    "ui": "UI dev agent",
    "capability": "capability dev agent",
    "quality": "quality agent",
    "deploy": "deploy agent",
    "sre": "sre agent",
    "dba": "dba agent",
}

# @all / @everyone / @brain / @所有人
_MENTION_RE = re.compile(r"@([A-Za-z_]+|所有人)")
# `cc @a @b` or `cc:@a` (word-boundary so "acc @x" is not CC)
_CC_BLOCK_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9_])cc\s*:?\s*((?:@(?:[A-Za-z_]+|所有人)\s*)+)"
)


@dataclass(frozen=True)
class MentionRoles:
    """action = 主送 (must formal reply); cc = 抄送 (ack badge only)."""

    action: list[str]
    cc: list[str]

    @property
    def all_mentions(self) -> list[str]:
        """Deduped union for audience / pull visibility. @all collapses."""
        if "all" in self.action:
            return ["all"]
        out: list[str] = []
        for handle in self.action + self.cc:
            if handle == "all":
                return ["all"]
            if handle not in out:
                out.append(handle)
        return out


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


def _append_handle(found: list[str], *, saw_all: list[bool], token: str) -> None:
    if token == "所有人" or token.lower() in ALL_ALIASES:
        saw_all[0] = True
        return
    handle = normalize_handle(token)
    if handle == "all":
        saw_all[0] = True
        return
    if handle == OWNER:
        if OWNER not in found:
            found.append(OWNER)
        return
    if handle in HANDLE_SET and handle not in found:
        found.append(handle)


def parse_mention_roles(body: str) -> MentionRoles:
    """Split primary @mentions from `cc @handle` copies."""
    text = body or ""
    cc_spans: list[tuple[int, int]] = []
    cc_found: list[str] = []
    cc_all = [False]
    for block in _CC_BLOCK_RE.finditer(text):
        cc_spans.append(block.span())
        for match in _MENTION_RE.finditer(block.group(1)):
            _append_handle(cc_found, saw_all=cc_all, token=match.group(1))
    if cc_all[0]:
        cc_found = ["all"]

    action_found: list[str] = []
    action_all = [False]
    for match in _MENTION_RE.finditer(text):
        start = match.start()
        if any(lo <= start < hi for lo, hi in cc_spans):
            continue
        _append_handle(action_found, saw_all=action_all, token=match.group(1))
    if action_all[0]:
        action_found = ["all"]

    # Primary wins if the same handle appears in both.
    if "all" in action_found:
        cc_clean: list[str] = []
    else:
        action_set = set(action_found)
        cc_clean = [h for h in cc_found if h not in action_set and h != "all"]

    return MentionRoles(action=action_found, cc=cc_clean)


def parse_mentions(body: str) -> list[str]:
    """Return ['all'] or de-duplicated registered handles (action ∪ cc)."""
    return parse_mention_roles(body).all_mentions


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
            if handle == OWNER:
                if OWNER not in recips:
                    recips.append(OWNER)
            elif handle in HANDLE_SET and handle not in recips:
                recips.append(handle)
    if sender != OWNER and OWNER not in recips:
        recips.append(OWNER)
    return recips
