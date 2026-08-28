from __future__ import annotations

import logging
import threading
import time
from typing import Any

from cursor_sdk import Agent, AgentOptions, CursorAgentError, LocalAgentOptions

from agent_bridge.attachments import materialize_dev_task_attachments
from agent_bridge.cancel import clear_run, is_cancelled, mark_cancelled
from agent_bridge.chat_notify import notify_dev_task
from agent_bridge.cli_backend import execute_cli_run
from agent_bridge.config import BridgeConfig
from agent_bridge.fleet_handles import DEFAULT_HANDLE, FLEET_HANDLES
from agent_bridge.fleet_state import FleetStateStore
from agent_bridge.state import RunRecord, StateStore

from agent_bridge.session_utils import is_agent_not_found

log = logging.getLogger(__name__)


def _sdk_message_event(message: Any) -> dict[str, Any] | None:
    msg_type = getattr(message, "type", None)
    if msg_type == "assistant":
        content = getattr(getattr(message, "message", None), "content", None) or []
        chunks: list[str] = []
        for block in content:
            if getattr(block, "type", None) == "text":
                chunks.append(getattr(block, "text", ""))
        text = "".join(chunks).strip()
        if text:
            return {"type": "assistant", "text": text, "ts": time.time()}
    if msg_type:
        return {"type": str(msg_type), "ts": time.time()}
    return None


class AgentRunner:
    """Owns Cursor agent lifecycle; one session pool per Fleet handle (CLI or SDK)."""

    def __init__(
        self,
        config: BridgeConfig,
        store: StateStore,
        fleet: FleetStateStore,
    ) -> None:
        self._config = config
        self._store = store
        self._fleet = fleet
        self._agents: dict[str, Agent] = {}
        self._agent_lock = threading.Lock()
        self._run_lock = threading.Lock()
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._queue: list[str] = []
        self._queue_cv = threading.Condition()
        self._shutdown = False
        self._fleet.migrate_legacy_agent_id(self._store.get_agent_id())

    def start(self) -> None:
        self._recover_after_restart()
        self._worker.start()

    def _recover_after_restart(self) -> None:
        snapshot = self._store.snapshot()
        requeue: list[str] = []
        for run in snapshot.runs:
            if run.status == "running":
                log.warning(
                    "recovering orphaned run %s as error after bridge restart",
                    run.run_id,
                )
                notify_dev_task(
                    "failed",
                    handle=run.target_handle,
                    run_id=run.run_id,
                    status="error",
                    detail="bridge restarted while run was active",
                )
                self._store.update_run(
                    run.run_id,
                    status="error",
                    finished_at=time.time(),
                    error="bridge restarted while run was active",
                )
            elif run.status == "queued":
                requeue.append(run.run_id)
        for run_id in requeue:
            log.info("re-queueing persisted run %s after bridge restart", run_id)
            self.enqueue(run_id)

    def shutdown(self) -> None:
        with self._queue_cv:
            self._shutdown = True
            self._queue_cv.notify_all()
        self._worker.join(timeout=5)
        self._close_all_agents()

    def enqueue(self, run_id: str) -> None:
        with self._queue_cv:
            self._queue.append(run_id)
            self._queue_cv.notify()

    def pending_queue_depth(self) -> int:
        with self._queue_cv:
            return len(self._queue)

    def cancel_run(self, run_id: str) -> dict[str, Any] | None:
        record = self._store.get_run(run_id)
        if record is None:
            return None

        status = str(record.status or "")
        if status in ("finished", "error", "cancelled"):
            return {
                "run_id": run_id,
                "status": status,
                "cancelled": False,
                "reason": "already_terminal",
            }

        if status == "queued":
            with self._queue_cv:
                try:
                    self._queue.remove(run_id)
                except ValueError:
                    pass
            current = self._store.get_run(run_id)
            if current is not None and current.status == "queued":
                notify_dev_task(
                    "cancelled",
                    handle=current.target_handle,
                    run_id=run_id,
                    status="cancelled",
                    detail="cancelled by user",
                )
                self._store.update_run(
                    run_id,
                    status="cancelled",
                    finished_at=time.time(),
                    error="cancelled by user",
                )
                return {"run_id": run_id, "status": "cancelled", "cancelled": True}
            record = self._store.get_run(run_id)
            if record is None:
                return None
            status = str(record.status or "")

        if status == "running":
            mark_cancelled(run_id)
            self._close_all_agents()
            return {
                "run_id": run_id,
                "status": "running",
                "cancelled": True,
                "cancelling": True,
            }

        return {
            "run_id": run_id,
            "status": status,
            "cancelled": False,
            "reason": "not_active",
        }

    def fleet_status(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for state in self._fleet.list_handles():
            running = self._store.running_run_for_handle(state.handle)
            rows.append(
                {
                    "handle": state.handle,
                    "agent_id": state.agent_id,
                    "last_wake_at": state.last_wake_at,
                    "running_run_id": None if running is None else running.run_id,
                    "running_status": None if running is None else running.status,
                }
            )
        return rows

    def status(self) -> dict[str, Any]:
        running = self._store.running_run()
        active = self._store.active_run()
        controller_id = self._fleet.get_agent_id(DEFAULT_HANDLE)
        return {
            "agent_id": controller_id,
            "agent_connected": bool(self._agents) or (
                self._config.backend == "cli" and controller_id is not None
            ),
            "active_run_id": None if active is None else active.run_id,
            "active_status": None if active is None else active.status,
            "running_run_id": None if running is None else running.run_id,
            "queue_depth": self.pending_queue_depth(),
            "queued_count": len(self._store.queued_runs()),
            "cwd": str(self._config.cwd),
            "model": self._config.model,
            "backend": self._config.backend,
            "fleet_handles": list(FLEET_HANDLES),
            "agents": self.fleet_status(),
        }

    def _worker_loop(self) -> None:
        while True:
            with self._queue_cv:
                while not self._queue and not self._shutdown:
                    self._queue_cv.wait()
                if self._shutdown and not self._queue:
                    return
                run_id = self._queue.pop(0)
            self._execute_run(run_id)

    def _execute_run(self, run_id: str) -> None:
        with self._run_lock:
            record = self._store.get_run(run_id)
            if record is None:
                return
            handle = record.target_handle or DEFAULT_HANDLE
            self._store.update_run(
                run_id,
                status="running",
                started_at=time.time(),
            )
            notify_dev_task(
                "started",
                handle=handle,
                run_id=run_id,
                text=record.text[:200],
                status="running",
            )
            try:
                if self._config.backend == "cli":
                    execute_cli_run(
                        run_id,
                        config=self._config,
                        store=self._store,
                        fleet=self._fleet,
                    )
                    return

                agent = self._ensure_agent(handle)
                prompt_text = record.text
                if record.attachments:
                    prompt_text, _paths = materialize_dev_task_attachments(
                        record.text,
                        attachments=record.attachments,
                        task_id=record.task_id,
                        run_id=run_id,
                        data_dir=self._config.data_dir,
                        config=self._config,
                    )
                run = agent.send(prompt_text)
                self._store.update_run(run_id, agent_id=agent.agent_id)
                self._fleet.set_agent_id(handle, agent.agent_id)

                for message in run.messages():
                    if is_cancelled(run_id):
                        break
                    event = _sdk_message_event(message)
                    if event is not None:
                        self._store.append_event(run_id, event)
                        if event.get("type") == "assistant" and event.get("text"):
                            notify_dev_task(
                                "progress",
                                handle=handle,
                                run_id=run_id,
                                detail=str(event.get("text") or "")[:400],
                                status="running",
                            )

                if is_cancelled(run_id):
                    notify_dev_task(
                        "cancelled",
                        handle=handle,
                        run_id=run_id,
                        status="cancelled",
                        detail="cancelled by user",
                    )
                    self._store.update_run(
                        run_id,
                        status="cancelled",
                        finished_at=time.time(),
                        error="cancelled by user",
                    )
                    clear_run(run_id)
                    return

                result = run.wait()
                if result.status == "error":
                    notify_dev_task(
                        "failed",
                        handle=handle,
                        run_id=run_id,
                        status="error",
                        detail=str(result.result or "run failed")[:400],
                    )
                    self._store.update_run(
                        run_id,
                        status="error",
                        finished_at=time.time(),
                        error=result.result or "run failed",
                        result=result.result,
                    )
                else:
                    notify_dev_task(
                        "finished",
                        handle=handle,
                        run_id=run_id,
                        status="finished",
                        detail=str(result.result or "")[:400],
                    )
                    self._store.update_run(
                        run_id,
                        status="finished",
                        finished_at=time.time(),
                        result=result.result,
                    )
            except CursorAgentError as err:
                log.exception("cursor startup failed for run %s", run_id)
                notify_dev_task(
                    "failed",
                    handle=handle,
                    run_id=run_id,
                    status="error",
                    detail=f"{err.message} (retryable={err.is_retryable})",
                )
                self._store.update_run(
                    run_id,
                    status="error",
                    finished_at=time.time(),
                    error=f"{err.message} (retryable={err.is_retryable})",
                )
                self._close_agent(handle)
            except Exception as err:  # pragma: no cover
                log.exception("run %s failed", run_id)
                notify_dev_task(
                    "failed",
                    handle=handle,
                    run_id=run_id,
                    status="error",
                    detail=str(err)[:400],
                )
                self._store.update_run(
                    run_id,
                    status="error",
                    finished_at=time.time(),
                    error=str(err),
                )

    def _ensure_agent(self, handle: str) -> Agent:
        with self._agent_lock:
            cached = self._agents.get(handle)
            if cached is not None:
                return cached

            if not self._config.api_key:
                raise CursorAgentError(
                    message="CURSOR_API_KEY is not set",
                    is_retryable=False,
                )

            options = AgentOptions(
                api_key=self._config.api_key,
                model=self._config.model,
                local=LocalAgentOptions(cwd=str(self._config.cwd)),
            )
            saved_id = self._fleet.get_agent_id(handle)
            if saved_id:
                log.info("resuming agent %s for handle %s", saved_id, handle)
                try:
                    agent = Agent.resume(saved_id, options)
                except CursorAgentError as err:
                    if not is_agent_not_found(err):
                        raise
                    log.warning(
                        "stale agent %s for %s (%s), creating new session",
                        saved_id,
                        handle,
                        getattr(err, "message", err),
                    )
                    self._fleet.set_agent_id(handle, None)
                    agent = Agent.create(options)
            else:
                log.info("creating new agent for handle %s in %s", handle, self._config.cwd)
                agent = Agent.create(options)
            self._fleet.set_agent_id(handle, agent.agent_id)
            self._agents[handle] = agent
            return agent

    def _close_agent(self, handle: str) -> None:
        with self._agent_lock:
            agent = self._agents.pop(handle, None)
            if agent is None:
                return
            try:
                agent.close()
            except Exception:
                log.exception("failed to close agent for %s", handle)

    def _close_all_agents(self) -> None:
        with self._agent_lock:
            handles = list(self._agents.keys())
        for handle in handles:
            self._close_agent(handle)
