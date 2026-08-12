"""Edge node info report — DEPRECATED for heartbeat/register.

请改用：
  server/edge_heartbeat_flask.py
  POST /api/v1/edge-register   （首次，返回 edgeId）
  POST /api/v1/edge-heartbeat  （后续，必须带 edgeId）

本文件仅保留调试注册参考：
  POST /api/v1/edges/<edge_id>/capabilities
  body: { "services": [...], "registered_at": ... }
"""

from __future__ import annotations

import time
from copy import deepcopy
from typing import Any

from flask import Flask, jsonify, request

try:
    from edge_services import normalize_services, strip_legacy_edge_fields, validate_services
except ImportError:  # pragma: no cover
    from server.edge_services import (  # type: ignore
        normalize_services,
        strip_legacy_edge_fields,
        validate_services,
    )

# edge_id -> latest EdgeNodeInfo dict
_EDGES: dict[str, dict[str, Any]] = {}
# edge_id -> last services registration (debug)
_SERVICES: dict[str, dict[str, Any]] = {}
ONLINE_TTL_SEC = 30


def upsert_edge(edge_id: str, body: dict[str, Any]) -> dict[str, Any]:
    info = deepcopy(body) if isinstance(body, dict) else {}
    info["edge_id"] = edge_id
    info.pop("edgeId", None)
    info["services"] = normalize_services(info.get("services"))
    strip_legacy_edge_fields(info)
    info["server_received_at"] = time.time()
    _EDGES[edge_id] = info
    return info


def list_edges(*, apply_ttl: bool = True) -> list[dict[str, Any]]:
    now = time.time()
    out: list[dict[str, Any]] = []
    for edge_id, info in sorted(_EDGES.items()):
        item = deepcopy(info)
        strip_legacy_edge_fields(item)
        if apply_ttl:
            last = float(item.get("server_received_at") or item.get("reported_at") or 0)
            status = str(item.get("online_status") or "online").lower()
            if status == "online" and now - last > ONLINE_TTL_SEC:
                item["online_status"] = "offline"
                item["online_status_note"] = f"ttl expired (>{ONLINE_TTL_SEC}s)"
        out.append(item)
    return out


def get_edge(edge_id: str, *, apply_ttl: bool = True) -> dict[str, Any] | None:
    for item in list_edges(apply_ttl=apply_ttl):
        if item.get("edge_id") == edge_id:
            return item
    return None


def register_edge_routes(app: Flask) -> None:
    @app.route("/api/v1/edges/<edge_id>/report", methods=["POST"])
    def edge_report(edge_id: str):
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({"ok": False, "error": "JSON object required"}), 400
        info = upsert_edge(edge_id, body)
        return jsonify({"ok": True, "edge": info})

    @app.route("/api/v1/edges/<edge_id>/capabilities", methods=["POST"])
    def edge_capabilities_register(edge_id: str):
        """Debug: POST { services, registered_at } — path kept, semantics are services."""
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({"ok": False, "error": "JSON object required"}), 400
        services = normalize_services(body.get("services"))
        if not services:
            return jsonify({"ok": False, "error": "services list required"}), 400
        errors = validate_services(services)
        if errors:
            return jsonify({"ok": False, "error": "; ".join(errors)}), 400
        record = {
            "edge_id": edge_id,
            "services": services,
            "registered_at": body.get("registered_at") or body.get("registeredAt") or time.time(),
            "server_received_at": time.time(),
        }
        _SERVICES[edge_id] = record
        if edge_id in _EDGES:
            _EDGES[edge_id]["services"] = services
            _EDGES[edge_id]["server_received_at"] = time.time()
            strip_legacy_edge_fields(_EDGES[edge_id])
        else:
            _EDGES[edge_id] = {
                "edge_id": edge_id,
                "services": services,
                "online_status": "online",
                "server_received_at": time.time(),
            }
        return jsonify({"ok": True, "registration": record})

    @app.route("/api/v1/edges/<edge_id>/capabilities", methods=["GET"])
    def edge_capabilities_get(edge_id: str):
        rec = _SERVICES.get(edge_id)
        if rec is None:
            return jsonify({"ok": False, "error": "not found"}), 404
        return jsonify({"ok": True, "registration": rec})

    @app.route("/api/v1/edges", methods=["GET"])
    def edges_index():
        return jsonify({"ok": True, "edges": list_edges()})

    @app.route("/api/v1/edges/<edge_id>", methods=["GET"])
    def edge_detail(edge_id: str):
        info = get_edge(edge_id)
        if info is None:
            return jsonify({"ok": False, "error": "not found"}), 404
        return jsonify({"ok": True, "edge": info})


def create_app() -> Flask:
    app = Flask(__name__)
    register_edge_routes(app)

    @app.get("/health")
    def health():
        return jsonify({"ok": True, "edges": len(_EDGES)})

    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=9527, debug=True)
