"""P0 dual-Brain client: one logical BrainClient backed by multiple Brain URLs.

Why: a Runtime registers with (and heartbeats to) every Brain in its reachability
set, but a given intent is dispatched by exactly one Brain. Status / step / delivery
posts must therefore route back to the Brain that owns the intent (its origin),
while register / heartbeat broadcast to all.

This wrapper exposes the BrainClient surface used by agent / executor / scheduler,
so callers stay single-Brain. Each pulled intent is tagged with
`_brain_origin` (the base URL it came from); a iid→origin map routes later posts.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import httpx

from mac_edge.brain_client import BrainClient, BrainError, RegisterResult, HeartbeatResult

log = logging.getLogger("mac_edge.multi_brain")

_ORIGIN_TAG = "_brain_origin"
_SHARED_ORIGIN_LOCK = threading.Lock()
_SHARED_INTENT_ORIGIN: dict[str, str] = {}


def remember_intent_origin(intent_id: str | int, brain_url: str | None) -> None:
    """Process-wide iid→Brain URL map (control + executor use separate clients)."""
    iid = str(intent_id or "").strip()
    url = str(brain_url or "").strip().rstrip("/")
    if not iid or not url:
        return
    with _SHARED_ORIGIN_LOCK:
        _SHARED_INTENT_ORIGIN[iid] = url


def intent_origin_brain_url(intent_id: str | int) -> str | None:
    with _SHARED_ORIGIN_LOCK:
        return _SHARED_INTENT_ORIGIN.get(str(intent_id).strip()) or None


def _missing_intent_error(exc: BrainError) -> bool:
    if exc.status_code == 404:
        return True
    msg = str(exc).casefold()
    return "intent not exist" in msg or "intent not found" in msg


class MultiBrainClient:
    """Aggregate multiple BrainClients behind the BrainClient API."""

    def __init__(self, base_urls: list[str], *, config: Any, timeout_sec: float | None = None):
        self._base_urls = list(dict.fromkeys(u.rstrip("/") for u in base_urls if u))
        if not self._base_urls:
            raise ValueError("MultiBrainClient requires at least one Brain URL")
        self._config = config
        self._timeout = timeout_sec
        self._clients: list[BrainClient] = []
        self._by_url: dict[str, BrainClient] = {}
        self._lock = threading.Lock()
        self._owns_clients = True

    @property
    def primary(self) -> BrainClient:
        return self._clients[0]

    @property
    def primary_url(self) -> str:
        return self._base_urls[0]

    @property
    def base_urls(self) -> list[str]:
        return list(self._base_urls)

    def __enter__(self) -> "MultiBrainClient":
        self._open()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _open(self) -> None:
        from dataclasses import replace
        for url in self._base_urls:
            sub_cfg = replace(self._config, brain_base_url=url, brain_base_urls=(url,))
            client_kwargs: dict[str, Any] = {}
            if self._timeout is not None:
                client_kwargs["client"] = httpx.Client(timeout=self._timeout)
            bc = BrainClient(sub_cfg, **client_kwargs)
            self._clients.append(bc)
            self._by_url[url] = bc

    def close(self) -> None:
        for bc in self._clients:
            try:
                bc.close()
            except Exception:
                pass
        self._clients.clear()
        self._by_url.clear()

    def _client_for(self, url: str | None) -> BrainClient:
        if not url:
            return self.primary
        bc = self._by_url.get(url.rstrip("/"))
        return bc or self.primary

    def _route_url_for_intent(self, intent_id: str, *, prefer: str | None = None) -> str:
        iid = str(intent_id).strip()
        mapped = intent_origin_brain_url(iid)
        if mapped:
            return mapped
        if prefer:
            return prefer.rstrip("/")
        return self.primary_url

    def _brain_probe_order(self, intent_id: str) -> list[str]:
        primary = self._route_url_for_intent(str(intent_id).strip()).rstrip("/")
        out = [primary]
        for url in self._base_urls:
            norm = url.rstrip("/")
            if norm not in out:
                out.append(norm)
        return out

    def _call_routed(
        self,
        intent_id: str | int,
        label: str,
        fn,
    ):
        """Route to origin Brain; on missing-intent 404 probe other Brains."""
        iid = str(intent_id).strip()
        last_err: BrainError | None = None
        for url in self._brain_probe_order(iid):
            try:
                result = fn(self._client_for(url))
            except BrainError as e:
                last_err = e
                if not _missing_intent_error(e):
                    raise
                log.warning(
                    "%s intent=%s not on %s (%s) — probe next Brain",
                    label,
                    iid,
                    url,
                    e,
                )
                continue
            remember_intent_origin(iid, url)
            return result
        if last_err is not None:
            raise last_err
        raise BrainError(f"{label}: intent {iid} not found on any Brain")

    # ---- broadcast ops ----

    def register(self) -> RegisterResult:
        result: RegisterResult | None = None
        last_err: Exception | None = None
        for url, bc in zip(self._base_urls, self._clients):
            try:
                r = bc.register()
                if result is None:
                    result = r
            except BrainError as e:
                last_err = e
                log.warning("register to %s failed: %s", url, e)
        if result is not None:
            return result
        raise last_err or BrainError("register failed on all Brains")

    def heartbeat(self, edge_id: str) -> HeartbeatResult:
        from mac_edge.cloud_usage import drain, snapshot

        delta = snapshot()
        result: HeartbeatResult | None = None
        last_err: BrainError | None = None
        try:
            for url, bc in zip(self._base_urls, self._clients):
                try:
                    r = bc.heartbeat(edge_id, cloud_usage_delta=delta)
                    if result is None:
                        result = r
                except BrainError as e:
                    last_err = e
                    if e.is_unauthorized:
                        # Re-raise 401 from any Brain so the agent clears identity.
                        raise
                    log.warning("heartbeat to %s failed: %s", url, e)
            if result is not None:
                return result
            raise last_err or BrainError("heartbeat failed on all Brains", transient=True)
        finally:
            if delta:
                drain()

    def pull_intents(self, edge_id: str, *, consume: bool = False) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        for url, bc in zip(self._base_urls, self._clients):
            try:
                items = bc.pull_intents(edge_id, consume=consume) or []
            except BrainError as e:
                if e.is_unauthorized:
                    raise
                log.warning("pull_intents from %s failed: %s", url, e)
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                iid = str(item.get("id") or item.get("intent_id") or "").strip()
                if iid and iid in seen:
                    continue
                if iid:
                    seen.add(iid)
                    remember_intent_origin(iid, url)
                item.setdefault(_ORIGIN_TAG, url)
                merged.append(item)
        return merged

    # ---- routed ops (status / step / delivery) ----

    def fetch_intent_detail(self, intent_id: str | int) -> dict[str, Any] | None:
        iid = str(intent_id).strip()
        url = self._route_url_for_intent(iid)
        detail = self._client_for(url).fetch_intent_detail(intent_id)
        if detail:
            remember_intent_origin(iid, url)
            return detail
        for probe_url, bc in self._by_url.items():
            if probe_url.rstrip("/") == url.rstrip("/"):
                continue
            detail = bc.fetch_intent_detail(intent_id)
            if detail:
                remember_intent_origin(iid, probe_url)
                return detail
        return None

    def post_intent_status(
        self,
        intent_id: str | int,
        *,
        status: str,
        edge_node_id: str,
        message: str = "",
    ) -> dict[str, Any]:
        return self._call_routed(
            intent_id,
            "post_intent_status",
            lambda bc: bc.post_intent_status(
                intent_id,
                status=status,
                edge_node_id=edge_node_id,
                message=message,
            ),
        )

    def post_delivery_complete(
        self,
        intent_id: str | int,
        *,
        edge_node_id: str,
    ) -> dict[str, Any]:
        return self._call_routed(
            intent_id,
            "post_delivery_complete",
            lambda bc: bc.post_delivery_complete(
                intent_id, edge_node_id=edge_node_id
            ),
        )

    def post_step_status(
        self,
        intent_id: str | int,
        step_id: str | int,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return self._call_routed(
            intent_id,
            "post_step_status",
            lambda bc: bc.post_step_status(intent_id, step_id, **kwargs),
        )

    def post_intent_status_bg(self, intent_id: str | int, **kwargs: Any) -> None:
        url = self._route_url_for_intent(str(intent_id))
        self._client_for(url).post_intent_status_bg(intent_id, **kwargs)

    def post_step_status_bg(self, intent_id: str | int, step_id: str | int, **kwargs: Any) -> None:
        url = self._route_url_for_intent(str(intent_id))
        self._client_for(url).post_step_status_bg(intent_id, step_id, **kwargs)

    def begin_running_reports(self, intent_id: str | int, step_id: str | int) -> tuple[int, int]:
        url = self._route_url_for_intent(str(intent_id))
        return self._client_for(url).begin_running_reports(intent_id, step_id)

    def invalidate_running_reports(self, intent_id: str | int, step_id: str | int) -> None:
        url = self._route_url_for_intent(str(intent_id))
        self._client_for(url).invalidate_running_reports(intent_id, step_id)

    # ---- catalog: ads stay on primary; asset bytes follow the Brain that owns the intent ----

    def upload_asset(self, **kwargs: Any) -> dict[str, Any]:
        iid = str(kwargs.get("intent_id") or "").strip()
        return self._call_routed(
            iid,
            "upload_asset",
            lambda bc: bc.upload_asset(**kwargs),
        )

    def register_asset(self, body: dict[str, Any]) -> dict[str, Any]:
        return self.primary.register_asset(body)

    def list_assets(self, **kwargs: Any) -> dict[str, Any]:
        return self.primary.list_assets(**kwargs)

    def list_capabilities(self, **kwargs: Any) -> dict[str, Any]:
        return self.primary.list_capabilities(**kwargs)

    def fetch_asset(self, asset_id: str, **kwargs: Any) -> dict[str, Any] | None:
        return self.primary.fetch_asset(asset_id, **kwargs)
