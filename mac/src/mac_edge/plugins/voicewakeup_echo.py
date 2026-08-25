"""Mac Edge capability: voicewakeup.echo — local TTS of 又咋了.

This step only sees its own resolved params.
Does not import notify.speak.

Do not set the tts_playing mute flag here: the command (几点了) is spoken
immediately after 又咋了. Mute belongs on notify.speak (the long answer).
The wake gate already drops ack echo.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from typing import Any

log = logging.getLogger("mac_edge.voicewakeup_echo")

SAY_BIN = "/usr/bin/say"
DEFAULT_ECHO = "又咋了"
DEFAULT_TIMEOUT_SEC = 12
# Compact zh_CN first; do not fall back to the English system voice.
_ZH_SAY_VOICES = ("Tingting", "Ting-Ting", "Meijia", "Mei-Jia", "Sinji", "Sin-ji")


class VoiceWakeupEchoError(Exception):
    pass


_cached_voice: str | None = None


def _pick_zh_say_voice() -> str | None:
    global _cached_voice
    if _cached_voice:
        return _cached_voice
    say = shutil.which("say") or SAY_BIN
    try:
        proc = subprocess.run(
            [say, "-v", "?"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception as e:
        log.warning("say -v ? failed: %s", e)
        return _ZH_SAY_VOICES[0]
    names: list[str] = []
    zh_cn: list[str] = []
    for line in (proc.stdout or "").splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        name, locale = parts[0], parts[1].lower().replace("-", "_")
        names.append(name)
        if locale.startswith("zh_cn"):
            zh_cn.append(name)
    for prefer in _ZH_SAY_VOICES:
        if prefer in names:
            _cached_voice = prefer
            return prefer
    if zh_cn:
        _cached_voice = zh_cn[0]
        return _cached_voice
    return None


def echo(text: str | None = None, *, timeout_sec: float = DEFAULT_TIMEOUT_SEC) -> str:
    body = (text or "").strip() or DEFAULT_ECHO
    say = shutil.which("say") or SAY_BIN
    if not say:
        raise VoiceWakeupEchoError("macOS say not found")
    voice = _pick_zh_say_voice()
    cmd = [say]
    if voice:
        cmd.extend(["-v", voice])
    cmd.append(body)
    log.info("voicewakeup.echo via say voice=%s text=%r", voice or "(default)", body)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=max(2.0, timeout_sec),
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise VoiceWakeupEchoError(f"say timed out after {timeout_sec}s") from e
    except OSError as e:
        raise VoiceWakeupEchoError(f"say failed to start: {e}") from e
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        raise VoiceWakeupEchoError(f"say failed: {err}")
    return body


def echo_from_params(params: dict[str, Any] | None = None) -> tuple[str, dict[str, str]]:
    raw = params if isinstance(params, dict) else {}
    spoken = echo(str(raw.get("text") or "").strip() or None)
    return f"voicewakeup.echo {spoken}", {"echo_text": spoken}
