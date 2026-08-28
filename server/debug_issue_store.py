"""Persistent store for Agent Debug Gateway issues (User/Business → Dev Task)."""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from debug_attachments import normalize_attachments

_TERMINAL = frozenset({"failed", "resolved", "cancelled"})


def _default_path() -> Path:
    env = (os.environ.get("DEBUG_ISSUE_DATA_PATH") or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parent / "data" / "debug_issues.json"


@dataclass
class DebugIssue:
    issue_id: int
    intent_id: int
    session_id: str = ""
    source: str = "user_console"
    participant_id: str = ""
    status: str = "submitted"
    task_id: int | None = None
    user_summary: str = ""
    problem_type: str = ""
    attachments: list[dict[str, str]] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> DebugIssue:
        task_raw = row.get("task_id")
        task_id = int(task_raw) if task_raw is not None and str(task_raw).strip() != "" else None
        attachments = normalize_attachments(row.get("attachments"))
        if not attachments:
            attachments = normalize_attachments(row.get("attachment_asset_ids"))
        return cls(
            issue_id=int(row["issue_id"]),
            intent_id=int(row["intent_id"]),
            session_id=str(row.get("session_id") or ""),
            source=str(row.get("source") or "user_console"),
            participant_id=str(row.get("participant_id") or ""),
            status=str(row.get("status") or "submitted"),
            task_id=task_id,
            user_summary=str(row.get("user_summary") or ""),
            problem_type=str(row.get("problem_type") or ""),
            attachments=attachments,
            context=dict(row.get("context") or {}),
            error=str(row.get("error") or ""),
            created_at=float(row.get("created_at") or time.time()),
            updated_at=float(row.get("updated_at") or time.time()),
        )


class DebugIssueStore:
    def __init__(self, path: Path | None = None, *, max_issues: int = 500) -> None:
        self._path = path or _default_path()
        self._max_issues = max_issues
        self._lock = threading.Lock()
        self._next_id = 1
        self._issues: dict[int, DebugIssue] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.is_file():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            return
        self._next_id = int(raw.get("next_id") or 1)
        for row in raw.get("issues") or []:
            if not isinstance(row, dict) or row.get("issue_id") is None:
                continue
            issue = DebugIssue.from_dict(row)
            self._issues[issue.issue_id] = issue

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "next_id": self._next_id,
            "issues": [i.to_dict() for i in sorted(self._issues.values(), key=lambda x: x.issue_id)],
        }
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    def create(
        self,
        *,
        intent_id: int,
        session_id: str = "",
        source: str = "user_console",
        participant_id: str = "",
        user_summary: str = "",
        problem_type: str = "",
        attachments: list[dict[str, str]] | None = None,
        context: dict[str, Any] | None = None,
    ) -> DebugIssue:
        with self._lock:
            issue_id = self._next_id
            self._next_id += 1
            issue = DebugIssue(
                issue_id=issue_id,
                intent_id=intent_id,
                session_id=session_id,
                source=source,
                participant_id=participant_id,
                user_summary=user_summary,
                problem_type=problem_type.strip(),
                attachments=normalize_attachments(attachments or []),
                context=context or {},
            )
            self._issues[issue_id] = issue
            if len(self._issues) > self._max_issues:
                oldest = sorted(self._issues.values(), key=lambda x: x.issue_id)
                for stale in oldest[: len(self._issues) - self._max_issues]:
                    self._issues.pop(stale.issue_id, None)
            self._save()
            return issue

    def get(self, issue_id: int) -> DebugIssue | None:
        with self._lock:
            return self._issues.get(int(issue_id))

    def update(self, issue_id: int, **fields: Any) -> DebugIssue | None:
        with self._lock:
            issue = self._issues.get(int(issue_id))
            if issue is None:
                return None
            for key, value in fields.items():
                if key == "task_id" and value is not None:
                    issue.task_id = int(value)
                elif key == "context" and isinstance(value, dict):
                    issue.context = value
                elif key == "attachments":
                    issue.attachments = normalize_attachments(value)
                elif hasattr(issue, key):
                    setattr(issue, key, value)
            issue.updated_at = time.time()
            self._save()
            return issue

    def list_issues(
        self,
        *,
        before_id: int | None = None,
        limit: int = 30,
        intent_id: int | None = None,
    ) -> tuple[list[DebugIssue], bool]:
        with self._lock:
            rows = sorted(self._issues.values(), key=lambda x: x.issue_id, reverse=True)
        if intent_id is not None:
            rows = [r for r in rows if r.intent_id == int(intent_id)]
        if before_id is not None:
            rows = [r for r in rows if r.issue_id < int(before_id)]
        exhausted = len(rows) <= limit
        return rows[:limit], exhausted


_store: DebugIssueStore | None = None


def get_store(path: Path | None = None) -> DebugIssueStore:
    global _store
    if _store is None:
        _store = DebugIssueStore(path)
    return _store


def reset_store(path: Path | None = None) -> DebugIssueStore:
    global _store
    _store = DebugIssueStore(path)
    return _store
