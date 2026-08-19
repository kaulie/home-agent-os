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
        "description": (
            "能：按 song / album / artist 在网易云播放。用户要放歌、播放某某的歌时用本能力。"
            "不能：用 query.content 或 notify.speak 顶替；无本能力时 plan=[]；"
            "不投屏、不 TTS 念歌词当播放、不开灯。song/artist/album 至少填一个。"
        ),
        "input_schema": {
            "song": {"type": "string", "required": False, "description": "歌曲"},
            "artist": {"type": "string", "required": False, "description": "歌手"},
            "album": {"type": "string", "required": False, "description": "专辑"},
        },
        "output_schema": {},
    },
    "music.pause": {
        "group": "music",
        "service_id": "netease.music",
        "description": (
            "能：暂停当前网易云播放。不能：开始播放（用 music.play）；搜歌；TTS；投屏。"
        ),
    },
    "music.stop": {
        "group": "music",
        "service_id": "netease.music",
        "description": (
            "能：停止当前网易云播放。不能：开始播放（用 music.play）；搜歌；TTS；投屏。"
        ),
    },
    "music.next": {
        "group": "music",
        "service_id": "netease.music",
        "description": (
            "能：网易云切到下一首。不能：指定歌名播放（用 music.play）；TTS；投屏。"
        ),
    },
    "music.previous": {
        "group": "music",
        "service_id": "netease.music",
        "description": (
            "能：网易云切到上一首。不能：指定歌名播放（用 music.play）；TTS；投屏。"
        ),
    },
    "camera.capture": {
        "group": "camera",
        "service_id": "gopro.camera",
        "description": (
            "能：用 GoPro 拍一张照片并上传，产出 capture_ref（AssetRef）。"
            "用户要拍照/拍一张时用本能力。"
            "不能：分析照片、投电视、TTS、开灯、放歌、无图硬答已经看了；产出 photo_url。"
        ),
        "input_schema": {
            "upload_dest": {
                "type": "string",
                "required": False,
                "description": (
                    "默认不要填（Edge 用 lan → http://192.168.3.65:8080）。"
                    "投屏/电视/display.photo 必须 lan，禁止 cloud。"
                    "仅当用户明确要求公网/远程查看时才填 cloud。"
                    "未填时读 MAC_EDGE_PHOTO_UPLOAD_DEST，再默认 lan。"
                    "别名 local/home → lan"
                ),
            },
        },
        "output_schema": {
            "capture_ref": {
                "type": "string",
                "required": True,
                "description": (
                    "AssetRef JSON {asset_id, type, mime_type?}。"
                    "禁止 photo_url / path / 永久 URL。"
                ),
            },
        },
    },
    "take_video": {
        "group": "camera",
        "service_id": "gopro.camera",
        "description": (
            "能：开始 GoPro 录像。不能：当拍照（拍照用 camera.capture）；分析画面；投屏。"
        ),
    },
    "display.photo": {
        "group": "display",
        "service_id": "chromecast.display",
        "description": (
            "能：把本步已给出的 image_ref（AssetRef）投到 Chromecast 显示一张图。"
            "仅用户明确要投电视时用。"
            "不能：拍照、自己捡图、收 photo_url/path、当默认用户交付、TTS、问答。"
        ),
        "input_schema": {
            "image_ref": {
                "type": "string",
                "required": True,
                "description": (
                    "AssetRef JSON {asset_id, type, mime_type?}。"
                    "禁止 photo_url / path / 永久 URL。常为 $capture_ref。"
                ),
            },
        },
        "output_schema": {},
    },
    "display.slideshow": {
        "group": "display",
        "service_id": "chromecast.display",
        "description": (
            "能：把本步必填 image_refs（AssetRef JSON 数组）轮播投到电视。不要拆成多个 display.photo。"
            "不能：从前序自己拼列表、空数组、photo_url、拍照、TTS。"
        ),
        "input_schema": {
            "image_refs": {
                "type": "string",
                "required": True,
                "description": (
                    "必填 AssetRef JSON 数组，至少一张。"
                    '例 [{"asset_id":"asset_…","type":"image"}]。'
                    "禁止 photo_urls / path / 永久 URL。不传则能力无效。"
                    "轮播用本能力，不要拆成多个 display.photo。"
                ),
            },
            "interval_sec": {
                "type": "number",
                "required": False,
                "description": "每张停留秒数，默认 5",
            },
            "order": {
                "type": "string",
                "required": False,
                "description": (
                    "默认 array_asc：array_asc / array_desc / "
                    "alphabet_asc / alphabet_desc / random"
                ),
            },
        },
        "output_schema": {},
    },
    "bluetooth.connect": {
        "group": "speaker",
        "service_id": "marshall.willen",
        "description": (
            "能：连接已配对的 Marshall WILLEN 蓝牙音箱。"
            "不能：放歌（用 music.play）；TTS；开灯；当音源。"
        ),
    },
    "bluetooth.disconnect": {
        "group": "speaker",
        "service_id": "marshall.willen",
        "description": (
            "能：断开 Marshall WILLEN 蓝牙音箱。不能：放歌、TTS、开灯。"
        ),
    },
    "notify.speak": {
        "group": "notify",
        "service_id": "local.notify",
        "description": (
            "能：把本步 text 用本机 TTS 念出来。只用于纯提醒或定时播报。"
            "不能：开灯（light.set）；报时（clock.now）；问答；拍照；投屏；放歌；缺能力时顶替。"
        ),
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
    "vision.perceive": {
        "group": "vision",
        "service_id": "local.vision",
        "description": (
            "能：给定本步 image_ref（AssetRef），产出 summary/people/spatial/actions/posture/lighting。"
            "看客厅有几个人、场景适不适合看书用本能力。"
            "不能：无图；收 photo_url；指向问答（vision.ask）；拍照；投屏；TTS；文字百科。"
        ),
        "input_schema": {
            "image_ref": {
                "type": "string",
                "required": True,
                "description": (
                    "AssetRef JSON {asset_id, type, mime_type?}。"
                    "禁止 photo_url / path。常为 $capture_ref。"
                ),
            },
            "prompt": {
                "type": "string",
                "required": False,
                "description": "可选额外分析提示",
            },
        },
            "output_schema": {
                "summary": {
                    "type": "string",
                    "required": True,
                    "description": "一句话画面摘要",
                },
                "people": {
                    "type": "string",
                    "required": False,
                    "description": "人物列表 JSON（含 id/description/count/position）",
                },
                "spatial": {
                    "type": "string",
                    "required": False,
                    "description": "空间布局描述",
                },
                "actions": {
                    "type": "string",
                    "required": False,
                    "description": "主要动作",
                },
                "posture": {
                    "type": "string",
                    "required": False,
                    "description": "体态/姿势",
                },
                "lighting": {
                    "type": "string",
                    "required": False,
                    "description": "光线 JSON（whole + region）",
                },
            },
    },
    "vision.ask": {
        "group": "vision",
        "service_id": "local.vision",
        "description": (
            "能：给定本步 image_ref（AssetRef）+ query，只根据图中可见内容产出 answer_text。"
            "不能：无图问答（query.content）；收 photo_url；场景结构字段（vision.perceive）；拍照；生图；TTS。"
        ),
        "input_schema": {
            "image_ref": {
                "type": "string",
                "required": True,
                "description": (
                    "AssetRef JSON {asset_id, type, mime_type?}。"
                    "禁止 photo_url / path。常为 $capture_ref。"
                ),
            },
            "query": {
                "type": "string",
                "required": True,
                "description": "用户原话，如「这个字读啥」",
            },
        },
        "output_schema": {
            "answer_text": {
                "type": "string",
                "required": True,
                "description": "针对图+问句的中文回答；不确定时直说我不知道",
            },
        },
    },
    "query.content": {
        "group": "query",
        "service_id": "local.query",
        "description": (
            "能：根据本步 query 文字问答，产出 answer_text；"
            "本能力自带文生图：用户要图、要投屏/电视展示，或画面/示意/步骤/笔顺比纯文字更清楚时，"
            "按 query 生成图片并在成功时产出 image_ref。简单口头事实问答默认只出文字、不生图。"
            "不能：报时（clock.now）；看已有图（vision.ask/perceive）；拍照；自己投电视；TTS；开灯；放歌；产出 photo_url。"
        ),
        "input_schema": {
            "query": {
                "type": "string",
                "required": True,
                "description": "一句话 / prompt",
            },
            "upload_dest": {
                "type": "string",
                "required": False,
                "description": "生图上传目标 lan（默认）| cloud",
            },
        },
        "output_schema": {
            "answer_text": {
                "type": "string",
                "required": True,
                "description": "文字答案；不确定时直说我不知道",
            },
            "image_ref": {
                "type": "string",
                "required": False,
                "description": (
                    "仅生图成功时的 AssetRef JSON {asset_id, type, mime_type?}。"
                    "禁止 photo_url / path / 永久 URL。"
                ),
            },
            "citations": {
                "type": "string",
                "required": False,
                "description": "来源 JSON 数组；拒答时为 []",
            },
        },
    },
    "clock.now": {
        "group": "clock",
        "service_id": "local.clock",
        "description": (
            "能：读本机墙上时钟，产出 now_iso 与 time_text。问几点必须用本能力。"
            "不能：LLM 编时刻；用 query.content 或 notify.speak 顶替；TTS；看图；开灯。"
        ),
        "input_schema": {
            "timezone": {
                "type": "string",
                "required": False,
                "description": "IANA 时区，如 Asia/Shanghai；缺省为本机本地时区",
            },
        },
        "output_schema": {
            "now_iso": {
                "type": "string",
                "required": True,
                "description": "ISO-8601 时刻，含 UTC 偏移",
            },
            "time_text": {
                "type": "string",
                "required": True,
                "description": "人类可读时刻，含时区",
            },
        },
    },
    "light.set": {
        "group": "light",
        "service_id": "livingroom.ceiling_light",
        "description": (
            "能：开关客厅大路灯。必填 state=on|off。内部自己唤醒小书再发开灯/关灯。"
            "不能：拆成 notify.speak；调亮度；控制窗帘或其他灯；听「在呢」；报时；问答。"
        ),
        "input_schema": {
            "state": {
                "type": "string",
                "required": True,
                "description": (
                    "客厅大路灯：on 开 / off 关（兼容 开、关、开灯、关灯）。"
                    "禁止拆成 notify.speak。缺 state 则本能力无效。"
                ),
            },
        },
        "output_schema": {
            "state": {
                "type": "string",
                "required": True,
                "description": "规范化后的 on 或 off",
            },
        },
    },
}

# Old / rejected capability ids (planner and enqueue must not emit these).
LEGACY_CAPABILITIES = frozenset(
    {
        "music.playback",
        "music.search",
        "take_photo",
        "bluetooth.a2dp",
        "gopro.capture",
        "gopro.shutter",
        "endpoint.feedback",
        "endpoint.present",
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


def plan_assigned_edge_ids(plan: Any) -> list[str]:
    """Distinct non-empty per-step assigned_edge_id values, in first-seen order."""
    if not isinstance(plan, list):
        return []
    seen: list[str] = []
    for step in plan:
        if not isinstance(step, dict):
            continue
        eid = str(
            step.get("assigned_edge_id") or step.get("assignedEdgeId") or ""
        ).strip()
        if eid and eid not in seen:
            seen.append(eid)
    return seen


def assign_steps_to_edges(
    plan: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    preferred_edge_id: str | None = None,
    room: str | None = None,
) -> tuple[list[dict[str, Any]], str, str | None]:
    """Assign each step to an online edge that covers that step's capability."""
    if not plan:
        raise ValueError("execution_plan has no steps")
    assigned_steps: list[dict[str, Any]] = []
    reasons: list[str] = []
    scheduler_node: str | None = None
    for step in plan:
        if not isinstance(step, dict):
            continue
        step_copy = dict(step)
        existing = str(step_copy.get("assigned_edge_id") or "").strip()
        routed = resolve_edge_for_plan(
            [step_copy],
            edges,
            preferred_edge_id=existing or preferred_edge_id,
            room=room,
            online_only=True,
        )
        if not routed.get("ok") or not routed.get("edge_id"):
            cap = str(step_copy.get("capability") or "?")
            raise ValueError(
                str(routed.get("reason") or f"no online edge for step capability {cap}")
            )
        eid = str(routed["edge_id"]).strip()
        step_copy["assigned_edge_id"] = eid
        step_copy.pop("assignedEdgeId", None)
        assigned_steps.append(step_copy)
        reasons.append(
            f"step{step_copy.get('step')}:{step_copy.get('capability')}→{eid}"
        )
        if step_copy.get("execution_timing") and not scheduler_node:
            scheduler_node = eid
    if not scheduler_node and assigned_steps:
        scheduler_node = str(assigned_steps[0].get("assigned_edge_id") or "").strip() or None
    top = scheduler_node or (
        str(assigned_steps[0].get("assigned_edge_id") or "") if assigned_steps else ""
    )
    return assigned_steps, top, scheduler_node


def resolve_tts_edge_id(edges: list[dict[str, Any]]) -> str | None:
    """Pick the designated Edge for voice TTS delivery (notify.speak)."""
    import os

    explicit = os.environ.get("PRESENTATION_TTS_EDGE_ID", "").strip()
    online = [
        e
        for e in edges
        if str(e.get("online_status") or e.get("onlineStatus") or "").lower() == "online"
        and e.get("schedule_eligible") is not False
    ]

    def has_speak(edge: dict[str, Any]) -> bool:
        return "notify.speak" in edge_capability_ids(edge)

    if explicit:
        for edge in online:
            if str(edge.get("edge_id") or edge.get("edgeId") or "").strip() == explicit:
                return explicit if has_speak(edge) else None
        return None

    laptop_candidates: list[dict[str, Any]] = []
    for edge in online:
        if not has_speak(edge):
            continue
        hint = str(
            edge.get("role")
            or edge.get("client_hint")
            or edge.get("clientHint")
            or ""
        ).lower()
        if "laptop" in hint or hint == "living-room-mac":
            laptop_candidates.append(edge)
    if laptop_candidates:
        return str(laptop_candidates[0].get("edge_id") or "").strip() or None
    for edge in online:
        if has_speak(edge):
            return str(edge.get("edge_id") or "").strip() or None
    return None


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
    return [
        {
            "capability": "camera.capture",
            "step": step,
            "input_constrict": {},
            "output_constrict": {
                "photo_url": {"type": "string", "data_dest": "context"}
            },
        }
    ]


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


def plan_vision_perceive(
    *,
    photo_url: str = "$photo_url",
    prompt: str | None = None,
    step: int = 1,
) -> list[dict[str, Any]]:
    """photo_url in → flat summary/people/… out (helper for tests/docs only).

    Brain does not rewrite vision output_constrict — planner/Edge own the keys.
    """
    flat = {
        k: {"type": "string", "data_dest": "context"}
        for k in (
            "summary",
            "people",
            "spatial",
            "actions",
            "posture",
            "lighting",
        )
    }
    item: dict[str, Any] = {
        "capability": "vision.perceive",
        "step": step,
        "input_constrict": {"photo_url": (photo_url or "").strip() or "$photo_url"},
        "output_constrict": flat,
    }
    if prompt and str(prompt).strip():
        item["input_constrict"]["prompt"] = str(prompt).strip()
    return [item]


def plan_vision_ask(
    *,
    photo_url: str = "$photo_url",
    query: str,
    step: int = 1,
) -> list[dict[str, Any]]:
    """photo_url + query in → answer_text (helper for tests/docs only)."""
    return [
        {
            "capability": "vision.ask",
            "step": step,
            "input_constrict": {
                "photo_url": (photo_url or "").strip() or "$photo_url",
                "query": (query or "").strip(),
            },
            "output_constrict": {
                "answer_text": {"type": "string", "data_dest": "context"},
            },
        }
    ]


def plan_query_content(
    *,
    query: str,
    step: int = 1,
) -> list[dict[str, Any]]:
    """query in → answer_text / optional photo_url / citations (helper for tests/docs)."""
    return [
        {
            "capability": "query.content",
            "step": step,
            "input_constrict": {"query": (query or "").strip()},
            "output_constrict": {
                "answer_text": {"type": "string", "data_dest": "context"},
                "photo_url": {"type": "string", "data_dest": "context"},
                "citations": {"type": "string", "data_dest": "context"},
            },
        }
    ]


def plan_clock_now(*, step: int = 1) -> list[dict[str, Any]]:
    return [
        {
            "capability": "clock.now",
            "step": step,
            "input_constrict": {},
            "output_constrict": {
                "now_iso": {"type": "string", "data_dest": "context"},
                "time_text": {"type": "string", "data_dest": "context"},
            },
        }
    ]


def plan_display_photo(*, photo_url: str = "$photo_url", step: int = 1) -> list[dict[str, Any]]:
    return [
        {
            "capability": "display.photo",
            "step": step,
            "input_constrict": {"photo_url": (photo_url or "").strip() or "$photo_url"},
        }
    ]


def plan_music_control(*, capability: str, step: int = 1) -> list[dict[str, Any]]:
    cap = (capability or "").strip()
    return [{"capability": cap, "step": step}]
