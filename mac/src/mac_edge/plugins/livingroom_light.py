"""Mac Edge capability: light.set — living-room ceiling light via speaker wake.

Independent of notify.speak as a plan step. This step only sees its own
resolved params. Voice protocol is internal: wake → wait → command.

Prefers pre-recorded clips in ``plugins/livingroom-ceiling-light/audio/``
(or ``MAC_EDGE_LIGHT_AUDIO_DIR``); falls back to TTS when a clip is missing.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mac_edge.plugins.notify_speak import NotifySpeakError, speak

log = logging.getLogger("mac_edge.livingroom_light")

WAKE_PHRASE = "小书小书"
WAIT_AFTER_WAKE_SEC = 2.0
COMMAND_ON = "开灯"
COMMAND_OFF = "关灯"

_CLIP_EXTS = (".m4a", ".wav", ".mp3", ".caf", ".aiff")
AFPLAY_BIN = "/usr/bin/afplay"
_DEFAULT_PLAY_TIMEOUT_SEC = 30.0

_ON_ALIASES = frozenset({"on", "开", "开灯", "true", "1"})
_OFF_ALIASES = frozenset({"off", "关", "关灯", "false", "0"})


class LivingRoomLightError(Exception):
    pass


def _repo_audio_dir() -> Path:
    here = Path(__file__).resolve()
    return here.parents[4] / "plugins" / "livingroom-ceiling-light" / "audio"


def audio_dir() -> Path:
    raw = (os.environ.get("MAC_EDGE_LIGHT_AUDIO_DIR") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return _repo_audio_dir()


def resolve_clip(name: str) -> Path | None:
    base = audio_dir()
    stem = (name or "").strip()
    if not stem:
        return None
    for ext in _CLIP_EXTS:
        path = base / f"{stem}{ext}"
        try:
            if path.is_file() and path.stat().st_size > 0:
                return path
        except OSError:
            continue
    return None


def play_clip(
    path: Path,
    *,
    timeout_sec: float = _DEFAULT_PLAY_TIMEOUT_SEC,
) -> None:
    afplay = shutil.which("afplay") or AFPLAY_BIN
    if not afplay or not Path(afplay).exists():
        raise LivingRoomLightError("灯控失败：本机找不到 afplay，无法播放预录音频。")
    try:
        proc = subprocess.run(
            [afplay, str(path)],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise LivingRoomLightError(
            f"灯控失败：预录音频播放超时（{path.name}）。"
        ) from e
    except OSError as e:
        raise LivingRoomLightError(f"灯控失败：预录音频播放失败（{e}）。") from e
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        raise LivingRoomLightError(f"灯控失败：预录音频播放失败（{err}）。")


def utter(
    clip_key: str,
    tts_text: str,
    *,
    speak_fn: Callable[..., Any] | None = None,
    play_clip_fn: Callable[[Path], None] | None = None,
) -> None:
    """Play ``clip_key`` clip when present; otherwise TTS ``tts_text``."""
    clip = resolve_clip(clip_key)
    if clip is not None:
        player = play_clip_fn or play_clip
        log.info("light.set clip %s → %s", clip_key, clip)
        player(clip)
        return
    speaker = speak_fn or speak
    log.info("light.set tts %s text=%r", clip_key, tts_text)
    speaker(tts_text, lang="zh_CN")


def _normalize_state(raw: Any) -> str:
    folded = str(raw or "").strip().lower().replace(" ", "")
    if not folded:
        raise LivingRoomLightError("灯控失败：缺少必填入参 state（on 或 off）。")
    if folded in _ON_ALIASES:
        return "on"
    if folded in _OFF_ALIASES:
        return "off"
    raise LivingRoomLightError(
        f"灯控失败：无法识别 state「{raw}」。请用 on 或 off。"
    )


def set_light(
    state: str,
    *,
    speak_fn: Callable[..., Any] | None = None,
    play_clip_fn: Callable[[Path], None] | None = None,
    sleep_fn: Callable[[float], None] | None = None,
) -> dict[str, str]:
    """Wake 小书, wait, then 开灯/关灯. Prefers recorded clips over TTS."""
    sleeper = sleep_fn or time.sleep
    command_key = "on" if state == "on" else "off"
    command_text = COMMAND_ON if state == "on" else COMMAND_OFF
    try:
        utter("wake", WAKE_PHRASE, speak_fn=speak_fn, play_clip_fn=play_clip_fn)
        sleeper(WAIT_AFTER_WAKE_SEC)
        utter(command_key, command_text, speak_fn=speak_fn, play_clip_fn=play_clip_fn)
    except NotifySpeakError as e:
        raise LivingRoomLightError(f"灯控失败：本机语音没发出去（{e}）") from e
    except LivingRoomLightError:
        raise
    except Exception as e:
        raise LivingRoomLightError(f"灯控失败：{e}") from e
    log.info(
        "light.set state=%s wake=%s command=%s audio_dir=%s",
        state,
        WAKE_PHRASE,
        command_text,
        audio_dir(),
    )
    return {"state": state}


def set_from_params(
    params: dict[str, Any] | None = None,
    *,
    speak_fn: Callable[..., Any] | None = None,
    play_clip_fn: Callable[[Path], None] | None = None,
    sleep_fn: Callable[[float], None] | None = None,
) -> tuple[str, dict[str, str]]:
    raw = params if isinstance(params, dict) else {}
    state_raw = raw.get("state")
    if state_raw is None or str(state_raw).strip() == "":
        raise LivingRoomLightError("灯控失败：缺少必填入参 state（on 或 off）。")
    state = _normalize_state(state_raw)
    outputs = set_light(
        state,
        speak_fn=speak_fn,
        play_clip_fn=play_clip_fn,
        sleep_fn=sleep_fn,
    )
    msg = f"light.set {COMMAND_ON if state == 'on' else COMMAND_OFF}"
    return msg, outputs
