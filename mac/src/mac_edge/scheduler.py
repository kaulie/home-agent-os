"""Independent intent-level scheduler (Brain intent_scheduled → intent_dispatched)."""

from __future__ import annotations

import logging
import threading
from typing import Any

from mac_edge.brain_client import BrainClient, edge_has_assigned_step
from mac_edge.executor import (
    STEP_FAILED,
    STEP_RUNNING,
    STEP_SUCCEEDED,
    EMPTY_PLAN_MSG,
    _try_post_intent_status,
    all_steps_succeeded,
    finalize_intent_from_plan,
    normalize_plan,
    plan_has_remaining_work,
    step_status,
)
from mac_edge.local_ledger import active as _ledger_active

log = logging.getLogger("mac_edge.scheduler")


class IntentScheduler:
    """
    Reports intent-level schedule states when this node has an assigned
    plan step, and aggregates step outcomes into intent running/succeeded/failed.
    Does not execute capabilities or write step status.

    Local ledger is the source of truth; Brain posts are best-effort sync.
    """

    def __init__(self) -> None:
        # intent_id → schedule hops already done
        self._dispatched: set[str] = set()
        self._lock = threading.Lock()

    def handle(
        self,
        intent: dict[str, Any],
        *,
        edge_id: str,
        brain: BrainClient | None,
    ) -> None:
        with self._lock:
            self._handle_unlocked(intent, edge_id=edge_id, brain=brain)

    def _handle_unlocked(
        self,
        intent: dict[str, Any],
        *,
        edge_id: str,
        brain: BrainClient | None,
    ) -> None:
        eid = edge_id.strip()
        if not eid:
            return
        if not edge_has_assigned_step(intent, eid):
            return

        ledger = _ledger_active()
        if ledger is not None:
            intent = ledger.overlay_intent(intent)

        iid = str(intent.get("id") or intent.get("intent_id") or "").strip()
        if not iid:
            log.warning("scheduler: intent missing id, skip")
            return

        plan = normalize_plan(intent.get("execution_plan"))
        if not plan:
            wire = str(
                intent.get("intent_status") or intent.get("status") or ""
            ).strip().lower()
            if wire not in ("succeeded", "failed"):
                posted = _try_post_intent_status(
                    brain,
                    iid,
                    status="failed",
                    edge_id=eid,
                    message=EMPTY_PLAN_MSG,
                )
                log.warning(
                    "scheduler: intent %s empty plan → failed%s",
                    iid,
                    "" if posted else " locally (Brain unsynced)",
                )
            return

        wire = str(
            intent.get("intent_status") or intent.get("status") or ""
        ).strip().lower()
        if wire in ("succeeded", "failed"):
            plan = normalize_plan(intent.get("execution_plan"))
            if not plan_has_remaining_work(plan, intent_id=iid):
                log.debug("scheduler: intent %s already terminal (%s)", iid, wire)
                return
            posted = _try_post_intent_status(
                brain,
                iid,
                status="running",
                edge_id=eid,
                message="scheduler: resume interval after beat",
            )
            if posted:
                log.info("scheduler: intent %s → running (resume interval)", iid)
            else:
                log.info(
                    "scheduler: intent %s → running locally (Brain unsynced)", iid
                )
            self._dispatched.add(iid)
            self._reconcile_from_steps(iid, intent, eid, brain, "running")
            return

        if wire in ("intent_dispatched", "running") or iid in self._dispatched:
            self._dispatched.add(iid)
            self._reconcile_from_steps(iid, intent, eid, brain, wire)
            return

        if wire == "intent_scheduled":
            posted = _try_post_intent_status(
                brain,
                iid,
                status="intent_dispatched",
                edge_id=eid,
            )
            self._dispatched.add(iid)
            if posted:
                log.info("scheduler: intent %s → intent_dispatched", iid)
            else:
                log.info(
                    "scheduler: intent %s → intent_dispatched locally (Brain unsynced)",
                    iid,
                )
            return

        posted_sched = _try_post_intent_status(
            brain,
            iid,
            status="intent_scheduled",
            edge_id=eid,
        )
        posted_disp = _try_post_intent_status(
            brain,
            iid,
            status="intent_dispatched",
            edge_id=eid,
        )
        self._dispatched.add(iid)
        if posted_sched and posted_disp:
            log.info("scheduler: intent %s scheduled → dispatched (node=%s)", iid, eid)
        else:
            log.info(
                "scheduler: intent %s scheduled → dispatched locally (Brain unsynced)",
                iid,
            )

    def _reconcile_from_steps(
        self,
        iid: str,
        intent: dict[str, Any],
        eid: str,
        brain: BrainClient | None,
        wire: str,
    ) -> None:
        plan = normalize_plan(intent.get("execution_plan"))
        if not plan:
            log.debug("scheduler: intent %s dispatched — no plan", iid)
            return
        statuses = [step_status(s) for s in plan]
        if any(s == STEP_FAILED for s in statuses) and not plan_has_remaining_work(
            plan, intent_id=iid
        ):
            _try_post_intent_status(
                brain,
                iid,
                status="failed",
                edge_id=eid,
                message="scheduler: step failed",
            )
            log.info("scheduler: intent %s → failed from steps", iid)
            return
        if any(s == STEP_RUNNING for s in statuses) and wire != "running":
            _try_post_intent_status(
                brain,
                iid,
                status="running",
                edge_id=eid,
                message="scheduler: step running",
            )
            log.info("scheduler: intent %s → running from steps", iid)
            return
        if all_steps_succeeded(plan, intent_id=iid) and wire not in (
            "succeeded",
            "failed",
        ):
            finalize_intent_from_plan(
                brain,
                iid,
                eid,
                plan,
                current_wire=wire,
            )
            log.info("scheduler: intent %s → succeeded from steps", iid)
            return
        log.debug("scheduler: intent %s waiting on steps (status=%s)", iid, wire)

    def reconcile_peeked_terminal(
        self,
        peeked: list[dict[str, Any]],
        *,
        edge_id: str,
        brain: BrainClient | None,
    ) -> None:
        """Bump terminal intent status when steps are done but wire is still open."""
        eid = (edge_id or "").strip()
        if not eid or not peeked:
            return
        ledger = _ledger_active()
        for intent in peeked:
            if not isinstance(intent, dict):
                continue
            if not edge_has_assigned_step(intent, eid):
                continue
            if ledger is not None:
                intent = ledger.overlay_intent(intent)
            iid = str(intent.get("id") or intent.get("intent_id") or "").strip()
            if not iid:
                continue
            wire = str(
                intent.get("intent_status") or intent.get("status") or ""
            ).strip().lower()
            if wire in ("succeeded", "failed"):
                continue
            plan = normalize_plan(intent.get("execution_plan"))
            if not plan:
                continue
            if not all_steps_succeeded(plan, intent_id=iid) and plan_has_remaining_work(
                plan, intent_id=iid
            ):
                continue
            if not any(
                step_status(s) in (STEP_SUCCEEDED, STEP_FAILED) for s in plan
            ):
                continue
            self._reconcile_from_steps(iid, intent, eid, brain, wire)
