"""Generate TTS to a file, then play it. Playback success is not lamp success.

Uses macOS ``say -o`` / edge-tts for synthesis and ``afplay -v`` for volume.
Does not change notify.speak (that capability still generate-and-play in one shot).
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
from pathlib import Path

from mac_edge.plugins.notify_speak import (
    AFPLAY_BIN,
    SAY_BIN,
    NotifySpeakError,
    _edge_voice_for_lang,
    _pick_say_voice,
)
from mac_edge.plugins.voice_test.loopback import LoopbackError, LoopbackResult, confirm_play, write_sidecar
from mac_edge.plugins.voice_test.profile import VoiceProfile
from mac_edge.plugins.voice_test.timeline import iso_now

log = logging.getLogger("mac_edge.voice_test.tts")


class VoiceTtsError(Exception):
    pass


def _say_bin() -> str:
    path = shutil.which("say") or SAY_BIN
    if not path or not Path(path).exists():
        raise VoiceTtsError("本机找不到 macOS say，无法生成测试语音。")
    return path


def _afplay_bin() -> str:
    path = shutil.which("afplay") or AFPLAY_BIN
    if not path or not Path(path).exists():
        raise VoiceTtsError("本机找不到 afplay，无法播放测试语音。")
    return path


def resolve_say_voice(profile: VoiceProfile) -> str | None:
    requested = (profile.voice or "").strip()
    if requested:
        return requested
    return _pick_say_voice("zh_CN")


def generate_speech(
    text: str,
    dest: Path,
    *,
    profile: VoiceProfile,
    timeout_sec: float = 30.0,
) -> Path:
    """Synthesize ``text`` to ``dest``. Does not play."""
    body = (text or "").strip()
    if not body:
        raise VoiceTtsError("生成语音失败：文案为空。")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()

    if profile.backend == "edge":
        return _generate_edge(body, dest, profile=profile, timeout_sec=timeout_sec)
    return _generate_say(body, dest, profile=profile, timeout_sec=timeout_sec)


def _generate_say(
    text: str,
    dest: Path,
    *,
    profile: VoiceProfile,
    timeout_sec: float,
) -> Path:
    out = dest.with_suffix(".aiff")
    voice = resolve_say_voice(profile)
    cmd = [_say_bin()]
    if voice:
        cmd.extend(["-v", voice])
    cmd.extend(["-r", str(profile.say_rate_wpm()), "-o", str(out), text])
    log.info("voice_test generate say voice=%s rate=%s text=%r", voice, profile.say_rate_wpm(), text[:40])
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise VoiceTtsError(f"生成语音超时（say，{timeout_sec:.0f}s）。") from e
    except OSError as e:
        raise VoiceTtsError(f"生成语音失败（say：{e}）。") from e
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        raise VoiceTtsError(f"生成语音失败（say：{err}）。")
    if not out.is_file() or out.stat().st_size < 64:
        raise VoiceTtsError("生成语音失败：say 输出文件为空。")
    if (profile.pitch or "").strip():
        log.info("say backend ignores pitch=%r", profile.pitch)
    return out


def _generate_edge(
    text: str,
    dest: Path,
    *,
    profile: VoiceProfile,
    timeout_sec: float,
) -> Path:
    try:
        import edge_tts  # type: ignore
    except ImportError as e:
        raise VoiceTtsError("生成语音失败：未安装 edge-tts。") from e
    out = dest.with_suffix(".mp3")
    voice = _edge_voice_for_lang("zh_CN", profile.voice)
    rate = profile.edge_rate_pct()
    pitch = profile.edge_pitch()

    async def _synthesize() -> None:
        communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
        await communicate.save(str(out))

    log.info(
        "voice_test generate edge-tts voice=%s rate=%s pitch=%s text=%r",
        voice,
        rate,
        pitch,
        text[:40],
    )
    try:
        asyncio.run(asyncio.wait_for(_synthesize(), timeout=min(timeout_sec, 20.0)))
    except TimeoutError as e:
        raise VoiceTtsError("生成语音超时（edge-tts）。") from e
    except Exception as e:
        raise VoiceTtsError(f"生成语音失败（edge-tts：{e}）。") from e
    if not out.is_file() or out.stat().st_size < 64:
        raise VoiceTtsError("生成语音失败：edge-tts 输出文件为空。")
    return out


def play_audio(
    path: Path,
    *,
    volume: float,
    timeout_sec: float = 60.0,
    confirm: bool = True,
    heard_wav: Path | None = None,
    skip_ambient: bool = False,
) -> LoopbackResult | None:
    """Play a local audio file. afplay exit 0 is not lamp SUCCESS.

    When ``confirm`` is true, USB-mic loopback must hear energy above ambient
    or this raises VoiceTtsError.

    ``skip_ambient``: do not wait 0.35s of silence before afplay. Use for the
    second phrase so the wake→command gap stays ``wake_word_pause_ms``.
    """
    if not path.is_file() or path.stat().st_size < 32:
        raise VoiceTtsError(f"播放失败：音频文件无效（{path}）。")
    vol = max(0.0, min(float(volume), 1.0))
    cmd = [_afplay_bin(), "-v", f"{vol:.3f}", str(path)]
    log.info("voice_test play file=%s volume=%s confirm=%s", path.name, vol, confirm)
    play_started_at = iso_now()

    def _run() -> None:
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise VoiceTtsError(f"播放超时（{path.name}）。") from e
        except OSError as e:
            raise VoiceTtsError(f"播放失败（{e}）。") from e
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
            raise VoiceTtsError(f"播放失败（{err}）。")

    if not confirm:
        _run()
        play_ended_at = iso_now()
        result = LoopbackResult(
            heard=False,
            rms_ambient=0.0,
            rms_play=0.0,
            ratio=0.0,
            error_reason="confirm_off",
            play_started_at=play_started_at,
            play_ended_at=play_ended_at,
            confirmed_at=play_ended_at,
        )
        write_sidecar(path, result)
        return result
    dest = heard_wav if heard_wav is not None else path.with_name(path.stem + ".heard.wav")
    try:
        result = confirm_play(
            _run, wav_dest=dest, required=True, skip_ambient=skip_ambient
        )
    except LoopbackError as e:
        raise VoiceTtsError(str(e)) from e
    if not result.play_started_at:
        result = LoopbackResult(
            **{**result.to_dict(), "play_started_at": play_started_at, "play_ended_at": iso_now()}
        )
    write_sidecar(path, result)
    return result


def prepare_utterance(
    text: str,
    dest: Path,
    *,
    profile: VoiceProfile,
    clip_path: str = "",
) -> Path:
    """Resolve a clip or synthesize. Does not play."""
    clip = (clip_path or "").strip()
    if clip:
        path = Path(clip).expanduser()
        if not path.is_file() or path.stat().st_size < 32:
            raise VoiceTtsError(f"播放失败：音频文件无效（{path}）。")
        return path
    return generate_speech(text, dest, profile=profile)


def utter_text(
    text: str,
    dest: Path,
    *,
    profile: VoiceProfile,
    clip_path: str = "",
) -> Path:
    """Load a clip if given, otherwise generate, then play at profile.volume."""
    generated = prepare_utterance(text, dest, profile=profile, clip_path=clip_path)
    heard = dest.with_name(dest.stem + ".heard.wav") if dest else generated.with_name(
        generated.stem + ".heard.wav"
    )
    play_audio(
        generated,
        volume=profile.volume,
        confirm=profile.confirm_playback,
        heard_wav=heard,
    )
    return generated


def utter_text_safe(
    text: str,
    dest: Path,
    *,
    profile: VoiceProfile,
    clip_path: str = "",
) -> Path:
    """Same as utter_text; maps notify.speak errors to VoiceTtsError."""
    try:
        return utter_text(text, dest, profile=profile, clip_path=clip_path)
    except NotifySpeakError as e:
        raise VoiceTtsError(f"生成/播放失败（{e}）。") from e
