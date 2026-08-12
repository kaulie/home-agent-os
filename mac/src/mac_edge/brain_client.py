from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from mac_edge.config import Config, Identity

log = logging.getLogger("mac_edge.brain")


class BrainError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        body: Any = None,
        transient: bool = False,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.body = body
        self.transient = transient

    @property
    def is_unauthorized(self) -> bool:
        return self.status_code == 401

    @property
    def is_transient(self) -> bool:
        """Network / Brain-down style errors — safe to retry with backoff."""
        return bool(self.transient)


@dataclass
class RegisterResult:
    edge_id: str
    message: str
    raw: dict[str, Any]


@dataclass
class HeartbeatResult:
    edge_id: str
    online_status: str
    raw: dict[str, Any]


class BrainClient:
    def __init__(self, config: Config, client: httpx.Client | None = None):
        self.config = config
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=config.http_timeout_sec)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> BrainClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _post(self, url: str, **kwargs: Any) -> httpx.Response:
        try:
            return self._client.post(url, **kwargs)
        except httpx.RequestError as e:
            raise BrainError(f"brain unreachable: {e}", transient=True) from e

    def _get(self, url: str, **kwargs: Any) -> httpx.Response:
        try:
            return self._client.get(url, **kwargs)
        except httpx.RequestError as e:
            raise BrainError(f"brain unreachable: {e}", transient=True) from e

    def register(self) -> RegisterResult:
        body = self._identity_body(include_edge_id=False)
        body["client_hint"] = self.config.identity.client_hint
        log.info("POST register hint=%s → %s", body["client_hint"], self.config.register_url)
        resp = self._post(self.config.register_url, json=body)
        data = self._json_or_raise(resp, "register")
        ok = bool(data.get("ok"))
        status = str(data.get("status") or "")
        edge_id = str(data.get("edge_id") or data.get("edgeId") or "").strip()
        message = str(data.get("message") or data.get("error") or "")
        if not ok or status != "approved" or not edge_id:
            raise BrainError(
                f"register rejected: ok={ok} status={status!r} message={message!r}",
                status_code=resp.status_code,
                body=data,
            )
        log.info("register OK edge_id=%s message=%s", edge_id, message)
        return RegisterResult(edge_id=edge_id, message=message, raw=data)

    def heartbeat(self, edge_id: str) -> HeartbeatResult:
        eid = edge_id.strip()
        if not eid:
            raise BrainError("edge_id required for heartbeat")
        body = self._identity_body(include_edge_id=True, edge_id=eid)
        body["online_status"] = "online"
        body["client_time_ms"] = int(time.time() * 1000)
        body["health"] = {
            "status": "healthy",
            "summary": "mac-edge agent running",
            "details": {"role": "background"},
        }
        log.debug("POST heartbeat edge_id=%s", eid)
        resp = self._post(self.config.heartbeat_url, json=body)
        if resp.status_code == 401:
            data = _safe_json(resp)
            raise BrainError(
                "unknown edge_id; register first",
                status_code=401,
                body=data,
            )
        data = self._json_or_raise(resp, "heartbeat")
        if not data.get("ok", True) and data.get("error"):
            raise BrainError(
                str(data.get("error")),
                status_code=resp.status_code,
                body=data,
            )
        brain_time = data.get("brain_time_ms")
        if brain_time is None and isinstance(data.get("edge"), dict):
            brain_time = data["edge"].get("brain_time_ms")
        try:
            from mac_edge.brain_time import BRAIN_CLOCK

            BRAIN_CLOCK.apply_heartbeat(int(brain_time) if brain_time is not None else None)
        except Exception:
            pass
        online = str(data.get("online_status") or body["online_status"])
        eligible = data.get("schedule_eligible")
        if eligible is None and isinstance(data.get("edge"), dict):
            eligible = data["edge"].get("schedule_eligible")
        log.info(
            "heartbeat OK edge_id=%s online=%s schedule_eligible=%s brain_time_ms=%s",
            eid,
            online,
            eligible if eligible is not None else "?",
            brain_time,
        )
        return HeartbeatResult(edge_id=eid, online_status=online, raw=data)

    def pull_intents(self, edge_id: str, *, consume: bool = False) -> list[dict[str, Any]]:
        """
        Peek intents visible to this edge (default: peek, not pop).
        Keep where this node is scheduler_node OR any step.assigned_edge_id.
        Drop succeeded/failed — those are not work.
        """
        eid = edge_id.strip()
        if not eid:
            raise BrainError("edge_id required for intents pull")
        params: dict[str, str] = {"edge_id": eid}
        status_pin = (self.config.intent_status or "").strip()
        if status_pin:
            params["intent_status"] = status_pin
        if not consume:
            params["peek"] = "1"
        log.debug(
            "GET intents edge_id=%s consume=%s status_pin=%s",
            eid,
            consume,
            status_pin or "(none)",
        )
        resp = self._get(self.config.intents_url, params=params)
        data = self._json_or_raise(resp, "intents")
        intents = data.get("intents")
        if intents is None and isinstance(data.get("commands"), list):
            intents = data["commands"]
        if not isinstance(intents, list):
            intents = []

        matched: list[dict[str, Any]] = []
        skipped_terminal = 0
        skipped_irrelevant = 0
        for item in intents:
            if not isinstance(item, dict) or not item:
                continue
            wire = str(item.get("status") or item.get("intent_status") or "").lower()
            if wire in ("succeeded", "failed"):
                skipped_terminal += 1
                continue
            if intent_relevant_to_edge(item, eid):
                matched.append(item)
            else:
                skipped_irrelevant += 1
        if not matched:
            log.debug(
                "intents: empty after filter (raw=%d terminal=%d irrelevant=%d edge_id=%s)",
                len(intents),
                skipped_terminal,
                skipped_irrelevant,
                eid,
            )
        return matched

    def fetch_intent_detail(self, intent_id: str | int) -> dict[str, Any] | None:
        """GET /api/v1/intent_detail?intent_id= — fresh plan/outputs for step eligibility."""
        iid = str(intent_id).strip()
        if not iid:
            return None
        url = f"{self.config.brain_base_url}/api/v1/intent_detail"
        try:
            resp = self._get(url, params={"intent_id": iid})
            data = self._json_or_raise(resp, "intent_detail")
            return data if isinstance(data, dict) else None
        except BrainError as e:
            log.warning("intent_detail %s failed: %s", iid, e)
            return None

    def post_intent_status(
        self,
        intent_id: str | int,
        *,
        status: str,
        edge_node_id: str,
        message: str = "",
    ) -> dict[str, Any]:
        iid = str(intent_id).strip()
        url = f"{self.config.brain_base_url}/api/v1/intent/{iid}/status"
        body: dict[str, Any] = {
            "intent_id": iid,
            "intent_status": status,
            "status": status,
            "edge_node_id": edge_node_id,
        }
        if message:
            body["message"] = message
        log.info("POST intent status %s → %s", iid, status)
        resp = self._post(url, json=body)
        return self._json_or_raise(resp, "intent_status")

    def post_step_status(
        self,
        intent_id: str | int,
        step_id: str | int,
        *,
        step_status: int,
        edge_node_id: str,
        ts_ms: int | None = None,
        outputs: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        iid = str(intent_id).strip()
        sid = str(step_id).strip()
        url = f"{self.config.brain_base_url}/api/v1/intent/{iid}/step/{sid}/status"
        body: dict[str, Any] = {
            "step_status": int(step_status),
            "edge_node_id": edge_node_id,
            "ts": int(ts_ms if ts_ms is not None else time.time() * 1000),
        }
        if outputs:
            # Skill outputs only — Brain registers into ctx_param via output_constrict.
            body["outputs"] = outputs
        log.info(
            "POST step status intent=%s step=%s step_status=%s outputs=%s",
            iid,
            sid,
            step_status,
            ",".join(sorted(outputs)) if outputs else "-",
        )
        resp = self._post(url, json=body)
        return self._json_or_raise(resp, "step_status")

    def _identity_body(
        self,
        *,
        include_edge_id: bool,
        edge_id: str | None = None,
    ) -> dict[str, Any]:
        ident: Identity = self.config.identity
        body: dict[str, Any] = {
            "display_name": ident.display_name,
            "device_type": ident.device_type,
            "room": ident.room,
            "app_version": ident.app_version,
            "services": list(ident.services),
            "reported_at": time.time(),
        }
        if include_edge_id and edge_id:
            body["edge_id"] = edge_id
        return body

    @staticmethod
    def _json_or_raise(resp: httpx.Response, label: str) -> dict[str, Any]:
        try:
            data = resp.json()
        except Exception as e:
            raise BrainError(
                f"{label}: invalid JSON HTTP {resp.status_code}: {resp.text[:200]}",
                status_code=resp.status_code,
                body=resp.text,
            ) from e
        if not isinstance(data, dict):
            raise BrainError(
                f"{label}: expected JSON object, got {type(data).__name__}",
                status_code=resp.status_code,
                body=data,
            )
        if resp.status_code >= 400:
            err = data.get("error") or data.get("message") or resp.text[:200]
            raise BrainError(
                f"{label}: HTTP {resp.status_code}: {err}",
                status_code=resp.status_code,
                body=data,
            )
        return data


def intent_relevant_to_edge(intent: dict[str, Any], edge_id: str) -> bool:
    eid = edge_id.strip()
    scheduler = str(intent.get("scheduler_node") or "").strip()
    if scheduler and scheduler == eid:
        return True
    plan = intent.get("execution_plan") or []
    if isinstance(plan, list):
        for step in plan:
            if not isinstance(step, dict):
                continue
            assigned = str(step.get("assigned_edge_id") or "").strip()
            if assigned == eid:
                return True
    return False


def _safe_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        return resp.text


def format_intent_summary(intent: dict[str, Any]) -> str:
    iid = intent.get("id") or intent.get("intent_id") or "?"
    status = intent.get("intent_status") or intent.get("status") or "?"
    scheduler = intent.get("scheduler_node") or "-"
    plan = intent.get("execution_plan") or []
    steps: list[str] = []
    if isinstance(plan, list):
        for step in plan:
            if not isinstance(step, dict):
                continue
            cap = step.get("capability") or "?"
            num = step.get("step", "?")
            assigned = step.get("assigned_edge_id") or "?"
            st = step.get("status", step.get("step_status", 0))
            steps.append(f"{num}:{cap}@{assigned}[{st}]")
    plan_s = ", ".join(steps) if steps else "(no plan)"
    text = (intent.get("text") or "")[:60]
    extra = f" text={text!r}" if text else ""
    return (
        f"intent id={iid} status={status} scheduler={scheduler} "
        f"plan=[{plan_s}]{extra}"
    )
