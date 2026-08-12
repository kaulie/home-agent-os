"""Brain wire services[] advertised by this Mac Edge."""

from __future__ import annotations

from typing import Any

CHROMECAST_DISPLAY_SERVICE: dict[str, Any] = {
    "service_id": "chromecast.display",
    "display_name": "Chromecast Cast",
    "version": "0.2.0",
    "group": "display",
    "capabilities": [
        {
            "capability_id": "display.photo",
            "description": "给定 photo_url，经 Google Cast API 投到 Chromecast",
            "input_schema": {
                "photo_url": {
                    "type": "string",
                    "required": True,
                    "description": "公网可达的图片 URL",
                }
            },
            "output_schema": {},
        }
    ],
}

LOCAL_NOTIFY_SERVICE: dict[str, Any] = {
    "service_id": "local.notify",
    "display_name": "Local Notify",
    "version": "0.1.0",
    "group": "notify",
    "capabilities": [
        {
            "capability_id": "notify.speak",
            "description": "本机 TTS 发声通知/提醒（优先 Microsoft edge-tts 男声，失败回退 macOS say）",
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
                    "description": "可选 edge-tts 音色名，如 zh-CN-YunxiNeural / zh-CN-YunyangNeural",
                },
            },
            "output_schema": {},
        }
    ],
}


def default_services() -> list[dict[str, Any]]:
    return [dict(CHROMECAST_DISPLAY_SERVICE), dict(LOCAL_NOTIFY_SERVICE)]
