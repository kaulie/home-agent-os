from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mac_edge.plugins.chromecast_display import DEFAULT_CAST_DISPLAY_URL
from mac_edge.services import default_services


def _project_root() -> Path:
    # src/mac_edge/config.py → parents[2] = project root
    return Path(__file__).resolve().parents[2]


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


@dataclass(frozen=True)
class Identity:
    client_hint: str = "living-room-mac"
    display_name: str = "客厅 · Mac Edge"
    device_type: str = "mac"
    room: str = "living-room"
    app_version: str = "0.3.0"
    services: list[dict[str, Any]] = field(default_factory=default_services)


@dataclass(frozen=True)
class IntranetPingSettings:
    """Runtime LAN ping monitor (not a Brain capability)."""

    enabled: bool = True
    mode: str = "gateway"  # gateway | targets | lan
    targets: tuple[str, ...] = ()
    interval_sec: float = 5.0
    timeout_ms: int = 1000
    discover_interval_sec: float = 300.0
    stats_interval_sec: float = 60.0
    log_path: Path = field(default_factory=lambda: _project_root() / "logs" / "intranet_ping.log")


@dataclass(frozen=True)
class Config:
    brain_base_url: str
    interval_sec: float
    identity: Identity
    data_dir: Path
    # External Cast HTTP base (no query). Plugin appends ?url=.
    cast_display_url: str
    # Empty = no status pin (need intent_dispatched / running for multi-tick / step 2).
    intent_status: str = ""
    http_timeout_sec: float = 20.0
    display_http_timeout_sec: float = 60.0
    intranet_ping: IntranetPingSettings = field(default_factory=IntranetPingSettings)

    @property
    def register_url(self) -> str:
        return f"{self.brain_base_url}/api/v1/edge-register"

    @property
    def heartbeat_url(self) -> str:
        return f"{self.brain_base_url}/api/v1/edge-heartbeat"

    @property
    def intents_url(self) -> str:
        room = self.identity.room
        return f"{self.brain_base_url}/api/v1/devices/{room}/intents"

    @property
    def edge_id_path(self) -> Path:
        return self.data_dir / "edge_id.json"


def _load_intranet_ping(root: Path) -> IntranetPingSettings:
    mode = (
        os.environ.get("MAC_EDGE_INTRANET_PING_MODE", "gateway").strip().lower() or "gateway"
    )
    if mode not in ("gateway", "targets", "lan"):
        mode = "gateway"
    targets_raw = os.environ.get("MAC_EDGE_INTRANET_PING_TARGETS", "").strip()
    targets = tuple(p.strip() for p in targets_raw.split(",") if p.strip())
    interval = _clamp(float(os.environ.get("MAC_EDGE_INTRANET_PING_INTERVAL_SEC", "5")), 1.0, 3600.0)
    timeout_ms = int(_clamp(float(os.environ.get("MAC_EDGE_INTRANET_PING_TIMEOUT_MS", "1000")), 100, 10000))
    discover = _clamp(
        float(os.environ.get("MAC_EDGE_INTRANET_PING_DISCOVER_INTERVAL_SEC", "300")),
        30.0,
        86400.0,
    )
    stats = _clamp(
        float(os.environ.get("MAC_EDGE_INTRANET_PING_STATS_INTERVAL_SEC", "60")),
        10.0,
        3600.0,
    )
    log_env = os.environ.get("MAC_EDGE_INTRANET_PING_LOG", "").strip()
    log_path = Path(log_env).expanduser() if log_env else (root / "logs" / "intranet_ping.log")
    return IntranetPingSettings(
        enabled=_env_bool("MAC_EDGE_INTRANET_PING", True),
        mode=mode,
        targets=targets,
        interval_sec=interval,
        timeout_ms=timeout_ms,
        discover_interval_sec=discover,
        stats_interval_sec=stats,
        log_path=log_path,
    )


def load_config() -> Config:
    root = _project_root()
    data_dir = Path(
        os.environ.get("MAC_EDGE_DATA_DIR", str(root / "data"))
    ).expanduser()
    interval = float(os.environ.get("MAC_EDGE_INTERVAL_SEC", "3"))
    identity = Identity(
        client_hint=os.environ.get("MAC_EDGE_CLIENT_HINT", "living-room-mac").strip()
        or "living-room-mac",
        display_name=os.environ.get("MAC_EDGE_DISPLAY_NAME", "客厅 · Mac Edge").strip()
        or "客厅 · Mac Edge",
        device_type=os.environ.get("MAC_EDGE_DEVICE_TYPE", "mac").strip() or "mac",
        room=os.environ.get("MAC_EDGE_ROOM", "living-room").strip() or "living-room",
        app_version=os.environ.get("MAC_EDGE_APP_VERSION", "0.3.0").strip() or "0.3.0",
        services=default_services(),
    )
    base = os.environ.get("MAC_EDGE_BRAIN_URL", "http://115.190.153.53:9527").strip()
    base = base.rstrip("/")

    cast_display_url = (
        os.environ.get("MAC_EDGE_CAST_DISPLAY_URL", DEFAULT_CAST_DISPLAY_URL).strip()
        or DEFAULT_CAST_DISPLAY_URL
    )
    # Backward-compatible alias
    legacy = os.environ.get("MAC_EDGE_DISPLAY_URL", "").strip()
    if legacy and not os.environ.get("MAC_EDGE_CAST_DISPLAY_URL"):
        cast_display_url = legacy

    # Optional pin; default empty so dispatched intents stay visible for step 2.
    intent_status = os.environ.get("MAC_EDGE_INTENT_STATUS", "").strip()

    return Config(
        brain_base_url=base,
        interval_sec=max(3.0, interval),
        identity=identity,
        data_dir=data_dir,
        cast_display_url=cast_display_url.rstrip("/"),
        intent_status=intent_status,
        intranet_ping=_load_intranet_ping(root),
    )
