"""Shortcut / Mode intercept — bypass LLM when triggers match."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from . import reading
from .state import READING_MODE, enter_mode, exit_mode, get_active_mode

InterceptKind = Literal["enter_mode", "exit_mode", "plan"]


@dataclass
class InterceptResult:
    kind: InterceptKind
    mode: str | None
    plan: list[dict]
    presentation: dict
    planner_meta: dict | None = None


def intercept(text: str, *, intent: dict[str, Any] | None = None) -> InterceptResult | None:
    utterance = str(text or "").strip()
    if not utterance:
        return None

    if reading.match_exit(utterance):
        return InterceptResult(
            kind="exit_mode",
            mode=READING_MODE,
            plan=reading.copy_plan(reading.READING_EXIT_PLAN),
            presentation=dict(reading.READING_EXIT_PRESENTATION),
            planner_meta={"goal": "exit reading mode", "source": "shortcut"},
        )

    if reading.match_enter(utterance):
        return InterceptResult(
            kind="enter_mode",
            mode=READING_MODE,
            plan=reading.copy_plan(reading.READING_ENTER_PLAN),
            presentation=dict(reading.READING_ENTER_PRESENTATION),
            planner_meta={"goal": "enter reading mode", "source": "shortcut"},
        )

    active = get_active_mode()
    if active == READING_MODE and reading.match_existing_photo(utterance):
        return InterceptResult(
            kind="plan",
            mode=READING_MODE,
            plan=reading.copy_plan(reading.READING_EXISTING_PHOTO_PIPELINE_PLAN),
            presentation=dict(reading.READING_PIPELINE_PRESENTATION),
            planner_meta={"goal": "reading existing photo pipeline", "source": "shortcut"},
        )

    if active == READING_MODE and reading.match_pipeline(utterance):
        return InterceptResult(
            kind="plan",
            mode=READING_MODE,
            plan=reading.copy_plan(reading.READING_PIPELINE_PLAN),
            presentation=dict(reading.READING_PIPELINE_PRESENTATION),
            planner_meta={"goal": "reading pipeline", "source": "shortcut"},
        )

    return None


def apply_mode_event(result: InterceptResult, *, intent: dict[str, Any] | None = None) -> None:
    edge_id = str((intent or {}).get("edge_id") or "").strip()
    intent_id = (intent or {}).get("intent_id") or (intent or {}).get("id")
    text = str((intent or {}).get("text") or "").strip()
    payload = {"text": text} if text else None
    if result.kind == "enter_mode" and result.mode:
        enter_mode(result.mode, edge_id=edge_id, intent_id=intent_id, payload=payload)
    elif result.kind == "exit_mode" and result.mode:
        exit_mode(result.mode, edge_id=edge_id, intent_id=intent_id, payload=payload)
