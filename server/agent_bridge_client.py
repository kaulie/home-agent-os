"""HTTP client for the local agent-bridge daemon."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


class AgentBridgeError(Exception):
    pass


def bridge_base_url() -> str:
    raw = (os.environ.get("AGENT_BRIDGE_URL") or "http://127.0.0.1:9540").strip()
    return raw.rstrip("/")


def bridge_auth_token() -> str | None:
    token = (os.environ.get("AGENT_BRIDGE_TOKEN") or "").strip()
    return token or None


def bridge_enabled() -> bool:
    return (os.environ.get("AGENT_BRIDGE_ENABLED") or "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _request(
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    timeout: float = 15.0,
) -> dict[str, Any]:
    url = f"{bridge_base_url()}{path}"
    data = None
    headers = {"Accept": "application/json"}
    token = bridge_auth_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(detail) if detail else {}
        except json.JSONDecodeError:
            payload = {"error": detail[:500]}
        message = str(payload.get("error") or payload.get("message") or detail or err.reason)
        raise AgentBridgeError(f"bridge HTTP {err.code}: {message}") from err
    except urllib.error.URLError as err:
        raise AgentBridgeError(f"bridge unreachable: {err.reason}") from err
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as err:
        raise AgentBridgeError(f"bridge returned invalid JSON: {raw[:200]}") from err
    if not isinstance(parsed, dict):
        raise AgentBridgeError("bridge returned non-object JSON")
    return parsed


def submit_command(
    text: str,
    *,
    attachments: list[dict[str, str]] | None = None,
    task_id: int | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"text": text}
    if attachments:
        body["attachments"] = attachments
    if task_id is not None:
        body["task_id"] = task_id
    payload = _request("POST", "/api/v1/command", body=body)
    run_id = str(payload.get("run_id") or "").strip()
    if not run_id:
        raise AgentBridgeError("bridge did not return run_id")
    return payload


def get_run(run_id: str) -> dict[str, Any]:
    rid = str(run_id or "").strip()
    if not rid:
        raise AgentBridgeError("run_id is required")
    return _request("GET", f"/api/v1/runs/{rid}")


def cancel_run(run_id: str) -> dict[str, Any]:
    rid = str(run_id or "").strip()
    if not rid:
        raise AgentBridgeError("run_id is required")
    return _request("POST", f"/api/v1/runs/{rid}/cancel")


def bridge_status() -> dict[str, Any]:
    return _request("GET", "/api/v1/status")
