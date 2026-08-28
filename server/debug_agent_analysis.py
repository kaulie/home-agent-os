"""Parse structured fix recommendations from Dev Agent replies."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class FixRecommendationItem:
    title: str = ""
    priority: str = ""
    owner: str = ""
    purpose: str = ""
    expected_benefit: str = ""
    approach: str = ""

    @property
    def is_structured(self) -> bool:
        return bool(
            self.priority
            or self.owner
            or self.purpose
            or self.expected_benefit
            or self.approach
        )


_FIELD_SPECS = (
    (("优先级", "Priority"), "priority"),
    (("负责人", "Owner", "负责方"), "owner"),
    (("作用", "Purpose", "目的"), "purpose"),
    (("预期收益", "Expected benefit", "收益", "预期效果"), "expected_benefit"),
    (("改法", "具体改法", "修复步骤", "步骤", "Fix", "Implementation"), "approach"),
)


def parse_fix_recommendations(text: str) -> list[FixRecommendationItem]:
    cleaned = (text or "").strip()
    if not cleaned:
        return []

    blocks = _split_blocks(cleaned)
    items: list[FixRecommendationItem] = []
    for block in blocks:
        item = _parse_block(block)
        if item.is_structured or item.title or item.approach:
            items.append(item)

    if not items:
        return [FixRecommendationItem(approach=cleaned)]
    return items


def _split_blocks(text: str) -> list[str]:
    lines = text.splitlines()
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if _is_item_header(line) and current:
            blocks.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        blocks.append(current)

    if len(blocks) == 1 and "\n---\n" in text:
        return [part.strip() for part in text.split("\n---\n") if part.strip()]
    return ["\n".join(part).strip() for part in blocks if any(x.strip() for x in part)]


def _is_item_header(line: str) -> bool:
    stripped = line.strip()
    if stripped.startswith("### "):
        return True
    if re.match(r"^\d+\.\s", stripped):
        return True
    if stripped.startswith("**建议") and "**" in stripped:
        return True
    return False


def _parse_block(block: str) -> FixRecommendationItem:
    item = FixRecommendationItem()
    body_lines: list[str] = []
    for index, raw_line in enumerate(block.splitlines()):
        line = raw_line.strip()
        if not line:
            continue
        if index == 0 or (not item.title and _is_item_header(raw_line)):
            title = _parse_title(line)
            if title:
                item.title = title
                continue
        field = _parse_field_line(line)
        if field:
            setattr(item, field[0], field[1])
            continue
        body_lines.append(raw_line)
    if not item.approach and body_lines:
        item.approach = "\n".join(body_lines).strip()
    return item


def _parse_title(line: str) -> str:
    text = _strip_md(line)
    if text.startswith("### "):
        text = text[4:]
    text = re.sub(r"^\d+\.\s*", "", text)
    text = re.sub(r"^建议\s*\d+\s*[:：]\s*", "", text)
    return text.strip()


def _parse_field_line(line: str) -> tuple[str, str] | None:
    text = _strip_md(line)
    for prefix in ("- ", "* ", "• "):
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
            break
    for labels, attr in _FIELD_SPECS:
        for label in labels:
            for sep in ("：", ":"):
                prefix = f"{label}{sep}"
                if text.lower().startswith(prefix.lower()):
                    return attr, text[len(prefix) :].strip()
    return None


def _strip_md(line: str) -> str:
    return line.replace("**", "").replace("__", "").strip()
