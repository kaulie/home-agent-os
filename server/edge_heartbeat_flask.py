"""Edge register + heartbeat — 复制到你正在跑的 Flask app

流程：
  1) 首次：POST /api/v1/edge-register  （无可信 edgeId；Brain 确认后返回 edge_id）
  2) 之后：POST /api/v1/edge-heartbeat （必须带已签发的 edgeId）

App 默认：
  http://115.190.153.53:9527/api/v1/edge-register
  http://115.190.153.53:9527/api/v1/edge-heartbeat

curl 注册：
  curl -X POST http://127.0.0.1:9527/api/v1/edge-register \\
    -H 'Content-Type: application/json' \\
    -d '{
      "client_hint": "living-room-iphone",
      "display_name": "客厅 · iPhone Edge",
      "device_type": "iphone",
      "room": "living-room",
      "app_version": "1.0",
      "services": [
        {
          "service_id": "gopro.camera",
          "display_name": "GoPro Camera",
          "version": "0.7.0",
          "group": "camera",
          "capabilities": [
            {
              "capability_id": "camera.capture",
              "description": "拍照并上传，返回服务器下载地址",
              "input_schema": {},
              "output_schema": {
                "photo_local_path": {"type": "string", "required": false, "description": "本地照片路径"},
                "photo_url": {"type": "string", "required": true, "description": "服务器图片下载地址"},
                "saved_as": {"type": "string", "required": false, "description": "服务器侧文件名"}
              }
            },
            {
              "capability_id": "take_video",
              "description": "开始录像",
              "input_schema": {},
              "output_schema": {}
            }
          ]
        }
      ]
    }'

注册返回（App 按此解析）：
  {
    "ok": true,
    "ts": 1753830000.0,
    "status": "approved",
    "edge_id": "living-room-iphone-a1b2c3",
    "message": "registered"
  }
  拒绝时：ok=false, status="rejected", edge_id=""

curl 心跳：
  curl -X POST http://127.0.0.1:9527/api/v1/edge-heartbeat \\
    -H 'Content-Type: application/json' \\
    -d '{
      "edge_id": "<上一步返回的 edge_id>",
      "display_name": "客厅 · iPhone Edge",
      "device_type": "iphone",
      "room": "living-room",
      "online_status": "online",
      "health": {"status": "healthy", "summary": "agent running", "details": {}},
      "services": [
        {
          "service_id": "gopro.camera",
          "display_name": "GoPro Camera",
          "version": "0.7.0",
          "group": "camera",
          "capabilities": [
            {
              "capability_id": "camera.capture",
              "description": "拍照并上传，返回服务器下载地址",
              "input_schema": {},
              "output_schema": {
                "photo_local_path": {"type": "string", "required": false, "description": "本地照片路径"},
                "photo_url": {"type": "string", "required": true, "description": "服务器图片下载地址"},
                "saved_as": {"type": "string", "required": false, "description": "服务器侧文件名"}
              }
            }
          ]
        }
      ],
      "reported_at": 1753830000.0
    }'

查询：
  GET /api/v1/edges
  GET /api/v1/edges/<edge_id>
  GET /api/v1/capabilities   （从心跳 services 展开的在线能力索引）

说明：
  本 stub 默认 auto-approve（模拟「通信确认通过」后签发 edgeId）。
  wire 只存 services[]；顶层 skills / capabilities 丢弃。
  生产可改成 pending + 人工/挑战确认后再签发。
"""

from __future__ import annotations

import time
import uuid
from copy import deepcopy
from typing import Any

from flask import Flask, jsonify, request

try:
    from edge_services import (
        index_capabilities_from_edges,
        normalize_services,
        strip_legacy_edge_fields,
        validate_services,
    )
except ImportError:  # pragma: no cover
    from server.edge_services import (  # type: ignore
        index_capabilities_from_edges,
        normalize_services,
        strip_legacy_edge_fields,
        validate_services,
    )

# ---------------------------------------------------------------------------
# 内存存储（生产可换成 Redis / DB）
# ---------------------------------------------------------------------------

# 已签发 / 已信任的 edgeId → 注册档案
_REGISTERED: dict[str, dict[str, Any]] = {}
# 最新心跳快照
_EDGES: dict[str, dict[str, Any]] = {}
ONLINE_TTL_SEC = 30
# stub：True = 注册即签发；False = 返回 pending（需另接审批）
AUTO_APPROVE = True


def _issue_edge_id(client_hint: str, room: str, device_type: str) -> str:
    hint = (client_hint or "").strip()
    if hint and hint not in _REGISTERED:
        return hint
    base = hint or f"{room or 'edge'}-{device_type or 'device'}"
    return f"{base}-{uuid.uuid4().hex[:6]}"


def register_edge(body: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """首次注册。返回 (json_body, http_status)。"""
    client_hint = (body.get("client_hint") or body.get("clientHint") or "").strip()
    display_name = (body.get("display_name") or body.get("displayName") or client_hint or "edge").strip()
    device_type = (body.get("device_type") or body.get("deviceType") or "other").strip()
    room = (body.get("room") or "living-room").strip()
    services = normalize_services(body.get("services"))
    errors = validate_services(services)
    if errors:
        return (
            {
                "ok": False,
                "ts": time.time(),
                "status": "rejected",
                "edge_id": "",
                "message": "; ".join(errors),
            },
            400,
        )

    if not AUTO_APPROVE:
        return (
            {
                "ok": False,
                "ts": time.time(),
                "status": "rejected",
                "edge_id": "",
                "message": "awaiting confirmation / rejected",
            },
            200,
        )

    edge_id = _issue_edge_id(client_hint, room, device_type)
    record = {
        "edge_id": edge_id,
        "client_hint": client_hint,
        "display_name": display_name,
        "device_type": device_type,
        "room": room,
        "services": services,
        "app_version": body.get("appVersion") or body.get("app_version"),
        "status": "approved",
        "registered_at": time.time(),
        "server_received_at": time.time(),
    }
    _REGISTERED[edge_id] = record
    return (
        {
            "ok": True,
            "ts": time.time(),
            "status": "approved",
            "edge_id": edge_id,
            "message": "registered",
        },
        200,
    )


def upsert_edge_heartbeat(edge_id: str, body: dict[str, Any]) -> dict[str, Any]:
    info = deepcopy(body) if isinstance(body, dict) else {}
    info["edge_id"] = edge_id
    info.pop("edgeId", None)
    services = normalize_services(info.get("services"))
    info["services"] = services
    strip_legacy_edge_fields(info)
    status = str(info.get("online_status") or info.get("onlineStatus") or "online").strip().lower()
    if status not in ("online", "offline"):
        status = "online"
    info["online_status"] = status
    info.pop("onlineStatus", None)
    brain_time_ms = int(time.time() * 1000)
    info["server_received_at"] = brain_time_ms / 1000.0
    info["brain_time_ms"] = brain_time_ms
    # Prefer client_time_ms (Unix ms); fall back to reported_at.
    client_time_ms = info.get("client_time_ms")
    if client_time_ms is None:
        client_time_ms = info.get("clientTimeMs")
    try:
        client_time_ms = int(client_time_ms) if client_time_ms is not None else None
    except (TypeError, ValueError):
        client_time_ms = None
    if client_time_ms is None and ("reported_at" in info or "reportedAt" in info):
        try:
            reported = float(info.get("reported_at") or info.get("reportedAt") or 0)
            # reported_at historically seconds
            client_time_ms = int(reported * 1000) if reported < 10_000_000_000 else int(reported)
        except (TypeError, ValueError):
            client_time_ms = None
    if client_time_ms is not None:
        info["client_time_ms"] = client_time_ms
    info.pop("clientTimeMs", None)
    try:
        from execution_timing import CLOCK_SKEW_REJECT_MS, schedule_eligible_for_client
    except ImportError:  # pragma: no cover
        from server.execution_timing import (  # type: ignore
            CLOCK_SKEW_REJECT_MS,
            schedule_eligible_for_client,
        )
    eligible = schedule_eligible_for_client(client_time_ms, brain_time_ms)
    info["schedule_eligible"] = eligible
    if client_time_ms is not None:
        info["clock_skew_ms"] = abs(client_time_ms - brain_time_ms)
        if not eligible:
            info["schedule_reject_reason"] = (
                f"clock skew {info['clock_skew_ms']}ms > {CLOCK_SKEW_REJECT_MS}ms"
            )
    if "reported_at" not in info and "reportedAt" not in info:
        info["reported_at"] = info["server_received_at"]
    info.pop("reportedAt", None)
    # Keep registration services in sync with latest heartbeat.
    if edge_id in _REGISTERED:
        _REGISTERED[edge_id]["services"] = services
        _REGISTERED[edge_id]["server_received_at"] = info["server_received_at"]
        _REGISTERED[edge_id]["schedule_eligible"] = eligible
    _EDGES[edge_id] = info
    return info


def list_edges(*, apply_ttl: bool = True) -> list[dict[str, Any]]:
    now = time.time()
    out: list[dict[str, Any]] = []
    for edge_id, stored in sorted(_EDGES.items()):
        item = deepcopy(stored)
        strip_legacy_edge_fields(item)
        if "services" not in item or not isinstance(item.get("services"), list):
            item["services"] = []
        if apply_ttl and item.get("online_status") == "online":
            last = float(item.get("server_received_at") or item.get("reported_at") or 0)
            if now - last > ONLINE_TTL_SEC:
                item["online_status"] = "offline"
                item["online_status_note"] = f"ttl expired (>{ONLINE_TTL_SEC}s without heartbeat)"
        out.append(item)
    return out


def get_edge(edge_id: str, *, apply_ttl: bool = True) -> dict[str, Any] | None:
    for item in list_edges(apply_ttl=apply_ttl):
        if item.get("edge_id") == edge_id:
            return item
    return None


def register_edge_heartbeat_routes(app: Flask) -> None:
    @app.route("/api/v1/edge-register", methods=["POST"])
    def edge_register():
        """首次上报：Brain 确认后签发可信 edgeId。"""
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({"ok": False, "error": "JSON object required"}), 400
        payload, code = register_edge(body)
        return jsonify(payload), code

    @app.route("/api/v1/edge-heartbeat", methods=["POST"])
    def edge_heartbeat():
        """后续心跳：必须带已签发的 edgeId；body.services 为唯一能力契约。"""
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({"ok": False, "error": "JSON object required"}), 400
        edge_id = (body.get("edge_id") or "").strip()
        if not edge_id:
            return (
                jsonify({"ok": False, "error": "edge_id required; call /api/v1/edge-register first"}),
                400,
            )
        if edge_id not in _REGISTERED:
            return jsonify({"ok": False, "error": "unknown edge_id; register first"}), 401
        services = normalize_services(body.get("services"))
        errors = validate_services(services)
        if errors:
            return jsonify({"ok": False, "error": "; ".join(errors)}), 400
        body = dict(body)
        body["services"] = services
        info = upsert_edge_heartbeat(edge_id, body)
        return jsonify(
            {
                "ok": True,
                "edge_id": edge_id,
                "online_status": info.get("online_status"),
                "server_received_at": info.get("server_received_at"),
                "brain_time_ms": info.get("brain_time_ms"),
                "schedule_eligible": info.get("schedule_eligible", True),
                "clock_skew_ms": info.get("clock_skew_ms"),
                "edge": info,
            }
        )

    @app.route("/api/v1/edges", methods=["GET"])
    def edges_list():
        edges = list_edges()
        return jsonify(
            {
                "ok": True,
                "edges": edges,
                "registered": list(_REGISTERED.keys()),
            }
        )

    @app.route("/api/v1/edges/<edge_id>", methods=["GET"])
    def edge_get(edge_id: str):
        info = get_edge(edge_id)
        if info is None and edge_id not in _REGISTERED:
            return jsonify({"ok": False, "error": "not found"}), 404
        return jsonify(
            {
                "ok": True,
                "edge": info,
                "registration": _REGISTERED.get(edge_id),
            }
        )

    @app.route("/api/v1/capabilities", methods=["GET"])
    def capabilities_index():
        """Planner-facing index: flatten services[].capabilities from heartbeats."""
        edges = list_edges()
        rows = index_capabilities_from_edges(edges)
        capability = (request.args.get("capability") or request.args.get("capability_id") or "").strip()
        group = (request.args.get("group") or "").strip()
        if capability:
            rows = [r for r in rows if r["capability_id"] == capability]
        if group:
            rows = [r for r in rows if r["group"] == group]
        return jsonify({"ok": True, "capabilities": rows, "count": len(rows)})


register_edge_routes = register_edge_heartbeat_routes


def create_app() -> Flask:
    app = Flask(__name__)
    register_edge_heartbeat_routes(app)

    @app.get("/health")
    def health():
        return jsonify(
            {
                "ok": True,
                "registered": len(_REGISTERED),
                "edges": len(_EDGES),
                "ttlSec": ONLINE_TTL_SEC,
                "autoApprove": AUTO_APPROVE,
            }
        )

    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=9527, debug=True)
