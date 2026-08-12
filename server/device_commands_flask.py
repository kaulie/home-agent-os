"""Living-room intents queue — GET /api/v1/devices/living-room/intents

Production-shaped response::

  {
    "intents": [
      {
        "id": 1,
        "status": "intent_parsed",
        "assigned_edge_id": "living-room-iphone-xxxx",
        "execution_plan": [
          {"capability": "camera.capture", "step": 1}
        ]
      }
    ]
  }

Query:
  ?edge_id=<this-node>           **required** — missing → empty intents
  ?intent_status=intent_parsed   filter by status (optional)
  ?peek=1                        peek without consuming (optional)

App default URL:
  http://115.190.153.53:9527/api/v1/devices/living-room/intents?edge_id=...&intent_status=intent_parsed
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from flask import Flask, jsonify, request

try:
    from edge_services import (
        normalize_execution_plan,
        plan_camera_capture,
        plan_music_play,
        plan_take_video,
        resolve_edge_for_plan,
    )
except ImportError:  # pragma: no cover
    from server.edge_services import (  # type: ignore
        normalize_execution_plan,
        plan_camera_capture,
        plan_music_play,
        plan_take_video,
        resolve_edge_for_plan,
    )

INTENTS_PATH = "/api/v1/devices/living-room/intents"
# Backward-compatible alias (old clients).
COMMANDS_PATH = "/api/v1/devices/living-room/commands"

_PENDING_INTENTS: list[dict[str, Any]] = []
_NEXT_ID = 1


def _list_online_edges() -> list[dict[str, Any]]:
    try:
        from edge_heartbeat_flask import list_edges  # type: ignore
    except Exception:
        try:
            from server.edge_heartbeat_flask import list_edges  # type: ignore
        except Exception:
            return []
    return list_edges(apply_ttl=True)


def _assign_edge_for_plan(
    plan: list[dict[str, Any]],
    *,
    preferred_edge_id: str | None = None,
    room: str | None = None,
    assigned_edge_id: str | None = None,
) -> tuple[str, str]:
    """
    Resolve assigned_edge_id for a plan.
    Returns (edge_id, reason). Raises ValueError if none.
    """
    edges = _list_online_edges()
    explicit = (assigned_edge_id or "").strip()
    if explicit:
        match = next(
            (
                e
                for e in edges
                if str(e.get("edge_id") or "").strip() == explicit
                and str(e.get("online_status") or "").lower() == "online"
            ),
            None,
        )
        if match is None:
            raise ValueError(f"assigned_edge_id '{explicit}' not online or unknown")
        routed = resolve_edge_for_plan(
            plan,
            [match],
            preferred_edge_id=explicit,
            room=room,
            online_only=True,
        )
        if not routed.get("ok"):
            raise ValueError(
                routed.get("reason")
                or f"assigned_edge_id '{explicit}' missing required capabilities"
            )
        return explicit, str(routed.get("reason") or "explicit assigned_edge_id")

    routed = resolve_edge_for_plan(
        plan,
        edges,
        preferred_edge_id=preferred_edge_id,
        room=room,
        online_only=True,
    )
    if not routed.get("ok") or not routed.get("edge_id"):
        raise ValueError(str(routed.get("reason") or "no online edge for plan"))
    return str(routed["edge_id"]), str(routed.get("reason") or "routed")


def enqueue_intent(
    *,
    intent_id: int | None = None,
    status: str = "intent_parsed",
    execution_plan: list[dict[str, Any]] | None = None,
    preferred_edge_id: str | None = None,
    room: str | None = None,
    assigned_edge_id: str | None = None,
    skip_routing: bool = False,
    **extra: Any,
) -> dict[str, Any]:
    """Enqueue an intent for Edge pull (always sets assigned_edge_id unless skip_routing)."""
    global _NEXT_ID
    iid = int(intent_id) if intent_id is not None else _NEXT_ID
    if intent_id is None:
        _NEXT_ID += 1
    else:
        _NEXT_ID = max(_NEXT_ID, iid + 1)

    plan = execution_plan if execution_plan is not None else plan_camera_capture()
    normalized, err = normalize_execution_plan(plan)
    if err:
        raise ValueError(err)
    assert normalized is not None

    # Prefer explicit kwargs; fall back to extras from callers.
    preferred = preferred_edge_id or extra.pop("preferred_edge_id", None) or extra.pop("edge_id", None)
    preferred = str(preferred).strip() if preferred else None
    room_val = room or extra.pop("room", None)
    room_val = str(room_val).strip() if room_val else None
    assigned = assigned_edge_id or extra.pop("assigned_edge_id", None)
    assigned = str(assigned).strip() if assigned else None
    routing_reason = extra.pop("routing_reason", None)

    if not skip_routing:
        assigned, routing_reason = _assign_edge_for_plan(
            normalized,
            preferred_edge_id=preferred,
            room=room_val,
            assigned_edge_id=assigned,
        )

    item: dict[str, Any] = {
        "id": iid,
        "status": status,
        "execution_plan": normalized,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **extra,
    }
    # Intent arrival time at Brain (Unix ms). Callers may override via extra.
    if "base_time" not in item:
        try:
            from execution_timing import now_ms
        except ImportError:  # pragma: no cover
            from server.execution_timing import now_ms  # type: ignore
        item["base_time"] = now_ms()
    else:
        try:
            item["base_time"] = int(item["base_time"])
        except (TypeError, ValueError):
            try:
                from execution_timing import now_ms
            except ImportError:  # pragma: no cover
                from server.execution_timing import now_ms  # type: ignore
            item["base_time"] = now_ms()
    if assigned:
        item["assigned_edge_id"] = assigned
    if routing_reason:
        item["routing_reason"] = routing_reason
    # Same id → replace (re-queue after pop / cross-edge step handoff).
    return upsert_intent_in_queue(item)


def enqueue_command(action: str, device: str = "gopro", **extra: Any) -> dict[str, Any]:
    """Compat helper used by intent_dispatch_flask photo/music stubs.

    Maps shutter/gopro → camera.capture; play/music → music.play.
    """
    intent_id = extra.pop("intent_id", None) or extra.pop("job_id", None)
    try:
        iid = int(intent_id) if intent_id is not None else None
    except (TypeError, ValueError):
        iid = None
    a = (action or "").lower()
    d = (device or "").lower()
    song = extra.pop("song", None)
    artist = extra.pop("artist", None)
    # Rewrite then drop legacy aliases so they never remain on the plan.
    if artist is None:
        artist = extra.pop("singer_name", None) or extra.pop("author", None)
    else:
        extra.pop("singer_name", None)
        extra.pop("author", None)
    if song is None:
        song = extra.pop("song_name", None)
    else:
        extra.pop("song_name", None)

    if a in ("play", "play_song", "music.play") or d in ("netease", "netease.music", "music"):
        plan = plan_music_play(
            song=str(song or "").strip() or "十年",
            artist=str(artist).strip() if artist else None,
        )
    elif a in ("record", "start_recording", "take_video", "video"):
        plan = plan_take_video()
    else:
        plan = plan_camera_capture()
        if a in ("shutter", "capture", "capture_photo", "photo", "camera.capture", "take_photo") or d in (
            "gopro",
            "camera",
            "gopro.camera",
        ):
            plan = plan_camera_capture()

    timing = extra.pop("timing", None)
    if isinstance(timing, dict) and plan:
        plan = [dict(s) for s in plan]
        plan[0]["execution_timing"] = timing

    return enqueue_intent(
        intent_id=iid,
        status=str(extra.pop("status", "intent_parsed")),
        execution_plan=plan,
        **extra,
    )


def enqueue_music_play(
    *,
    song: str,
    artist: str | None = None,
    intent_id: int | None = None,
    status: str = "intent_parsed",
    **extra: Any,
) -> dict[str, Any]:
    """Enqueue music.play with wire schema params song / artist."""
    plan = plan_music_play(song=song, artist=artist)
    timing = extra.pop("timing", None)
    if isinstance(timing, dict) and plan:
        plan = [dict(plan[0])]
        plan[0]["execution_timing"] = timing
    return enqueue_intent(
        intent_id=intent_id,
        status=status,
        execution_plan=plan,
        **extra,
    )


def enqueue_notify_speak(
    *,
    text: str,
    lang: str | None = None,
    intent_id: int | None = None,
    status: str = "intent_parsed",
    **extra: Any,
) -> dict[str, Any]:
    """Enqueue notify.speak for Mac TTS."""
    try:
        from edge_services import plan_notify_speak
    except ImportError:
        from server.edge_services import plan_notify_speak  # type: ignore

    plan = plan_notify_speak(text=text, lang=lang)
    timing = extra.pop("timing", None)
    if isinstance(timing, dict) and plan:
        plan = [dict(plan[0])]
        plan[0]["execution_timing"] = timing
    return enqueue_intent(
        intent_id=intent_id,
        status=status,
        execution_plan=plan,
        **extra,
    )


_TERMINAL_STATUSES = frozenset({"succeeded", "failed"})


def _intent_status(item: dict[str, Any]) -> str:
    return str(item.get("status") or item.get("intent_status") or "").strip().lower()


def _intent_touches_edge(item: dict[str, Any], edge_id: str) -> bool:
    """True if this edge is scheduler, top-level assignee, or any plan step assignee."""
    want = edge_id.strip()
    if not want:
        return False
    if str(item.get("assigned_edge_id") or "").strip() == want:
        return True
    if str(item.get("scheduler_node") or item.get("schedulerNode") or "").strip() == want:
        return True
    plan = item.get("execution_plan")
    if isinstance(plan, list):
        for step in plan:
            if not isinstance(step, dict):
                continue
            assigned = str(
                step.get("assigned_edge_id") or step.get("assignedEdgeId") or ""
            ).strip()
            if assigned == want:
                return True
    return False


def _filter_intents(
    status: str | None = None,
    *,
    edge_id: str | None = None,
    include_terminal: bool = False,
) -> list[dict[str, Any]]:
    items = list(_PENDING_INTENTS)
    if status:
        want = status.strip().lower()
        items = [i for i in items if _intent_status(i) == want]
    elif not include_terminal:
        # Pull queue is for work-in-progress only; terminal intents must not block Edge.
        items = [i for i in items if _intent_status(i) not in _TERMINAL_STATUSES]
    if edge_id:
        items = [i for i in items if _intent_touches_edge(i, edge_id)]
    return items


def remove_intent_from_queue(intent_id: str | int) -> bool:
    """Drop an intent from the pull queue (used when status becomes terminal)."""
    global _PENDING_INTENTS
    want = str(intent_id).strip()
    if not want:
        return False
    before = len(_PENDING_INTENTS)
    _PENDING_INTENTS = [
        i for i in _PENDING_INTENTS if str(i.get("id") or "").strip() != want
    ]
    return len(_PENDING_INTENTS) < before


def upsert_intent_in_queue(item: dict[str, Any]) -> dict[str, Any]:
    """Insert or replace a queue row by id (keeps cross-edge steps visible after pop)."""
    global _PENDING_INTENTS
    want = str(item.get("id") or "").strip()
    if not want:
        raise ValueError("upsert_intent_in_queue requires item.id")
    for idx, existing in enumerate(_PENDING_INTENTS):
        if str(existing.get("id") or "").strip() == want:
            merged = dict(existing)
            merged.update(item)
            _PENDING_INTENTS[idx] = merged
            return merged
    copy = dict(item)
    _PENDING_INTENTS.append(copy)
    return copy


def pop_intents(
    *,
    intent_status: str | None = None,
    edge_id: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Return matching intents and remove them by id (FIFO within filter)."""
    global _PENDING_INTENTS
    matched = _filter_intents(intent_status, edge_id=edge_id)
    if limit is not None:
        matched = matched[:limit]
    if not matched:
        return []
    matched_ids: list[str] = []
    seen: set[str] = set()
    for item in matched:
        key = str(item.get("id") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        matched_ids.append(key)
    kept: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    remove_budget = set(matched_ids)
    for item in _PENDING_INTENTS:
        key = str(item.get("id") or "").strip()
        if key in remove_budget:
            removed.append(item)
            remove_budget.discard(key)
        else:
            kept.append(item)
    _PENDING_INTENTS = kept
    return removed


def peek_intents(
    *,
    intent_status: str | None = None,
    edge_id: str | None = None,
    include_terminal: bool = False,
) -> list[dict[str, Any]]:
    return _filter_intents(
        intent_status, edge_id=edge_id, include_terminal=include_terminal
    )


def pop_commands(limit: int | None = None) -> list[dict[str, Any]]:
    """Legacy name — pops all intents (no status / edge filter). Prefer pop_intents."""
    return pop_intents(limit=limit)


def peek_commands() -> list[dict[str, Any]]:
    return peek_intents()


def register_intent_queue_routes(app: Flask) -> None:
    def _pull():
        edge_id = (request.args.get("edge_id") or request.args.get("edgeId") or "").strip()
        if not edge_id:
            # Must pass this node's edge_id; otherwise return nothing.
            return jsonify({"intents": []})
        peek = request.args.get("peek") in ("1", "true", "yes")
        status = (request.args.get("intent_status") or request.args.get("status") or "").strip()
        status = status or None
        intents = (
            peek_intents(intent_status=status, edge_id=edge_id)
            if peek
            else pop_intents(intent_status=status, edge_id=edge_id)
        )
        return jsonify({"intents": intents})

    @app.route(INTENTS_PATH, methods=["GET"])
    def pull_living_room_intents():
        return _pull()

    @app.route(COMMANDS_PATH, methods=["GET"])
    def pull_living_room_commands_alias():
        """Alias: still returns intents-shaped JSON."""
        return _pull()

    @app.route(INTENTS_PATH, methods=["POST"])
    def enqueue_living_room_intent():
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            return jsonify(ok=False, error="JSON object required"), 400
        plan = body.get("execution_plan")
        normalized, err = normalize_execution_plan(plan)
        if err:
            return jsonify(ok=False, error=err), 400
        skip_routing = body.get("skip_routing") in (True, 1, "1", "true", "yes")
        extra: dict[str, Any] = {}
        for key in ("scheduler_node", "schedulerNode", "context", "ctx_param", "outputs", "text", "source"):
            if body.get(key) is not None:
                extra[key] = body[key]
        try:
            item = enqueue_intent(
                intent_id=body.get("id") or body.get("intent_id"),
                status=str(body.get("status") or body.get("intent_status") or "intent_parsed"),
                execution_plan=normalized,
                preferred_edge_id=body.get("preferred_edge_id") or body.get("edge_id"),
                room=body.get("room"),
                assigned_edge_id=body.get("assigned_edge_id"),
                skip_routing=skip_routing,
                **extra,
            )
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400
        return jsonify(ok=True, intent=item)

    @app.route("/health/intents", methods=["GET"])
    def intents_health():
        return jsonify(ok=True, intents=INTENTS_PATH, pending=len(_PENDING_INTENTS))


def create_app() -> Flask:
    app = Flask(__name__)
    register_intent_queue_routes(app)
    return app


app = create_app()


if __name__ == "__main__":
    print(f"intents GET  http://0.0.0.0:9527{INTENTS_PATH}")
    print(f"  required: ?edge_id=<this-node>")
    print(f"  filter:   ?intent_status=intent_parsed")
    print(f"  peek:     ?peek=1")
    app.run(host="0.0.0.0", port=9527, debug=True)
