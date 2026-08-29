"""Handle one transcript: print + optional Brain intent POST (kind=input privilege)."""

from __future__ import annotations

import logging
import sys
from typing import Any

from mac_voice.config import VoiceConfig
from mac_voice.edge_id import require_parent_edge_id
from mac_voice.intent_poster import post_intent
from mac_voice.wake import looks_like_ack_echo, looks_like_light_command_echo

log = logging.getLogger("mac_voice.pipeline")


def handle_transcript(
    cfg: VoiceConfig,
    text: str,
    *,
    post: bool,
    input_participant_id: str = "",
    ingress: str = "",
) -> dict[str, Any] | None:
    text = (text or "").strip()
    print(text, flush=True)
    if not text:
        log.warning("empty transcript; skip intent POST")
        return None
    if looks_like_ack_echo(text):
        log.info("skip wake-ack utterance; not an intent text=%r", text)
        return None
    if looks_like_light_command_echo(text):
        log.info("skip light.set speaker echo; not an intent text=%r", text)
        return None
    if not post:
        return None
    # kind=input may call Brain intent API under the hosting Runtime edge_id.
    voice_host = require_parent_edge_id(cfg)
    input_pid = (input_participant_id or "").strip() or voice_host
    result = post_intent(
        cfg,
        text=text,
        participant_id=voice_host,
        source="voice",
        input_participant_id=input_pid,
        ingress=ingress,
    )
    intent_id = result.get("intent_id")
    log.info(
        "intent posted intent_id=%s ok=%s input_participant=%s voice_host=%s ingress=%s",
        intent_id,
        result.get("ok"),
        input_pid,
        voice_host,
        (ingress or "-"),
    )
    print(f"intent_id={intent_id}", file=sys.stderr, flush=True)
    return result


def handle_wake(cfg: VoiceConfig, *, post: bool) -> dict[str, Any] | None:
    """Local TTS wake reply. Not an intent; do not run understand."""
    if not post:
        return None
    from mac_edge.plugins.voicewakeup_echo import echo

    spoken = echo(cfg.wake_ack)
    log.info("wake ack local echo=%r (not an intent)", spoken)
    print("wake_ack local", file=sys.stderr, flush=True)
    return {"ok": True, "echo_text": spoken, "local": True}
