"""Independent intent-level scheduler (Brain intent_scheduled → intent_dispatched)."""

from __future__ import annotations

import logging
from typing import Any

from mac_edge.brain_client import BrainClient, BrainError
from mac_edge.executor import (
    STEP_FAILED,
    STEP_RUNNING,
    STEP_SUCCEEDED,
    normalize_plan,
    step_status,
)

log = logging.getLogger("mac_edge.scheduler")


class IntentScheduler:
    """
    Reports intent-level schedule states when this node is scheduler_node,
    and aggregates step outcomes into intent running/succeeded/failed.
    Does not execute capabilities or write step status.
    """

    def __init__(self) -> None:
        # intent_id → schedule hops already done
        self._dispatched: set[str] = set()

    def handle(self, intent: dict[str, Any], *, edge_id: str, brain: BrainClient) -> None:
        eid = edge_id.strip()
        if not eid:
            return
        scheduler = str(intent.get("scheduler_node") or "").strip()
        if not scheduler or scheduler != eid:
            return

        iid = str(intent.get("id") or intent.get("intent_id") or "").strip()
        if not iid:
            log.warning("scheduler: intent missing id, skip")
            return

        wire = str(
            intent.get("intent_status") or intent.get("status") or ""
        ).strip().lower()
        if wire in ("succeeded", "failed"):
            log.debug("scheduler: intent %s already terminal (%s)", iid, wire)
            return

        if wire in ("intent_dispatched", "running") or iid in self._dispatched:
            self._dispatched.add(iid)
            self._reconcile_from_steps(iid, intent, eid, brain, wire)
            return

        if wire == "intent_scheduled":
            try:
                brain.post_intent_status(
                    iid,
                    status="intent_dispatched",
                    edge_node_id=eid,
                )
                self._dispatched.add(iid)
                log.info("scheduler: intent %s → intent_dispatched", iid)
            except BrainError as e:
                log.error("scheduler: intent %s dispatch failed: %s", iid, e)
            return

        try:
            brain.post_intent_status(
                iid,
                status="intent_scheduled",
                edge_node_id=eid,
            )
            brain.post_intent_status(
                iid,
                status="intent_dispatched",
                edge_node_id=eid,
            )
            self._dispatched.add(iid)
            log.info("scheduler: intent %s scheduled → dispatched (node=%s)", iid, eid)
        except BrainError as e:
            log.error("scheduler: intent %s status report failed: %s", iid, e)

    def _reconcile_from_steps(
        self,
        iid: str,
        intent: dict[str, Any],
        eid: str,
        brain: BrainClient,
        wire: str,
    ) -> None:
        plan = normalize_plan(intent.get("execution_plan"))
        if not plan:
            log.debug("scheduler: intent %s dispatched — no plan", iid)
            return
        statuses = [step_status(s) for s in plan]
        try:
            if any(s == STEP_FAILED for s in statuses):
                brain.post_intent_status(
                    iid,
                    status="failed",
                    edge_node_id=eid,
                    message="scheduler: step failed",
                )
                log.info("scheduler: intent %s → failed from steps", iid)
                return
            if statuses and all(s == STEP_SUCCEEDED for s in statuses):
                brain.post_intent_status(
                    iid,
                    status="succeeded",
                    edge_node_id=eid,
                    message="scheduler: all steps succeeded",
                )
                log.info("scheduler: intent %s → succeeded from steps", iid)
                return
            if any(s == STEP_RUNNING for s in statuses) and wire != "running":
                brain.post_intent_status(
                    iid,
                    status="running",
                    edge_node_id=eid,
                    message="scheduler: step running",
                )
                log.info("scheduler: intent %s → running from steps", iid)
                return
        except BrainError as e:
            log.warning("scheduler: intent %s reconcile failed: %s", iid, e)
            return
        log.debug("scheduler: intent %s waiting on steps (status=%s)", iid, wire)
