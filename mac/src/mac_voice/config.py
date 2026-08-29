from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from mac_voice.wake import (
    DEFAULT_COMMAND_WINDOW_MS,
    DEFAULT_DOUBLE_WAKE_MS,
    DEFAULT_PARTIAL_WAKE_MS,
    DEFAULT_WAKE_ACK,
    DEFAULT_WAKE_ALIASES,
    DEFAULT_WAKE_REPEAT,
    DEFAULT_WAKE_WORD,
)


def _project_root() -> Path:
    # src/mac_voice/config.py → parents[2] = mac/
    return Path(__file__).resolve().parents[2]


def _load_dotenv(root: Path) -> None:
    path = root / ".env"
    if not path.is_file():
        return
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ[key] = value


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


LISTEN_MODES = frozenset({"always_on", "wait_command", "wake_word"})


@dataclass(frozen=True)
class VoiceConfig:
    brain_url: str
    client_hint: str
    display_name: str
    device_type: str
    room: str
    app_version: str
    data_dir: Path
    edge_id_path: Path
    listen_mode: str
    stt_provider: str
    sauc_api_key: str
    sauc_app_key: str
    sauc_access_key: str
    sauc_url: str
    sauc_resource_id: str
    sauc_seg_duration_ms: int
    input_device: int | str | None
    energy_threshold: float
    silence_ms: int
    min_speech_ms: int
    max_speech_ms: int
    wake_word: str
    wake_repeat: int
    wake_aliases: tuple[str, ...]
    command_window_ms: int
    partial_wake_ms: int
    double_wake_ms: int
    wake_ack: str
    pickup_ingest_enabled: bool
    pickup_ingest_host: str
    pickup_ingest_port: int
    stt_wav_dir: Path | None
    stt_wav_keep: bool
    stt_wav_max_age_hours: float
    stt_wav_max_files: int
    stt_wav_max_mb: float


def _parse_device(raw: str) -> int | str | None:
    raw = (raw or "").strip().strip("\"'")
    if not raw:
        return 0
    try:
        return int(raw)
    except ValueError:
        return raw


def _parse_int(raw: str, default: int, *, lo: int, hi: int) -> int:
    try:
        value = int((raw or "").strip() or default)
    except ValueError:
        return default
    return max(lo, min(hi, value))


def _parse_aliases(raw: str) -> tuple[str, ...]:
    parts = tuple(p.strip() for p in (raw or "").split(",") if p.strip())
    return parts or DEFAULT_WAKE_ALIASES


def _parse_float(raw: str, default: float, *, lo: float, hi: float) -> float:
    try:
        value = float((raw or "").strip() or default)
    except ValueError:
        return default
    return max(lo, min(hi, value))


def _parse_stt_wav_dir(raw: str, data_dir: Path) -> Path | None:
    """Empty → system temp. `default` → data_dir/stt_wav. Else expand path."""
    text = (raw or "").strip()
    if not text:
        return None
    if text.lower() in ("1", "true", "yes", "on", "default"):
        return data_dir / "stt_wav"
    return Path(text).expanduser()


def _brain_wake_ack(brain_url: str) -> str | None:
    try:
        import httpx
    except ImportError:
        return None
    url = f"{brain_url.rstrip('/')}/api/v1/voice/settings"
    try:
        with httpx.Client(timeout=3.0) as client:
            resp = client.get(url)
        if resp.status_code >= 400:
            return None
        data = resp.json()
    except Exception:
        return None
    if not isinstance(data, dict) or not data.get("ok"):
        return None
    ack = str(data.get("wake_ack") or "").strip()
    return ack or None


def load_config() -> VoiceConfig:
    root = _project_root()
    _load_dotenv(root)
    data_dir = Path(_env("MAC_VOICE_DATA_DIR", str(root / "data" / "mac_voice"))).expanduser()
    edge_data = Path(_env("MAC_EDGE_DATA_DIR", str(root / "data"))).expanduser()
    brain_raw = _env("MAC_VOICE_BRAIN_URL") or _env("MAC_EDGE_BRAIN_URL")
    from mac_edge.config import _resolve_brain_urls, primary_brain_url

    if brain_raw:
        brain = primary_brain_url(brain_raw)
    else:
        urls, _ = _resolve_brain_urls()
        brain = urls[0] if urls else "http://127.0.0.1:9527"
    seg = int(_env("MAC_VOICE_SAUC_SEG_DURATION_MS", "200") or "200")
    # Same hint as Mac Runtime — voice is not a separate participant.
    client_hint = (
        _env("MAC_VOICE_CLIENT_HINT")
        or _env("MAC_EDGE_CLIENT_HINT", "living-room-mac")
        or "living-room-mac"
    )
    mode = (_env("MAC_VOICE_LISTEN_MODE", "wake_word") or "wake_word").strip().lower()
    if mode not in LISTEN_MODES:
        raise ValueError(
            f"MAC_VOICE_LISTEN_MODE={mode!r} invalid; expected one of {sorted(LISTEN_MODES)}"
        )
    wake_word = _env("MAC_VOICE_WAKE_WORD", DEFAULT_WAKE_WORD) or DEFAULT_WAKE_WORD
    wake_ack_env = _env("MAC_VOICE_WAKE_ACK")
    if wake_ack_env:
        wake_ack = wake_ack_env
    else:
        wake_ack = _brain_wake_ack(brain) or DEFAULT_WAKE_ACK
    return VoiceConfig(
        brain_url=brain.rstrip("/"),
        client_hint=client_hint,
        display_name=_env("MAC_VOICE_DISPLAY_NAME")
        or _env("MAC_EDGE_DISPLAY_NAME", "客厅 · Mac Edge")
        or "客厅 · Mac Edge",
        device_type=_env("MAC_VOICE_DEVICE_TYPE", "mac") or "mac",
        room=_env("MAC_VOICE_ROOM") or _env("MAC_EDGE_ROOM", "living-room") or "living-room",
        app_version=_env("MAC_VOICE_APP_VERSION", "0.2.0") or "0.2.0",
        data_dir=data_dir,
        edge_id_path=edge_data / "edge_id.json",
        listen_mode=mode,
        stt_provider=_env("MAC_VOICE_STT_PROVIDER", "volc_sauc") or "volc_sauc",
        sauc_api_key=_env("MAC_VOICE_SAUC_API_KEY"),
        sauc_app_key=_env("MAC_VOICE_SAUC_APP_KEY"),
        sauc_access_key=_env("MAC_VOICE_SAUC_ACCESS_KEY"),
        sauc_url=_env(
            "MAC_VOICE_SAUC_URL",
            "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async",
        )
        or "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async",
        sauc_resource_id=_env("MAC_VOICE_SAUC_RESOURCE_ID", "volc.seedasr.sauc.duration")
        or "volc.seedasr.sauc.duration",
        sauc_seg_duration_ms=max(50, seg),
        input_device=_parse_device(_env("MAC_VOICE_INPUT_DEVICE", "0")),
        energy_threshold=float(_env("MAC_VOICE_ENERGY_THRESHOLD", "500") or "500"),
        silence_ms=int(_env("MAC_VOICE_SILENCE_MS", "1000") or "1000"),
        min_speech_ms=int(_env("MAC_VOICE_MIN_SPEECH_MS", "400") or "400"),
        max_speech_ms=int(_env("MAC_VOICE_MAX_SPEECH_MS", "8000") or "8000"),
        wake_word=wake_word,
        wake_repeat=_parse_int(
            _env("MAC_VOICE_WAKE_REPEAT"),
            DEFAULT_WAKE_REPEAT,
            lo=1,
            hi=5,
        ),
        wake_aliases=_parse_aliases(_env("MAC_VOICE_WAKE_ALIASES")),
        command_window_ms=_parse_int(
            _env("MAC_VOICE_COMMAND_WINDOW_MS"),
            DEFAULT_COMMAND_WINDOW_MS,
            lo=500,
            hi=60_000,
        ),
        partial_wake_ms=_parse_int(
            _env("MAC_VOICE_PARTIAL_WAKE_MS"),
            DEFAULT_PARTIAL_WAKE_MS,
            lo=200,
            hi=15_000,
        ),
        double_wake_ms=_parse_int(
            _env("MAC_VOICE_DOUBLE_WAKE_MS"),
            DEFAULT_DOUBLE_WAKE_MS,
            lo=400,
            hi=4000,
        ),
        wake_ack=wake_ack,
        pickup_ingest_enabled=_env("MAC_VOICE_PICKUP_INGEST", "1").lower()
        not in ("0", "false", "no", "off"),
        pickup_ingest_host=_env("MAC_VOICE_PICKUP_INGEST_HOST", "0.0.0.0") or "0.0.0.0",
        pickup_ingest_port=_parse_int(
            _env("MAC_VOICE_PICKUP_INGEST_PORT"),
            8792,
            lo=1,
            hi=65535,
        ),
        stt_wav_dir=_parse_stt_wav_dir(_env("MAC_VOICE_STT_WAV_DIR"), data_dir),
        stt_wav_keep=_env("MAC_VOICE_STT_WAV_KEEP", "0").lower()
        in ("1", "true", "yes", "on"),
        stt_wav_max_age_hours=_parse_float(
            _env("MAC_VOICE_STT_WAV_MAX_AGE_HOURS"),
            24.0,
            lo=0.0,
            hi=24.0 * 365,
        ),
        stt_wav_max_files=_parse_int(
            _env("MAC_VOICE_STT_WAV_MAX_FILES"),
            100,
            lo=0,
            hi=100_000,
        ),
        stt_wav_max_mb=_parse_float(
            _env("MAC_VOICE_STT_WAV_MAX_MB"),
            200.0,
            lo=0.0,
            hi=100_000.0,
        ),
    )
