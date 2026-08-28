"""Load per-handle wake prompts for Fleet workers."""

from __future__ import annotations

from pathlib import Path

from agent_bridge.fleet_handles import normalize_fleet_handle

_PROFILES_DIR = Path(__file__).resolve().parents[2] / "agent_profiles"

_FALLBACK = {
    "coordinator": "You are system coordinator agent (@coordinator). Coordinate, dispatch, daily reports. Do not write product code.",
    "controller": "You are dev controller agent (@controller). Orchestrate Fleet workers, summarize for the user, small single-layer fixes only.",
    "brain": "You are brain agent (@brain). Planner, routing, home_brain.py, server/prompts/. Do not edit plugins or UI.",
    "runtime": "You are runtime dev agent (@runtime). Scheduler, hydrate, pre-step gates, mac_edge executor. Do not edit UI.",
    "ui": "You are UI dev agent (@ui). All user-facing UI: Intent windows, logistics, Cast receiver, games presentation, Admin/Dev consoles.",
    "capability": "You are capability dev agent (@capability). Plugins and services without UI.",
    "quality": "You are quality agent (@quality). Black-box API tests only; update tests/blackbox/. Do not change product code.",
    "deploy": "You are deploy agent (@deploy). Cloud Brain rsync and restart per cloud-deploy rules.",
    "sre": "You are sre agent (@sre). LAN Brain, Mac Edge, service health, dependencies.",
    "dba": "You are dba agent (@dba). server/sql/ and schema migrations only.",
}


def profile_path(handle: str) -> Path:
    return _PROFILES_DIR / f"{handle}.md"


def load_profile(handle: str) -> str:
    normalized = normalize_fleet_handle(handle) or handle
    path = profile_path(normalized)
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return _FALLBACK.get(normalized, f"You are Fleet worker @{normalized}.")


def build_wake_prompt(
    handle: str,
    *,
    task_text: str = "",
    chat_summary: str = "",
) -> str:
    normalized = normalize_fleet_handle(handle) or handle
    parts = [
        load_profile(normalized),
        "",
        f"Your Chatbox handle is @{normalized}. After work, push_msg to Chatbox with from={normalized!r}.",
        "Read docs/agent-coordination.md before pull_msg if you have not recently.",
    ]
    if chat_summary.strip():
        parts.extend(["", "## Unread Chatbox messages", chat_summary.strip()])
    if task_text.strip():
        parts.extend(["", "## Task", task_text.strip()])
    parts.extend(
        [
            "",
            "## Workflow",
            "1. GET pull_msg for your handle if needed.",
            "2. push_msg acknowledge, then implement within your layer.",
            "3. Product code: git commit (see docs/git-commit-convention.md), then test, then deploy — never treat dirty workspace as shipped.",
            "4. Record each node in Chatbox with [release] stage=committed|tested|deploy_requested|deployed (or skipped+note); @controller. See .cursor/rules/release-pipeline.mdc.",
            "5. push_msg completion; @quality if API acceptance needed; @deploy only with commit sha after tests.",
        ]
    )
    return "\n".join(parts)
