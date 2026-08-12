"""Shared Edge wire helpers: services[] → capabilities + schemas.

Used by register/heartbeat, debug registration, and intent planning stubs.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

# Wire capability_ids Edge clients advertise / accept.
KNOWN_CAPABILITIES: dict[str, dict[str, Any]] = {
    "music.play": {
        "group": "music",
        "service_id": "netease.music",
        "input_schema": {
            "song": {"type": "string", "required": False, "description": "歌曲"},
            "artist": {"type": "string", "required": False, "description": "歌手"},
            "album": {"type": "string", "required": False, "description": "专辑"},
        },
        "output_schema": {},
    },
    "music.pause": {"group": "music", "service_id": "netease.music"},
    "music.stop": {"group": "music", "service_id": "netease.music"},
    "music.next": {"group": "music", "service_id": "netease.music"},
    "music.previous": {"group": "music", "service_id": "netease.music"},
    "camera.capture": {
        "group": "camera",
        "service_id": "gopro.camera",
        "input_schema": {},
        "output_schema": {
            "photo_local_path": {
                "type": "string",
                "required": False,
                "description": "本地照片路径",
            },
            "photo_url": {
                "type": "string",
                "required": True,
                "description": "服务器图片下载地址",
            },
            "saved_as": {
                "type": "string",
                "required": False,
                "description": "服务器侧文件名",
            },
        },
    },
    "take_video": {"group": "camera", "service_id": "gopro.camera"},
    "display.photo": {
        "group": "display",
        "service_id": "chromecast.display",
        "input_schema": {
            "photo_url": {
                "type": "string",
                "required": True,
                "description": "服务器图片下载地址（iPhone Cast Sender → Chromecast）",
            },
        },
        "output_schema": {},
    },
    "bluetooth.connect": {"group": "speaker", "service_id": "marshall.willen"},
    "bluetooth.disconnect": {"group": "speaker", "service_id": "marshall.willen"},
    "notify.speak": {
        "group": "notify",
        "service_id": "local.notify",
        "input_schema": {
            "text": {
                "type": "string",
                "required": True,
                "description": "要念出的通知/提醒文案",
            },
            "lang": {
                "type": "string",
                "required": False,
                "description": "语言提示，如 zh_CN / en_US（映射本机 TTS 音色）",
            },
            "voice": {
                "type": "string",
                "required": False,
                "description": "可选 edge-tts 音色，如 zh-CN-YunxiNeural（男）/ zh-CN-YunyangNeural",
            },
        },
        "output_schema": {},
    },
}

# Old / rejected capability ids (Edge will skip/fail; planner must not emit these).
LEGACY_CAPABILITIES = frozenset(
    {
        "music.playback",
        "music.search",
        "take_photo",
        "bluetooth.a2dp",
        "gopro.capture",
        "gopro.shutter",
    }
)


def _as_schema_object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, Any] = {}
    for name, field in value.items():
        key = str(name).strip()
        if not key:
            continue
        if isinstance(field, dict):
            entry: dict[str, Any] = {
                "type": str(field.get("type") or "string"),
                "description": str(field.get("description") or ""),
            }
            if "required" in field:
                entry["required"] = bool(field.get("required"))
            out[key] = entry
        else:
            out[key] = {"type": "string", "required": False, "description": ""}
    return out


def normalize_capability(raw: Any) -> dict[str, Any] | None:
    """Normalize one capability descriptor; return None if invalid."""
    if not isinstance(raw, dict):
        return None
    cap_id = str(
        raw.get("capability_id") or raw.get("capabilityId") or raw.get("id") or ""
    ).strip()
    if not cap_id:
        return None
    return {
        "capability_id": cap_id,
        "description": str(raw.get("description") or ""),
        "input_schema": _as_schema_object(
            raw.get("input_schema") if "input_schema" in raw else raw.get("inputSchema")
        ),
        "output_schema": _as_schema_object(
            raw.get("output_schema") if "output_schema" in raw else raw.get("outputSchema")
        ),
    }


def normalize_service(raw: Any) -> dict[str, Any] | None:
    """Normalize one service descriptor; return None if invalid."""
    if not isinstance(raw, dict):
        return None
    service_id = str(
        raw.get("service_id") or raw.get("serviceId") or raw.get("id") or ""
    ).strip()
    group = str(raw.get("group") or "").strip()
    if not service_id or not group:
        return None
    caps_raw = raw.get("capabilities")
    caps: list[dict[str, Any]] = []
    if isinstance(caps_raw, list):
        for item in caps_raw:
            cap = normalize_capability(item)
            if cap is not None:
                caps.append(cap)
    return {
        "service_id": service_id,
        "display_name": str(
            raw.get("display_name") or raw.get("displayName") or service_id
        ).strip(),
        "version": str(raw.get("version") or "").strip() or "0.0.0",
        "group": group,
        "capabilities": caps,
    }


def normalize_services(raw: Any) -> list[dict[str, Any]]:
    """Parse body.services into canonical list (drops invalid entries)."""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        svc = normalize_service(item)
        if svc is None:
            continue
        sid = svc["service_id"]
        if sid in seen:
            continue
        seen.add(sid)
        out.append(svc)
    return out


def strip_legacy_edge_fields(info: dict[str, Any]) -> dict[str, Any]:
    """Destructive: remove top-level skills / flat capabilities from edge snapshot."""
    info.pop("skills", None)
    info.pop("capabilities", None)
    return info


def validate_services(services: list[dict[str, Any]]) -> list[str]:
    """Return human-readable validation errors (empty = ok). Empty services is allowed."""
    errors: list[str] = []
    for i, svc in enumerate(services):
        if not svc.get("service_id"):
            errors.append(f"services[{i}].service_id required")
        if not svc.get("group"):
            errors.append(f"services[{i}].group required")
        caps = svc.get("capabilities")
        if not isinstance(caps, list):
            errors.append(f"services[{i}].capabilities must be a list")
            continue
        for j, cap in enumerate(caps):
            if not isinstance(cap, dict) or not cap.get("capability_id"):
                errors.append(f"services[{i}].capabilities[{j}].capability_id required")
                continue
            if not isinstance(cap.get("input_schema"), dict):
                errors.append(f"services[{i}].capabilities[{j}].input_schema must be object")
            if not isinstance(cap.get("output_schema"), dict):
                errors.append(f"services[{i}].capabilities[{j}].output_schema must be object")
    return errors


def index_capabilities_from_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Build online capability index from edge heartbeats:
    [{ edge_id, service_id, group, capability_id, description, input_schema, output_schema }]
    """
    rows: list[dict[str, Any]] = []
    for edge in edges:
        edge_id = str(edge.get("edge_id") or edge.get("edgeId") or "").strip()
        services = edge.get("services")
        if not isinstance(services, list):
            continue
        for svc in services:
            if not isinstance(svc, dict):
                continue
            service_id = str(svc.get("service_id") or "").strip()
            group = str(svc.get("group") or "").strip()
            for cap in svc.get("capabilities") or []:
                if not isinstance(cap, dict):
                    continue
                cap_id = str(cap.get("capability_id") or "").strip()
                if not cap_id:
                    continue
                rows.append(
                    {
                        "edge_id": edge_id,
                        "service_id": service_id,
                        "group": group,
                        "capability_id": cap_id,
                        "description": cap.get("description") or "",
                        "input_schema": cap.get("input_schema") or {},
                        "output_schema": cap.get("output_schema") or {},
                        "online_status": edge.get("online_status") or edge.get("onlineStatus"),
                    }
                )
    return rows


def find_edges_for_capability(
    edges: list[dict[str, Any]],
    capability_id: str,
    *,
    online_only: bool = True,
) -> list[dict[str, Any]]:
    """Edges that advertise capability_id (optionally online only)."""
    want = (capability_id or "").strip()
    if not want:
        return []
    out: list[dict[str, Any]] = []
    for edge in edges:
        status = str(edge.get("online_status") or edge.get("onlineStatus") or "").lower()
        if online_only and status != "online":
            continue
        for row in index_capabilities_from_edges([edge]):
            if row["capability_id"] == want:
                out.append(deepcopy(edge))
                break
    return out


def edge_capability_ids(edge: dict[str, Any]) -> set[str]:
    """Set of capability_id advertised on one edge snapshot."""
    return {
        str(row["capability_id"])
        for row in index_capabilities_from_edges([edge])
        if row.get("capability_id")
    }


def plan_required_capabilities(plan: list[dict[str, Any]]) -> list[str]:
    """Ordered unique capability ids from an execution_plan."""
    seen: set[str] = set()
    out: list[str] = []
    for step in plan:
        if not isinstance(step, dict):
            continue
        cap = str(step.get("capability") or "").strip()
        if not cap or cap in seen:
            continue
        seen.add(cap)
        out.append(cap)
    return out


def resolve_edge_for_plan(
    plan: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    preferred_edge_id: str | None = None,
    room: str | None = None,
    online_only: bool = True,
) -> dict[str, Any]:
    """
    Pick a single online edge that covers all capabilities in the plan.

    Returns:
      { ok, edge_id?, reason, required_capabilities, candidates[] }
    """
    required = plan_required_capabilities(plan)
    if not required:
        return {
            "ok": False,
            "edge_id": None,
            "reason": "execution_plan has no capabilities",
            "required_capabilities": [],
            "candidates": [],
        }

    preferred = (preferred_edge_id or "").strip()
    want_room = (room or "").strip()
    candidates: list[dict[str, Any]] = []
    skipped_skew: list[str] = []
    for edge in edges:
        status = str(edge.get("online_status") or edge.get("onlineStatus") or "").lower()
        if online_only and status != "online":
            continue
        edge_id = str(edge.get("edge_id") or edge.get("edgeId") or "").strip()
        if not edge_id:
            continue
        # Clock skew: Brain refuses to schedule onto ineligible nodes.
        if edge.get("schedule_eligible") is False:
            skipped_skew.append(edge_id)
            continue
        caps = edge_capability_ids(edge)
        if not set(required).issubset(caps):
            continue
        candidates.append(deepcopy(edge))

    if not candidates:
        reason = f"no online edge for capabilities: {', '.join(required)}"
        if skipped_skew:
            reason += f"; clock-skew rejected: {', '.join(skipped_skew)}"
        return {
            "ok": False,
            "edge_id": None,
            "reason": reason,
            "required_capabilities": required,
            "candidates": [],
            "clock_skew_rejected": skipped_skew,
        }

    def sort_key(edge: dict[str, Any]) -> tuple[int, int, str]:
        eid = str(edge.get("edge_id") or "").strip()
        pref_rank = 0 if preferred and eid == preferred else 1
        edge_room = str(edge.get("room") or "").strip()
        room_rank = 0 if want_room and edge_room == want_room else 1
        return (pref_rank, room_rank, eid)

    candidates.sort(key=sort_key)
    chosen = candidates[0]
    chosen_id = str(chosen.get("edge_id") or "").strip()
    reason_parts = [f"matched {', '.join(required)}"]
    if preferred and chosen_id == preferred:
        reason_parts.append("preferred_edge_id")
    elif want_room and str(chosen.get("room") or "").strip() == want_room:
        reason_parts.append(f"room={want_room}")
    return {
        "ok": True,
        "edge_id": chosen_id,
        "reason": "; ".join(reason_parts),
        "required_capabilities": required,
        "candidates": [str(c.get("edge_id") or "") for c in candidates],
    }


def normalize_execution_plan(plan: Any) -> tuple[list[dict[str, Any]] | None, str | None]:
    """
    Normalize execution_plan steps.
    Returns (plan, error). Rejects legacy capability ids.
    Extra step fields (song/artist/…) are preserved as params on the step.
    """
    if plan is None:
        return [], None
    if not isinstance(plan, list):
        return None, "execution_plan must be a list"
    out: list[dict[str, Any]] = []
    for i, step in enumerate(plan):
        if not isinstance(step, dict):
            return None, f"execution_plan[{i}] must be an object"
        cap = str(step.get("capability") or "").strip()
        if not cap:
            return None, f"execution_plan[{i}].capability required"
        if cap in LEGACY_CAPABILITIES:
            return None, (
                f"execution_plan[{i}].capability '{cap}' is legacy; "
                f"use new ids (e.g. music.play, camera.capture)"
            )
        normalized = dict(step)
        normalized["capability"] = cap
        if "step" not in normalized:
            normalized["step"] = i + 1
        # execution_timing: strip delay_sec; normalize absolute ms fields.
        try:
            from execution_timing import normalize_execution_timing_dict
        except ImportError:  # pragma: no cover
            from server.execution_timing import normalize_execution_timing_dict  # type: ignore
        normalized.pop("delay_sec", None)
        if "execution_timing" in normalized:
            timing = normalize_execution_timing_dict(normalized.get("execution_timing"))
            if timing is None:
                normalized.pop("execution_timing", None)
            else:
                normalized["execution_timing"] = timing
        # Wire schema field names for music.play: song / artist / album only.
        if cap == "music.play":
            if "author" in normalized and "artist" not in normalized:
                normalized["artist"] = normalized.pop("author")
            else:
                normalized.pop("author", None)
            if "singer_name" in normalized and "artist" not in normalized:
                normalized["artist"] = normalized.pop("singer_name")
            else:
                normalized.pop("singer_name", None)
            if "song_name" in normalized and "song" not in normalized:
                normalized["song"] = normalized.pop("song_name")
            else:
                normalized.pop("song_name", None)
            if "song" in normalized and normalized["song"] is not None:
                normalized["song"] = str(normalized["song"]).strip()
            if "artist" in normalized and normalized["artist"] is not None:
                artist = str(normalized["artist"]).strip()
                if artist:
                    normalized["artist"] = artist
                else:
                    normalized.pop("artist", None)
            if "album" in normalized and normalized["album"] is not None:
                album = str(normalized["album"]).strip()
                if album:
                    normalized["album"] = album
                else:
                    normalized.pop("album", None)
        out.append(normalized)
    return out, None


def plan_music_play(*, song: str, artist: str | None = None, step: int = 1) -> list[dict[str, Any]]:
    item: dict[str, Any] = {"capability": "music.play", "step": step, "song": song.strip()}
    if artist and artist.strip():
        item["artist"] = artist.strip()
    return [item]


def plan_camera_capture(*, step: int = 1) -> list[dict[str, Any]]:
    return [{"capability": "camera.capture", "step": step}]


def plan_take_video(*, step: int = 1) -> list[dict[str, Any]]:
    return [{"capability": "take_video", "step": step}]


def plan_notify_speak(
    *,
    text: str,
    lang: str | None = None,
    step: int = 1,
) -> list[dict[str, Any]]:
    """Mac local TTS notification (notify.speak)."""
    item: dict[str, Any] = {
        "capability": "notify.speak",
        "step": step,
        "input_constrict": {"text": (text or "").strip() or "提醒"},
    }
    if lang and str(lang).strip():
        item["input_constrict"]["lang"] = str(lang).strip()
    return [item]
