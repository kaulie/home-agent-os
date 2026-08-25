"""Brain wire services[] advertised by this Mac Edge."""

from __future__ import annotations

import hashlib
import logging
import os
import socket
from typing import Any
from urllib.parse import urlparse

from mac_edge.capability_ads import attach, named_appliance_overrides
from mac_edge.plugins.chromecast_display import DEFAULT_CAST_DISPLAY_URL
from mac_edge.plugins.image_search_providers import any_provider_configured
from mac_edge.plugins.hisense_ac import (
    bound_appliance_label,
    bound_hisense_devices,
    credentials_configured,
)
from mac_edge.plugins.xiaomi_cloud import credentials_configured as xiaomi_credentials_configured
from mac_edge.plugins.xiaomi_tv_display import display_backend

log = logging.getLogger("mac_edge.services")

CHROMECAST_DISPLAY_SERVICE: dict[str, Any] = {
    "service_id": "chromecast.display",
    "display_name": "Chromecast Cast",
    "version": "0.4.0",
    "group": "display",
    "capabilities": [
        attach(
            'display.photo',
            input_schema={
                'asset_ref': {
                    'type': 'string',
                    'required': True,
                    'description': 'AssetRef JSON {asset_id, type, mime_type?}。禁止 photo_url / path / 永久 URL。常为 $asset_ref。',
                },
            },
            output_schema={},
        ),
        attach(
            'display.slideshow',
            input_schema={
                'asset_refs': {
                    'type': 'string',
                    'required': True,
                    'description': '必填 AssetRef JSON 数组，至少一张。例 [{"asset_id":"asset_…","type":"image"}]。禁止 photo_urls / path / 永久 URL。不传或空数组则本能力无效。',
                },
                'interval_sec': {
                    'type': 'number',
                    'required': False,
                    'description': '每张停留秒数，默认 5',
                },
                'order': {
                    'type': 'string',
                    'required': False,
                    'description': '播放顺序，默认 array_asc：array_asc / array_desc（入参数组顺序/倒序）；alphabet_asc / alphabet_desc（按文件名）；random',
                },
            },
            output_schema={},
        ),
    ],
}

XIAOMI_TV_DISPLAY_SERVICE: dict[str, Any] = {
    "service_id": "xiaomi.tv.display",
    "display_name": "小米电视 DLNA",
    "version": "0.1.0",
    "group": "display",
    "capabilities": list(CHROMECAST_DISPLAY_SERVICE["capabilities"]),
}

LOCAL_NOTIFY_SERVICE: dict[str, Any] = {
    "service_id": "local.notify",
    "display_name": "Local Notify",
    "version": "0.1.1",
    "group": "notify",
    "capabilities": [
        attach(
            'notify.speak',
            input_schema={
                'text': {
                    'type': 'string',
                    'required': True,
                    'description': '要念出的文案',
                },
                'lang': {
                    'type': 'string',
                    'required': False,
                    'description': '语言提示，如 zh_CN / en_US',
                },
                'voice': {
                    'type': 'string',
                    'required': False,
                    'description': '可选 say 音色名；edge 后端时为 edge-tts 音色',
                },
            },
            output_schema={},
        ),
    ],
}

LOCAL_QUERY_SERVICE: dict[str, Any] = {
    "service_id": "local.query",
    "display_name": "Local Query",
    "version": "0.2.1",
    "group": "query",
    "capabilities": [
        attach(
            'query.content',
            input_schema={
                'query': {
                    'type': 'string',
                    'required': True,
                    'description': '用户原话 / prompt。出图投屏时请保留「来张图/投电视」等语义，不要只塞主题词。',
                },
                'want_image': {
                    'type': 'string',
                    'required': False,
                    'description': 'true 时本步必须生图并产出 asset_ref（planner 在出图/投屏计划里可显式传）。缺省则看 query 是否含来张/图片/投屏等。',
                },
                'upload_dest': {
                    'type': 'string',
                    'required': False,
                    'description': '生图上传目标 lan（默认）| cloud',
                },
            },
            output_schema={
                'answer_text': {
                    'type': 'string',
                    'required': True,
                    'description': '文字答案；不确定时直说我不知道',
                },
                'asset_ref': {
                    'type': 'string',
                    'required': False,
                    'description': '仅生图成功时的 AssetRef JSON {asset_id, type, mime_type?}。禁止 photo_url / path / 永久 URL。',
                },
                'citations': {
                    'type': 'string',
                    'required': False,
                    'description': '来源 JSON 数组；拒答时为 []',
                },
            },
        ),
    ],
}

LOCAL_SEARCH_SERVICE: dict[str, Any] = {
    "service_id": "local.search",
    "display_name": "Web Image Search",
    "version": "0.1.0",
    "group": "search",
    "capabilities": [
        attach(
            "search.images",
            input_schema={
                "query": {
                    "type": "string",
                    "required": True,
                    "description": "搜索关键词。检索网上存量实拍图，不是 AI 生图。",
                },
                "count": {
                    "type": "string",
                    "required": False,
                    "description": "返回张数 1–8，默认 4",
                },
                "size": {
                    "type": "string",
                    "required": False,
                    "description": "可选尺寸（Bing）：Small / Medium / Large / Wallpaper",
                },
                "freshness": {
                    "type": "string",
                    "required": False,
                    "description": "可选时效（Bing）：Day / Week / Month",
                },
                "provider": {
                    "type": "string",
                    "required": False,
                    "description": "搜图源 bing | openverse。缺省：环境变量，否则有密钥用 Bing，否则 Openverse",
                },
                "upload_dest": {
                    "type": "string",
                    "required": False,
                    "description": "登记图床目标 lan（默认）| cloud",
                },
            },
            output_schema={
                "asset_refs": {
                    "type": "string",
                    "required": True,
                    "description": "AssetRef JSON 数组，至少一张。禁止 photo_url / path / 永久 URL。",
                },
                "query_used": {
                    "type": "string",
                    "required": True,
                    "description": "实际搜索关键词",
                },
                "hit_count": {
                    "type": "string",
                    "required": True,
                    "description": "成功登记的张数",
                },
                "provider": {
                    "type": "string",
                    "required": False,
                    "description": "实际使用的搜图源 bing | openverse",
                },
                "sources": {
                    "type": "string",
                    "required": False,
                    "description": "来源页 JSON 数组 [{name, host_page, license?}]",
                },
            },
        ),
    ],
}

LOCAL_CLOCK_SERVICE: dict[str, Any] = {
    "service_id": "local.clock",
    "display_name": "Local Clock",
    "version": "0.1.1",
    "group": "clock",
    "capabilities": [
        attach(
            'clock.now',
            input_schema={
                'timezone': {
                    'type': 'string',
                    'required': False,
                    'description': 'IANA 时区，如 Asia/Shanghai；缺省为本机本地时区',
                },
            },
            output_schema={
                'now_iso': {
                    'type': 'string',
                    'required': True,
                    'description': 'ISO-8601 时刻，含 UTC 偏移',
                },
                'time_text': {
                    'type': 'string',
                    'required': True,
                    'description': '给人听/看的中文时刻（现在是…点…分）；时区在 now_iso，不要念 IANA 名或 UTC+08:00',
                },
            },
        ),
    ],
}

LOCAL_MATH_SERVICE: dict[str, Any] = {
    "service_id": "local.math",
    "display_name": "Local Math",
    "version": "0.1.0",
    "group": "math",
    "capabilities": [
        attach(
            'math.calculate',
            input_schema={
                'expression': {
                    'type': 'string',
                    'required': True,
                    'description': '纯算式或算术问句。支持四则、括号、次方/平方/立方、根号。应用题、方程、单位换算、百科类问题勿填本字段。',
                },
            },
            output_schema={
                'answer_text': {
                    'type': 'string',
                    'required': True,
                    'description': '如「一加一等于二。」',
                },
                'result': {
                    'type': 'string',
                    'required': True,
                    'description': '数值结果字符串，如「2」',
                },
            },
        ),
    ],
}

LOCAL_CHAT_SERVICE: dict[str, Any] = {
    "service_id": "local.chat",
    "display_name": "Local Chat",
    "version": "0.1.0",
    "group": "chat",
    "capabilities": [
        attach(
            "chat.smalltalk",
            input_schema={
                "text": {
                    "type": "string",
                    "required": True,
                    "description": "用户的话",
                },
            },
            output_schema={
                "reply": {
                    "type": "string",
                    "required": True,
                    "description": "回复的话",
                },
            },
        ),
    ],
}

LOCAL_ASSET_SERVICE: dict[str, Any] = {
    "service_id": "local.asset",
    "display_name": "Local Asset",
    "version": "0.3.0",
    "group": "asset",
    "capabilities": [
        attach(
            "asset.upload",
            input_schema={
                "capture_ref": {
                    "type": "string",
                    "required": False,
                    "description": "本机 inbox CaptureRef JSON {capture_id, type, mime_type}。拍照后上传常为 $capture_ref。",
                },
                "asset_ref": {
                    "type": "string",
                    "required": False,
                    "description": "已登记 Asset 的 AssetRef JSON。禁止 photo_url / path / 永久 URL。已有 Asset 再传一份时用。",
                },
                "dest": {
                    "type": "string",
                    "required": False,
                    "description": "img_server（默认，本机图床）| cloud | gdrive | dropbox。别名 lan/local/home → img_server。gdrive/dropbox 本轮未实现，必须失败。",
                },
            },
            output_schema={
                "asset_ref": {
                    "type": "string",
                    "required": True,
                    "description": "上传后的 AssetRef JSON。禁止 photo_url。",
                },
                "dest": {
                    "type": "string",
                    "required": True,
                    "description": "实际写入的 dest：img_server 或 cloud",
                },
            },
        ),
    ],
}

LOCAL_VOICE_SERVICE: dict[str, Any] = {
    "service_id": "local.voice",
    "display_name": "Local Voice Stream",
    "version": "0.2.0",
    "group": "voice",
    "capabilities": [
        attach(
            "voice.stream",
            input_schema={},
            output_schema={
                "transcript": {
                    "type": "string",
                    "required": False,
                    "description": "最近一次转写（观测用；常驻入口不经计划逐步产出）",
                },
            },
        ),
        attach(
            "voicewakeup.echo",
            input_schema={
                "text": {
                    "type": "string",
                    "required": False,
                    "description": "回声文案；缺省为又咋了",
                },
            },
            output_schema={
                "echo_text": {
                    "type": "string",
                    "required": True,
                    "description": "实际念出的文案",
                },
            },
        ),
    ],
}

LOCAL_VISION_SERVICE: dict[str, Any] = {
    "service_id": "local.vision",
    "display_name": "Local Vision",
    "version": "0.5.0",
    "group": "vision",
    "capabilities": [
        attach(
            'vision.perceive',
            input_schema={
                'asset_ref': {
                    'type': 'string',
                    'required': True,
                    'description': 'AssetRef JSON {asset_id, type, mime_type?}。禁止 photo_url / path / 永久 URL。常为 $asset_ref。',
                },
                'prompt': {
                    'type': 'string',
                    'required': False,
                    'description': '可选额外提示',
                },
            },
            output_schema={
                'summary': {
                    'type': 'string',
                    'required': True,
                    'description': '一句话画面摘要',
                },
                'people': {
                    'type': 'string',
                    'required': False,
                    'description': '人物列表 JSON',
                },
                'spatial': {
                    'type': 'string',
                    'required': False,
                    'description': '空间布局描述',
                },
                'actions': {
                    'type': 'string',
                    'required': False,
                    'description': '主要动作',
                },
                'posture': {
                    'type': 'string',
                    'required': False,
                    'description': '体态/姿势',
                },
                'lighting': {
                    'type': 'string',
                    'required': False,
                    'description': '光线 JSON（whole + region）',
                },
            },
        ),
        attach(
            'vision.ask',
            input_schema={
                'asset_ref': {
                    'type': 'string',
                    'required': True,
                    'description': 'AssetRef JSON {asset_id, type, mime_type?}。禁止 photo_url / path / 永久 URL。常为 $asset_ref。',
                },
                'query': {
                    'type': 'string',
                    'required': True,
                    'description': '用户原话或完整问题，如「这个字读啥」「电视画面里是哪部剧」',
                },
            },
            output_schema={
                'answer_text': {
                    'type': 'string',
                    'required': True,
                    'description': '针对图+问句的中文回答；不确定时直说我不知道',
                },
            },
        ),
    ],
}

LIVINGROOM_LIGHT_SERVICE: dict[str, Any] = {
    "service_id": "livingroom.ceiling_light",
    "display_name": "客厅大路灯",
    "version": "0.1.1",
    "group": "light",
    "capabilities": [
        attach(
            'light.set',
            input_schema={
                'state': {
                    'type': 'string',
                    'required': True,
                    'description': 'on 开灯 / off 关灯；兼容 开、关、开灯、关灯',
                },
            },
            output_schema={
                'state': {
                    'type': 'string',
                    'required': True,
                    'description': '规范化后的 on 或 off',
                },
            },
        ),
    ],
}

LOCAL_VOICE_TEST_SERVICE: dict[str, Any] = {
    "service_id": "local.voice_test",
    "display_name": "台灯语音控制实验",
    "version": "0.1.0",
    "group": "experiment",
    "capabilities": [
        attach(
            "voice_test.run_trial",
            input_schema={
                "voice": {
                    "type": "string",
                    "required": False,
                    "description": "TTS 音色，如 Tingting；缺省读 VoiceProfile",
                },
                "speed": {
                    "type": "number",
                    "required": False,
                    "description": "语速倍率，1.0 为默认；范围 0.5–2.0",
                },
                "volume": {
                    "type": "number",
                    "required": False,
                    "description": "播放音量 0.0–1.0，afplay -v",
                },
                "pitch": {
                    "type": "string",
                    "required": False,
                    "description": "仅 edge-tts，如 +0Hz；say 后端忽略",
                },
                "wake_word": {
                    "type": "string",
                    "required": False,
                    "description": "唤醒词，默认 小书小书",
                },
                "command": {
                    "type": "string",
                    "required": False,
                    "description": "命令文案，默认 打开台灯。日常开灯不要用本能力。",
                },
                "wake_word_pause_ms": {
                    "type": "number",
                    "required": False,
                    "description": "「小书小书」与「打开台灯/关闭台灯」之间的停顿毫秒；识别率试验变量。>2000 命令窗口高风险。默认 1500。不是 settle_ms。",
                },
                "settle_ms": {
                    "type": "number",
                    "required": False,
                    "description": "命令播放后、拍照前等待毫秒，默认 1500",
                },
                "experiment_id": {
                    "type": "string",
                    "required": False,
                    "description": "实验批次 id；缺省自动生成",
                },
            },
            output_schema={
                "result": {
                    "type": "string",
                    "required": True,
                    "description": "SUCCESS / FAIL / INVALID。SUCCESS 仅当摄像头验证台灯已亮。",
                },
                "answer_text": {
                    "type": "string",
                    "required": True,
                    "description": "人类可读试验摘要",
                },
                "verification_result": {
                    "type": "string",
                    "required": False,
                    "description": "on / off / unknown",
                },
                "error_reason": {
                    "type": "string",
                    "required": False,
                    "description": "FAIL/INVALID 原因，如 lamp_not_on / lamp_already_on",
                },
                "latency_ms": {
                    "type": "string",
                    "required": False,
                    "description": "本轮墙钟耗时毫秒",
                },
                "timeline_text": {
                    "type": "string",
                    "required": False,
                    "description": "逐步墙钟：第一句/第二句触发、拍照、看图、拾音确认、最终结果",
                },
                "asset_ref": {
                    "type": "string",
                    "required": False,
                    "description": "验证图 AssetRef JSON。禁止 photo_url / path。",
                },
            },
        ),
    ],
}

_CLIMATE_INPUT_SCHEMA: dict[str, Any] = {
    'power': {
        'type': 'string',
        'required': False,
        'description': 'on 开 / off 关（兼容 开、关、打开、关闭）。与 mode、target_temp、fan、swing 至少填一项。off 时不可同时设模式、温度、风速或扫风。',
    },
    'mode': {
        'type': 'string',
        'required': False,
        'description': 'cool 制冷 / heat 制热 / fan 送风。未写 power 时本步内部先开机。',
    },
    'target_temp': {
        'type': 'number',
        'required': False,
        'description': '设定温度，摄氏整数 16–32。送风模式不可设温。未写 power 时本步内部先开机。',
    },
    'fan': {
        'type': 'string',
        'required': False,
        'description': 'auto 自动 / diffuse 柔风 / low 低 / medium 中 / high 高。未写 power 时本步内部先开机。',
    },
    'swing': {
        'type': 'string',
        'required': False,
        'description': 'off 关 / on 开 / horizontal 左右 / vertical 上下。未写 power 时本步内部先开机。',
    },
    'appliance': {
        'type': 'string',
        'required': False,
        'description': '绑定空调的显示名，如 客厅空调、儿童房空调。本机绑定多台时必填。',
    },
}
_CLIMATE_OUTPUT_SCHEMA: dict[str, Any] = {
    'power': {
        'type': 'string',
        'required': True,
        'description': '规范化后的 on 或 off',
    },
    'mode': {
        'type': 'string',
        'required': True,
        'description': 'cool / heat / fan / dry / auto',
    },
    'status_text': {
        'type': 'string',
        'required': True,
        'description': '人类可读状态，如「空调已开，制冷 26°C，风速中，左右扫风」',
    },
    'target_temp': {
        'type': 'number',
        'required': False,
        'description': '当前设定温度',
    },
    'indoor_temp': {
        'type': 'number',
        'required': False,
        'description': '室内温度',
    },
    'fan': {
        'type': 'string',
        'required': False,
        'description': 'auto / diffuse / low / medium / high',
    },
    'swing': {
        'type': 'string',
        'required': False,
        'description': 'off / on / horizontal / vertical',
    },
}

# Advertise-gate id (whitelist / laptop set). Actual heartbeat service_id
# is climate.living_room / climate.kids_room / … from the bound label.
CLIMATE_ADVERTISE_ID = "livingroom.climate"
_CLIMATE_SERVICE_ALIASES = {
    "客厅空调": "climate.living_room",
    "客厅海信空调": "climate.living_room",
    "儿童房空调": "climate.kids_room",
    "儿童房": "climate.kids_room",
}


def climate_service_id(label: str) -> str:
    name = str(label or "").strip()
    if not name or name == "海信空调":
        return CLIMATE_ADVERTISE_ID
    alias = _CLIMATE_SERVICE_ALIASES.get(name)
    if alias:
        return alias
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:10]
    return f"climate.{digest}"


def build_climate_service(label: str | None = None) -> dict[str, Any]:
    """Heartbeat climate service for one Hisense unit bound on this Mac."""
    label = str(label or bound_appliance_label() or "海信空调").strip() or "海信空调"
    overrides = named_appliance_overrides(
        label,
        generic_triggers=list(
            attach("climate.set")["typical_triggers"]
        ),
    )
    cap = attach(
        "climate.set",
        input_schema=_CLIMATE_INPUT_SCHEMA,
        output_schema=_CLIMATE_OUTPUT_SCHEMA,
        role=overrides.get("role"),
        planner_recognize=overrides.get("planner_recognize"),
        typical_triggers=overrides.get("typical_triggers"),
    )
    return {
        "service_id": climate_service_id(label),
        "display_name": label,
        "version": "0.1.0",
        "group": "climate",
        "capabilities": [cap],
    }


# Backward-compatible snapshot for imports / tests that still name the constant.
LIVINGROOM_CLIMATE_SERVICE: dict[str, Any] = {
    "service_id": CLIMATE_ADVERTISE_ID,
    "display_name": "客厅海信空调",
    "version": "0.1.0",
    "group": "climate",
    "capabilities": [
        attach(
            "climate.set",
            input_schema=_CLIMATE_INPUT_SCHEMA,
            output_schema=_CLIMATE_OUTPUT_SCHEMA,
        ),
    ],
}

LIVINGROOM_AQUARIUM_SERVICE: dict[str, Any] = {
    "service_id": "livingroom.aquarium",
    "display_name": "米家智能鱼缸",
    "version": "0.1.0",
    "group": "aquarium",
    "capabilities": [
        attach(
            'aquarium.set',
            input_schema={
                'power': {
                    'type': 'string',
                    'required': False,
                    'description': 'on 开 / off 关（兼容 开、关、打开、关闭）。与 light、pump、pump_flux、feed 至少填一项。',
                },
                'light': {
                    'type': 'string',
                    'required': False,
                    'description': 'on 开灯 / off 关灯',
                },
                'pump': {
                    'type': 'string',
                    'required': False,
                    'description': 'on 开水泵 / off 关水泵',
                },
                'pump_flux': {
                    'type': 'number',
                    'required': False,
                    'description': '水泵流量 1–10',
                },
                'feed': {
                    'type': 'string',
                    'required': False,
                    'description': 'true 或 1–10：立即喂一份或指定份数',
                },
            },
            output_schema={
                'status_text': {
                    'type': 'string',
                    'required': True,
                    'description': '人类可读状态，如「鱼缸已开，灯开，水温26°C」',
                },
                'power': {
                    'type': 'string',
                    'required': False,
                    'description': 'on / off',
                },
                'light': {
                    'type': 'string',
                    'required': False,
                    'description': 'on / off',
                },
                'pump': {
                    'type': 'string',
                    'required': False,
                    'description': 'on / off',
                },
                'pump_flux': {
                    'type': 'number',
                    'required': False,
                    'description': '当前水泵流量',
                },
                'water_temp': {
                    'type': 'number',
                    'required': False,
                    'description': '水温摄氏',
                },
                'fed': {
                    'type': 'boolean',
                    'required': False,
                    'description': '本步是否已喂食',
                },
            },
        ),
    ],
}

ENTRY_LOCK_SERVICE: dict[str, Any] = {
    "service_id": "entry.lock",
    "display_name": "小米门锁",
    "version": "0.1.0",
    "group": "lock",
    "capabilities": [
        attach(
            'lock.status',
            input_schema={},
            output_schema={
                'status_text': {
                    'type': 'string',
                    'required': True,
                    'description': '人类可读状态，如「已上锁，门关着」',
                },
                'locked': {
                    'type': 'string',
                    'required': False,
                    'description': 'locked / unlocked',
                },
                'door': {
                    'type': 'string',
                    'required': False,
                    'description': 'closed / open / ajar / unknown',
                },
                'online': {
                    'type': 'boolean',
                    'required': True,
                    'description': '门锁云端是否在线',
                },
            },
        ),
    ],
}

GOPRO_CAMERA_SERVICE: dict[str, Any] = {
    "service_id": "gopro.camera",
    "display_name": "GoPro Camera",
    "version": "0.9.0",
    "group": "camera",
    "capabilities": [
        attach(
            'camera.capture',
            input_schema={},
            output_schema={
                'capture_ref': {
                    'type': 'string',
                    'required': True,
                    'description': 'CaptureRef JSON {capture_id, type, mime_type}。本机 inbox 句柄，还不是 Asset。禁止 path / photo_url / asset_id。',
                },
            },
        ),
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


# GoPro stays home-server-only. Living-room light is also advertised on the
# laptop speaker (same 小书 wake protocol) so Mac-origin voice 开灯 does not
# depend on a backgrounded iPhone AVAudioSession.
# Hisense AC is cloud-backed and registers on the laptop (本机), like query/clock.
# img-server is not an Edge capability.
HOME_SERVER_ONLY_SERVICES = frozenset(
    {"gopro.camera", "livingroom.ceiling_light", "local.asset"}
)
HOME_SERVER_SERVICES = frozenset(
    {"gopro.camera", "livingroom.ceiling_light", "local.asset"}
)

_LAPTOP_SERVICE_ORDER = (
    CHROMECAST_DISPLAY_SERVICE,
    LOCAL_NOTIFY_SERVICE,
    LOCAL_VISION_SERVICE,
    LOCAL_QUERY_SERVICE,
    LOCAL_SEARCH_SERVICE,
    LOCAL_CLOCK_SERVICE,
    LOCAL_MATH_SERVICE,
    LOCAL_CHAT_SERVICE,
    LOCAL_ASSET_SERVICE,
    LOCAL_VOICE_SERVICE,
    LIVINGROOM_LIGHT_SERVICE,
    LIVINGROOM_CLIMATE_SERVICE,
    LIVINGROOM_AQUARIUM_SERVICE,
    ENTRY_LOCK_SERVICE,
    XIAOMI_TV_DISPLAY_SERVICE,
    LOCAL_VOICE_TEST_SERVICE,
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
    """laptop = Mac caps except GoPro; home-server = GoPro + living-room light."""
    raw = (os.environ.get("MAC_EDGE_ROLE") or "").strip().lower().replace("_", "-")
    if raw in ("home-server", "homeserver"):
        return "home-server"
    if raw in ("laptop", "local"):
        return "laptop"
    whitelist = _service_whitelist()
    if whitelist is not None and whitelist <= HOME_SERVER_ONLY_SERVICES:
        return "home-server"
    return "laptop"


def voice_stream_enabled() -> bool:
    """Advertise/supervise voice.stream (default on for laptop). MAC_EDGE_VOICE=0 to disable."""
    flag = _env_flag("MAC_EDGE_VOICE")
    if flag == "off":
        return False
    if flag == "on":
        return True
    return _edge_role() == "laptop"


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
            "advertise role=home-server (gopro.camera + livingroom.ceiling_light + "
            "local.asset; img-server is separate)"
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
    backend = display_backend()
    if backend == "xiaomi":
        if _allow_service(XIAOMI_TV_DISPLAY_SERVICE["service_id"], allowed_set):
            services.append(dict(XIAOMI_TV_DISPLAY_SERVICE))
            log.info("advertise xiaomi.tv.display (DLNA)")
    elif _allow_service(CHROMECAST_DISPLAY_SERVICE["service_id"], allowed_set):
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
    if _allow_service(LOCAL_SEARCH_SERVICE["service_id"], allowed_set):
        if any_provider_configured():
            services.append(dict(LOCAL_SEARCH_SERVICE))
            log.info("advertise local.search (search.images)")
        else:
            log.info("skip local.search — no image search provider usable")
    if _allow_service(LOCAL_CLOCK_SERVICE["service_id"], allowed_set):
        services.append(dict(LOCAL_CLOCK_SERVICE))
    if _allow_service(LOCAL_MATH_SERVICE["service_id"], allowed_set):
        services.append(dict(LOCAL_MATH_SERVICE))
    if _allow_service(LOCAL_CHAT_SERVICE["service_id"], allowed_set):
        services.append(dict(LOCAL_CHAT_SERVICE))
    if _allow_service(LOCAL_ASSET_SERVICE["service_id"], allowed_set):
        services.append(dict(LOCAL_ASSET_SERVICE))
    if _allow_service(LOCAL_VOICE_SERVICE["service_id"], allowed_set):
        if voice_stream_enabled():
            services.append(dict(LOCAL_VOICE_SERVICE))
            log.info("advertise local.voice (voice.stream)")
        else:
            log.info("skip local.voice — MAC_EDGE_VOICE off or not laptop")
    if _allow_service(LOCAL_VOICE_TEST_SERVICE["service_id"], allowed_set):
        services.append(dict(LOCAL_VOICE_TEST_SERVICE))
        log.info("advertise local.voice_test")
    if _allow_service(GOPRO_CAMERA_SERVICE["service_id"], allowed_set):
        if (os.environ.get("MAC_EDGE_GOPRO_SSID") or "").strip():
            services.append(dict(GOPRO_CAMERA_SERVICE))
            log.info("advertise gopro.camera (MAC_EDGE_GOPRO_SSID set)")
        else:
            log.info("skip gopro.camera — MAC_EDGE_GOPRO_SSID unset")
    if _allow_service(LIVINGROOM_LIGHT_SERVICE["service_id"], allowed_set):
        services.append(dict(LIVINGROOM_LIGHT_SERVICE))
        log.info("advertise livingroom.ceiling_light")
    if _allow_service(CLIMATE_ADVERTISE_ID, allowed_set):
        if credentials_configured():
            bound = bound_hisense_devices()
            labels = [
                str(item.get("label") or "").strip() or "海信空调"
                for item in bound
            ]
            if not labels:
                labels = [bound_appliance_label() or "海信空调"]
            seen_sids = set()
            for label in labels:
                climate = build_climate_service(label)
                sid = str(climate.get("service_id") or "")
                if sid in seen_sids:
                    continue
                seen_sids.add(sid)
                services.append(climate)
                log.info(
                    "advertise %s display_name=%s",
                    climate.get("service_id"),
                    climate.get("display_name"),
                )
        else:
            log.info(
                "skip climate — MAC_EDGE_HISENSE_USERNAME/PASSWORD unset"
            )
    if _allow_service(LIVINGROOM_AQUARIUM_SERVICE["service_id"], allowed_set):
        if xiaomi_credentials_configured():
            services.append(dict(LIVINGROOM_AQUARIUM_SERVICE))
            log.info("advertise livingroom.aquarium")
        else:
            log.info(
                "skip livingroom.aquarium — MAC_EDGE_XIAOMI_USERNAME/PASSWORD unset"
            )
    if _allow_service(ENTRY_LOCK_SERVICE["service_id"], allowed_set):
        if xiaomi_credentials_configured():
            services.append(dict(ENTRY_LOCK_SERVICE))
            log.info("advertise entry.lock")
        else:
            log.info("skip entry.lock — MAC_EDGE_XIAOMI_USERNAME/PASSWORD unset")
    return services
