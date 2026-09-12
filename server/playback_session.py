"""Playback session tracking — capability step outputs → playback_sessions rows.

Brain-side central record of "what is playing where" (TV PDF cast today;
music/photo scenes later). Written automatically from step status reports
(`_apply_step_status_record` funnel); edges do not change.

Extend to a new scene: add the capability → scene mapping plus an extractor
that normalizes that capability's outputs into position/total/state/payload.
"""

from __future__ import annotations

import logging
from typing import Any

try:
    import db as brain_db
except ImportError:  # pragma: no cover
    from server import db as brain_db  # type: ignore

log = logging.getLogger(__name__)

# capability → scene. Only succeeded steps (status 2) with mapped capabilities
# produce session writes.
SCENE_BY_CAPABILITY = {
    "display.pdf": "tv_pdf",
    "display.pdf.page": "tv_pdf",
    "display.pdf.zoom": "tv_pdf",
}

STATE_PLAYING = "playing"


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_tv_pdf(step: dict, outputs: dict) -> dict[str, Any]:
    """display.pdf / display.pdf.page / display.pdf.zoom outputs → session fields."""
    constrict = step.get("input_constrict") or {}
    payload: dict[str, Any] = {}
    status_text = str(outputs.get("status_text") or "").strip()
    if status_text:
        payload["status_text"] = status_text
    zoom = _float_or_none(outputs.get("zoom"))
    if zoom is not None:
        payload["zoom"] = zoom
    return {
        "target": str(constrict.get("appliance") or "").strip(),
        "asset_id": str(outputs.get("asset_id") or "").strip(),
        "position": _int_or_none(outputs.get("page")),
        "total": _int_or_none(outputs.get("page_count")),
        "state": STATE_PLAYING,
        "payload": payload,
    }


_EXTRACTOR_BY_SCENE = {
    "tv_pdf": _extract_tv_pdf,
}


def _step_capability(intent: dict, step_id: int) -> tuple[dict | None, str]:
    for step in intent.get("execution_plan") or []:
        if not isinstance(step, dict):
            continue
        try:
            n = int(step.get("step") or 0)
        except (TypeError, ValueError):
            continue
        if n == step_id:
            return step, str(step.get("capability") or "").strip()
    return None, ""


def record_from_step(
    *,
    intent: dict,
    step_id: int,
    step_status: int,
    outputs: dict | None,
    edge_id: str = "",
) -> int | None:
    """Upsert playback_sessions from one succeeded step. Returns session_id or None.

    No-op unless the step's capability is scene-mapped and the step succeeded.
    Never raises — session tracking must not break step recording.
    """
    try:
        if step_status != 2 or not isinstance(outputs, dict) or not outputs:
            return None
        step, capability = _step_capability(intent or {}, int(step_id))
        scene = SCENE_BY_CAPABILITY.get(capability)
        if not scene:
            return None
        extractor = _EXTRACTOR_BY_SCENE.get(scene)
        if extractor is None or step is None:
            return None
        fields = extractor(step, outputs)
        actor = str(edge_id or "").strip() or str(step.get("assigned_edge_id") or "").strip()
        if not actor:
            return None
        record = {
            "scene": scene,
            "edge_id": actor,
            "last_intent_id": str((intent or {}).get("intent_id") or (intent or {}).get("id") or ""),
            **fields,
        }
        return brain_db.upsert_playback_session(record)
    except Exception:  # pragma: no cover - defensive
        log.exception("playback session record failed step=%s status=%s", step_id, step_status)
        return None
