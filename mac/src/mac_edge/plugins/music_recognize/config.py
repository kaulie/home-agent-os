"""music.recognize runtime config (env-driven; Mac Edge)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2  # int16

PROVIDER_NONE = "none"
PROVIDER_MOCK = "mock"
PROVIDER_AUDD = "audd"
PROVIDER_ACRCLOUD = "acrcloud"
PROVIDER_SHAZAM = "shazam"
KNOWN_PROVIDERS = (
    PROVIDER_NONE,
    PROVIDER_MOCK,
    PROVIDER_AUDD,
    PROVIDER_ACRCLOUD,
    PROVIDER_SHAZAM,
)

DEFAULT_MIN_SEC = 10.0
DEFAULT_MAX_SEC = 30.0
DEFAULT_RETRY_EVERY_SEC = 5.0

# Bytes of PCM per captured second (16 kHz * 1ch * 2B).
BYTES_PER_SEC = SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _float_env(name: str, default: float, *, lo: float, hi: float) -> float:
    try:
        value = float((os.environ.get(name) or "").strip() or default)
    except (TypeError, ValueError):
        value = default
    return max(lo, min(hi, value))


def _bool_env(name: str, default: bool) -> bool:
    raw = _env(name)
    if not raw:
        return default
    return raw.lower() in ("1", "true", "yes", "on")


def _project_root() -> Path:
    # src/mac_edge/plugins/music_recognize/config.py → parents[4] = mac/
    return Path(__file__).resolve().parents[4]


@dataclass(frozen=True)
class MusicRecognizeConfig:
    provider: str
    min_sec: float
    max_sec: float
    retry_every_sec: float
    input_device: int | str | None
    data_dir: Path
    keep_wav: bool
    wav_dir: Path | None
    signal_threshold: float
    http_timeout_sec: float
    audd_token: str
    acr_access_key: str
    acr_access_secret: str
    acr_host: str
    shazam_key: str
    shazam_host: str

    @property
    def max_bytes(self) -> int:
        return int(self.max_sec * BYTES_PER_SEC)

    @property
    def window_bytes(self) -> int:
        return int(self.min_sec * BYTES_PER_SEC)


def _parse_device(raw: str) -> int | str | None:
    raw = (raw or "").strip().strip("\"'")
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return raw


def provider_name() -> str:
    name = _env("MAC_EDGE_MUSIC_RECOGNIZE_PROVIDER", PROVIDER_NONE).strip().lower()
    if name not in KNOWN_PROVIDERS:
        return PROVIDER_NONE
    return name


def provider_selected() -> bool:
    """Whether the operator intentionally enabled a usable provider.

    mock is always usable once explicitly selected. Real providers additionally
    require their key(s). none → not selected.
    """
    name = provider_name()
    if name == PROVIDER_MOCK:
        return True
    if name == PROVIDER_AUDD:
        return bool(_env("MAC_EDGE_MUSIC_RECOGNIZE_AUDD_TOKEN"))
    if name == PROVIDER_ACRCLOUD:
        return bool(
            _env("MAC_EDGE_MUSIC_RECOGNIZE_ACR_ACCESS_KEY")
            and _env("MAC_EDGE_MUSIC_RECOGNIZE_ACR_ACCESS_SECRET")
            and _env("MAC_EDGE_MUSIC_RECOGNIZE_ACR_HOST")
        )
    if name == PROVIDER_SHAZAM:
        return bool(
            _env("MAC_EDGE_MUSIC_RECOGNIZE_SHAZAM_KEY")
            and _env("MAC_EDGE_MUSIC_RECOGNIZE_SHAZAM_HOST")
        )
    return False


def load_config() -> MusicRecognizeConfig:
    root = _project_root()
    base_dir = Path(_env("MAC_EDGE_DATA_DIR", str(root / "data"))).expanduser()
    data_dir = base_dir / "music_recognize"

    min_sec = _float_env(
        "MAC_EDGE_MUSIC_RECOGNIZE_MIN_SEC", DEFAULT_MIN_SEC, lo=5.0, hi=30.0
    )
    max_sec = max(
        min_sec,
        _float_env(
            "MAC_EDGE_MUSIC_RECOGNIZE_MAX_SEC", DEFAULT_MAX_SEC, lo=10.0, hi=60.0
        ),
    )
    retry_every_sec = min(
        max(1.0, max_sec - min_sec),
        _float_env(
            "MAC_EDGE_MUSIC_RECOGNIZE_RETRY_EVERY_SEC",
            DEFAULT_RETRY_EVERY_SEC,
            lo=1.0,
            hi=15.0,
        ),
    )

    input_device = (
        _env("MAC_EDGE_MUSIC_RECOGNIZE_INPUT_DEVICE")
        or _env("MAC_VOICE_INPUT_DEVICE")
        or "0"
    )
    wav_dir_raw = _env("MAC_EDGE_MUSIC_RECOGNIZE_WAV_DIR")
    wav_dir = (
        Path(wav_dir_raw).expanduser()
        if wav_dir_raw
        else (data_dir / "wav" if _bool_env("MAC_EDGE_MUSIC_RECOGNIZE_WAV_KEEP", False) else None)
    )

    return MusicRecognizeConfig(
        provider=provider_name(),
        min_sec=min_sec,
        max_sec=max_sec,
        retry_every_sec=retry_every_sec,
        input_device=_parse_device(input_device),
        data_dir=data_dir,
        keep_wav=_bool_env("MAC_EDGE_MUSIC_RECOGNIZE_WAV_KEEP", False),
        wav_dir=wav_dir,
        signal_threshold=_float_env(
            "MAC_EDGE_MUSIC_RECOGNIZE_SIGNAL_THRESHOLD", 200.0, lo=0.0, hi=5000.0
        ),
        http_timeout_sec=_float_env(
            "MAC_EDGE_MUSIC_RECOGNIZE_HTTP_TIMEOUT_SEC", 20.0, lo=3.0, hi=120.0
        ),
        audd_token=_env("MAC_EDGE_MUSIC_RECOGNIZE_AUDD_TOKEN"),
        acr_access_key=_env("MAC_EDGE_MUSIC_RECOGNIZE_ACR_ACCESS_KEY"),
        acr_access_secret=_env("MAC_EDGE_MUSIC_RECOGNIZE_ACR_ACCESS_SECRET"),
        acr_host=_env("MAC_EDGE_MUSIC_RECOGNIZE_ACR_HOST"),
        shazam_key=_env("MAC_EDGE_MUSIC_RECOGNIZE_SHAZAM_KEY"),
        shazam_host=_env("MAC_EDGE_MUSIC_RECOGNIZE_SHAZAM_HOST"),
    )
