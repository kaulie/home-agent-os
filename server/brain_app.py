"""Unified Brain Flask app — register/heartbeat + intents queue + intent dispatch.

Run (from repo root or server/):

  python brain_app.py
  # or: python -m server.brain_app

Shares in-memory edge registry with the intents router so capability-based
assignment works in one process.
"""

from __future__ import annotations

from flask import Flask, jsonify

try:
    from edge_heartbeat_flask import register_edge_heartbeat_routes
    from device_commands_flask import register_intent_queue_routes
    from intent_dispatch_flask import register_intent_routes
except ImportError:  # pragma: no cover
    from server.edge_heartbeat_flask import register_edge_heartbeat_routes  # type: ignore
    from server.device_commands_flask import register_intent_queue_routes  # type: ignore
    from server.intent_dispatch_flask import register_intent_routes  # type: ignore


def create_app() -> Flask:
    app = Flask(__name__)
    register_edge_heartbeat_routes(app)
    register_intent_queue_routes(app)
    register_intent_routes(app)

    @app.get("/health")
    def health():
        try:
            from edge_heartbeat_flask import _EDGES, _REGISTERED, ONLINE_TTL_SEC  # type: ignore
        except ImportError:
            from server.edge_heartbeat_flask import (  # type: ignore
                _EDGES,
                _REGISTERED,
                ONLINE_TTL_SEC,
            )
        try:
            from device_commands_flask import _PENDING_INTENTS  # type: ignore
        except ImportError:
            from server.device_commands_flask import _PENDING_INTENTS  # type: ignore
        return jsonify(
            {
                "ok": True,
                "app": "brain",
                "registered": len(_REGISTERED),
                "edges": len(_EDGES),
                "pending_intents": len(_PENDING_INTENTS),
                "ttlSec": ONLINE_TTL_SEC,
            }
        )

    return app


app = create_app()


if __name__ == "__main__":
    print("Brain unified app on :9527")
    print("  POST /api/v1/edge-register")
    print("  POST /api/v1/edge-heartbeat")
    print("  GET  /api/v1/capabilities")
    print("  GET  /api/v1/devices/living-room/intents?edge_id=...&intent_status=intent_parsed")
    print("  POST /api/v1/intent")
    app.run(host="0.0.0.0", port=9527, debug=True, threaded=True)
