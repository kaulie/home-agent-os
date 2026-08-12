"""Mac local TTS: notify.speak via Microsoft edge-tts (male neural), say fallback."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

log = logging.getLogger("mac_edge.notify_speak")

SAY_BIN = "/usr/bin/say"
AFPLAY_BIN = "/usr/bin/afplay"
DEFAULT_TIMEOUT_SEC = 120

# Microsoft Edge neural voices (edge-tts). Prefer male for zh/en.
_EDGE_VOICE_ZH_MALE = "zh-CN-YunxiNeural"
_EDGE_VOICE_EN_MALE = "en-US-GuyNeural"

# macOS say fallbacks (female system voices are fine as last resort).
_ZH_SAY_VOICES = ("Ting-Ting", "Tingting", "Mei-Jia", "Sin-ji", "Sinji", "Yu-shu", "Lilian")
_EN_SAY_VOICES = ("Alex", "Samantha", "Victoria")


class NotifySpeakError(Exception):
    pass


def _edge_voice_for_lang(lang: str | None, override: str | None = None) -> str:
    if override and override.strip():
        return override.strip()
    env = (os.environ.get("MAC_EDGE_TTS_VOICE") or "").strip()
    if env:
        return env
    lang_l = (lang or "zh_CN").strip().lower().replace("-", "_")
    if lang_l.startswith("zh"):
        return _EDGE_VOICE_ZH_MALE
    return _EDGE_VOICE_EN_MALE


def _edge_tts_speak(text: str, *, voice: str, timeout_sec: float) -> None:
    try:
        import edge_tts  # type: ignore
    except ImportError as e:
        raise NotifySpeakError(
            "edge-tts not installed (pip install edge-tts)"
        ) from e

    afplay = shutil.which("afplay") or AFPLAY_BIN
    if not afplay or not Path(afplay).exists():
        raise NotifySpeakError("afplay not found (needed to play edge-tts audio)")

    async def _synthesize(path: Path) -> None:
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(str(path))

    log.info("notify.speak via edge-tts voice=%s text=%r", voice, text[:80])
    tmp: Path | None = None
    last_err: Exception | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as fh:
            tmp = Path(fh.name)
        # edge-tts occasionally returns empty audio; retry a couple times.
        for attempt in range(1, 4):
            try:
                asyncio.run(asyncio.wait_for(_synthesize(tmp), timeout=timeout_sec))
                if tmp.stat().st_size < 64:
                    raise NotifySpeakError("edge-tts returned empty audio")
                last_err = None
                break
            except Exception as e:
                last_err = e
                log.warning("edge-tts attempt %s failed: %s", attempt, e)
                try:
                    tmp.write_bytes(b"")
                except OSError:
                    pass
        if last_err is not None:
            if isinstance(last_err, TimeoutError):
                raise NotifySpeakError(f"edge-tts timed out after {timeout_sec}s") from last_err
            raise NotifySpeakError(f"edge-tts failed: {last_err}") from last_err

        try:
            proc = subprocess.run(
                [afplay, str(tmp)],
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise NotifySpeakError(f"afplay timed out after {timeout_sec}s") from e
        except OSError as e:
            raise NotifySpeakError(f"afplay failed to start: {e}") from e
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
            raise NotifySpeakError(f"afplay failed: {err}")
    finally:
        if tmp is not None:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass


def _list_say_voices() -> set[str]:
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
        return set()
    names: set[str] = set()
    for line in (proc.stdout or "").splitlines():
        parts = line.split()
        if parts:
            names.add(parts[0])
    return names


def _voices_for_lang_prefix(lang_prefix: str) -> list[str]:
    say = shutil.which("say") or SAY_BIN
    try:
        proc = subprocess.run(
            [say, "-v", "?"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception:
        return []
    prefix = lang_prefix.lower().replace("-", "_")
    out: list[str] = []
    for line in (proc.stdout or "").splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        locale = parts[1].lower().replace("-", "_")
        if locale.startswith(prefix):
            out.append(parts[0])
    return out


def _pick_say_voice(lang: str | None, available: set[str] | None = None) -> str | None:
    avail = available if available is not None else _list_say_voices()
    lang_l = (lang or "zh_CN").strip().lower().replace("-", "_")
    prefer = _ZH_SAY_VOICES if lang_l.startswith("zh") else _EN_SAY_VOICES
    for name in prefer:
        if not avail or name in avail:
            return name
    prefix = "zh" if lang_l.startswith("zh") else (lang_l.split("_", 1)[0] or "en")
    for name in _voices_for_lang_prefix(prefix):
        if not avail or name in avail:
            return name
    return None


def _say(text: str, *, voice: str | None, timeout_sec: float) -> None:
    say = shutil.which("say") or SAY_BIN
    if not say:
        raise NotifySpeakError("macOS say not found")
    cmd = [say]
    if voice:
        cmd.extend(["-v", voice])
    cmd.append(text)
    log.info("notify.speak via say voice=%s text=%r", voice or "(default)", text[:80])
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise NotifySpeakError(f"say timed out after {timeout_sec}s") from e
    except OSError as e:
        raise NotifySpeakError(f"say failed to start: {e}") from e
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        raise NotifySpeakError(f"say failed: {err}")


def _pyttsx3_fallback(text: str) -> None:
    try:
        import pyttsx3  # type: ignore
    except ImportError as e:
        raise NotifySpeakError("pyttsx3 is not installed") from e
    log.info("notify.speak fallback pyttsx3 text=%r", text[:80])
    engine = pyttsx3.init()
    engine.say(text)
    engine.runAndWait()


def speak(
    text: str,
    *,
    lang: str | None = "zh_CN",
    voice: str | None = None,
    timeout_sec: float = DEFAULT_TIMEOUT_SEC,
) -> str:
    """Speak text on the default audio device. Prefer edge-tts male neural voice."""
    body = (text or "").strip()
    if not body:
        raise NotifySpeakError("missing text")

    edge_voice = _edge_voice_for_lang(lang, voice)
    errors: list[str] = []
    try:
        _edge_tts_speak(body, voice=edge_voice, timeout_sec=timeout_sec)
        return f"spoke via edge-tts voice={edge_voice}"
    except NotifySpeakError as e:
        errors.append(str(e))
        log.warning("edge-tts path failed: %s — trying macOS say", e)

    say_voice = _pick_say_voice(lang)
    try:
        _say(body, voice=say_voice, timeout_sec=timeout_sec)
        return f"spoke via say voice={say_voice or 'default'}"
    except NotifySpeakError as e:
        errors.append(str(e))
        log.warning("say path failed: %s — trying pyttsx3", e)

    try:
        _pyttsx3_fallback(body)
        return "spoke via pyttsx3"
    except NotifySpeakError as e:
        errors.append(str(e))
        raise NotifySpeakError("; ".join(errors)) from None


def speak_from_params(params: dict[str, Any], *, timeout_sec: float = DEFAULT_TIMEOUT_SEC) -> str:
    text = str(params.get("text") or "").strip()
    lang = str(params.get("lang") or "zh_CN").strip() or "zh_CN"
    voice = str(params.get("voice") or "").strip() or None
    return speak(text, lang=lang, voice=voice, timeout_sec=timeout_sec)
