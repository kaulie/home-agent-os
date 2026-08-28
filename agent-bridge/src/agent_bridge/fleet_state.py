"""Per-handle cursor-agent session state."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_bridge.fleet_handles import DEFAULT_HANDLE, FLEET_HANDLES


@dataclass
class HandleState:
    handle: str
    agent_id: str | None = None
    last_wake_at: float | None = None
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "handle": self.handle,
            "agent_id": self.agent_id,
            "last_wake_at": self.last_wake_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, handle: str, data: dict[str, Any]) -> HandleState:
        return cls(
            handle=handle,
            agent_id=data.get("agent_id"),
            last_wake_at=data.get("last_wake_at"),
            updated_at=float(data.get("updated_at") or time.time()),
        )


class FleetStateStore:
    def __init__(self, data_dir: Path) -> None:
        self._dir = data_dir / "agents"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._cache: dict[str, HandleState] = {}

    def _path(self, handle: str) -> Path:
        return self._dir / f"{handle}.json"

    def _load_locked(self, handle: str) -> HandleState:
        if handle in self._cache:
            return self._cache[handle]
        path = self._path(handle)
        if path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                state = HandleState.from_dict(handle, raw if isinstance(raw, dict) else {})
            except (json.JSONDecodeError, TypeError, ValueError):
                state = HandleState(handle=handle)
        else:
            state = HandleState(handle=handle)
        self._cache[handle] = state
        return state

    def _persist_locked(self, state: HandleState) -> None:
        state.updated_at = time.time()
        path = self._path(state.handle)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(state.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)
        self._cache[state.handle] = state

    def get_agent_id(self, handle: str) -> str | None:
        with self._lock:
            return self._load_locked(handle).agent_id

    def set_agent_id(self, handle: str, agent_id: str | None) -> None:
        with self._lock:
            state = self._load_locked(handle)
            state.agent_id = agent_id
            self._persist_locked(state)

    def touch_wake(self, handle: str) -> None:
        with self._lock:
            state = self._load_locked(handle)
            state.last_wake_at = time.time()
            self._persist_locked(state)

    def snapshot(self, handle: str) -> HandleState:
        with self._lock:
            return HandleState.from_dict(handle, self._load_locked(handle).to_dict())

    def list_handles(self) -> list[HandleState]:
        with self._lock:
            return [self._load_locked(h) for h in FLEET_HANDLES]

    def migrate_legacy_agent_id(self, legacy_agent_id: str | None) -> None:
        """Move single global agent_id from bridge_state.json into controller pool."""
        if not legacy_agent_id:
            return
        with self._lock:
            state = self._load_locked(DEFAULT_HANDLE)
            if state.agent_id:
                return
            state.agent_id = legacy_agent_id
            self._persist_locked(state)
