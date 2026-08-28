from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mac_edge.plugins.chromecast_display import DEFAULT_CAST_DISPLAY_URL
from mac_edge.services import default_services

_DEFAULT_BRAIN_URL = "http://127.0.0.1:9527"
_DOMAIN_ORDER = ("lan", "cloud")


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


def _load_dotenv(root: Path) -> None:
    """Load KEY=VALUE from project `.env` if present. Existing env wins."""
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


@dataclass(frozen=True)
class Identity:
    client_hint: str = "living-room-mac"
    display_name: str = "客厅 · Mac Edge"
    device_type: str = "mac"
    room: str = "living-room"
    app_version: str = "0.3.0"
    services: list[dict[str, Any]] = field(default_factory=default_services)
    # P0 dual-Brain: stable Runtime Identity (generated+persisted by agent).
    # None = agent will load/generate it from data_dir/runtime_id.json.
    runtime_id: str | None = None
    # P0 Capability Exposure Policy: {lan:[cap...], cloud:[cap...]}.
    # None = open by default (backward compatible).
    exposure_policy: dict[str, list[str]] | None = None


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
    # P0 dual-Brain: primary URL (lan if present) + full list.
    brain_base_url: str
    brain_base_urls: tuple[str, ...] = ()
    # Domain → URL when MAC_EDGE_BRAIN_URL is a JSON object {"lan": "...", "cloud": "..."}.
    brain_urls_by_domain: dict[str, str] = field(default_factory=dict)
    interval_sec: float = 3.0
    identity: Identity = field(default_factory=Identity)
    data_dir: Path = field(default_factory=lambda: _project_root() / "data")
    # External Cast HTTP base (no query). Plugin appends ?url=.
    cast_display_url: str = DEFAULT_CAST_DISPLAY_URL
    # Empty = no status pin (need intent_dispatched / running for multi-tick / step 2).
    intent_status: str = ""
    http_timeout_sec: float = 20.0
    display_http_timeout_sec: float = 60.0
    query_http_timeout_sec: float = 90.0
    # Wall-clock cap per capability execution (one-shot or one recurring beat).
    capability_timeout_sec: float = 300.0
    intranet_ping: IntranetPingSettings = field(default_factory=IntranetPingSettings)

    def __post_init__(self) -> None:
        url = (self.brain_base_url or "").rstrip("/")
        urls = tuple(u.rstrip("/") for u in self.brain_base_urls if u)
        if not urls and url:
            object.__setattr__(self, "brain_base_urls", (url,))
        elif urls and not url:
            object.__setattr__(self, "brain_base_url", urls[0])

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

    @property
    def runtime_id_path(self) -> Path:
        return self.data_dir / "runtime_id.json"

    def for_brain(self, base_url: str) -> "Config":
        """Clone this config pinned to a single Brain URL (for per-Brain clients)."""
        from dataclasses import replace
        url = base_url.rstrip("/")
        domain_map = {d: u for d, u in self.brain_urls_by_domain.items() if u == url}
        return replace(self, brain_base_url=url, brain_base_urls=(url,), brain_urls_by_domain=domain_map)


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


def parse_brain_url_env(raw: str) -> tuple[tuple[str, ...], dict[str, str]]:
    """Parse MAC_EDGE_BRAIN_URL: a single URL, or JSON {"lan": "...", "cloud": "..."}.

    Returns (ordered urls, domain → url). Primary is lan when present, else first.
    Empty raw → empty urls. Raises ValueError on invalid JSON object form.
    """
    text = (raw or "").strip()
    if not text:
        return (), {}
    if text.startswith("{"):
        try:
            obj = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"MAC_EDGE_BRAIN_URL is not valid JSON: {e}") from e
        if not isinstance(obj, dict):
            raise ValueError("MAC_EDGE_BRAIN_URL JSON must be an object of domain → url")
        by_domain: dict[str, str] = {}
        for key, value in obj.items():
            domain = str(key).strip().lower()
            url = str(value or "").strip().rstrip("/")
            if domain and url:
                by_domain[domain] = url
        urls: list[str] = []
        seen: set[str] = set()
        for domain in _DOMAIN_ORDER:
            url = by_domain.get(domain)
            if url and url not in seen:
                urls.append(url)
                seen.add(url)
        for url in by_domain.values():
            if url not in seen:
                urls.append(url)
                seen.add(url)
        if not urls:
            raise ValueError("MAC_EDGE_BRAIN_URL JSON object has no Brain URLs")
        return tuple(urls), by_domain
    url = text.rstrip("/")
    return ((url,) if url else ()), {}


def primary_brain_url(raw: str | None = None, *, default: str = _DEFAULT_BRAIN_URL) -> str:
    """Single Brain URL for callers that cannot dual-register (voice, probe).

    Prefers lan when MAC_EDGE_BRAIN_URL is a JSON domain map.
    """
    text = default if raw is None else raw
    urls, by_domain = parse_brain_url_env(text)
    if by_domain.get("lan"):
        return by_domain["lan"]
    if urls:
        return urls[0]
    return default.rstrip("/")


def _resolve_brain_urls() -> tuple[tuple[str, ...], dict[str, str]]:
    """JSON object on MAC_EDGE_BRAIN_URL wins; else MAC_EDGE_BRAIN_URLS; else single URL."""
    raw = os.environ.get("MAC_EDGE_BRAIN_URL", "").strip()
    urls, by_domain = parse_brain_url_env(raw) if raw else ((), {})
    if by_domain:
        return urls, by_domain
    urls_raw = os.environ.get("MAC_EDGE_BRAIN_URLS", "").strip()
    if urls_raw:
        listed = tuple(u.strip().rstrip("/") for u in urls_raw.split(",") if u.strip())
        if listed:
            return listed, {}
    if urls:
        return urls, {}
    return (_DEFAULT_BRAIN_URL,), {}


def load_config() -> Config:
    root = _project_root()
    _load_dotenv(root)
    data_dir = Path(
        os.environ.get("MAC_EDGE_DATA_DIR", str(root / "data"))
    ).expanduser()
    interval = float(os.environ.get("MAC_EDGE_INTERVAL_SEC", "3"))
    brain_urls, by_domain = _resolve_brain_urls()
    primary = brain_urls[0]

    # P0 Capability Exposure Policy: MAC_EDGE_EXPOSURE_POLICY="lan:cap1,cap2;cloud:cap3"
    exposure_policy: dict[str, list[str]] | None = None
    ep_raw = os.environ.get("MAC_EDGE_EXPOSURE_POLICY", "").strip()
    if ep_raw:
        exposure_policy = {}
        for part in ep_raw.split(";"):
            if ":" not in part:
                continue
            dom, _, caps = part.partition(":")
            dom = dom.strip().lower()
            if not dom:
                continue
            exposure_policy[dom] = [c.strip() for c in caps.split(",") if c.strip()]
        if not exposure_policy:
            exposure_policy = None

    runtime_id_env = os.environ.get("MAC_EDGE_RUNTIME_ID", "").strip() or None

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
    query_timeout = float(os.environ.get("MAC_EDGE_QUERY_TIMEOUT_SEC", "90"))
    cap_timeout = float(os.environ.get("MAC_EDGE_CAPABILITY_TIMEOUT_SEC", "300"))

    identity = Identity(
        client_hint=os.environ.get("MAC_EDGE_CLIENT_HINT", "living-room-mac").strip()
        or "living-room-mac",
        display_name=os.environ.get("MAC_EDGE_DISPLAY_NAME", "客厅 · Mac Edge").strip()
        or "客厅 · Mac Edge",
        device_type=os.environ.get("MAC_EDGE_DEVICE_TYPE", "mac").strip() or "mac",
        room=os.environ.get("MAC_EDGE_ROOM", "living-room").strip() or "living-room",
        app_version=os.environ.get("MAC_EDGE_APP_VERSION", "0.3.0").strip() or "0.3.0",
        services=default_services(),
        runtime_id=runtime_id_env,
        exposure_policy=exposure_policy,
    )

    return Config(
        brain_base_url=primary,
        brain_base_urls=brain_urls,
        brain_urls_by_domain=dict(by_domain),
        interval_sec=max(3.0, interval),
        identity=identity,
        data_dir=data_dir,
        cast_display_url=cast_display_url.rstrip("/"),
        intent_status=intent_status,
        query_http_timeout_sec=max(30.0, query_timeout),
        capability_timeout_sec=max(30.0, min(cap_timeout, 3600.0)),
        intranet_ping=_load_intranet_ping(root),
    )
