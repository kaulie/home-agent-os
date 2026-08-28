"""Standalone store for HomeAgent Admin → agent-bridge tasks (not Brain intents)."""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_TERMINAL = frozenset({"succeeded", "failed", "error", "cancelled"})


def _default_path() -> Path:
    env = (os.environ.get("AGENT_TASK_DATA_PATH") or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parent / "data" / "agent_tasks.json"


@dataclass
class AgentTask:
    task_id: int
    text: str
    status: str = "queued"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    bridge_run_id: str = ""
    bridge_url: str = ""
    bridge_status: str = "queued"
    target_handle: str = ""
    queue_depth: int | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    result: str = ""
    error: str = ""
    status_log: list[dict[str, Any]] = field(default_factory=list)
    thread_id: int = 0
    parent_task_id: int | None = None
    category: str = "other"
    token_usage: dict[str, Any] = field(default_factory=dict)
    attachments: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> AgentTask:
        return cls(
            task_id=int(row["task_id"]),
            text=str(row.get("text") or ""),
            status=str(row.get("status") or "queued"),
            created_at=float(row.get("created_at") or time.time()),
            updated_at=float(row.get("updated_at") or time.time()),
            bridge_run_id=str(row.get("bridge_run_id") or ""),
            bridge_url=str(row.get("bridge_url") or ""),
            bridge_status=str(row.get("bridge_status") or ""),
            target_handle=str(row.get("target_handle") or ""),
            queue_depth=row.get("queue_depth"),
            events=list(row.get("events") or []),
            result=str(row.get("result") or ""),
            error=str(row.get("error") or ""),
            status_log=list(row.get("status_log") or []),
            thread_id=int(row.get("thread_id") or 0),
            parent_task_id=(
                int(row["parent_task_id"])
                if row.get("parent_task_id") is not None
                and str(row.get("parent_task_id")).strip() != ""
                else None
            ),
            category=str(row.get("category") or "other"),
            token_usage=dict(row.get("token_usage") or {}),
            attachments=list(row.get("attachments") or []),
        )


class AgentTaskStore:
    def __init__(self, path: Path | None = None, *, max_tasks: int = 200) -> None:
        self._path = path or _default_path()
        self._max_tasks = max_tasks
        self._lock = threading.Lock()
        self._next_id = 1
        self._tasks: dict[int, AgentTask] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.is_file():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            return
        self._next_id = int(raw.get("next_id") or 1)
        for row in raw.get("tasks") or []:
            if not isinstance(row, dict) or row.get("task_id") is None:
                continue
            task = AgentTask.from_dict(row)
            self._tasks[task.task_id] = task
        if self._tasks:
            self._next_id = max(self._next_id, max(self._tasks) + 1)

    def _persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        rows = sorted(self._tasks.values(), key=lambda t: t.task_id)
        if len(rows) > self._max_tasks:
            rows = rows[-self._max_tasks :]
            self._tasks = {t.task_id: t for t in rows}
        payload = {
            "next_id": self._next_id,
            "tasks": [t.to_dict() for t in rows],
        }
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    def create(
        self,
        text: str,
        *,
        thread_id: int | None = None,
        parent_task_id: int | None = None,
        category: str | None = None,
        attachments: list[dict[str, str]] | None = None,
    ) -> AgentTask:
        now = time.time()
        with self._lock:
            task_id = self._next_id
            self._next_id += 1
            resolved_thread = int(thread_id or 0)
            resolved_category = str(category or "other")
            if parent_task_id is not None:
                parent = self._tasks.get(int(parent_task_id))
                if parent is not None:
                    resolved_thread = int(parent.thread_id or parent.task_id)
                    root = self._tasks.get(resolved_thread) or parent
                    resolved_category = str(root.category or "other")
            else:
                from dev_task_category import normalize_category

                resolved_category = normalize_category(category)
            if resolved_thread <= 0:
                resolved_thread = task_id
            task = AgentTask(
                task_id=task_id,
                text=text,
                status="queued",
                created_at=now,
                updated_at=now,
                thread_id=resolved_thread,
                parent_task_id=parent_task_id,
                category=resolved_category,
                attachments=list(attachments or []),
                status_log=[{"status": "queued", "ts": int(now * 1000)}],
            )
            self._tasks[task_id] = task
            self._persist()
            return AgentTask.from_dict(task.to_dict())


    def set_thread_category(self, thread_id: int, category: str) -> AgentTask | None:
        from dev_task_category import normalize_category

        want = normalize_category(category)
        with self._lock:
            root = self._tasks.get(int(thread_id))
            if root is None:
                return None
            tid = int(root.thread_id or root.task_id)
            root = self._tasks.get(tid)
            if root is None:
                return None
            root.category = want
            root.updated_at = time.time()
            self._persist()
            return AgentTask.from_dict(root.to_dict())

    def get(self, task_id: int) -> AgentTask | None:
        with self._lock:
            task = self._tasks.get(int(task_id))
            return None if task is None else AgentTask.from_dict(task.to_dict())

    def update(self, task_id: int, **fields: Any) -> AgentTask | None:
        with self._lock:
            task = self._tasks.get(int(task_id))
            if task is None:
                return None
            for key, value in fields.items():
                if hasattr(task, key):
                    setattr(task, key, value)
            task.updated_at = time.time()
            self._persist()
            return AgentTask.from_dict(task.to_dict())

    def append_status(self, task_id: int, status: str, *, msg: str = "") -> None:
        with self._lock:
            task = self._tasks.get(int(task_id))
            if task is None:
                return
            if task.status != status:
                task.status = status
                entry: dict[str, Any] = {"status": status, "ts": int(time.time() * 1000)}
                if msg:
                    entry["msg"] = msg
                task.status_log.append(entry)
            task.updated_at = time.time()
            self._persist()

    def list_tasks(
        self,
        *,
        before_id: int | None = None,
        limit: int = 30,
        thread_id: int | None = None,
        roots_only: bool = False,
        category: str | None = None,
    ) -> tuple[list[AgentTask], bool]:
        limit = max(1, min(int(limit), 100))
        with self._lock:
            rows = sorted(self._tasks.values(), key=lambda t: t.task_id, reverse=True)
            if thread_id is not None:
                tid = int(thread_id)
                rows = [t for t in rows if int(t.thread_id or t.task_id) == tid]
                rows = sorted(rows, key=lambda t: t.created_at)
                exhausted = len(rows) <= limit
                return [AgentTask.from_dict(t.to_dict()) for t in rows[:limit]], exhausted
            if roots_only:
                rows = [t for t in rows if t.parent_task_id is None]
            if category is not None:
                from dev_task_category import normalize_category

                want = normalize_category(category)
                rows = [t for t in rows if normalize_category(t.category) == want]
            if before_id is not None:
                rows = [t for t in rows if t.task_id < int(before_id)]
            exhausted = len(rows) <= limit
            return [AgentTask.from_dict(t.to_dict()) for t in rows[:limit]], exhausted

    def usage_summary(
        self,
        *,
        since: float | None = None,
        until: float | None = None,
    ) -> dict[str, Any]:
        from dev_task_category import category_meta, normalize_category
        from token_usage import add_usage, empty_usage_summary, normalize_token_usage

        with self._lock:
            rows = list(self._tasks.values())
        totals = empty_usage_summary()
        task_count = 0
        by_category: dict[str, dict[str, Any]] = {}
        for task in rows:
            ts = float(task.created_at or 0)
            if since is not None and ts < since:
                continue
            if until is not None and ts >= until:
                continue
            usage = normalize_token_usage(task.token_usage)
            if not usage:
                continue
            task_count += 1
            add_usage(totals, usage)
            cat = normalize_category(task.category)
            bucket = by_category.setdefault(
                cat,
                {"task_count": 0, **empty_usage_summary()},
            )
            bucket["task_count"] = int(bucket["task_count"]) + 1
            add_usage(bucket, usage)

        categories = []
        for cat, bucket in sorted(
            by_category.items(),
            key=lambda item: int(item[1].get("total_tokens") or 0),
            reverse=True,
        ):
            categories.append({**category_meta(cat), **bucket})
        return {
            "task_count": task_count,
            **totals,
            "by_category": categories,
        }

    def usage_by_time(
        self,
        *,
        since: float | None = None,
        until: float | None = None,
        granularity: str = "day",
    ) -> list[dict[str, Any]]:
        from dev_task_usage_period import bucket_for_timestamp, bucket_label
        from token_usage import add_usage, empty_usage_summary, normalize_token_usage

        with self._lock:
            rows = list(self._tasks.values())
        buckets: dict[str, dict[str, Any]] = {}
        for task in rows:
            ts = float(task.created_at or 0)
            if since is not None and ts < since:
                continue
            if until is not None and ts >= until:
                continue
            usage = normalize_token_usage(task.token_usage)
            if not usage:
                continue
            key = bucket_for_timestamp(ts, granularity)
            bucket = buckets.setdefault(
                key,
                {
                    "bucket_key": key,
                    "bucket_label": bucket_label(key, granularity),
                    "task_count": 0,
                    **empty_usage_summary(),
                },
            )
            bucket["task_count"] = int(bucket["task_count"]) + 1
            add_usage(bucket, usage)
        return sorted(buckets.values(), key=lambda item: str(item["bucket_key"]))


_STORE: AgentTaskStore | None = None
_STORE_LOCK = threading.Lock()


def get_store() -> AgentTaskStore:
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            _STORE = AgentTaskStore()
        return _STORE


def reset_store(path: Path | None = None) -> AgentTaskStore:
    global _STORE
    with _STORE_LOCK:
        _STORE = AgentTaskStore(path=path)
        return _STORE
