"""VoiceProfile: TTS and timing knobs for one lamp-voice trial.

Loaded from defaults < profile file < env < capability params.
No grid search here (Phase 5). Pitch is recorded even when the backend
cannot apply it.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class VoiceProfileError(Exception):
    pass


_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})

DEFAULT_VERIFY_QUERY = (
    "图中请只判断落地台灯或书桌台灯的灯头/灯罩是否自己在发光。"
    "不要把天花板主灯、电视、窗外自然光当成台灯亮。"
    "若目标台灯亮着，answer_text 只写「亮」；若关着，只写「灭」；看不清则说「我不知道」。"
)

# Gap 小书小书 → 打开台灯/关闭台灯. Above this, command often does not take.
COMMAND_WINDOW_HIGH_RISK_MS = 2000
RECOMMENDED_PAUSE_MS = (500, 800, 1200, 1500, 2000, 3000)
RECOMMENDED_SPEEDS = (0.8, 1.0, 1.2)
RECOMMENDED_VOLUMES = (0.6, 0.8, 1.0)
RECOMMENDED_VOICES = ("Tingting", "Mei-Jia")
RECOMMENDED_BACKENDS = ("say", "edge")
RECOMMENDED_PITCHES = ("+0Hz", "+10Hz", "-10Hz")
RECOMMENDED_SETTLE_MS = (1000, 1500, 2000)


def pause_window_risk(pause_ms: int) -> str:
    return "high_risk" if int(pause_ms) > COMMAND_WINDOW_HIGH_RISK_MS else "ok"


@dataclass(frozen=True)
class VoiceProfile:
    backend: str = "say"
    voice: str = "Tingting"
    speed: float = 1.0
    volume: float = 0.8
    pitch: str = ""
    wake_word: str = "小书小书"
    command: str = "打开台灯"
    wake_word_pause_ms: int = 1500
    settle_ms: int = 1500
    verify_query: str = DEFAULT_VERIFY_QUERY
    capture_before: bool = True
    capture_backend: str = "gopro"
    webcam_device: str = "0"
    wake_audio: str = ""
    command_audio: str = ""
    confirm_playback: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def say_rate_wpm(self) -> int:
        """Map speed=1.0 to macOS say default ~175 wpm."""
        rate = int(round(175.0 * float(self.speed)))
        return max(90, min(rate, 350))

    def edge_rate_pct(self) -> str:
        delta = int(round((float(self.speed) - 1.0) * 100.0))
        if delta == 0:
            return "+0%"
        return f"{delta:+d}%"

    def edge_pitch(self) -> str:
        raw = (self.pitch or "").strip()
        return raw if raw else "+0Hz"


def _parse_capture_backend(raw: Any, default: str) -> str:
    text = str(raw or default).strip().lower() or default
    if text in ("gopro", "camera.capture", "camera"):
        return "gopro"
    if text in ("webcam", "local", "facetime"):
        return "webcam"
    raise VoiceProfileError(f"不支持的 capture_backend：{raw}（gopro | webcam）")


def _plugin_profile_path() -> Path:
    here = Path(__file__).resolve()
    return here.parents[5] / "plugins" / "voice-lamp-test" / "profiles" / "default.yaml"


def default_profile_path() -> Path:
    raw = (os.environ.get("MAC_EDGE_VOICE_TEST_PROFILE") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return _plugin_profile_path()


def _parse_bool(raw: Any, default: bool) -> bool:
    if raw is None or raw == "":
        return default
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    raise VoiceProfileError(f"无法解析布尔值：{raw!r}")


def _parse_float(raw: Any, default: float, *, lo: float, hi: float, name: str) -> float:
    if raw is None or raw == "":
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError) as e:
        raise VoiceProfileError(f"{name} 不是数字：{raw!r}") from e
    if value < lo or value > hi:
        raise VoiceProfileError(f"{name}={value} 超出范围 {lo}–{hi}")
    return value


def _parse_int(raw: Any, default: int, *, lo: int, hi: int, name: str) -> int:
    if raw is None or raw == "":
        return default
    try:
        value = int(float(raw))
    except (TypeError, ValueError) as e:
        raise VoiceProfileError(f"{name} 不是整数：{raw!r}") from e
    if value < lo or value > hi:
        raise VoiceProfileError(f"{name}={value} 超出范围 {lo}–{hi}")
    return value


def _unquote(raw: str) -> str:
    text = raw.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    return text


def _load_flat_file(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        data = json.loads(text)
        if not isinstance(data, dict):
            raise VoiceProfileError(f"配置文件必须是对象：{path}")
        return data
    out: dict[str, Any] = {}
    for line in text.splitlines():
        cut = line.split("#", 1)[0].strip()
        if not cut or ":" not in cut:
            continue
        key, _, value = cut.partition(":")
        key = key.strip()
        if not key:
            continue
        out[key] = _unquote(value)
    return out


def _env_overrides() -> dict[str, Any]:
    mapping = {
        "MAC_EDGE_VOICE_TEST_BACKEND": "backend",
        "MAC_EDGE_VOICE_TEST_VOICE": "voice",
        "MAC_EDGE_VOICE_TEST_SPEED": "speed",
        "MAC_EDGE_VOICE_TEST_VOLUME": "volume",
        "MAC_EDGE_VOICE_TEST_PITCH": "pitch",
        "MAC_EDGE_VOICE_TEST_WAKE": "wake_word",
        "MAC_EDGE_VOICE_TEST_COMMAND": "command",
        "MAC_EDGE_VOICE_TEST_WAKE_PAUSE_MS": "wake_word_pause_ms",
        "MAC_EDGE_VOICE_TEST_SETTLE_MS": "settle_ms",
        "MAC_EDGE_VOICE_TEST_VERIFY_QUERY": "verify_query",
        "MAC_EDGE_VOICE_TEST_CAPTURE_BEFORE": "capture_before",
        "MAC_EDGE_VOICE_TEST_CAPTURE": "capture_backend",
        "MAC_EDGE_WEBCAM_DEVICE": "webcam_device",
        "MAC_EDGE_VOICE_TEST_WAKE_AUDIO": "wake_audio",
        "MAC_EDGE_VOICE_TEST_COMMAND_AUDIO": "command_audio",
        "MAC_EDGE_VOICE_TEST_CONFIRM_PLAYBACK": "confirm_playback",
    }
    out: dict[str, Any] = {}
    for env_name, field in mapping.items():
        raw = os.environ.get(env_name)
        if raw is None or str(raw).strip() == "":
            continue
        out[field] = raw
    return out


def _merge(*layers: dict[str, Any] | None) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for layer in layers:
        if not layer:
            continue
        for key, value in layer.items():
            if value is None:
                continue
            if isinstance(value, str) and value.strip() == "" and key not in (
                "pitch",
                "wake_audio",
                "command_audio",
            ):
                continue
            merged[str(key)] = value
    return merged


def build_profile(
    *,
    file_path: Path | None = None,
    params: dict[str, Any] | None = None,
    use_env: bool = True,
) -> VoiceProfile:
    """Build a VoiceProfile. Missing file is OK (use defaults)."""
    file_data: dict[str, Any] = {}
    path = file_path if file_path is not None else default_profile_path()
    try:
        if path.is_file():
            file_data = _load_flat_file(path)
    except OSError as e:
        raise VoiceProfileError(f"读 VoiceProfile 失败：{e}") from e
    except json.JSONDecodeError as e:
        raise VoiceProfileError(f"VoiceProfile JSON 无效：{e}") from e

    merged = _merge(
        file_data,
        _env_overrides() if use_env else {},
        params if isinstance(params, dict) else {},
    )
    base = VoiceProfile()
    backend = str(merged.get("backend") or base.backend).strip().lower() or "say"
    if backend not in ("say", "edge"):
        raise VoiceProfileError(f"不支持的 TTS backend：{backend}（say | edge）")
    return VoiceProfile(
        backend=backend,
        voice=str(merged.get("voice") or base.voice).strip() or base.voice,
        speed=_parse_float(merged.get("speed"), base.speed, lo=0.5, hi=2.0, name="speed"),
        volume=_parse_float(
            merged.get("volume"), base.volume, lo=0.0, hi=1.0, name="volume"
        ),
        pitch=str(merged.get("pitch") if merged.get("pitch") is not None else base.pitch),
        wake_word=str(merged.get("wake_word") or base.wake_word).strip() or base.wake_word,
        command=str(merged.get("command") or base.command).strip() or base.command,
        wake_word_pause_ms=_parse_int(
            merged.get("wake_word_pause_ms"),
            base.wake_word_pause_ms,
            lo=0,
            hi=15_000,
            name="wake_word_pause_ms",
        ),
        settle_ms=_parse_int(
            merged.get("settle_ms"),
            base.settle_ms,
            lo=0,
            hi=15_000,
            name="settle_ms",
        ),
        verify_query=str(merged.get("verify_query") or base.verify_query).strip()
        or base.verify_query,
        capture_before=_parse_bool(merged.get("capture_before"), base.capture_before),
        capture_backend=_parse_capture_backend(
            merged.get("capture_backend"), base.capture_backend
        ),
        webcam_device=str(merged.get("webcam_device") or base.webcam_device).strip()
        or "0",
        wake_audio=str(merged.get("wake_audio") or "").strip(),
        command_audio=str(merged.get("command_audio") or "").strip(),
        confirm_playback=_parse_bool(
            merged.get("confirm_playback"), base.confirm_playback
        ),
    )
