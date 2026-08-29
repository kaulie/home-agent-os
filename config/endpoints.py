"""Load home LAN / cloud endpoint defaults from config/endpoints.json.

Source of truth for Brain + Mac service addresses. Runtime overrides:
  - Mac: MAC_EDGE_BRAIN_URL / MAC_VOICE_BRAIN_URL / .env
  - Mobile: UserDefaults / SharedPreferences (after first save)
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


def repo_root() -> Path:
    """Walk up from this file to the repo root that contains config/endpoints.json."""
    here = Path(__file__).resolve().parent
    if (here / "endpoints.json").is_file():
        return here.parent
    for parent in Path(__file__).resolve().parents:
        if (parent / "config" / "endpoints.json").is_file():
            return parent
    # Fallback: config/ is next to expected layout
    return here.parent


def endpoints_path() -> Path:
    return repo_root() / "config" / "endpoints.json"


@lru_cache(maxsize=1)
def load_endpoints() -> dict[str, Any]:
    path = endpoints_path()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a JSON object")
    return data


def brain_lan_base() -> str:
    brain = load_endpoints().get("brain") or {}
    return str(brain.get("lan") or "").strip().rstrip("/")


def brain_cloud_base() -> str:
    brain = load_endpoints().get("brain") or {}
    return str(brain.get("cloud") or "").strip().rstrip("/")


def brain_url_json() -> str:
    """MAC_EDGE_BRAIN_URL-compatible JSON object."""
    return json.dumps(
        {"lan": brain_lan_base(), "cloud": brain_cloud_base()},
        ensure_ascii=False,
    )


def mac_lan_host() -> str:
    mac = load_endpoints().get("mac") or {}
    return str(mac.get("lan_host") or "").strip()


def mac_service_url(port_key: str) -> str:
    mac = load_endpoints().get("mac") or {}
    host = mac_lan_host()
    port = int(mac.get(port_key) or 0)
    if not host or port <= 0:
        return ""
    return f"http://{host}:{port}"
