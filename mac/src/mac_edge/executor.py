"""Executor: step-level closed loop (report → run → report → find next)."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any

from mac_edge.brain_client import BrainClient, BrainError
from mac_edge.brain_time import BRAIN_CLOCK
from mac_edge.config import Config
from mac_edge.asset.manager import AssetManager
from mac_edge.asset.sdk import CapAsset
from mac_edge.asset.types import AssetError
from mac_edge.execution_timing import (
    MODE_DELAY,
    parse_execution_timing,
    planned_start_ms,
    timing_gate,
)
from mac_edge.plugins.chromecast_display import (
    CastError,
    photo_from_params,
    slideshow_from_params,
)
from mac_edge.plugins.xiaomi_tv_display import (
    XiaomiTvError,
    display_backend,
    photo_from_params as xiaomi_photo_from_params,
    slideshow_from_params as xiaomi_slideshow_from_params,
)
from mac_edge.plugins.pdf_display import (
    PdfDisplayError,
    open_from_params as pdf_display_open_from_params,
    page_from_params as pdf_display_page_from_params,
)
from mac_edge.capability_ads import composition_of, decomposes_to
from mac_edge.capability_availability import is_available
from mac_edge.plugins.clock_now import ClockNowError, now_from_params
from mac_edge.plugins.netease_music import NeteaseMusicError, run_from_params as music_from_params
from mac_edge.plugins.music_recognize import (
    MusicRecognizeError,
    run_from_params as music_recognize_from_params,
)
from mac_edge.plugins.math_calculate import MathCalculateError, calculate_from_params
from mac_edge.plugins.chat_smalltalk import ChatSmalltalkError, smalltalk_from_params
from mac_edge.plugins.asset_upload import AssetUploadError, upload_from_params
from mac_edge.plugins.voice_stream import VoiceStreamError, run_from_params as voice_stream_from_params
from mac_edge.plugins.video_live_stream import (
    VideoLiveStreamError,
    run_from_params as video_live_stream_from_params,
)
from mac_edge.plugins.gopro_camera import (
    GoProCameraError,
    capture_from_params,
    humanize_capture_error,
)
from mac_edge.plugins.hisense_ac import HisenseAcError, set_from_params as climate_set_from_params
from mac_edge.plugins.xiaomi_aquarium import (
    XiaomiAquariumError,
    set_from_params as aquarium_set_from_params,
)
from mac_edge.plugins.xiaomi_aio_printer import (
    XiaomiPrinterError,
    print_from_params as printer_print_from_params,
)
from mac_edge.plugins.file_convert import (
    FileConvertError,
    convert_from_params as file_convert_from_params,
)
from mac_edge.plugins.pdf_rotate import (
    PdfRotateError,
    rotate_from_params as pdf_rotate_from_params,
)
from mac_edge.plugins.pdf_to_images import (
    PdfToImagesError,
    images_from_params as pdf_to_images_from_params,
)
from mac_edge.plugins.web_scraper import (
    WebScraperError,
    scrape_from_params as web_scraper_from_params,
)
from mac_edge.plugins.xiaomi_lock import (
    XiaomiLockError,
    status_from_params as lock_status_from_params,
)
from mac_edge.plugins.livingroom_light import LivingRoomLightError, set_from_params
from mac_edge.plugins.notify_speak import NotifySpeakError, prefetch_from_params, speak_from_params
from mac_edge.plugins.xiaodu_speaker import XiaoduSpeakerError, speak_from_params as xiaodu_speak_from_params
from mac_edge.plugins.tv_game import GameLaunchError, launch_from_params
from mac_edge.plugins.voice_test.trial import VoiceTestError, run_trial_from_params
from mac_edge.plugins.query_content import QueryContentError, query_from_params
from mac_edge.plugins.search_images import SearchImagesError, search_from_params
from mac_edge.plugins.vision_ask import VisionAskError, ask_from_params
from mac_edge.plugins.vision_perceive import VisionPerceiveError, perceive_from_params
from mac_edge.plugins.point_to_character import (
    READING_STAGE_CAPS,
    PointToCharacterError,
    reading_stage_from_params,
)
from mac_edge.plugins.pronunciation_assess import (
    PronunciationAssessError,
    assess_from_params,
)
from mac_edge.runtime_context import (
    RuntimeContext,
    input_params_of,
    output_constrict_of,
    resolve_params,
    unresolved_var_name,
)
from mac_edge.timing_beats import advance_beat, get_beat

log = logging.getLogger("mac_edge.executor")

STEP_WAITING = 0
STEP_RUNNING = 1
STEP_SUCCEEDED = 2
STEP_FAILED = 3

EMPTY_PLAN_MSG = "execution_plan 为空，无法调度"

# (intent_id, step) currently inside _execute_capability on this process.
_EXECUTING_STEPS: set[tuple[str, int]] = set()
# Wall-clock start of the current local RUNNING attempt.
_STEP_STARTED_AT_MS: dict[tuple[str, int], int] = {}
_CAP_EXEC_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="cap-exec")

# Composite reading pipeline should fail faster than generic 5m wall clock.
_CAP_TIMEOUT_SEC: dict[str, float] = {
    "reading.point_to_character": 120.0,
    "music.cache": 360.0,
    "music.recognize": 90.0,
}


def _capability_timeout_sec(cap: str, config: Config) -> float:
    cid = str(cap or "").strip()
    if cid in _CAP_TIMEOUT_SEC:
        return max(30.0, min(float(_CAP_TIMEOUT_SEC[cid]), 3600.0))
    timeout = float(getattr(config, "capability_timeout_sec", 300.0) or 300.0)
    return max(30.0, min(timeout, 3600.0))

# Deadline-aware idle sleep: never longer than this, and never more than half
# the remaining time — so wakes get denser as exec_time approaches.
DEADLINE_SLEEP_CAP_SEC = 10.0
DEADLINE_SLEEP_MIN_SEC = 0.1
# Prefetch TTS when a timed speak is this far from due (ms).
_PREFETCH_SPEAK_WITHIN_MS = 25_000
_PREFETCH_SPEAK_MIN_REMAINING_MS = 1_500


def capability_timeout_msg(capability_id: str, timeout_sec: float) -> str:
    cap = (capability_id or "capability").strip() or "capability"
    sec = int(max(1.0, float(timeout_sec)))
    return f"{cap} 超时（>{sec}s），已回收"


def _step_key(intent_id: str, step_num: int) -> tuple[str, int]:
    return ((intent_id or "").strip(), int(step_num))


def _mark_step_started(intent_id: str, step_num: int, *, ts_ms: int | None = None) -> int:
    started = int(ts_ms) if ts_ms is not None else BRAIN_CLOCK.now_ms()
    _STEP_STARTED_AT_MS[_step_key(intent_id, step_num)] = started
    return started


def _clear_step_started(intent_id: str, step_num: int) -> None:
    _STEP_STARTED_AT_MS.pop(_step_key(intent_id, step_num), None)


def running_since_ms(
    intent: dict[str, Any] | None,
    intent_id: str,
    step_num: int,
) -> int | None:
    """Best-effort RUNNING start time: local tracker, then Brain step_log."""
    key = _step_key(intent_id, step_num)
    local = _STEP_STARTED_AT_MS.get(key)
    if local is not None:
        return int(local)
    if not isinstance(intent, dict):
        return None
    latest: int | None = None
    for entry in intent.get("step_log") or []:
        if not isinstance(entry, dict):
            continue
        try:
            if int(entry.get("step") or 0) != int(step_num):
                continue
            if int(entry.get("status") or -1) != STEP_RUNNING:
                continue
            ts = int(entry.get("ts") or 0)
        except (TypeError, ValueError):
            continue
        if ts <= 0:
            continue
        if latest is None or ts > latest:
            latest = ts
    return latest


def _execute_capability_bounded(
    cap: str,
    asset: CapAsset,
    *,
    params: dict[str, str],
    config: Config,
) -> tuple[bool, str, dict[str, Any]]:
    """Run capability with a wall-clock timeout; orphaned worker may still finish later."""
    timeout = _capability_timeout_sec(cap, config)
    fut = _CAP_EXEC_POOL.submit(
        _execute_capability,
        cap,
        asset,
        params=params,
        config=config,
    )
    try:
        return fut.result(timeout=timeout)
    except FuturesTimeoutError:
        msg = capability_timeout_msg(cap, timeout)
        log.error("capability timeout cap=%s limit_sec=%s", cap, int(timeout))
        return False, msg, {}


def sleep_sec_until_deadline(
    deadline_ms: int | None,
    *,
    default_interval_sec: float,
) -> float:
    """Compute next main-loop sleep.

    - No pending deadline → normal poll interval.
    - Past due → short spin.
    - Otherwise → min(10s, remaining/2), floored at 100ms.
    """
    if deadline_ms is None:
        return max(DEADLINE_SLEEP_MIN_SEC, float(default_interval_sec))
    remaining_ms = int(deadline_ms) - BRAIN_CLOCK.now_ms()
    if remaining_ms <= 0:
        return DEADLINE_SLEEP_MIN_SEC
    remaining_sec = remaining_ms / 1000.0
    return max(
        DEADLINE_SLEEP_MIN_SEC,
        min(DEADLINE_SLEEP_CAP_SEC, remaining_sec / 2.0),
    )


def fail_empty_plan_intent(
    intent: dict[str, Any],
    *,
    edge_id: str,
    brain: BrainClient | None,
) -> bool:
    """Post failed when execution_plan is empty. True if handled (skip further work)."""
    plan = intent.get("execution_plan")
    if isinstance(plan, list) and plan:
        return False
    wire = str(
        intent.get("intent_status") or intent.get("status") or ""
    ).strip().lower()
    if wire in ("succeeded", "failed"):
        return True
    iid = str(intent.get("id") or intent.get("intent_id") or "").strip()
    if not iid:
        return False
    posted = _try_post_intent_status(
        brain,
        iid,
        status="failed",
        edge_id=edge_id,
        message=EMPTY_PLAN_MSG,
    )
    log.warning(
        "intent %s empty plan → failed%s",
        iid,
        "" if posted else " (Brain unsynced)",
    )
    return True


def earliest_local_deadline_ms(
    intents: list[dict[str, Any]],
    edge_id: str,
) -> int | None:
    """Earliest planned_start among local WAITING steps that are not yet due.

    Returns ``now`` (via a due sentinel) when any local step is already due,
    so the caller sleeps only the minimum spin interval.
    """
    eid = (edge_id or "").strip()
    if not eid or not intents:
        return None
    now = BRAIN_CLOCK.now_ms()
    best: int | None = None
    for intent in intents:
        if not isinstance(intent, dict):
            continue
        iid = str(intent.get("id") or intent.get("intent_id") or "").strip()
        plan = normalize_plan(intent.get("execution_plan"))
        if not plan:
            continue
        ordered = sorted(plan, key=lambda s: int(s.get("step") or 0))
        for step in ordered:
            assigned = str(step.get("assigned_edge_id") or "").strip()
            if assigned != eid:
                continue
            n = int(step.get("step") or 0)
            if not _step_open_for_run(step, iid, n):
                continue
            if not predecessors_all_succeeded(ordered, n):
                continue
            timing = parse_execution_timing(step)
            beat = get_beat(iid, n) if iid else 0
            gate = timing_gate(timing, now, beat)
            if gate.due:
                return now
            planned = gate.planned_start
            if planned is None or planned <= now:
                continue
            if best is None or planned < best:
                best = planned
    return best


def prefetch_upcoming_speaks(
    intents: list[dict[str, Any]],
    edge_id: str,
) -> None:
    """Kick off TTS synthesize for local notify.speak steps nearing exec_time."""
    eid = (edge_id or "").strip()
    if not eid or not intents:
        return
    now = BRAIN_CLOCK.now_ms()
    for intent in intents:
        if not isinstance(intent, dict):
            continue
        iid = str(intent.get("id") or intent.get("intent_id") or "").strip()
        plan = normalize_plan(intent.get("execution_plan"))
        ordered = sorted(plan, key=lambda s: int(s.get("step") or 0))
        for step in ordered:
            assigned = str(step.get("assigned_edge_id") or "").strip()
            if assigned != eid:
                continue
            if str(step.get("capability") or "").strip() != "notify.speak":
                continue
            if step_status(step) != STEP_WAITING:
                continue
            n = int(step.get("step") or 0)
            if not predecessors_all_succeeded(ordered, n):
                continue
            timing = parse_execution_timing(step)
            beat = get_beat(iid, n) if iid else 0
            gate = timing_gate(timing, now, beat)
            planned = gate.planned_start
            if planned is None:
                continue
            remain = planned - now
            if remain > _PREFETCH_SPEAK_WITHIN_MS or remain < _PREFETCH_SPEAK_MIN_REMAINING_MS:
                continue
            try:
                params = resolve_params(input_params_of(step), RuntimeContext())
            except ValueError:
                # Unresolved $vars — skip prefetch; execute path will wait/retry.
                continue
            prefetch_from_params(params)


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

    from mac_edge.local_ledger import active as _ledger_active

    ledger = _ledger_active()
    if ledger is not None:
        intent = ledger.overlay_intent(intent)

    # Working copy of plan statuses so later finds in same tick see updates.
    plan = normalize_plan(intent.get("execution_plan"))
    if not plan:
        log.warning("intent %s: no execution_plan — fail", iid)
        _try_post_intent_status(
            brain,
            iid,
            status="failed",
            edge_id=eid,
            message=EMPTY_PLAN_MSG,
        )
        return

    # Same model as iOS: hydrate context from Brain, resolve $vars from context.
    context = RuntimeContext()
    asset_mgr = AssetManager(brain=brain, edge_id=eid)
    _hydrate_context(context, intent)
    if context.snapshot():
        log.info(
            "intent %s: context keys=%s",
            iid,
            ",".join(sorted(context.snapshot())),
        )
    else:
        # Cross-edge outputs arrive via peek→ledger merge. Skip Brain detail when
        # the ledger owns this intent so a Brain outage cannot stall execution.
        if ledger is None:
            detail = brain.fetch_intent_detail(iid)
            if isinstance(detail, dict) and detail:
                _hydrate_context(context, detail)
                _hydrate_context(context, intent)
                if context.snapshot():
                    log.info(
                        "intent %s: context keys after detail refresh=%s",
                        iid,
                        ",".join(sorted(context.snapshot())),
                    )

    first = True
    posted_terminal = False
    while True:
        # Advance past interval/cron beats that already missed their window.
        # Also reclaim stale RUNNING/FAILED and close exhausted series on Brain.
        _advance_skipped_beats(plan, iid, eid, brain=brain, intent=intent, config=config)

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
        # AssetRef identities stay in params; Capability resolves via CapAsset SDK.
        try:
            params = resolve_params(input_params_of(step), context)
        except ValueError as e:
            var_name = unresolved_var_name(e)
            if var_name and should_wait_for_unresolved(plan, step_num, var_name):
                log.warning(
                    "intent %s step %s: %s — skip this tick (wait for context)",
                    iid,
                    step_num,
                    e,
                )
                break
            fail_msg = (
                f"缺少上下文变量 ${var_name}，无法执行"
                if var_name
                else str(e)
            )
            log.error(
                "intent %s step %s: %s — fail (no producer still running)",
                iid,
                step_num,
                fail_msg,
            )
            step["status"] = STEP_FAILED
            step["msg"] = fail_msg
            _try_post_step_status(
                brain,
                iid,
                step_num,
                status=STEP_FAILED,
                edge_id=eid,
                msg=fail_msg,
            )
            _try_post_intent_status(
                brain,
                iid,
                status="failed",
                edge_id=eid,
                message=fail_msg,
            )
            posted_terminal = True
            break

        # Local RUNNING immediately. Sync flush to Brain before long I/O so
        # clients leave intent_dispatched without waiting minutes in the dark.
        step["status"] = STEP_RUNNING
        if ledger is not None:
            ledger.set_step_status(
                iid, step_num, STEP_RUNNING, ts_ms=BRAIN_CLOCK.now_ms()
            )
            ledger.set_intent_status(iid, "running")
            _flush_ledger_to_brain(
                ledger,
                brain,
                eid,
                label=f"running {iid}/{step_num}",
            )
        else:
            step_ep, intent_ep = brain.begin_running_reports(iid, step_num)
            brain.post_step_status_bg(
                iid,
                step_num,
                step_status=STEP_RUNNING,
                edge_node_id=eid,
                epoch=step_ep,
                ts_ms=BRAIN_CLOCK.now_ms(),
            )
            brain.post_intent_status_bg(
                iid,
                status="running",
                edge_node_id=eid,
                message=f"executing {cap}",
                epoch=intent_ep,
            )

        _EXECUTING_STEPS.add((iid, step_num))
        _mark_step_started(iid, step_num)
        cap_asset = CapAsset(manager=asset_mgr, intent_id=iid, step_num=step_num)
        try:
            avail = is_available(cap, config=config)
            if not avail.ok:
                ok, message, outputs = False, avail.msg, {}
                log.warning(
                    "intent %s step %s: is_available failed (%s): %s",
                    iid,
                    step_num,
                    cap,
                    message,
                )
            else:
                if cap == "notify.speak":
                    ctx = intent.get("source_context")
                    if isinstance(ctx, dict):
                        params = dict(params)
                        params["delivery_ingress"] = str(ctx.get("ingress") or "").strip()
                        params["delivery_participant_id"] = str(
                            ctx.get("input_participant_id") or ctx.get("device_id") or ""
                        ).strip()
                ok, message, outputs = _execute_capability_bounded(
                    cap, cap_asset, params=params, config=config
                )
        except Exception as e:
            ok, message, outputs = False, f"{type(e).__name__}: {e}", {}
            log.exception("intent %s step %s: capability crashed (%s)", iid, step_num, cap)
        finally:
            _EXECUTING_STEPS.discard((iid, step_num))
            _clear_step_started(iid, step_num)
        if not ok:
            message = (message or "").strip() or f"{cap} 失败"
            step["msg"] = message
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

        if ledger is None:
            # Drop in-flight RUNNING posts so a late reply cannot overwrite terminal.
            brain.invalidate_running_reports(iid, step_num)

        # Recurring: one beat done (ok or fail) → arm next; do not fail the series.
        # POST 2/3 so step_log has the beat, then immediately re-arm 0.
        if timing.is_recurring:
            beat_status = STEP_SUCCEEDED if ok else STEP_FAILED
            step["status"] = beat_status
            posted = _try_post_step_status(
                brain,
                iid,
                step_num,
                status=beat_status,
                edge_id=eid,
                outputs=outputs or None if ok else None,
                msg=None if ok else message,
            )
            if ok:
                log.info("intent %s step %s OK (%s): %s", iid, step_num, cap, message)
            else:
                log.error(
                    "intent %s step %s FAIL beat (%s): %s — series continues",
                    iid,
                    step_num,
                    cap,
                    message,
                )
                if not posted:
                    log.warning(
                        "intent %s step %s: beat fail not on Brain; still re-arm waiting",
                        iid,
                        step_num,
                    )
            advance_beat(iid, step_num)
            skipped = skip_passed_interval_triggers(
                iid, step_num, timing, BRAIN_CLOCK.now_ms()
            )
            gate = timing_gate(timing, BRAIN_CLOCK.now_ms(), get_beat(iid, step_num))
            if gate.terminal or all_steps_succeeded(plan, intent_id=iid):
                log.info(
                    "intent %s step %s: recurring series done after beat next_beat=%s skipped_passed=%s",
                    iid,
                    step_num,
                    get_beat(iid, step_num),
                    skipped,
                )
                _try_post_intent_status(
                    brain,
                    iid,
                    status="succeeded",
                    edge_id=eid,
                    message="interval/cron series complete",
                )
            else:
                _rearm_recurring_waiting(brain, iid, eid, step, step_num)
                log.info(
                    "intent %s step %s: re-arm waiting after beat (%s) next_beat=%s skipped_passed=%s",
                    iid,
                    step_num,
                    "ok" if ok else "fail",
                    get_beat(iid, step_num),
                    skipped,
                )
            break

        # Always close this beat locally so a Brain blip cannot leave status=1.
        step["status"] = final
        posted = _try_post_step_status(
            brain,
            iid,
            step_num,
            status=final,
            edge_id=eid,
            outputs=outputs or None,
            msg=None if ok else message,
        )
        if ok:
            log.info("intent %s step %s OK (%s): %s", iid, step_num, cap, message)
        else:
            log.error("intent %s step %s FAIL (%s): %s", iid, step_num, cap, message)
            if not posted:
                log.warning(
                    "intent %s step %s: terminal %s not on Brain (local unsynced)",
                    iid,
                    step_num,
                    final,
                )

        if not ok and not plan_has_remaining_work(plan, intent_id=iid):
            _try_post_intent_status(
                brain,
                iid,
                status="failed",
                edge_id=eid,
                message=message or f"step {step_num} failed",
            )
            posted_terminal = True

        if not ok:
            break

    wire = str(
        intent.get("intent_status") or intent.get("status") or ""
    ).strip().lower()
    finalize_intent_from_plan(
        brain,
        iid,
        eid,
        plan,
        current_wire=wire,
        skip_failed=posted_terminal,
    )


def finalize_intent_from_plan(
    brain: BrainClient | None,
    intent_id: str,
    edge_id: str,
    plan: list[dict[str, Any]],
    *,
    current_wire: str = "",
    skip_failed: bool = False,
) -> None:
    """Post terminal intent status when the plan has no remaining work."""
    if not plan:
        return
    wire = (current_wire or "").strip().lower()
    if wire in ("succeeded", "failed"):
        return

    if all_steps_succeeded(plan, intent_id=intent_id):
        _try_post_intent_status(
            brain,
            intent_id,
            status="succeeded",
            edge_id=edge_id,
            message="all steps complete",
        )
        log.info("intent %s → succeeded (all steps complete)", intent_id)
        return

    if skip_failed:
        return

    if not plan_has_remaining_work(plan, intent_id=intent_id):
        if any(step_status(s) == STEP_FAILED for s in plan):
            msg = _terminal_fail_message(plan)
            _try_post_intent_status(
                brain,
                intent_id,
                status="failed",
                edge_id=edge_id,
                message=msg,
            )
            log.info("intent %s → failed (%s)", intent_id, msg)


def _terminal_fail_message(plan: list[dict[str, Any]]) -> str:
    for step in plan:
        if step_status(step) != STEP_FAILED:
            continue
        msg = str(step.get("msg") or "").strip()
        if msg:
            return msg
    return "step failed"


def skip_passed_interval_triggers(
    intent_id: str,
    step_num: int,
    timing: Any,
    now_ms: int,
) -> int:
    """After a beat, do not catch up triggers whose planned_start is already past.

    Times come from this step's execution_timing (interval_sec / cron next),
    never a hardcoded 1 minute. The next future slot still runs.
    """
    if not getattr(timing, "is_recurring", False):
        return 0
    skipped = 0
    for _ in range(64):
        beat = get_beat(intent_id, step_num)
        if timing.count is not None and beat >= timing.count:
            return skipped
        planned = planned_start_ms(timing, beat)
        if planned is None or planned > now_ms:
            return skipped
        log.info(
            "intent %s step %s: skip beat %s planned_start=%s (passed, no catch-up)",
            intent_id,
            step_num,
            beat,
            planned,
        )
        advance_beat(intent_id, step_num)
        skipped += 1
    return skipped


def _flush_ledger_to_brain(
    ledger: Any,
    brain: BrainClient | None,
    edge_id: str,
    *,
    label: str,
) -> bool:
    """Best-effort synchronous ledger → Brain replay (RUNNING must not lag)."""
    if brain is None:
        return False
    try:
        posted = ledger.flush_to_brain(brain, edge_id)
        if posted:
            log.info("ledger: sync flush %s posted=%s", label, posted)
        return posted > 0
    except Exception as e:
        log.warning("ledger: sync flush %s failed: %s", label, e)
        return False


def _try_post_step_status(
    brain: BrainClient | None,
    intent_id: str,
    step_num: int,
    *,
    status: int,
    edge_id: str,
    outputs: dict[str, Any] | None = None,
    attempts: int = 2,
    ts_ms: int | None = None,
    msg: str | None = None,
) -> bool:
    from mac_edge.local_ledger import active as _ledger_active

    ledger = _ledger_active()
    event_ts = int(ts_ms) if ts_ms is not None else BRAIN_CLOCK.now_ms()
    note = str(msg).strip() if msg else None
    if ledger is not None:
        ledger.set_step_status(
            intent_id,
            step_num,
            status,
            outputs=outputs,
            ts_ms=event_ts,
            msg=note,
        )
        if brain is None:
            return False
        return ledger.flush_to_brain(brain, edge_id) > 0
    if brain is None:
        return False
    last: BrainError | None = None
    for i in range(max(1, attempts)):
        try:
            brain.post_step_status(
                intent_id,
                step_num,
                step_status=status,
                edge_node_id=edge_id,
                outputs=outputs,
                ts_ms=event_ts,
                msg=note,
            )
            return True
        except BrainError as e:
            last = e
            log.warning(
                "intent %s step %s: post status=%s attempt %s failed: %s",
                intent_id,
                step_num,
                status,
                i + 1,
                e,
            )
    if last is not None:
        log.warning(
            "intent %s step %s: give up posting status=%s (local unsynced): %s",
            intent_id,
            step_num,
            status,
            last,
        )
    return False


def _try_post_intent_status(
    brain: BrainClient | None,
    intent_id: str,
    *,
    status: str,
    edge_id: str,
    message: str = "",
) -> bool:
    from mac_edge.local_ledger import active as _ledger_active

    ledger = _ledger_active()
    if ledger is not None:
        ledger.set_intent_status(intent_id, status)
    if brain is None:
        return False
    try:
        brain.post_intent_status(
            intent_id,
            status=status,
            edge_node_id=edge_id,
            message=message,
        )
        if ledger is not None:
            ledger.mark_intent_synced(intent_id, status=status)
        return True
    except BrainError as e:
        log.warning(
            "intent %s: post intent status=%s failed (local unsynced): %s",
            intent_id,
            status,
            e,
        )
        return False


def _rearm_recurring_waiting(
    brain: BrainClient | None,
    intent_id: str,
    edge_id: str,
    step: dict[str, Any],
    step_num: int,
) -> None:
    step["status"] = STEP_WAITING
    _try_post_step_status(
        brain,
        intent_id,
        step_num,
        status=STEP_WAITING,
        edge_id=edge_id,
    )


def _advance_skipped_beats(
    plan: list[dict[str, Any]],
    intent_id: str,
    edge_id: str,
    *,
    brain: BrainClient | None = None,
    intent: dict[str, Any] | None = None,
    config: Config | None = None,
) -> None:
    """Skip interval/cron beats past the miss window; reclaim stale RUNNING/FAILED.

    Live RUNNING (this process inside execute) is busy, not missed — unless it
    exceeds capability_timeout_sec (wall clock), in which case we fail+report.
    Stale RUNNING after restart, or FAILED left from a beat, can skip and re-arm.
    Skip late unstarted beats until the next wait/due slot; do not catch up.
    """
    now = BRAIN_CLOCK.now_ms()
    eid = edge_id.strip()
    default_timeout = (
        float(getattr(config, "capability_timeout_sec", 300.0) or 300.0)
        if config is not None
        else 300.0
    )
    default_timeout = max(30.0, min(default_timeout, 3600.0))
    for step in plan:
        assigned = str(step.get("assigned_edge_id") or "").strip()
        if assigned != eid:
            continue
        n = int(step.get("step") or 0)
        st = step_status(step)
        cap = str(step.get("capability") or "").strip()
        timeout_sec = (
            _capability_timeout_sec(cap, config) if config is not None else default_timeout
        )
        timeout_ms = int(timeout_sec * 1000)
        # Wall-clock reclaim for stuck RUNNING (one-shot or recurring beat).
        if st == STEP_RUNNING:
            since = running_since_ms(intent, intent_id, n)
            if not _is_locally_executing(intent_id, n) and since is None:
                log.warning(
                    "intent %s step %s: orphan RUNNING — reset to waiting",
                    intent_id,
                    n,
                )
                step["status"] = STEP_WAITING
                continue
            if since is not None and now - since >= timeout_ms:
                fail_msg = capability_timeout_msg(cap, timeout_sec)
                log.error(
                    "intent %s step %s: %s (running_for_ms=%s)",
                    intent_id,
                    n,
                    fail_msg,
                    now - since,
                )
                step["status"] = STEP_FAILED
                step["msg"] = fail_msg
                _clear_step_started(intent_id, n)
                _EXECUTING_STEPS.discard(_step_key(intent_id, n))
                _try_post_step_status(
                    brain,
                    intent_id,
                    n,
                    status=STEP_FAILED,
                    edge_id=eid,
                    msg=fail_msg,
                )
                if brain is not None:
                    finalize_intent_from_plan(
                        brain,
                        intent_id,
                        eid,
                        plan,
                        current_wire="running",
                    )
                continue
            if _is_locally_executing(intent_id, n):
                continue
        timing = parse_execution_timing(step)
        if not timing.is_recurring:
            if timing.mode == MODE_DELAY and st == STEP_WAITING:
                gate = timing_gate(timing, now, 0)
                if gate.terminal:
                    log.warning(
                        "intent %s step %s: %s — mark failed (no catch-up)",
                        intent_id,
                        n,
                        gate.reason,
                    )
                    step["status"] = STEP_FAILED
                    _try_post_step_status(
                        brain,
                        intent_id,
                        n,
                        status=STEP_FAILED,
                        edge_id=eid,
                        msg=gate.reason,
                    )
            continue
        # Recurring SUCCEEDED is often a beat result, not series-done.
        for _ in range(64):
            beat = get_beat(intent_id, n)
            gate = timing_gate(timing, now, beat)
            if gate.terminal:
                step["status"] = STEP_SUCCEEDED
                _try_post_step_status(
                    brain,
                    intent_id,
                    n,
                    status=STEP_SUCCEEDED,
                    edge_id=eid,
                )
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
        st = step_status(step)
        if st == STEP_SUCCEEDED:
            gate = timing_gate(timing, now, get_beat(intent_id, n))
            if gate.terminal:
                continue
        gate = timing_gate(timing, now, get_beat(intent_id, n))
        # FAILED / beat-SUCCEEDED must return to WAITING or the series looks done.
        # Stale RUNNING that is not due should not look busy until the next slot.
        if st in (STEP_FAILED, STEP_SUCCEEDED) or (
            st == STEP_RUNNING and not gate.due
        ):
            log.info(
                "intent %s step %s: reclaim status=%s → waiting (beat=%s %s)",
                intent_id,
                n,
                st,
                get_beat(intent_id, n),
                gate.reason,
            )
            _rearm_recurring_waiting(brain, intent_id, eid, step, n)



def unique_assigned_edge_ids(plan: list[dict[str, Any]]) -> list[str]:
    """Distinct non-empty per-step assigned_edge_id values, first-seen order."""
    seen: list[str] = []
    for step in plan:
        if not isinstance(step, dict):
            continue
        eid = str(
            step.get("assigned_edge_id") or step.get("assignedEdgeId") or ""
        ).strip()
        if eid and eid not in seen:
            seen.append(eid)
    return seen


def should_wait_for_unresolved(
    plan: list[dict[str, Any]],
    step_num: int,
    var_name: str,
) -> bool:
    """True only if an earlier step that publishes this var is still waiting/running.

    No producer, or all producers already terminal → caller must fail the step.
    """
    root = (var_name or "").strip().split(".", 1)[0]
    if not root:
        return False
    producers: list[dict[str, Any]] = []
    for step in plan:
        if not isinstance(step, dict):
            continue
        n = int(step.get("step") or 0)
        if n <= 0 or n >= int(step_num):
            continue
        constrict = output_constrict_of(step)
        if root in constrict or (var_name or "") in constrict:
            producers.append(step)
    if not producers:
        return False
    for prod in producers:
        if step_status(prod) in (STEP_WAITING, STEP_RUNNING):
            return True
    return False


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
        if not _step_open_for_run(step, intent_id, n):
            parts.append(f"step{n}({cap}): status={st} (need 0)")
            continue
        timing = parse_execution_timing(step)
        if not predecessors_all_succeeded(ordered, n):
            pending = [
                f"step{int(p.get('step') or 0)}={step_status(p)}"
                for p in ordered
                if int(p.get("step") or 0) < n and step_status(p) != STEP_SUCCEEDED
            ]
            parts.append(f"step{n}({cap}): waiting predecessors {pending}")
            continue
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
        if not _step_open_for_run(step, intent_id, n):
            continue
        # Both gates: predecessors (all status=2) AND timing due.
        # delay/interval never skip the predecessor gate — same-key $photo_url
        # last-wins only works if this display waits for its paired capture.
        if not predecessors_all_succeeded(ordered, n):
            continue
        timing = parse_execution_timing(step)
        beat = get_beat(intent_id, n) if intent_id else 0
        gate = timing_gate(timing, now, beat)
        if gate.due:
            return step
    return None


def _is_locally_executing(intent_id: str, step_num: int) -> bool:
    iid = (intent_id or "").strip()
    if not iid:
        return False
    return (iid, int(step_num)) in _EXECUTING_STEPS


def _step_open_for_run(step: dict[str, Any], intent_id: str, step_num: int) -> bool:
    """WAITING, or stale RUNNING/FAILED on a recurring step this process is not running.

    One-shot RUNNING is in-flight (or just finished while Brain still shows
    running). Re-running it would speak/act twice. Timeout reclaim in
    ``_advance_skipped_beats`` can fail a stuck one-shot; until then skip.
    """
    st = step_status(step)
    if st == STEP_WAITING:
        return True
    if _is_locally_executing(intent_id, step_num):
        return False
    if st == STEP_RUNNING:
        if parse_execution_timing(step).is_recurring:
            return True
        # Crash / restart left RUNNING in the local ledger but this worker
        # is idle — reopen so dispatch does not stall at intent_dispatched.
        log.warning(
            "intent %s step %s: stale one-shot RUNNING — reopen for run",
            intent_id,
            step_num,
        )
        step["status"] = STEP_WAITING
        return True
    if st == STEP_FAILED and parse_execution_timing(step).is_recurring:
        return True
    return False


def predecessors_all_succeeded(plan: list[dict[str, Any]], step_num: int) -> bool:
    """True iff every step < N has status=2. Timing mode does not bypass this."""
    for step in plan:
        n = int(step.get("step") or 0)
        if n >= step_num:
            continue
        if step_status(step) != STEP_SUCCEEDED:
            return False
    return True


def _step_permanently_blocked(plan: list[dict[str, Any]], step: dict[str, Any]) -> bool:
    """Later steps cannot run once any predecessor has failed (status=3)."""
    if step_status(step) != STEP_WAITING:
        return False
    n = int(step.get("step") or 0)
    for pred in plan:
        pn = int(pred.get("step") or 0)
        if pn >= n:
            continue
        st = step_status(pred)
        if st == STEP_FAILED:
            return True
        if st == STEP_WAITING and _step_permanently_blocked(plan, pred):
            return True
    return False


def plan_has_remaining_work(
    plan: list[dict[str, Any]], *, intent_id: str = ""
) -> bool:
    """True if a waiting/running step can still succeed (no failed predecessor).

    A failed or just-succeeded interval/cron beat is not the end of the series.
    """
    now = BRAIN_CLOCK.now_ms()
    for step in plan:
        st = step_status(step)
        timing = parse_execution_timing(step)
        if timing.is_recurring:
            n = int(step.get("step") or 0)
            beat = get_beat(intent_id, n) if intent_id else 0
            gate = timing_gate(timing, now, beat)
            if not gate.terminal:
                return True
            continue
        if st == STEP_RUNNING:
            return True
        if st == STEP_WAITING and not _step_permanently_blocked(plan, step):
            return True
    return False


def all_steps_succeeded(
    plan: list[dict[str, Any]], *, intent_id: str = ""
) -> bool:
    if not plan:
        return False
    now = BRAIN_CLOCK.now_ms()
    for s in plan:
        timing = parse_execution_timing(s)
        if timing.is_recurring:
            n = int(s.get("step") or 0)
            beat = get_beat(intent_id, n) if intent_id else 0
            gate = timing_gate(timing, now, beat)
            if not gate.terminal:
                return False
            continue
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
            et.pop("delaySec", None)
            legacy_cron = et.pop("cron", None)
            if not str(et.get("cron_expr") or "").strip() and legacy_cron is not None:
                expr = str(legacy_cron).strip()
                if expr:
                    et["cron_expr"] = expr
            if "end_time" not in et and "end_exec_time" in et:
                et["end_time"] = et.pop("end_exec_time")
            else:
                et.pop("end_exec_time", None)
            copy["execution_timing"] = et
        out.append(copy)
    return out


def _load_output_bag(context: RuntimeContext, bag: Any) -> None:
    if isinstance(bag, dict):
        context.load(bag)


def _is_context_output(constrict: dict[str, Any], key: str) -> bool:
    meta = constrict.get(key) if isinstance(constrict, dict) else None
    if not isinstance(meta, dict):
        return False
    return str(meta.get("data_dest") or "").strip().lower() == "context"


def _load_producer_bag(
    context: RuntimeContext, bag: Any, constrict: dict[str, Any]
) -> None:
    """Load only keys declared as context outputs (skip display.photo echo)."""
    if not isinstance(bag, dict) or not isinstance(constrict, dict) or not constrict:
        return
    filtered: dict[str, Any] = {}
    for key, value in bag.items():
        if _is_context_output(constrict, str(key)):
            filtered[str(key)] = value
    if filtered:
        context.load(filtered)


def _plan_step_by_num(plan: list[Any], num: int) -> dict[str, Any] | None:
    for step in plan:
        if isinstance(step, dict) and int(step.get("step") or 0) == num:
            return step
    return None


def _step_outputs_items(raw: Any) -> list[tuple[int, dict[str, Any]]]:
    """Production peek/detail: `step_outputs` is `{ "1": {photo_url, …}, … }`."""
    if not isinstance(raw, dict):
        return []
    items: list[tuple[int, dict[str, Any]]] = []
    for key, bag in raw.items():
        if not isinstance(bag, dict):
            continue
        try:
            num = int(key)
        except (TypeError, ValueError):
            continue
        items.append((num, bag))
    items.sort(key=lambda pair: pair[0])
    return items


def _hydrate_context(context: RuntimeContext, intent: dict[str, Any]) -> None:
    """Load Brain ctx_param plus predecessor *producer* outputs (not display echoes)."""
    for key in ("ctx_param", "context", "outputs"):
        _load_output_bag(context, intent.get(key))
    plan_raw = intent.get("execution_plan")
    plan: list[Any] = plan_raw if isinstance(plan_raw, list) else []
    for num, bag in _step_outputs_items(intent.get("step_outputs")):
        step = _plan_step_by_num(plan, num)
        _load_producer_bag(context, bag, output_constrict_of(step or {}))
    for step in plan:
        if not isinstance(step, dict):
            continue
        st = step_status(step)
        if st not in (STEP_SUCCEEDED, STEP_RUNNING):
            continue
        constrict = output_constrict_of(step)
        _load_producer_bag(context, step.get("outputs"), constrict)


def _composite_upload_failure_msg(msg: str) -> str:
    text = str(msg or "").strip() or "上传失败"
    if text.startswith("拍照成功"):
        return text
    if "上传" in text or "upload" in text.lower():
        return f"拍照成功，照片已保存在本机；但{text}"
    return f"拍照成功，照片已保存在本机；但上传失败：{text}"


def _execute_composite(
    cap: str,
    asset: CapAsset,
    *,
    params: dict[str, str],
    config: Config,
) -> tuple[bool, str, dict[str, Any]]:
    """Run decomposes_to atomics on this Runtime; report one step to Brain."""
    parts = decomposes_to(cap)
    if not parts:
        return False, f"{cap} 缺少 decomposes_to", {}
    merged: dict[str, Any] = {}
    last_msg = ""
    capture_ok = False
    params_in = dict(params or {})
    for atom in parts:
        if composition_of(atom) == "composite":
            return False, f"{cap} 的 decomposes_to 不能再嵌套 composite（{atom}）", {}
        atom_params = dict(params_in)
        has_asset = atom_params.get("asset_ref") is not None or merged.get("asset_ref") is not None
        has_capture = (
            atom_params.get("capture_ref") is not None or merged.get("capture_ref") is not None
        )
        if atom == "camera.capture" and (has_asset or has_capture):
            continue
        if atom == "asset.upload" and has_asset:
            continue
        # asset_ref: a prior atom may emit a smaller/different asset than the
        # composite's original input (reading.detect_finger emits a finger crop
        # that ocr/rank should read instead of the full photo). So when merged
        # carries an asset_ref, it overrides params_in — not just fills None.
        # Other keys (finger/chars/full_image_shape) stay fill-if-None so a
        # caller-supplied value isn't silently replaced by a re-derived one.
        if merged.get("asset_ref") is not None:
            atom_params["asset_ref"] = merged["asset_ref"]
        for key in ("capture_ref", "finger", "chars", "full_image_shape"):
            if atom_params.get(key) is None and merged.get(key) is not None:
                atom_params[key] = merged[key]
        ok, message, outputs = _execute_capability(
            atom, asset, params=atom_params, config=config
        )
        if not ok:
            if capture_ok:
                return False, _composite_upload_failure_msg(message), {}
            return False, message, {}
        if atom == "camera.capture":
            capture_ok = True
        if isinstance(outputs, dict):
            merged.update(outputs)
        last_msg = message
    hide = {
        "capture_ref",
        "finger",
        "chars",
        "blocks",
        "landmarks",
        "timing",
        "ocr_blocks",
        "char_boxes",
        "candidates",
        "top3",
        "replay",
        "debug_png_base64",
        "crop_origin",
        "full_image_shape",
    }
    out = {k: v for k, v in merged.items() if k not in hide}
    return True, last_msg, out


def _execute_capability(
    cap: str,
    asset: CapAsset,
    *,
    params: dict[str, str],
    config: Config,
) -> tuple[bool, str, dict[str, Any]]:
    """Returns (ok, message, outputs).

    ``asset`` is the Runtime SDK Asset Manager session for this step.
    Params hold non-asset fields + AssetRef identities — never photo_url as identity.
    """
    if composition_of(cap) == "composite":
        return _execute_composite(cap, asset, params=params, config=config)
    if cap == "game.launch":
        try:
            msg, outputs = launch_from_params(params)
            return True, msg, outputs
        except GameLaunchError as e:
            return False, str(e), {}
        except Exception as e:
            return False, f"{type(e).__name__}: {e}", {}
    if cap == "display.photo":
        try:
            if display_backend() == "xiaomi":
                msg, outputs = xiaomi_photo_from_params(
                    params,
                    asset=asset,
                    timeout_sec=config.display_http_timeout_sec,
                )
            else:
                msg, outputs = photo_from_params(
                    params,
                    asset=asset,
                    display_base_url=config.cast_display_url,
                    timeout_sec=config.display_http_timeout_sec,
                )
            return True, msg, outputs
        except (CastError, XiaomiTvError, AssetError) as e:
            return False, str(e), {}
        except Exception as e:
            return False, f"{type(e).__name__}: {e}", {}
    if cap == "display.slideshow":
        try:
            if display_backend() == "xiaomi":
                msg, outputs = xiaomi_slideshow_from_params(
                    params,
                    asset=asset,
                    timeout_sec=config.display_http_timeout_sec,
                )
            else:
                msg, outputs = slideshow_from_params(
                    params,
                    asset=asset,
                    display_base_url=config.cast_display_url,
                    timeout_sec=config.display_http_timeout_sec,
                )
            return True, msg, outputs
        except (CastError, XiaomiTvError, AssetError) as e:
            return False, str(e), {}
        except Exception as e:
            return False, f"{type(e).__name__}: {e}", {}
    if cap == "display.pdf":
        try:
            msg, outputs = pdf_display_open_from_params(
                params,
                asset=asset,
                display_base_url=config.cast_display_url,
                timeout_sec=config.display_http_timeout_sec,
            )
            return True, msg, outputs
        except (PdfDisplayError, CastError, XiaomiTvError, AssetError) as e:
            return False, str(e), {}
        except Exception as e:
            return False, f"{type(e).__name__}: {e}", {}
    if cap == "display.pdf.page":
        try:
            msg, outputs = pdf_display_page_from_params(
                params,
                asset=asset,
                display_base_url=config.cast_display_url,
                timeout_sec=config.display_http_timeout_sec,
            )
            return True, msg, outputs
        except (PdfDisplayError, CastError, XiaomiTvError, AssetError) as e:
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
    if cap == "printer.print":
        try:
            msg, outputs = printer_print_from_params(params, asset=asset)
            return True, msg, outputs
        except (XiaomiPrinterError, AssetError) as e:
            return False, str(e), {}
        except Exception as e:
            return False, f"{type(e).__name__}: {e}", {}
    if cap == "file.convert":
        try:
            msg, outputs = file_convert_from_params(params, asset=asset)
            return True, msg, outputs
        except (FileConvertError, AssetError) as e:
            return False, str(e), {}
        except Exception as e:
            return False, f"{type(e).__name__}: {e}", {}
    if cap == "pdf.rotate":
        try:
            msg, outputs = pdf_rotate_from_params(params, asset=asset)
            return True, msg, outputs
        except (PdfRotateError, AssetError) as e:
            return False, str(e), {}
        except Exception as e:
            return False, f"{type(e).__name__}: {e}", {}
    if cap == "pdf.to_images":
        try:
            msg, outputs = pdf_to_images_from_params(params, asset=asset)
            return True, msg, outputs
        except (PdfToImagesError, AssetError) as e:
            return False, str(e), {}
        except Exception as e:
            return False, f"{type(e).__name__}: {e}", {}
    if cap == "web.scraper":
        try:
            msg, outputs = web_scraper_from_params(params, asset=asset)
            return True, msg, outputs
        except (WebScraperError, AssetError) as e:
            return False, str(e), {}
        except Exception as e:
            return False, f"{type(e).__name__}: {e}", {}
    if cap == "xiaodu.speak":
        try:
            msg = xiaodu_speak_from_params(params)
            return True, msg, {}
        except XiaoduSpeakerError as e:
            return False, str(e), {}
        except Exception as e:
            return False, f"{type(e).__name__}: {e}", {}
    if cap == "voicewakeup.echo":
        try:
            msg, outputs = echo_from_params(params)
            return True, msg, outputs
        except VoiceWakeupEchoError as e:
            return False, str(e), {}
        except Exception as e:
            return False, f"{type(e).__name__}: {e}", {}
    if cap == "vision.perceive":
        try:
            msg, outputs = perceive_from_params(
                params,
                asset=asset,
                timeout_sec=max(60.0, float(config.display_http_timeout_sec)),
            )
            return True, msg, outputs
        except (VisionPerceiveError, AssetError) as e:
            return False, str(e), {}
        except Exception as e:
            return False, f"{type(e).__name__}: {e}", {}
    if cap == "vision.ask":
        try:
            msg, outputs = ask_from_params(
                params,
                asset=asset,
                timeout_sec=max(60.0, float(config.display_http_timeout_sec)),
            )
            return True, msg, outputs
        except (VisionAskError, AssetError) as e:
            return False, str(e), {}
        except Exception as e:
            return False, f"{type(e).__name__}: {e}", {}
    if cap in READING_STAGE_CAPS:
        try:
            msg, outputs = reading_stage_from_params(
                cap,
                params,
                asset=asset,
                timeout_sec=max(120.0, float(config.display_http_timeout_sec)),
            )
            return True, msg, outputs
        except (PointToCharacterError, AssetError) as e:
            return False, str(e), {}
        except Exception as e:
            return False, f"{type(e).__name__}: {e}", {}
    if cap == "pronunciation.assess":
        try:
            msg, outputs = assess_from_params(
                params,
                asset=asset,
                timeout_sec=max(180.0, float(config.display_http_timeout_sec)),
            )
            return True, msg, outputs
        except (PronunciationAssessError, AssetError) as e:
            return False, str(e), {}
        except Exception as e:
            return False, f"{type(e).__name__}: {e}", {}
    if cap == "query.content":
        try:
            msg, outputs = query_from_params(
                params,
                asset=asset,
                timeout_sec=float(config.query_http_timeout_sec),
            )
            return True, msg, outputs
        except (QueryContentError, AssetError) as e:
            return False, str(e), {}
        except Exception as e:
            return False, f"{type(e).__name__}: {e}", {}
    if cap == "search.images":
        try:
            msg, outputs = search_from_params(
                params,
                asset=asset,
                timeout_sec=float(config.query_http_timeout_sec),
            )
            return True, msg, outputs
        except (SearchImagesError, AssetError) as e:
            return False, str(e), {}
        except Exception as e:
            return False, f"{type(e).__name__}: {e}", {}
    if cap == "clock.now":
        try:
            msg, outputs = now_from_params(params)
            return True, msg, outputs
        except ClockNowError as e:
            return False, str(e), {}
        except Exception as e:
            return False, f"{type(e).__name__}: {e}", {}
    if cap == "music.recognize":
        try:
            msg, outputs = music_recognize_from_params(
                params,
                session_tag=str(asset.intent_id or "").strip() or None,
            )
            return True, msg, outputs
        except MusicRecognizeError as e:
            return False, str(e), {}
        except Exception as e:
            return False, f"{type(e).__name__}: {e}", {}
    if cap.startswith("music."):
        try:
            msg, outputs = music_from_params(cap, params)
            return True, msg, outputs
        except NeteaseMusicError as e:
            return False, str(e), {}
        except Exception as e:
            return False, f"{type(e).__name__}: {e}", {}
    if cap == "math.calculate":
        try:
            msg, outputs = calculate_from_params(params)
            return True, msg, outputs
        except MathCalculateError as e:
            return False, str(e), {}
        except Exception as e:
            return False, f"{type(e).__name__}: {e}", {}
    if cap == "chat.smalltalk":
        try:
            msg, outputs = smalltalk_from_params(params)
            return True, msg, outputs
        except ChatSmalltalkError as e:
            return False, str(e), {}
        except Exception as e:
            return False, f"{type(e).__name__}: {e}", {}
    if cap == "asset.upload":
        try:
            msg, outputs = upload_from_params(params, asset=asset)
            return True, msg, outputs
        except AssetUploadError as e:
            return False, str(e), {}
        except Exception as e:
            return False, f"{type(e).__name__}: {e}", {}
    if cap == "voice.stream":
        try:
            msg, outputs = voice_stream_from_params(params)
            return True, msg, outputs
        except VoiceStreamError as e:
            return False, str(e), {}
        except Exception as e:
            return False, f"{type(e).__name__}: {e}", {}
    if cap == "video.live_stream":
        try:
            msg, outputs = video_live_stream_from_params(params)
            return True, msg, outputs
        except VideoLiveStreamError as e:
            return False, str(e), {}
        except Exception as e:
            return False, f"{type(e).__name__}: {e}", {}
    if cap == "camera.capture":
        try:
            msg, outputs = capture_from_params(params, asset=asset)
            return True, msg, outputs
        except GoProCameraError as e:
            return False, humanize_capture_error(e), {}
        except AssetError as e:
            return False, str(e), {}
        except Exception as e:
            return False, f"{type(e).__name__}: {e}", {}
    if cap == "light.set":
        try:
            msg, outputs = set_from_params(params)
            return True, msg, outputs
        except LivingRoomLightError as e:
            return False, str(e), {}
        except Exception as e:
            return False, f"{type(e).__name__}: {e}", {}
    if cap == "climate.set":
        try:
            msg, outputs = climate_set_from_params(params)
            return True, msg, outputs
        except HisenseAcError as e:
            return False, str(e), {}
        except Exception as e:
            return False, f"{type(e).__name__}: {e}", {}
    if cap == "aquarium.set":
        try:
            msg, outputs = aquarium_set_from_params(params)
            return True, msg, outputs
        except XiaomiAquariumError as e:
            return False, str(e), {}
        except Exception as e:
            return False, f"{type(e).__name__}: {e}", {}
    if cap == "lock.status":
        try:
            msg, outputs = lock_status_from_params(params)
            return True, msg, outputs
        except XiaomiLockError as e:
            return False, str(e), {}
        except Exception as e:
            return False, f"{type(e).__name__}: {e}", {}
    if cap == "voice_test.run_trial":
        try:
            msg, outputs = run_trial_from_params(params, asset=asset)
            return True, msg, outputs
        except VoiceTestError as e:
            return False, str(e), {}
        except Exception as e:
            return False, f"{type(e).__name__}: {e}", {}
    return False, f"unsupported capability {cap or '(empty)'}", {}
