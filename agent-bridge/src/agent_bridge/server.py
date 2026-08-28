from __future__ import annotations

import logging
from functools import wraps
from typing import Any, Callable

from flask import Flask, jsonify, request

from agent_bridge.config import BridgeConfig
from agent_bridge.fleet_handles import normalize_fleet_handle
from agent_bridge.fleet_state import FleetStateStore
from agent_bridge.runner import AgentRunner
from agent_bridge.state import StateStore
from agent_bridge.wake import wake_handle

log = logging.getLogger(__name__)


def create_app(
    config: BridgeConfig,
    store: StateStore,
    fleet: FleetStateStore,
    runner: AgentRunner,
) -> Flask:
    app = Flask(__name__)

    def require_auth(handler: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(handler)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            if config.auth_token:
                auth = request.headers.get("Authorization", "")
                token = auth.removeprefix("Bearer ").strip()
                if token != config.auth_token:
                    return jsonify({"error": "unauthorized"}), 401
            return handler(*args, **kwargs)

        return wrapped

    @app.get("/health")
    def health() -> Any:
        return jsonify({"ok": True, "service": "agent-bridge"})

    @app.get("/api/v1/status")
    @require_auth
    def status() -> Any:
        return jsonify(runner.status())

    @app.get("/api/v1/agents")
    @require_auth
    def list_agents() -> Any:
        return jsonify({"agents": runner.fleet_status()})

    @app.post("/api/v1/agents/<handle>/wake")
    @require_auth
    def wake_agent(handle: str) -> Any:
        normalized = normalize_fleet_handle(handle)
        if normalized is None:
            return jsonify({"error": f"unknown handle: {handle}"}), 400
        if not config.can_run():
            return jsonify({"error": "agent backend is not configured"}), 503

        body = request.get_json(silent=True) or {}
        task_text = str(body.get("text") or body.get("task") or "").strip()
        pull_chat = bool(body.get("pull_chat", True))
        try:
            result = wake_handle(
                normalized,
                store=store,
                fleet=fleet,
                runner=runner,
                task_text=task_text,
                pull_chat=pull_chat,
            )
        except ValueError as err:
            return jsonify({"error": str(err)}), 400
        return jsonify(result), 202

    @app.post("/api/v1/command")
    @require_auth
    def command() -> Any:
        body = request.get_json(silent=True) or {}
        text = str(body.get("text", "")).strip()
        attachments_raw = body.get("attachments")
        if attachments_raw is not None and not isinstance(attachments_raw, list):
            return jsonify({"error": "attachments must be an array"}), 400
        attachments: list[dict[str, str]] = []
        if isinstance(attachments_raw, list):
            for item in attachments_raw:
                if not isinstance(item, dict):
                    continue
                aid = str(item.get("asset_id") or item.get("id") or "").strip()
                if not aid:
                    continue
                row = {"asset_id": aid, "kind": str(item.get("kind") or "image")}
                mime = str(item.get("mime_type") or item.get("mime") or "").strip()
                if mime:
                    row["mime_type"] = mime
                name = str(item.get("filename") or item.get("name") or "").strip()
                if name:
                    row["filename"] = name
                attachments.append(row)
        task_id_raw = body.get("task_id")
        task_id = None
        if task_id_raw not in (None, ""):
            try:
                task_id = int(task_id_raw)
            except (TypeError, ValueError):
                return jsonify({"error": "task_id must be an integer"}), 400

        target_raw = body.get("target_handle") or body.get("handle")
        target_handle = normalize_fleet_handle(str(target_raw) if target_raw else None)

        if not text and not attachments:
            return jsonify({"error": "text or attachments required"}), 400

        if not config.can_run():
            return jsonify({"error": "agent backend is not configured"}), 503

        if target_handle and (text or attachments):
            try:
                result = wake_handle(
                    target_handle,
                    store=store,
                    fleet=fleet,
                    runner=runner,
                    task_text=text,
                    pull_chat=bool(body.get("pull_chat", False)),
                    attachments=attachments or None,
                    task_id=task_id,
                )
            except ValueError as err:
                return jsonify({"error": str(err)}), 400
            return jsonify(result), 202

        run = store.create_run(
            text,
            attachments=attachments,
            task_id=task_id,
            target_handle=target_handle or "controller",
        )
        runner.enqueue(run.run_id)
        queue_depth = runner.pending_queue_depth()
        return (
            jsonify(
                {
                    "run_id": run.run_id,
                    "status": run.status,
                    "text": run.text,
                    "target_handle": run.target_handle,
                    "queue_depth": queue_depth,
                }
            ),
            202,
        )

    @app.get("/api/v1/runs")
    @require_auth
    def list_runs() -> Any:
        limit = min(int(request.args.get("limit", 20)), 100)
        rows = [run.to_dict() for run in store.list_runs(limit=limit)]
        return jsonify({"runs": rows})

    @app.get("/api/v1/runs/<run_id>")
    @require_auth
    def get_run(run_id: str) -> Any:
        run = store.get_run(run_id)
        if run is None:
            return jsonify({"error": "not_found"}), 404
        return jsonify(run.to_dict())

    @app.post("/api/v1/runs/<run_id>/cancel")
    @require_auth
    def cancel_run(run_id: str) -> Any:
        result = runner.cancel_run(run_id)
        if result is None:
            return jsonify({"error": "not_found"}), 404
        return jsonify(result)

    return app
