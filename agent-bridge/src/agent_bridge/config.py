from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        os.environ.setdefault(key, value)


def _resolve_cursor_agent_bin() -> str | None:
    override = (os.environ.get("CURSOR_AGENT_BIN") or "").strip()
    if override:
        return override
    return shutil.which("cursor-agent")


def _normalize_api_key(raw: str | None) -> str | None:
    if raw is None:
        return None
    value = raw.strip()
    if not value or value in {"cursor_...", "cursor_…"}:
        return None
    return value


@dataclass(frozen=True)
class BridgeConfig:
    host: str
    port: int
    cwd: Path
    data_dir: Path
    model: str
    api_key: str | None
    auth_token: str | None
    cursor_agent_bin: str | None
    backend_preference: str = ""
    brain_url: str = ""
    brain_admin_token: str | None = None

    @property
    def project_root(self) -> Path:
        return self.cwd

    @property
    def backend(self) -> str:
        pref = self.backend_preference.strip().lower()
        if pref == "sdk":
            if self.api_key:
                return "sdk"
            if self.cursor_agent_bin:
                return "cli"
            return "none"
        if pref == "cli":
            if self.cursor_agent_bin:
                return "cli"
            if self.api_key:
                return "sdk"
            return "none"
        # Default: local cursor-agent CLI is more stable for Mac bridge.
        if self.cursor_agent_bin:
            return "cli"
        if self.api_key:
            return "sdk"
        return "none"

    def can_run(self) -> bool:
        return self.backend != "none"


def load_config() -> BridgeConfig:
    here = Path(__file__).resolve().parents[2]
    _load_dotenv(here / ".env")

    project_root = Path(
        os.environ.get("AGENT_BRIDGE_CWD", str(here.parent))
    ).resolve()
    data_dir = Path(
        os.environ.get("AGENT_BRIDGE_DATA_DIR", str(here / "data"))
    ).resolve()

    return BridgeConfig(
        host=os.environ.get("AGENT_BRIDGE_HOST", "127.0.0.1"),
        port=int(os.environ.get("AGENT_BRIDGE_PORT", "9540")),
        cwd=project_root,
        data_dir=data_dir,
        model=os.environ.get("AGENT_BRIDGE_MODEL", "composer-2.5"),
        api_key=_normalize_api_key(os.environ.get("CURSOR_API_KEY")),
        auth_token=os.environ.get("AGENT_BRIDGE_TOKEN"),
        cursor_agent_bin=_resolve_cursor_agent_bin(),
        backend_preference=os.environ.get("AGENT_BRIDGE_BACKEND", ""),
        brain_url=(os.environ.get("AGENT_BRIDGE_BRAIN_URL") or "").strip(),
        brain_admin_token=(os.environ.get("AGENT_BRIDGE_BRAIN_ADMIN_TOKEN") or "").strip() or None,
    )
