"""POST /api/v1/intent after STT (same contract as iPhone Intent Source)."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from mac_voice.config import VoiceConfig

log = logging.getLogger("mac_voice.intent")


def post_intent(
    cfg: VoiceConfig,
    *,
    text: str,
    participant_id: str,
    source: str = "voice",
    input_participant_id: str = "",
    ingress: str = "",
    timeout_sec: float = 60.0,
) -> dict[str, Any]:
    """Post voice intent.

    ``participant_id`` / ``edge_id`` = Mac Runtime hosting voice.stream (processor).
    ``input_participant_id`` = Input Source identity (who the user spoke to) —
    Mac edge for USB mic, iPhone Runtime edge_id for Home Mic. Never invent
    static channel labels like home_mic/usb_mic as identity.
    """
    trimmed = (text or "").strip()
    if not trimmed:
        raise ValueError("text is empty; refuse POST /intent")
    pid = (participant_id or "").strip()
    if not pid:
        raise ValueError("participant_id required")
    src = "voice" if source == "voice" else "text"
    input_pid = (input_participant_id or "").strip() or pid
    ingress_l = (ingress or "").strip().lower()
    url = f"{cfg.brain_url}/api/v1/intent"
    source_context: dict[str, Any] = {
        # Input Source Affinity: the speaking Runtime's participant_id
        "device_id": input_pid,
        "input_participant_id": input_pid,
        "capability_id": "voice.stream",
        "endpoint_id": "microphone",
        # Host that ran STT (Mac voice hub)
        "voice_host_participant_id": pid,
    }
    if ingress_l:
        source_context["ingress"] = ingress_l
    payload = {
        "text": trimmed,
        "source": src,
        "client_hint": cfg.client_hint,
        "participant_id": pid,
        "edge_id": pid,
        "source_context": source_context,
    }
    log.info(
        "POST intent source=%s input_participant=%s voice_host=%s ingress=%s text=%r",
        src,
        input_pid,
        pid,
        ingress_l or "-",
        trimmed[:120],
    )
    with httpx.Client(timeout=timeout_sec) as client:
        resp = client.post(url, json=payload)
    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text[:500]}
    if resp.status_code >= 400:
        raise RuntimeError(f"intent HTTP {resp.status_code}: {data}")
    return data if isinstance(data, dict) else {"ok": True, "data": data}


def post_wake(
    cfg: VoiceConfig,
    *,
    participant_id: str,
    timeout_sec: float = 15.0,
) -> dict[str, Any]:
    """POST /api/v1/voice/wake — telemetry only; Brain must not create an intent."""
    pid = (participant_id or "").strip()
    if not pid:
        raise ValueError("participant_id required")
    url = f"{cfg.brain_url}/api/v1/voice/wake"
    payload = {
        "event": "wake",
        "source": "voice",
        "client_hint": cfg.client_hint,
        "participant_id": pid,
        "edge_id": pid,
    }
    log.info("POST voice/wake edge_id=%s", pid)
    with httpx.Client(timeout=timeout_sec) as client:
        resp = client.post(url, json=payload)
    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text[:500]}
    if resp.status_code >= 400:
        raise RuntimeError(f"voice/wake HTTP {resp.status_code}: {data}")
    return data if isinstance(data, dict) else {"ok": True, "data": data}


def wake_echo_is_done(payload: dict[str, Any] | None) -> bool:
    """True when voicewakeup.echo has finished (or the wake job failed)."""
    if not isinstance(payload, dict):
        return False
    status = str(payload.get("status") or payload.get("intent_status") or "").strip().lower()
    if status in ("succeeded", "failed"):
        return True
    plan = payload.get("execution_plan")
    if not isinstance(plan, list):
        return False
    for step in plan:
        if not isinstance(step, dict):
            continue
        if str(step.get("capability") or "").strip() != "voicewakeup.echo":
            continue
        st = step.get("status", step.get("step_status"))
        if st in (2, 3, "2", "3"):
            return True
        if str(st).strip().lower() in ("succeeded", "failed"):
            return True
    return False


def wait_wake_echo_done(
    cfg: VoiceConfig,
    intent_id: Any,
    *,
    timeout_sec: float = 12.0,
    poll_sec: float = 0.15,
) -> bool:
    """Poll intent_detail until the wake echo step finishes. Best-effort."""
    iid = str(intent_id or "").strip()
    if not iid:
        return False
    url = f"{cfg.brain_url}/api/v1/intent_detail"
    deadline = time.monotonic() + max(1.0, timeout_sec)
    with httpx.Client(timeout=5.0) as client:
        while time.monotonic() < deadline:
            try:
                resp = client.get(url, params={"intent_id": iid})
                data = resp.json() if resp.status_code < 400 else None
            except Exception as e:
                log.debug("wait wake echo poll failed: %s", e)
                data = None
            if wake_echo_is_done(data if isinstance(data, dict) else None):
                log.info("wake echo done intent_id=%s", iid)
                return True
            time.sleep(max(0.05, poll_sec))
    log.warning("wake echo wait timed out intent_id=%s", iid)
    return False
