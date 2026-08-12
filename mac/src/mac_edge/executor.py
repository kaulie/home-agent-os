"""Executor: step-level closed loop (report → run → report → find next)."""

from __future__ import annotations

import logging
from typing import Any

from mac_edge.brain_client import BrainClient, BrainError
from mac_edge.brain_time import BRAIN_CLOCK
from mac_edge.config import Config
from mac_edge.execution_timing import (
    MODE_DELAY,
    parse_execution_timing,
    timing_gate,
)
from mac_edge.plugins.chromecast_display import CastError, cast_photo
from mac_edge.plugins.notify_speak import NotifySpeakError, speak_from_params
from mac_edge.runtime_context import (
    RuntimeContext,
    input_params_of,
    output_constrict_of,
    resolve_params,
)
from mac_edge.timing_beats import advance_beat, get_beat

log = logging.getLogger("mac_edge.executor")

STEP_WAITING = 0
STEP_RUNNING = 1
STEP_SUCCEEDED = 2
STEP_FAILED = 3


def handle_intent(
    intent: dict[str, Any],
    *,
    edge_id: str,
    config: Config,
    brain: BrainClient,
) -> None:
    """Run locally eligible steps; Edge also reports intent-level running/succeeded/failed."""
    eid = edge_id.strip()
    iid = str(intent.get("id") or intent.get("intent_id") or "").strip()
    if not eid or not iid:
        log.warning("executor: missing edge_id or intent id")
        return

    # Working copy of plan statuses so later finds in same tick see updates.
    plan = normalize_plan(intent.get("execution_plan"))
    if not plan:
        log.info("intent %s: no execution_plan — skip execute", iid)
        return

    # Same model as iOS: hydrate context from Brain, resolve $vars from context.
    context = RuntimeContext()
    _hydrate_context(context, intent)
    if context.snapshot():
        log.info(
            "intent %s: context keys=%s",
            iid,
            ",".join(sorted(context.snapshot())),
        )
    else:
        # Cross-edge: step1 outputs may land a tick later — refresh detail once.
        detail = brain.fetch_intent_detail(iid)
        if isinstance(detail, dict) and detail:
            _hydrate_context(context, detail)
            if isinstance(detail.get("execution_plan"), list):
                plan = normalize_plan(detail.get("execution_plan"))
            if context.snapshot():
                log.info(
                    "intent %s: context keys after detail refresh=%s",
                    iid,
                    ",".join(sorted(context.snapshot())),
                )

    first = True
    while True:
        # Advance past interval/cron beats that already missed their window.
        _advance_skipped_beats(plan, iid, eid)

        step = find_next_eligible_local_step(plan, eid, intent_id=iid)
        if step is None:
            if first:
                log.info(
                    "intent %s: no eligible local step — %s",
                    iid,
                    explain_ineligible(plan, eid, intent_id=iid),
                )
            break
        first = False
        step_num = int(step["step"])
        cap = str(step.get("capability") or "").strip()
        timing = parse_execution_timing(step)

        # Resolve input_constrict `$name` from context before execute.
        try:
            params = resolve_params(input_params_of(step), context)
        except ValueError as e:
            if cap == "display.photo" and "photo_url" in str(e):
                _ensure_photo_url(context)
                try:
                    params = resolve_params(input_params_of(step), context)
                except ValueError as e2:
                    log.warning(
                        "intent %s step %s: %s — skip this tick (wait for context)",
                        iid,
                        step_num,
                        e2,
                    )
                    break
            else:
                # Do NOT mark failed yet — predecessor may still be publishing context.
                log.warning(
                    "intent %s step %s: %s — skip this tick (wait for context)",
                    iid,
                    step_num,
                    e,
                )
                break

        # 1) Report running first
        try:
            brain.post_step_status(
                iid,
                step_num,
                step_status=STEP_RUNNING,
                edge_node_id=eid,
            )
            step["status"] = STEP_RUNNING
        except BrainError as e:
            log.error("intent %s step %s: fail to report running: %s", iid, step_num, e)
            break

        # Edge owns whole-job status (Brain does not infer from steps).
        try:
            brain.post_intent_status(
                iid,
                status="running",
                edge_node_id=eid,
                message=f"executing {cap}",
            )
        except BrainError as e:
            log.warning("intent %s: fail to report intent running: %s", iid, e)

        # 2) Execute with resolved params
        ok, message, outputs = _execute_capability(cap, params, config)
        if ok and outputs:
            published = context.publish(outputs, output_constrict_of(step))
            if published:
                log.info(
                    "intent %s step %s: context publish keys=%s",
                    iid,
                    step_num,
                    ",".join(published),
                )
        final = STEP_SUCCEEDED if ok else STEP_FAILED

        # 3) Report terminal (+ outputs so Brain can register to context)
        try:
            brain.post_step_status(
                iid,
                step_num,
                step_status=final,
                edge_node_id=eid,
                outputs=outputs or None,
            )
            step["status"] = final
            if ok:
                log.info("intent %s step %s OK (%s): %s", iid, step_num, cap, message)
            else:
                log.error("intent %s step %s FAIL (%s): %s", iid, step_num, cap, message)
        except BrainError as e:
            log.error(
                "intent %s step %s: fail to report terminal %s: %s",
                iid,
                step_num,
                final,
                e,
            )
            break

        # Recurring: re-arm waiting + advance beat; do not treat as intent-complete yet.
        if ok and timing.is_recurring:
            advance_beat(iid, step_num)
            try:
                brain.post_step_status(
                    iid,
                    step_num,
                    step_status=STEP_WAITING,
                    edge_node_id=eid,
                )
                step["status"] = STEP_WAITING
            except BrainError as e:
                log.warning(
                    "intent %s step %s: fail to re-arm waiting after beat: %s",
                    iid,
                    step_num,
                    e,
                )
            # One beat per tick to avoid tight loops.
            break

        # 4) Aggregate intent status from plan
        try:
            if not ok:
                brain.post_intent_status(
                    iid,
                    status="failed",
                    edge_node_id=eid,
                    message=message or f"step {step_num} failed",
                )
            elif all_steps_succeeded(plan):
                brain.post_intent_status(
                    iid,
                    status="succeeded",
                    edge_node_id=eid,
                    message="all steps succeeded",
                )
        except BrainError as e:
            log.warning("intent %s: fail to report intent terminal: %s", iid, e)

        # Only after terminal report may we search for the next local step.
        if not ok:
            break


def _advance_skipped_beats(plan: list[dict[str, Any]], intent_id: str, edge_id: str) -> None:
    """Skip interval/cron beats that are past the miss window (not yet started)."""
    now = BRAIN_CLOCK.now_ms()
    eid = edge_id.strip()
    for step in plan:
        assigned = str(step.get("assigned_edge_id") or "").strip()
        if assigned != eid:
            continue
        if step_status(step) != STEP_WAITING:
            continue
        timing = parse_execution_timing(step)
        if not timing.is_recurring:
            if timing.mode == MODE_DELAY:
                gate = timing_gate(timing, now, 0)
                if gate.terminal:
                    n = int(step.get("step") or 0)
                    log.warning(
                        "intent %s step %s: %s — mark failed (no catch-up)",
                        intent_id,
                        n,
                        gate.reason,
                    )
                    step["status"] = STEP_FAILED
            continue
        n = int(step.get("step") or 0)
        for _ in range(64):
            beat = get_beat(intent_id, n)
            gate = timing_gate(timing, now, beat)
            if gate.terminal:
                step["status"] = STEP_SUCCEEDED
                log.info(
                    "intent %s step %s: recurring series done (%s)",
                    intent_id,
                    n,
                    gate.reason,
                )
                break
            if gate.skip_beat:
                log.info(
                    "intent %s step %s: skip beat %s (%s)",
                    intent_id,
                    n,
                    beat,
                    gate.reason,
                )
                advance_beat(intent_id, n)
                continue
            break


def explain_ineligible(
    plan: list[dict[str, Any]],
    edge_id: str,
    *,
    intent_id: str = "",
) -> str:
    eid = edge_id.strip()
    now = BRAIN_CLOCK.now_ms()
    parts: list[str] = []
    ordered = sorted(plan, key=lambda s: int(s.get("step") or 0))
    for step in ordered:
        n = int(step.get("step") or 0)
        cap = str(step.get("capability") or "?")
        assigned = str(step.get("assigned_edge_id") or "").strip()
        st = step_status(step)
        if assigned != eid:
            parts.append(f"step{n}({cap}): assigned={assigned or '-'} != self")
            continue
        if st != STEP_WAITING:
            parts.append(f"step{n}({cap}): status={st} (need 0)")
            continue
        if not predecessors_all_succeeded(ordered, n):
            pending = [
                f"step{int(p.get('step') or 0)}={step_status(p)}"
                for p in ordered
                if int(p.get("step") or 0) < n and step_status(p) != STEP_SUCCEEDED
            ]
            parts.append(f"step{n}({cap}): waiting predecessors {pending}")
            continue
        timing = parse_execution_timing(step)
        beat = get_beat(intent_id, n) if intent_id else 0
        gate = timing_gate(timing, now, beat)
        if not gate.due:
            parts.append(f"step{n}({cap}): timing {gate.reason}")
            continue
        parts.append(f"step{n}({cap}): eligible")
    return " | ".join(parts) if parts else "empty plan"


def find_next_eligible_local_step(
    plan: list[dict[str, Any]],
    edge_id: str,
    *,
    intent_id: str = "",
) -> dict[str, Any] | None:
    eid = edge_id.strip()
    now = BRAIN_CLOCK.now_ms()
    ordered = sorted(plan, key=lambda s: int(s.get("step") or 0))
    for step in ordered:
        assigned = str(step.get("assigned_edge_id") or "").strip()
        if assigned != eid:
            continue
        n = int(step.get("step") or 0)
        st = step_status(step)
        if st != STEP_WAITING:
            continue
        if not predecessors_all_succeeded(ordered, n):
            continue
        timing = parse_execution_timing(step)
        beat = get_beat(intent_id, n) if intent_id else 0
        gate = timing_gate(timing, now, beat)
        if gate.due:
            return step
    return None


def predecessors_all_succeeded(plan: list[dict[str, Any]], step_num: int) -> bool:
    for step in plan:
        n = int(step.get("step") or 0)
        if n >= step_num:
            continue
        if step_status(step) != STEP_SUCCEEDED:
            return False
    return True


def all_steps_succeeded(plan: list[dict[str, Any]]) -> bool:
    if not plan:
        return False
    for s in plan:
        timing = parse_execution_timing(s)
        if timing.is_recurring and step_status(s) == STEP_WAITING:
            return False
        if step_status(s) != STEP_SUCCEEDED:
            return False
    return True


def step_status(step: dict[str, Any]) -> int:
    raw = step.get("status", step.get("step_status", STEP_WAITING))
    try:
        return int(raw)
    except (TypeError, ValueError):
        return STEP_WAITING


def normalize_plan(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        copy = dict(item)
        if "status" not in copy and "step_status" in copy:
            copy["status"] = copy["step_status"]
        if "status" not in copy:
            copy["status"] = STEP_WAITING
        copy.pop("delay_sec", None)
        et = copy.get("execution_timing")
        if isinstance(et, dict):
            et = dict(et)
            et.pop("delay_sec", None)
            copy["execution_timing"] = et
        out.append(copy)
    return out


def _hydrate_context(context: RuntimeContext, intent: dict[str, Any]) -> None:
    """Load Brain `ctx_param` + predecessor step outputs."""
    bag = intent.get("ctx_param")
    if isinstance(bag, dict):
        context.load(bag)
    plan = intent.get("execution_plan")
    if not isinstance(plan, list):
        return
    for step in plan:
        if not isinstance(step, dict):
            continue
        st = step_status(step)
        if st not in (STEP_SUCCEEDED, STEP_RUNNING):
            continue
        outs = step.get("outputs")
        if isinstance(outs, dict):
            context.load(outs)
        v = step.get("photo_url")
        if isinstance(v, str) and v.strip().lower().startswith("http"):
            context.load({"photo_url": v.strip()})


def _latest_cloud_photo_url(base: str = "http://115.190.153.53:8080") -> str | None:
    """Fallback when Brain has no context yet: pick newest file from photo host listing."""
    import re
    import urllib.request

    root = base.rstrip("/")
    try:
        with urllib.request.urlopen(f"{root}/", timeout=8) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        log.warning("latest cloud photo listing failed: %s", e)
        return None
    files = re.findall(
        r'href="([^"]+\.(?:jpg|jpeg|png|JPG|JPEG|PNG))"',
        html,
    )
    if not files:
        return None

    def sort_key(name: str) -> int:
        m = re.search(r"_(\d{10})_", name)
        return int(m.group(1)) if m else 0

    newest = sorted(files, key=sort_key)[-1]
    return f"{root}/{newest.lstrip('/')}"


def _ensure_photo_url(context: RuntimeContext) -> None:
    if context.get("photo_url"):
        return
    url = _latest_cloud_photo_url()
    if url:
        context.load({"photo_url": url})
        log.warning("context missing photo_url — using latest cloud photo %s", url)


def _execute_capability(
    cap: str,
    params: dict[str, str],
    config: Config,
) -> tuple[bool, str, dict[str, str]]:
    """Returns (ok, message, outputs). Params are already context-resolved."""
    if cap == "display.photo":
        photo_url = (
            params.get("photo_url") or ""
        ).strip()
        if not photo_url:
            return False, "missing photo_url (context)", {}
        try:
            msg = cast_photo(
                photo_url,
                display_base_url=config.cast_display_url,
                timeout_sec=config.display_http_timeout_sec,
            )
            return True, msg, {"photo_url": photo_url}
        except CastError as e:
            return False, str(e), {}
        except Exception as e:
            return False, f"{type(e).__name__}: {e}", {}
    if cap == "notify.speak":
        try:
            msg = speak_from_params(params)
            return True, msg, {}
        except NotifySpeakError as e:
            return False, str(e), {}
        except Exception as e:
            return False, f"{type(e).__name__}: {e}", {}
    return False, f"unsupported capability {cap or '(empty)'}", {}
