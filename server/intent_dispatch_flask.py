"""Intent dispatch — aligned with production response shape.

POST /api/v1/intent →
  {
    "ok": true,
    "intent_id": 1,
    "intent_status": "intent_received",
    "text": "...",
    "source": "text|voice",
    "edge_id": "...",
    "reply": "..."
  }

Stub also advances status through the logistics timeline and exposes:
  GET  /api/v1/intent_detail?intent_id=<id>
  GET  /api/v1/intent/<intent_id>
  POST /api/v1/intent/<intent_id>/status
  GET  /api/v1/intent/jobs/<id>          (alias)
  POST /api/v1/intent/jobs/<id>/status   (alias)
"""

from __future__ import annotations

import time
from copy import deepcopy
from typing import Any

from flask import Flask, jsonify, request

INTENT_PATH = "/api/v1/intent"

# Wire statuses (production: intent_received → intent_parsed → …).
_STATUS_ORDER = [
    "intent_received",
    "intent_parsed",
    "hub_received",
    "scheduled",
    "assigned",
    "running",
    "succeeded",
    "failed",
]

_PHASE_LABELS = {
    "intent_received": "上传到服务器，待意图解析",
    "intent_parsed": "意图解析完成，待下发到中控节点",
    "hub_received": "中控节点已收到，待执行调度",
    "scheduled": "任务已调度",
    "assigned": "任务已分配到 edge runtime node",
    "running": "任务执行中",
    "succeeded": "任务执行完成（成功）",
    "failed": "任务执行完成（失败）",
}

_WIRE_ALIASES = {
    "uploaded": "intent_received",
    "success": "succeeded",
    "completed": "succeeded",
    "error": "failed",
}

_JOBS: dict[str, dict[str, Any]] = {}
_NEXT_INTENT_ID = 1


def _now() -> float:
    return time.time()


def _normalize_status(status: str) -> str:
    s = (status or "").strip().lower()
    return _WIRE_ALIASES.get(s, s)


def _status_rank(status: str) -> int:
    s = _normalize_status(status)
    try:
        return _STATUS_ORDER.index(s)
    except ValueError:
        return -1


def _append_step(job: dict[str, Any], status: str, detail: str = "") -> None:
    status = _normalize_status(status)
    steps: list[dict[str, Any]] = job.setdefault("steps", [])
    steps.append(
        {
            "status": status,
            "intent_status": status,
            "label": _PHASE_LABELS.get(status, status),
            "at": _now(),
            "detail": detail,
        }
    )
    job["status"] = status
    job["intent_status"] = status
    job["updated_at"] = _now()
    if detail:
        job["detail"] = detail


def _set_status(
    job: dict[str, Any],
    status: str,
    *,
    detail: str = "",
    edge_node_id: str | None = None,
    force: bool = False,
) -> bool:
    status = _normalize_status(status)
    cur = _normalize_status(str(job.get("intent_status") or job.get("status") or ""))
    if cur in ("succeeded", "failed") and not force:
        return False
    if not force and _status_rank(status) < _status_rank(cur):
        return False
    if status == cur and not detail and edge_node_id is None:
        return True
    if edge_node_id:
        job["edge_node_id"] = edge_node_id
    if status == "failed":
        job["error"] = detail or job.get("error") or "failed"
    _append_step(job, status, detail=detail)
    return True


def _looks_like_photo_intent(text: str) -> bool:
    t = text.strip().lower()
    keys = ("拍", "拍照", "照相", "photo", "shutter", "capture", "gopro", "相机")
    return any(k in t for k in keys)


def _looks_like_music_intent(text: str) -> bool:
    t = text.strip().lower()
    keys = ("播", "放歌", "播放", "听", "音乐", "网易云", "play", "song", "music", "netease")
    return any(k in t for k in keys)


def _looks_like_notify_intent(text: str) -> bool:
    t = text.strip().lower()
    keys = (
        "提醒",
        "叫我",
        "通知",
        "告诉",
        "该吃饭",
        "该睡觉",
        "吃饭了",
        "睡觉了",
        "平板支撑",
        "撑住",
        "倒计时",
        "notify",
        "remind",
        "say ",
        "念",
    )
    return any(k in t for k in keys)


def _parse_notify_text_from_intent(text: str) -> str:
    """Heuristic speak text for notify.speak."""
    t = (text or "").strip()
    if not t:
        return "提醒"
    # Common canned phrases
    if "吃饭" in t:
        return "该吃饭了"
    if "睡觉" in t:
        return "该睡觉了"
    if "平板支撑" in t or "撑住" in t:
        return "坚持，又过了三十秒"
    # "提醒我XXX" / "叫我XXX"
    for prefix in ("提醒我", "提醒一下", "提醒", "叫我", "通知我", "告诉我", "请说", "念一下"):
        if t.startswith(prefix):
            rest = t[len(prefix) :].strip(" ，,：:")
            if rest:
                return rest
    # Strip leading timing-ish wrappers for a shorter utterance
    return t


def _parse_song_artist_from_text(text: str) -> tuple[str, str | None]:
    """Heuristic: '播放 十年 陈奕迅' / '放歌 十年' → song, artist."""
    t = text.strip()
    for prefix in ("播放", "放歌", "听", "播一下", "来一首", "play", "播放歌曲"):
        if t.lower().startswith(prefix.lower()):
            t = t[len(prefix) :].strip()
            break
    if not t:
        return "十年", None
    parts = t.split()
    if len(parts) >= 2:
        return parts[0], " ".join(parts[1:])
    return t, None


def _try_enqueue_photo_command(
    intent_id: int,
    edge_id: str,
    *,
    timing: dict[str, Any] | None = None,
    base_time: int | None = None,
) -> dict[str, Any] | None:
    try:
        from device_commands_flask import enqueue_command  # type: ignore
    except Exception:
        try:
            from server.device_commands_flask import enqueue_command  # type: ignore
        except Exception:
            enqueue_command = None  # type: ignore
    if enqueue_command is None:
        return None
    try:
        return enqueue_command(
            "shutter",
            device="gopro",
            intent_id=intent_id,
            job_id=str(intent_id),
            preferred_edge_id=edge_id or None,
            room="living-room",
            timing=timing,
            base_time=base_time,
        )
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}


def _try_enqueue_music_command(
    intent_id: int,
    edge_id: str,
    *,
    song: str,
    artist: str | None,
    timing: dict[str, Any] | None = None,
    base_time: int | None = None,
) -> dict[str, Any] | None:
    try:
        from device_commands_flask import enqueue_music_play  # type: ignore
    except Exception:
        try:
            from server.device_commands_flask import enqueue_music_play  # type: ignore
        except Exception:
            enqueue_music_play = None  # type: ignore
    if enqueue_music_play is None:
        return None
    try:
        return enqueue_music_play(
            song=song,
            artist=artist,
            intent_id=intent_id,
            preferred_edge_id=edge_id or None,
            room="living-room",
            timing=timing,
            base_time=base_time,
        )
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}


def _try_enqueue_notify_command(
    intent_id: int,
    edge_id: str,
    *,
    text: str,
    lang: str | None = None,
    timing: dict[str, Any] | None = None,
    base_time: int | None = None,
) -> dict[str, Any] | None:
    try:
        from device_commands_flask import enqueue_notify_speak  # type: ignore
    except Exception:
        try:
            from server.device_commands_flask import enqueue_notify_speak  # type: ignore
        except Exception:
            enqueue_notify_speak = None  # type: ignore
    if enqueue_notify_speak is None:
        return None
    try:
        return enqueue_notify_speak(
            text=text,
            lang=lang,
            intent_id=intent_id,
            preferred_edge_id=edge_id or None,
            room="living-room",
            timing=timing,
            base_time=base_time,
        )
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}


def handle_intent(text: str, source: str, edge_id: str) -> str:
    return f"已收到指令（{source}）：{text}"


def create_intent_job(text: str, source: str, edge_id: str) -> dict[str, Any]:
    global _NEXT_INTENT_ID
    intent_id = _NEXT_INTENT_ID
    _NEXT_INTENT_ID += 1
    key = str(intent_id)
    try:
        from execution_timing import (
            infer_timing_from_text,
            stamp_base_time,
        )
    except ImportError:
        from server.execution_timing import (  # type: ignore
            infer_timing_from_text,
            stamp_base_time,
        )
    job: dict[str, Any] = {
        "intent_id": intent_id,
        "job_id": key,
        "text": text,
        "source": source,
        "edge_id": edge_id,
        "intent_status": "intent_received",
        "status": "intent_received",
        "execution_plan": [],
        "steps": [],
        "edge_node_id": None,
        "assigned_edge_id": None,
        "error": None,
        "command_id": None,
        "created_at": _now(),
        "updated_at": _now(),
        "reply": handle_intent(text, source, edge_id),
    }
    base_time = stamp_base_time(job)
    _append_step(job, "intent_received", detail="client uploaded intent")
    # Brain stub: stop at intent_parsed. Later stages come from Edge status POST.
    _set_status(job, "intent_parsed", detail="stub intent parse ok")

    timing = infer_timing_from_text(text, base_time)

    if _looks_like_photo_intent(text):
        try:
            from edge_services import plan_camera_capture
        except ImportError:
            from server.edge_services import plan_camera_capture  # type: ignore
        plan = plan_camera_capture()
        if timing:
            plan[0]["execution_timing"] = timing
        job["execution_plan"] = plan
        cmd = _try_enqueue_photo_command(intent_id, edge_id, timing=timing, base_time=base_time)
        if cmd and cmd.get("error"):
            job["error"] = cmd["error"]
            job["reply"] = f"无法调度拍照：{cmd['error']}"
        elif cmd:
            job["command_id"] = cmd.get("id")
            job["assigned_edge_id"] = cmd.get("assigned_edge_id")
            job["edge_node_id"] = cmd.get("assigned_edge_id")
    elif _looks_like_music_intent(text):
        try:
            from edge_services import plan_music_play
        except ImportError:
            from server.edge_services import plan_music_play  # type: ignore
        song, artist = _parse_song_artist_from_text(text)
        plan = plan_music_play(song=song, artist=artist)
        if timing:
            plan[0]["execution_timing"] = timing
        job["execution_plan"] = plan
        cmd = _try_enqueue_music_command(
            intent_id, edge_id, song=song, artist=artist, timing=timing, base_time=base_time
        )
        if cmd and cmd.get("error"):
            job["error"] = cmd["error"]
            job["reply"] = f"无法调度放歌：{cmd['error']}"
        elif cmd:
            job["command_id"] = cmd.get("id")
            job["assigned_edge_id"] = cmd.get("assigned_edge_id")
            job["edge_node_id"] = cmd.get("assigned_edge_id")
    elif _looks_like_notify_intent(text):
        try:
            from edge_services import plan_notify_speak
        except ImportError:
            from server.edge_services import plan_notify_speak  # type: ignore
        speak = _parse_notify_text_from_intent(text)
        plan = plan_notify_speak(text=speak, lang="zh_CN")
        if timing:
            plan[0]["execution_timing"] = timing
        job["execution_plan"] = plan
        cmd = _try_enqueue_notify_command(
            intent_id,
            edge_id,
            text=speak,
            lang="zh_CN",
            timing=timing,
            base_time=base_time,
        )
        if cmd and cmd.get("error"):
            job["error"] = cmd["error"]
            job["reply"] = f"无法调度提醒：{cmd['error']}"
        elif cmd:
            job["command_id"] = cmd.get("id")
            job["assigned_edge_id"] = cmd.get("assigned_edge_id")
            job["edge_node_id"] = cmd.get("assigned_edge_id")
            job["reply"] = f"已安排语音提醒：{speak}"
    # Keep status at intent_parsed so Edge can report hub_received → … forward-only.

    _JOBS[key] = job
    return job


def get_job(job_id: str) -> dict[str, Any] | None:
    job = _JOBS.get(str(job_id))
    return deepcopy(job) if job else None


def intent_detail_view(job: dict[str, Any]) -> dict[str, Any]:
    """Production GET /api/v1/intent_detail shape."""
    plan = job.get("execution_plan")
    if not isinstance(plan, list):
        plan = []
    view: dict[str, Any] = {
        "id": job["intent_id"],
        "status": job.get("intent_status") or job.get("status"),
        "assigned_edge_id": job.get("assigned_edge_id"),
        "execution_plan": plan,
    }
    if job.get("base_time") is not None:
        try:
            view["base_time"] = int(job["base_time"])
        except (TypeError, ValueError):
            pass
    # Production field name is `ctx_param`; keep `context`/`outputs` for older Edges.
    ctx = job.get("context") if isinstance(job.get("context"), dict) else {}
    outs = job.get("outputs") if isinstance(job.get("outputs"), dict) else {}
    ctx_param = {**outs, **ctx} if (ctx or outs) else {}
    if job.get("ctx_param") and isinstance(job.get("ctx_param"), dict):
        ctx_param = {**ctx_param, **job["ctx_param"]}
    if ctx_param:
        view["ctx_param"] = ctx_param
        view["context"] = ctx_param
    if outs:
        view["outputs"] = outs
    return view


def update_job_status(
    job_id: str,
    status: str,
    *,
    edge_node_id: str | None = None,
    message: str = "",
    outputs: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    job = _JOBS.get(str(job_id))
    if not job:
        return None, "job not found"
    status = _normalize_status(status)
    if status not in _STATUS_ORDER:
        return None, f"invalid status: {status}"
    ok = _set_status(
        job,
        status,
        detail=message,
        edge_node_id=edge_node_id,
    )
    if isinstance(outputs, dict) and outputs:
        cleaned = {
            str(k): str(v)
            for k, v in outputs.items()
            if v is not None and str(v).strip() and not str(v).strip().startswith("$")
        }
        if cleaned:
            prev = job.get("outputs") if isinstance(job.get("outputs"), dict) else {}
            job["outputs"] = {**prev, **cleaned}
            # Register into context only keys declared by plan output_constrict.
            _publish_outputs_via_plan_constrict(job, cleaned)
    if not ok:
        _sync_job_to_intent_queue(job_id, job, status=None)
        return deepcopy(job), "status not advanced (terminal or backward)"
    _sync_job_to_intent_queue(job_id, job, status=status)
    return deepcopy(job), None


def _publishes_to_context(meta: Any) -> bool:
    if not isinstance(meta, dict):
        return False
    dest = str(meta.get("data_dest") or meta.get("dataDest") or "").strip().lower()
    return dest == "context"


def _merge_context(job: dict[str, Any], values: dict[str, str]) -> None:
    ctx = job.get("context")
    if not isinstance(ctx, dict):
        ctx = {}
    ctx = {**ctx, **values}
    job["context"] = ctx
    # Production pull/detail field.
    prev = job.get("ctx_param") if isinstance(job.get("ctx_param"), dict) else {}
    job["ctx_param"] = {**prev, **ctx}


def _publish_outputs_via_plan_constrict(
    job: dict[str, Any], outputs: dict[str, str]
) -> list[str]:
    plan = job.get("execution_plan")
    if not isinstance(plan, list):
        return []
    published: dict[str, str] = {}
    for step in plan:
        if not isinstance(step, dict):
            continue
        raw = step.get("output_constrict") or step.get("output_construct") or {}
        if not isinstance(raw, dict):
            continue
        for key, meta in raw.items():
            if not _publishes_to_context(meta):
                continue
            k = str(key).strip()
            if k in outputs:
                published[k] = outputs[k]
    if published:
        _merge_context(job, published)
    return list(published.keys())


def _publish_outputs_to_context(
    job: dict[str, Any],
    step: dict[str, Any] | None,
    outputs: dict[str, Any],
) -> list[str]:
    """Register outputs into job.context using step output_constrict (data_dest=context)."""
    cleaned = {
        str(k): str(v).strip()
        for k, v in outputs.items()
        if v is not None and str(v).strip() and not str(v).strip().startswith("$")
    }
    if not cleaned:
        return []
    published: dict[str, str] = {}
    if isinstance(step, dict):
        raw = step.get("output_constrict") or step.get("output_construct") or {}
        if isinstance(raw, dict):
            for key, meta in raw.items():
                if not _publishes_to_context(meta):
                    continue
                k = str(key).strip()
                if k in cleaned:
                    published[k] = cleaned[k]
    if published:
        _merge_context(job, published)
    # Always keep raw capability outputs for debugging / legacy readers.
    prev = job.get("outputs") if isinstance(job.get("outputs"), dict) else {}
    job["outputs"] = {**prev, **cleaned}
    if isinstance(step, dict):
        step_out = step.get("outputs") if isinstance(step.get("outputs"), dict) else {}
        step["outputs"] = {**step_out, **cleaned}
    return list(published.keys())


def _sync_job_to_intent_queue(
    job_id: str | int,
    job: dict[str, Any],
    *,
    status: str | None,
) -> None:
    """Keep pull-queue row in sync with the job store.

    Critical for multi-edge plans: if an Edge popped the queue (or an old Brain
    ignored peek), step/status updates must **re-insert** the intent so the next
    assignee (e.g. Mac display.photo) can still pull it.
    """
    try:
        from device_commands_flask import (  # type: ignore
            peek_intents,
            remove_intent_from_queue,
            upsert_intent_in_queue,
        )
    except Exception:
        try:
            from server.device_commands_flask import (  # type: ignore
                peek_intents,
                remove_intent_from_queue,
                upsert_intent_in_queue,
            )
        except Exception:
            return
    wire = (status or job.get("intent_status") or job.get("status") or "").strip().lower()
    if wire in ("succeeded", "failed"):
        remove_intent_from_queue(job_id)
        return

    patch: dict[str, Any] = {
        "id": int(job_id) if str(job_id).isdigit() else job_id,
        "status": wire or str(job.get("status") or "running"),
    }
    if isinstance(job.get("execution_plan"), list):
        patch["execution_plan"] = job["execution_plan"]
    if isinstance(job.get("context"), dict) and job["context"]:
        patch["context"] = job["context"]
        patch["ctx_param"] = job.get("ctx_param") or job["context"]
    elif isinstance(job.get("ctx_param"), dict) and job["ctx_param"]:
        patch["ctx_param"] = job["ctx_param"]
        patch["context"] = job["ctx_param"]
    if isinstance(job.get("outputs"), dict) and job["outputs"]:
        patch["outputs"] = job["outputs"]
        # Prefer folding outputs into ctx_param for production pull consumers.
        base = patch.get("ctx_param") if isinstance(patch.get("ctx_param"), dict) else {}
        patch["ctx_param"] = {**job["outputs"], **base}
    for key in (
        "scheduler_node",
        "schedulerNode",
        "assigned_edge_id",
        "assignedEdgeId",
        "text",
        "source",
        "room",
        "base_time",
    ):
        if job.get(key) is not None:
            patch[key] = job[key]

    try:
        for item in peek_intents(include_terminal=True):
            if str(item.get("id")) != str(job_id):
                continue
            if status:
                item["status"] = status
            for k, v in patch.items():
                if k == "id":
                    continue
                if v is not None:
                    item[k] = v
            return
        # Not in queue anymore — put it back so Mac/iPhone can peek step 2+.
        upsert_intent_in_queue(patch)
    except Exception:
        pass


def update_step_status(
    job_id: str,
    step_id: str | int,
    *,
    step_status: int,
    edge_node_id: str | None = None,
    outputs: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Update execution_plan[step].status; publish outputs → context via output_constrict."""
    job = _JOBS.get(str(job_id))
    if not job:
        return None, "job not found"
    try:
        sid = int(step_id)
        st = int(step_status)
    except (TypeError, ValueError):
        return None, "invalid step_id or step_status"
    if st not in (0, 1, 2, 3):
        return None, "step_status must be 0|1|2|3"
    plan = job.get("execution_plan")
    if not isinstance(plan, list):
        return None, "no execution_plan"
    target = None
    for step in plan:
        if not isinstance(step, dict):
            continue
        try:
            n = int(step.get("step") or 0)
        except (TypeError, ValueError):
            continue
        if n == sid:
            target = step
            break
    if target is None:
        return None, f"step {sid} not found"
    target["status"] = st
    target["step_status"] = st
    if edge_node_id:
        job["edge_node_id"] = str(edge_node_id).strip()
    if isinstance(outputs, dict) and outputs:
        keys = _publish_outputs_to_context(job, target, outputs)
        if keys:
            # no-op log site; keys retained on job.context
            pass
    job["updated_at"] = _now()
    _sync_job_to_intent_queue(job_id, job, status=None)
    return deepcopy(job), None


def job_public_view(job: dict[str, Any]) -> dict[str, Any]:
    """Production-shaped payload (+ steps for timeline clients)."""
    view = {
        "ok": True,
        "intent_id": job["intent_id"],
        "intent_status": job.get("intent_status") or job.get("status"),
        "text": job.get("text"),
        "source": job.get("source"),
        "edge_id": job.get("edge_id"),
        "assigned_edge_id": job.get("assigned_edge_id"),
        "reply": job.get("reply"),
        # extras for logistics UI / edge
        "job_id": job.get("job_id"),
        "status": job.get("intent_status") or job.get("status"),
        "edge_node_id": job.get("edge_node_id"),
        "error": job.get("error"),
        "command_id": job.get("command_id"),
        "steps": job.get("steps") or [],
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
    }
    if isinstance(job.get("outputs"), dict) and job["outputs"]:
        view["outputs"] = job["outputs"]
    return view


def register_intent_routes(app: Flask) -> None:
    @app.route(INTENT_PATH, methods=["POST"])
    def dispatch_intent():
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return jsonify(ok=False, error="JSON object required"), 400

        text = str(data.get("text") or "").strip()
        if not text:
            return jsonify(ok=False, error="text is required"), 400

        source = str(data.get("source") or "text").strip().lower() or "text"
        if source not in ("text", "voice"):
            source = "text"
        edge_id = str(data.get("edge_id") or "").strip()

        job = create_intent_job(text, source, edge_id)
        return jsonify(job_public_view(job))

    def _get(job_id: str):
        job = get_job(job_id)
        if not job:
            return jsonify(ok=False, error="job not found"), 404
        return jsonify(job_public_view(job))

    def _post_status(job_id: str):
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return jsonify(ok=False, error="JSON object required"), 400
        status = str(
            data.get("intent_status") or data.get("status") or ""
        ).strip()
        edge_node_id = data.get("edge_node_id") or data.get("edgeNodeId") or data.get("edge_id")
        edge_node_id = str(edge_node_id).strip() if edge_node_id else None
        message = str(data.get("message") or data.get("detail") or "").strip()
        raw_outputs = data.get("outputs")
        if not isinstance(raw_outputs, dict):
            raw_outputs = data.get("ctx_param")
        outputs = raw_outputs if isinstance(raw_outputs, dict) else None
        job, err = update_job_status(
            job_id,
            status,
            edge_node_id=edge_node_id,
            message=message,
            outputs=outputs,
        )
        if job is None:
            return jsonify(ok=False, error=err or "job not found"), 404
        payload = job_public_view(job)
        if err:
            payload["warning"] = err
        return jsonify(payload)

    @app.route("/api/v1/intent_detail", methods=["GET"])
    def get_intent_detail():
        intent_id = (
            request.args.get("intent_id")
            or request.args.get("id")
            or ""
        ).strip()
        if not intent_id:
            return jsonify(ok=False, error="intent_id is required"), 400
        job = get_job(intent_id)
        if not job:
            # Fall back to intents pull queue (device_commands_flask).
            try:
                from device_commands_flask import peek_intents  # type: ignore
            except Exception:
                try:
                    from server.device_commands_flask import peek_intents  # type: ignore
                except Exception:
                    peek_intents = None  # type: ignore
            if peek_intents is not None:
                for item in peek_intents():
                    if str(item.get("id")) == intent_id:
                        view = {
                            "id": item.get("id"),
                            "status": item.get("status"),
                            "assigned_edge_id": item.get("assigned_edge_id"),
                            "execution_plan": item.get("execution_plan") or [],
                        }
                        if isinstance(item.get("ctx_param"), dict) and item["ctx_param"]:
                            view["ctx_param"] = item["ctx_param"]
                            view["context"] = item["ctx_param"]
                        elif isinstance(item.get("context"), dict) and item["context"]:
                            view["ctx_param"] = item["context"]
                            view["context"] = item["context"]
                        if isinstance(item.get("outputs"), dict) and item["outputs"]:
                            view["outputs"] = item["outputs"]
                        return jsonify(view)
            return jsonify(ok=False, error="intent not found"), 404
        return jsonify(intent_detail_view(job))

    @app.route(f"{INTENT_PATH}/<job_id>", methods=["GET"])
    def get_intent_by_id(job_id: str):
        return _get(job_id)

    @app.route(f"{INTENT_PATH}/<job_id>/status", methods=["POST"])
    def post_intent_status_by_id(job_id: str):
        return _post_status(job_id)

    @app.route(f"{INTENT_PATH}/<job_id>/step/<step_id>/status", methods=["POST"])
    def post_step_status(job_id: str, step_id: str):
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return jsonify(ok=False, error="JSON object required"), 400
        raw_status = data.get("step_status", data.get("status"))
        try:
            step_status = int(raw_status)
        except (TypeError, ValueError):
            return jsonify(ok=False, error="step_status required"), 400
        edge_node_id = data.get("edge_node_id") or data.get("edgeNodeId") or data.get("edge_id")
        edge_node_id = str(edge_node_id).strip() if edge_node_id else None
        raw_outputs = data.get("outputs")
        if not isinstance(raw_outputs, dict):
            raw_outputs = data.get("ctx_param")
        outputs = raw_outputs if isinstance(raw_outputs, dict) else None
        job, err = update_step_status(
            job_id,
            step_id,
            step_status=step_status,
            edge_node_id=edge_node_id,
            outputs=outputs,
        )
        if job is None:
            return jsonify(ok=False, error=err or "job not found"), 404
        payload = intent_detail_view(job)
        payload["ok"] = True
        if err:
            payload["warning"] = err
        return jsonify(payload)

    @app.route(f"{INTENT_PATH}/jobs/<job_id>", methods=["GET"])
    def get_intent_job(job_id: str):
        return _get(job_id)

    @app.route(f"{INTENT_PATH}/jobs/<job_id>/status", methods=["POST"])
    def post_intent_job_status(job_id: str):
        return _post_status(job_id)

    @app.route("/health/intent", methods=["GET"])
    def intent_health():
        return jsonify(
            ok=True,
            intent=INTENT_PATH,
            jobs=len(_JOBS),
            statuses=_STATUS_ORDER,
        )


def create_app() -> Flask:
    app = Flask(__name__)
    register_intent_routes(app)
    return app


app = create_app()


if __name__ == "__main__":
    print(f"intent POST   http://0.0.0.0:9527{INTENT_PATH}")
    print(f"intent detail http://0.0.0.0:9527/api/v1/intent_detail?intent_id=<id>")
    print(f"intent GET    http://0.0.0.0:9527{INTENT_PATH}/<intent_id>")
    print(f"intent POST   http://0.0.0.0:9527{INTENT_PATH}/<intent_id>/status")
    print("routes:", [str(r) for r in app.url_map.iter_rules()])
    app.run(host="0.0.0.0", port=9527, threaded=True)
