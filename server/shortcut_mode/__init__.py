"""Shortcut / Mode intercept — bypass LLM when triggers match."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from . import music, reading, rules
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

    rule_hit = rules.match_rules(utterance)
    if rule_hit is not None:
        return InterceptResult(
            kind="plan",
            mode=None,
            plan=rules.copy_plan(rule_hit.plan),
            presentation=dict(rule_hit.presentation),
            planner_meta={
                "goal": rule_hit.goal,
                "source": "shortcut",
                "rule": rule_hit.rule,
                "timing": {"match": rule_hit.match_ms},
            },
        )

    music_ctrl = music.match_control(utterance)
    if music_ctrl is not None:
        return InterceptResult(
            kind="plan",
            mode=None,
            plan=[
                {
                    "step": 1,
                    "capability": music_ctrl.capability,
                    "input_constrict": {"user_input": music_ctrl.user_input},
                    "output_constrict": {},
                }
            ],
            presentation={"type": "text"},
            planner_meta={
                "goal": music_ctrl.capability,
                "source": "shortcut",
                "timing": {"match": music_ctrl.match_ms},
            },
        )

    music_cache = music.match_cache(utterance)
    if music_cache is not None:
        constrict: dict[str, Any] = {"user_input": music_cache.user_input}
        if music_cache.song:
            constrict["song"] = music_cache.song
        if music_cache.count is not None:
            constrict["count"] = music_cache.count
        return InterceptResult(
            kind="plan",
            mode=None,
            plan=[
                {
                    "step": 1,
                    "capability": "music.cache",
                    "input_constrict": constrict,
                    "output_constrict": {},
                }
            ],
            presentation={"type": "text"},
            planner_meta={
                "goal": "cache songs",
                "source": "shortcut",
                "timing": {"match": music_cache.match_ms},
            },
        )

    music_hit = music.match_play(utterance)
    if music_hit is not None:
        constrict = {"user_input": music_hit.user_input}
        if music_hit.song:
            constrict["song"] = music_hit.song
        if music_hit.count is not None:
            constrict["count"] = music_hit.count
        return InterceptResult(
            kind="plan",
            mode=None,
            plan=[
                {
                    "step": 1,
                    "capability": "music.play",
                    "input_constrict": constrict,
                    "output_constrict": {},
                }
            ],
            presentation={"type": "text"},
            planner_meta={
                "goal": "play song",
                "source": "shortcut",
                "timing": {"match": music_hit.match_ms},
            },
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
