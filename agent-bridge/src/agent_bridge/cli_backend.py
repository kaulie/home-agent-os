from __future__ import annotations

import json
import logging
import subprocess
import time
from typing import Any

from agent_bridge.cancel import clear_run, is_cancelled, register_proc
from agent_bridge.token_usage import normalize_token_usage
from agent_bridge.chat_notify import notify_dev_task
from agent_bridge.config import BridgeConfig
from agent_bridge.fleet_handles import DEFAULT_HANDLE
from agent_bridge.fleet_state import FleetStateStore
from agent_bridge.session_utils import is_stale_session_error
from agent_bridge.state import StateStore

log = logging.getLogger(__name__)


def _cli_env() -> dict[str, str]:
    import os

    env = os.environ.copy()
    env.pop("CURSOR_API_KEY", None)
    return env


def _parse_stream_line(line: str) -> dict[str, Any] | None:
    line = line.strip()
    if not line:
        return None
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        log.debug("ignored non-json cli output: %s", line[:120])
        return None


def _run_cli_process(
    run_id: str,
    *,
    config: BridgeConfig,
    store: StateStore,
    fleet: FleetStateStore,
    handle: str,
    text: str,
    session_id: str | None,
) -> tuple[str, str, bool, int]:
    bin_path = config.cursor_agent_bin
    if not bin_path:
        raise RuntimeError("cursor-agent is not available")

    cmd = [
        bin_path,
        "-f",
        "-p",
        text,
        "--model",
        config.model,
        "--output-format",
        "stream-json",
    ]
    if session_id:
        cmd.extend(["--resume", session_id])

    log.info("cli run %s handle=%s via %s (resume=%s)", run_id, handle, bin_path, bool(session_id))
    proc = subprocess.Popen(
        cmd,
        cwd=str(config.cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=_cli_env(),
    )
    register_proc(run_id, proc)
    assert proc.stdout is not None

    final_result = ""
    final_error = ""
    was_cancelled = False
    exit_code = 0
    try:
        for raw in proc.stdout:
            if is_cancelled(run_id):
                was_cancelled = True
                break
            event = _parse_stream_line(raw)
            if event is None:
                continue

            session = event.get("session_id")
            if isinstance(session, str) and session:
                fleet.set_agent_id(handle, session)
                store.update_run(run_id, agent_id=session)

            event_type = event.get("type")
            if event_type == "assistant":
                message = event.get("message") or {}
                content = message.get("content") or []
                chunks: list[str] = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        chunks.append(str(block.get("text") or ""))
                text_chunk = "".join(chunks).strip()
                if text_chunk:
                    payload = {"type": "assistant", "text": text_chunk, "ts": time.time()}
                    store.append_event(run_id, payload)
                    notify_dev_task(
                        "progress",
                        handle=handle,
                        run_id=run_id,
                        detail=text_chunk[:400],
                        status="running",
                    )
            elif event_type == "result":
                usage = normalize_token_usage(event.get("usage"))
                if usage:
                    store.update_run(run_id, usage=usage)
                if event.get("is_error"):
                    final_error = str(event.get("result") or "run failed")
                else:
                    final_result = str(event.get("result") or "")

        stderr = proc.stderr.read() if proc.stderr is not None else ""
        exit_code = proc.wait()
    finally:
        was_cancelled = was_cancelled or is_cancelled(run_id)
        clear_run(run_id)

    if exit_code != 0 and not final_error:
        final_error = stderr.strip() or f"cursor-agent exited with code {exit_code}"

    return final_result, final_error, was_cancelled, exit_code


def execute_cli_run(
    run_id: str,
    *,
    config: BridgeConfig,
    store: StateStore,
    fleet: FleetStateStore,
) -> None:
    record = store.get_run(run_id)
    if record is None:
        return

    handle = record.target_handle or DEFAULT_HANDLE
    session_id = fleet.get_agent_id(handle)
    final_result, final_error, was_cancelled, _exit_code = _run_cli_process(
        run_id,
        config=config,
        store=store,
        fleet=fleet,
        handle=handle,
        text=record.text,
        session_id=session_id,
    )

    if (
        not was_cancelled
        and final_error
        and session_id
        and is_stale_session_error(final_error)
    ):
        log.warning(
            "cli resume failed for session %s handle=%s, retrying fresh",
            session_id,
            handle,
        )
        fleet.set_agent_id(handle, None)
        final_result, final_error, was_cancelled, _exit_code = _run_cli_process(
            run_id,
            config=config,
            store=store,
            fleet=fleet,
            handle=handle,
            text=record.text,
            session_id=None,
        )

    if was_cancelled:
        notify_dev_task(
            "cancelled",
            handle=handle,
            run_id=run_id,
            status="cancelled",
            detail="cancelled by user",
        )
        store.update_run(
            run_id,
            status="cancelled",
            finished_at=time.time(),
            error="cancelled by user",
            result=final_result or None,
        )
        return

    if final_error:
        notify_dev_task(
            "failed",
            handle=handle,
            run_id=run_id,
            status="error",
            detail=final_error[:400],
        )
        store.update_run(
            run_id,
            status="error",
            finished_at=time.time(),
            error=final_error,
            result=final_result or None,
        )
        return

    notify_dev_task(
        "finished",
        handle=handle,
        run_id=run_id,
        status="finished",
        detail=final_result[:400],
    )
    store.update_run(
        run_id,
        status="finished",
        finished_at=time.time(),
        result=final_result or None,
    )
