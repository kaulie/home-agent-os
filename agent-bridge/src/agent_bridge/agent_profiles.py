"""Load per-handle wake prompts for Fleet workers."""

from __future__ import annotations

from pathlib import Path

from agent_bridge.fleet_handles import normalize_fleet_handle

_PROFILES_DIR = Path(__file__).resolve().parents[2] / "agent_profiles"

_FALLBACK = {
    "coordinator": "You are system coordinator agent (@coordinator). DEFAULT SILENT. Only speak for cross-layer arbitration, nudges, dispatch, daily-report rollup, or doc summary. Never write product code. Never reply to closure/clearance confirmations with 统筹记录 or formal @ broadcasts — ack only (recv/got) then stop. Closures should arrive as cc @coordinator.",
    "controller": "You are dev controller agent (@controller). Orchestrate Fleet workers, summarize for the user, small single-layer fixes only.",
    "brain": "You are brain agent (@brain). Planner, routing, home_brain.py, server/prompts/. Do not edit plugins or UI.",
    "runtime": "You are runtime dev agent (@runtime). Scheduler, hydrate, pre-step gates, mac_edge executor. Do not edit UI.",
    "ui": "You are UI dev agent (@ui). All user-facing UI: Intent windows, logistics, Cast receiver, games presentation, Admin/Dev consoles.",
    "capability": "You are capability dev agent (@capability). Plugins and services without UI.",
    "quality": "You are quality agent (@quality). Black-box API tests (tests/blackbox/) AND App UI automation — XCUITest first (docs/testing/xcuitest.md). Do not change product feature logic.",
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
            "2. Role check on each message (docs/agent-coordination.md §4 / §4b):",
            "   - Formal @ (主送): FIRST push_msg a one-line [status] "
            "(phase=idle|wip|blocked|pending, WIP, tree=clean|dirty, 对本指令=接做|pending|转交). "
            "THEN ack_msg ack_type=recv (✅ 收到). Then implement or park as pending.",
            "   - cc @ (周知): POST ack_msg ack_type=got (👌 知道了) only. "
            "No [status] line. Do NOT implement. Do NOT use recv for CC.",
            "3. Product code: git commit (see docs/git-commit-convention.md; footer agent: <handle>), then test, then deploy — never treat dirty workspace as shipped.",
            "4. Docs you write must be standard Markdown (mobile-friendly); notify @boss with [[doc:path]] only, never paste full md. See docs/agent-coordination.md §2b.",
            "5. Record each node in Chatbox with [release] stage=committed|tested|deploy_requested|deployed (or skipped+note); @controller. See .cursor/rules/release-pipeline.mdc.",
            "6. Action owners: push_msg completion; use cc @boss (or cc @ui) to FYI; "
            "closures/clearance → cc @coordinator (never formal @coordinator for ACK loops); "
            "@quality if API acceptance needed; @deploy only with commit sha after tests.",
        ]
    )
    if normalized == "coordinator":
        parts.extend(
            [
                "",
                "## Coordinator silence (mandatory)",
                "- Default: do NOT push_msg after pull unless arbitration/nudge/dispatch/daily-report/doc work.",
                "- Closure / 清仓 / 无异议 / tree clean confirms: ack only, then STOP. No 统筹记录. No formal @ to peers.",
                "- If wake task is only archival confirmation noise: ack + exit without further Chat posts.",
            ]
        )
    return "\n".join(parts)
