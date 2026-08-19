"""Brain wire services[] advertised by this Mac Edge."""

from __future__ import annotations

import logging
import os
import socket
from typing import Any
from urllib.parse import urlparse

from mac_edge.plugins.chromecast_display import DEFAULT_CAST_DISPLAY_URL

log = logging.getLogger("mac_edge.services")

CHROMECAST_DISPLAY_SERVICE: dict[str, Any] = {
    "service_id": "chromecast.display",
    "display_name": "Chromecast Cast",
    "version": "0.4.0",
    "group": "display",
    "capabilities": [
        {
            "capability_id": "display.photo",
            "description": (
                "能：把本步已给出的 image_ref（AssetRef）投到家里 Chromecast 电视上显示一张图。"
                "仅当用户明确说投电视/投屏/放到电视上时才用。"
                "不能：拍照、看图、问答、TTS、开灯、放歌；不能收 photo_url/path/永久 URL；"
                "不能从前序 step 自己捡图；缺 image_ref 则失败。"
                "本能力不是用户结果的默认交付（交付由 Brain presentation 决定）。"
            ),
            "input_schema": {
                "image_ref": {
                    "type": "string",
                    "required": True,
                    "description": (
                        "AssetRef JSON {asset_id, type, mime_type?}。"
                        "禁止 photo_url / path / 永久 URL。常为 $capture_ref。"
                    ),
                }
            },
            "output_schema": {},
        },
        {
            "capability_id": "display.slideshow",
            "description": (
                "能：把本步必填 image_refs（AssetRef JSON 数组，至少一张）按 interval_sec 轮播投到 Chromecast。"
                "轮播必须用本能力，不要拆成多个 display.photo。"
                "不能：拍照、自己从前序 capture 拼列表、空数组、photo_url、TTS、问答、开灯。"
                "缺 image_refs 则失败。用户没说投电视时不要派本能力。"
            ),
            "input_schema": {
                "image_refs": {
                    "type": "string",
                    "required": True,
                    "description": (
                        "必填 AssetRef JSON 数组，至少一张。"
                        '例 [{"asset_id":"asset_…","type":"image"}]。'
                        "禁止 photo_urls / path / 永久 URL。不传或空数组则本能力无效。"
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
                        "播放顺序，默认 array_asc："
                        "array_asc / array_desc（入参数组顺序/倒序）；"
                        "alphabet_asc / alphabet_desc（按文件名）；"
                        "random"
                    ),
                },
            },
            "output_schema": {},
        },
    ],
}

LOCAL_NOTIFY_SERVICE: dict[str, Any] = {
    "service_id": "local.notify",
    "display_name": "Local Notify",
    "version": "0.1.1",
    "group": "notify",
    "capabilities": [
        {
            "capability_id": "notify.speak",
            "description": (
                "能：把本步必填 text 用本机 TTS 念出来。只用于纯提醒或定时播报"
                "（例如「一分钟后该喝水了」）。"
                "不能：开灯/关灯（用 light.set）；报时（用 clock.now）；回答问题（用 query.content）；"
                "看图、拍照、投屏、放歌。禁止在缺能力时用本能力顶替。"
                "缺 text 则失败。不产出用户可见的图或时刻。"
            ),
            "input_schema": {
                "text": {
                    "type": "string",
                    "required": True,
                    "description": "要念出的文案",
                },
                "lang": {
                    "type": "string",
                    "required": False,
                    "description": "语言提示，如 zh_CN / en_US",
                },
                "voice": {
                    "type": "string",
                    "required": False,
                    "description": "可选 say 音色名；edge 后端时为 edge-tts 音色",
                },
            },
            "output_schema": {},
        }
    ],
}

LOCAL_QUERY_SERVICE: dict[str, Any] = {
    "service_id": "local.query",
    "display_name": "Local Query",
    "version": "0.2.0",
    "group": "query",
    "capabilities": [
        {
            "capability_id": "query.content",
            "description": (
                "能：根据本步必填 query 做文字问答，产出 answer_text；"
                "本能力自带文生图：用户要图、要投屏/电视展示，或画面/示意/步骤/笔顺比纯文字更清楚时，"
                "按 query 生成图片并在成功时产出 image_ref。简单口头事实问答默认只出文字、不生图。"
                "不知道就直说我不知道；专业域须有来源，禁止编造。"
                "不能：读墙上时钟（用 clock.now）；看已有图（无图入参，看图用 vision.ask/perceive）；"
                "产出 photo_url；拍照、自己投电视、TTS、开灯、放歌。缺 query 则失败，禁止从前序补问句。"
                "不要用本能力顶替任何未广告的执行能力。"
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
        }
    ],
}

LOCAL_CLOCK_SERVICE: dict[str, Any] = {
    "service_id": "local.clock",
    "display_name": "Local Clock",
    "version": "0.1.1",
    "group": "clock",
    "capabilities": [
        {
            "capability_id": "clock.now",
            "description": (
                "能：读本机墙上时钟，产出 now_iso 与 time_text。问「现在几点了」必须用本能力。"
                "可选 timezone（IANA，默认本地）。"
                "不能：用 LLM 编时刻；TTS；看图；问答百科；开灯；投屏。"
                "没有本能力时禁止用 query.content 或 notify.speak 顶替。"
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
        }
    ],
}

LOCAL_VISION_SERVICE: dict[str, Any] = {
    "service_id": "local.vision",
    "display_name": "Local Vision",
    "version": "0.5.0",
    "group": "vision",
    "capabilities": [
        {
            "capability_id": "vision.perceive",
            "description": (
                "能：给定本步必填 image_ref（AssetRef），产出画面结构 summary/people/spatial/actions/"
                "posture/lighting。问客厅有几个人、适不适合看书、场景里在干什么，用本能力。"
                "不能：没有图；收 photo_url/path/永久 URL；回答「这个字读啥/这个是什么」等指向问答"
                "（用 vision.ask）；拍照、投屏、TTS、开灯、文字百科（query.content）。"
                "缺 image_ref 则失败，禁止从前序自己捡图。不生图。"
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
                "prompt": {
                    "type": "string",
                    "required": False,
                    "description": "可选额外提示",
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
                    "description": "人物列表 JSON",
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
        {
            "capability_id": "vision.ask",
            "description": (
                "能：给定本步必填 image_ref（AssetRef）+ query，只根据图中可见内容产出 answer_text。"
                "「这个/手指指的/这个字读啥」必须落到画面里的具体对象。"
                "不能：无图问答（那是 query.content）；收 photo_url/path；产出 people/lighting 等场景结构"
                "（那是 vision.perceive）；拍照、生图、TTS、投屏、开灯。"
                "缺 image_ref 或 query 则失败，禁止从前序补图或补问句。看不清就说不知道。"
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
    ],
}

LIVINGROOM_LIGHT_SERVICE: dict[str, Any] = {
    "service_id": "livingroom.ceiling_light",
    "display_name": "客厅大路灯",
    "version": "0.1.1",
    "group": "light",
    "capabilities": [
        {
            "capability_id": "light.set",
            "description": (
                "能：开关客厅大路灯。用户说开灯/关灯/打开客厅灯时用本能力。"
                "必填 state=on 或 off（兼容 开、关、开灯、关灯）。"
                "内部自己喊「小书小书」、等 2 秒、再喊开灯或关灯。"
                "不能：调亮度/色温；控制别的灯或窗帘；拆成 notify.speak；录音听「在呢」；"
                "验证灯是否真亮；报时、问答、拍照。"
                "缺 state 则失败，禁止猜测开或关。"
            ),
            "input_schema": {
                "state": {
                    "type": "string",
                    "required": True,
                    "description": "on 开灯 / off 关灯；兼容 开、关、开灯、关灯",
                },
            },
            "output_schema": {
                "state": {
                    "type": "string",
                    "required": True,
                    "description": "规范化后的 on 或 off",
                },
            },
        }
    ],
}

GOPRO_CAMERA_SERVICE: dict[str, Any] = {
    "service_id": "gopro.camera",
    "display_name": "GoPro Camera",
    "version": "0.9.0",
    "group": "camera",
    "capabilities": [
        {
            "capability_id": "camera.capture",
            "description": (
                "能：用 GoPro 拍一张照片并上传，产出 capture_ref（AssetRef）。"
                "用户要拍照/拍一张/看看现场时先用本能力。默认传到家里 LAN img-server。"
                "不能：分析照片（vision.perceive/ask）；投电视（display.photo，且须用户明确要投）；"
                "产出 photo_url/path/永久 URL；TTS；开灯；放歌；无图硬答「已经看了」。"
                "不自己投屏、不自己看图。仅用户明确要求公网时才填 upload_dest=cloud。"
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
        }
    ],
}


def _env_flag(name: str) -> str | None:
    raw = (os.environ.get(name) or "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return "on"
    if raw in ("0", "false", "no", "off"):
        return "off"
    return None


def _cast_service_listening() -> bool:
    """True when the independent Cast HTTP process is accepting connections."""
    raw = (
        os.environ.get("MAC_EDGE_CAST_DISPLAY_URL") or DEFAULT_CAST_DISPLAY_URL
    ).strip() or DEFAULT_CAST_DISPLAY_URL
    parsed = urlparse(raw)
    host = parsed.hostname or "127.0.0.1"
    if parsed.port:
        port = parsed.port
    elif parsed.scheme == "https":
        port = 443
    else:
        port = 80
    try:
        with socket.create_connection((host, port), timeout=0.4):
            return True
    except OSError:
        return False


# GoPro (+ img-server process) and living-room ceiling light stay on home-server.
# Everything else registers on the laptop (本机). img-server is not an Edge capability.
HOME_SERVER_ONLY_SERVICES = frozenset({"gopro.camera", "livingroom.ceiling_light"})
HOME_SERVER_SERVICES = frozenset({"gopro.camera", "livingroom.ceiling_light"})

_LAPTOP_SERVICE_ORDER = (
    CHROMECAST_DISPLAY_SERVICE,
    LOCAL_NOTIFY_SERVICE,
    LOCAL_VISION_SERVICE,
    LOCAL_QUERY_SERVICE,
    LOCAL_CLOCK_SERVICE,
)


def _should_advertise_cast() -> bool:
    """Same idea as GoPro: only advertise capabilities this machine can run.

    home-server has no :9095 Cast process; advertising display.photo there makes
    Brain assign 投屏 to it and the App shows 失败 (connection refused).
    """
    flag = _env_flag("MAC_EDGE_ADVERTISE_CAST")
    if flag == "on":
        return True
    if flag == "off":
        return False
    return _cast_service_listening()


def _service_whitelist() -> frozenset[str] | None:
    raw = (os.environ.get("MAC_EDGE_SERVICE_WHITELIST") or "").strip()
    if not raw:
        return None
    names = frozenset(p.strip() for p in raw.split(",") if p.strip())
    return names or None


def _edge_role() -> str:
    """laptop = all Mac caps except GoPro/light; home-server = GoPro + living-room light."""
    raw = (os.environ.get("MAC_EDGE_ROLE") or "").strip().lower().replace("_", "-")
    if raw in ("home-server", "homeserver"):
        return "home-server"
    if raw in ("laptop", "local"):
        return "laptop"
    whitelist = _service_whitelist()
    if whitelist is not None and whitelist <= HOME_SERVER_ONLY_SERVICES:
        return "home-server"
    return "laptop"


def _allow_service(service_id: str, allowed: frozenset[str]) -> bool:
    if service_id in allowed:
        return True
    log.info("skip %s — not in this Mac's advertise set", service_id)
    return False


def default_services() -> list[dict[str, Any]]:
    role = _edge_role()
    whitelist = _service_whitelist()
    if role == "home-server":
        allowed = set(HOME_SERVER_SERVICES)
        log.info(
            "advertise role=home-server (gopro.camera + livingroom.ceiling_light; "
            "img-server is separate)"
        )
    else:
        allowed = {
            str(svc["service_id"])
            for svc in _LAPTOP_SERVICE_ORDER
        }
        log.info("advertise role=laptop (all Mac caps except gopro / img-server)")
    if whitelist is not None:
        allowed &= set(whitelist)
        log.info("advertise whitelist=%s", ",".join(sorted(whitelist)))
    allowed_set = frozenset(allowed)

    services: list[dict[str, Any]] = []
    if _allow_service(CHROMECAST_DISPLAY_SERVICE["service_id"], allowed_set):
        if _should_advertise_cast():
            services.append(dict(CHROMECAST_DISPLAY_SERVICE))
            log.info(
                "advertise chromecast.display (Cast HTTP reachable or MAC_EDGE_ADVERTISE_CAST=1)"
            )
        else:
            log.info("skip chromecast.display — no Cast HTTP on this machine")
    if _allow_service(LOCAL_NOTIFY_SERVICE["service_id"], allowed_set):
        services.append(dict(LOCAL_NOTIFY_SERVICE))
    if _allow_service(LOCAL_VISION_SERVICE["service_id"], allowed_set):
        services.append(dict(LOCAL_VISION_SERVICE))
    if _allow_service(LOCAL_QUERY_SERVICE["service_id"], allowed_set):
        services.append(dict(LOCAL_QUERY_SERVICE))
    if _allow_service(LOCAL_CLOCK_SERVICE["service_id"], allowed_set):
        services.append(dict(LOCAL_CLOCK_SERVICE))
    if _allow_service(GOPRO_CAMERA_SERVICE["service_id"], allowed_set):
        if (os.environ.get("MAC_EDGE_GOPRO_SSID") or "").strip():
            services.append(dict(GOPRO_CAMERA_SERVICE))
            log.info("advertise gopro.camera (MAC_EDGE_GOPRO_SSID set)")
        else:
            log.info("skip gopro.camera — MAC_EDGE_GOPRO_SSID unset")
    if _allow_service(LIVINGROOM_LIGHT_SERVICE["service_id"], allowed_set):
        services.append(dict(LIVINGROOM_LIGHT_SERVICE))
        log.info("advertise livingroom.ceiling_light")
    return services
