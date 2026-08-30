from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from agent_bridge.fleet_handles import DEFAULT_HANDLE

RunStatus = Literal["queued", "running", "finished", "error", "cancelled"]


@dataclass
class RunRecord:
    run_id: str
    text: str
    status: RunStatus = "queued"
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    agent_id: str | None = None
    result: str | None = None
    error: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    attachments: list[dict[str, str]] = field(default_factory=list)
    task_id: int | None = None
    target_handle: str = DEFAULT_HANDLE
    brain_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BridgeState:
    agent_id: str | None = None
    runs: list[RunRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "runs": [run.to_dict() for run in self.runs],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BridgeState:
        runs = []
        for row in data.get("runs", []):
            if not isinstance(row, dict):
                continue
            runs.append(
                RunRecord(
                    run_id=str(row.get("run_id") or ""),
                    text=str(row.get("text") or ""),
                    status=row.get("status") or "queued",
                    created_at=float(row.get("created_at") or time.time()),
                    started_at=row.get("started_at"),
                    finished_at=row.get("finished_at"),
                    agent_id=row.get("agent_id"),
                    result=row.get("result"),
                    error=row.get("error"),
                    events=list(row.get("events") or []),
                    usage=dict(row.get("usage") or {}),
                    attachments=list(row.get("attachments") or []),
                    task_id=row.get("task_id"),
                    target_handle=str(row.get("target_handle") or DEFAULT_HANDLE),
                    brain_url=str(row.get("brain_url") or ""),
                )
            )
        return cls(agent_id=data.get("agent_id"), runs=runs)


class StateStore:
    def __init__(self, data_dir: Path, *, max_runs: int = 50) -> None:
        self._path = data_dir / "bridge_state.json"
        self._max_runs = max_runs
        self._lock = threading.Lock()
        self._state = BridgeState()
        self._load()

    def _load(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.is_file():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            self._state = BridgeState.from_dict(raw)
        except (json.JSONDecodeError, TypeError, ValueError):
            self._state = BridgeState()

    def _persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(self._state.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self._path)

    def snapshot(self) -> BridgeState:
        with self._lock:
            return BridgeState.from_dict(self._state.to_dict())

    def get_agent_id(self) -> str | None:
        with self._lock:
            return self._state.agent_id

    def set_agent_id(self, agent_id: str | None) -> None:
        with self._lock:
            self._state.agent_id = agent_id
            self._persist()

    def create_run(
        self,
        text: str,
        *,
        attachments: list[dict[str, str]] | None = None,
        task_id: int | None = None,
        target_handle: str = DEFAULT_HANDLE,
        brain_url: str | None = None,
    ) -> RunRecord:
        run = RunRecord(
            run_id=uuid.uuid4().hex,
            text=text,
            attachments=list(attachments or []),
            task_id=task_id,
            target_handle=target_handle,
            brain_url=str(brain_url or "").strip().rstrip("/"),
        )
        with self._lock:
            self._state.runs.append(run)
            if len(self._state.runs) > self._max_runs:
                self._state.runs = self._state.runs[-self._max_runs :]
            self._persist()
        return run

    def update_run(self, run_id: str, **fields: Any) -> RunRecord | None:
        with self._lock:
            run = self._find_run_locked(run_id)
            if run is None:
                return None
            for key, value in fields.items():
                setattr(run, key, value)
            self._persist()
            return RunRecord(**run.to_dict())

    def append_event(self, run_id: str, event: dict[str, Any]) -> None:
        with self._lock:
            run = self._find_run_locked(run_id)
            if run is None:
                return
            run.events.append(event)
            self._persist()

    def get_run(self, run_id: str) -> RunRecord | None:
        with self._lock:
            run = self._find_run_locked(run_id)
            return None if run is None else RunRecord(**run.to_dict())

    def list_runs(self, *, limit: int = 20) -> list[RunRecord]:
        with self._lock:
            rows = self._state.runs[-limit:]
            return [RunRecord(**row.to_dict()) for row in reversed(rows)]

    def active_run(self) -> RunRecord | None:
        with self._lock:
            for run in reversed(self._state.runs):
                if run.status in ("queued", "running"):
                    return RunRecord(**run.to_dict())
            return None

    def running_run(self) -> RunRecord | None:
        with self._lock:
            for run in reversed(self._state.runs):
                if run.status == "running":
                    return RunRecord(**run.to_dict())
            return None

    def running_run_for_handle(self, handle: str) -> RunRecord | None:
        with self._lock:
            for run in reversed(self._state.runs):
                if run.status == "running" and run.target_handle == handle:
                    return RunRecord(**run.to_dict())
            return None

    def queued_runs(self) -> list[RunRecord]:
        with self._lock:
            return [
                RunRecord(**run.to_dict())
                for run in self._state.runs
                if run.status == "queued"
            ]

    def _find_run_locked(self, run_id: str) -> RunRecord | None:
        for run in self._state.runs:
            if run.run_id == run_id:
                return run
        return None
