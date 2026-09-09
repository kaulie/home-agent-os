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

GAME_HOST_SERVICE: dict[str, Any] = {
    "service_id": "mac.game.host",
    "display_name": "Mac Game Host",
    "version": "0.1.0",
    "group": "game",
    "capabilities": [
        attach(
            "game.launch",
            input_schema={
                "game_id": {
                    "type": "string",
                    "required": True,
                    "description": "游戏 id，如 coin_catcher",
                },
                "game_url": {
                    "type": "string",
                    "required": False,
                    "description": "可选 LAN URL；缺省由 Mac 启动 serve.py 并返回",
                },
            },
            output_schema={
                "game_url": {
                    "type": "string",
                    "required": True,
                    "description": "LAN 游戏页 URL（Chromecast iframe 加载）",
                },
                "game_id": {
                    "type": "string",
                    "required": True,
                    "description": "已启动的游戏 id",
                },
                "status": {
                    "type": "string",
                    "required": True,
                    "description": "ready",
                },
            },
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

LOCAL_PRINTER_SERVICE: dict[str, Any] = {
    "service_id": "local.printer",
    "display_name": "米家喷墨一体机",
    "version": "0.1.0",
    "group": "printer",
    "capabilities": [
        attach(
            "printer.print",
            input_schema={
                "asset_ref": {
                    "type": "object",
                    "required": True,
                    "description": (
                        "必填 AssetRef JSON，type=document（PDF）。"
                        "例 {\"asset_id\":\"asset_…\",\"type\":\"document\"}。"
                        "禁止 path / 永久 URL；缺则本能力无效。"
                    ),
                },
                "copies": {
                    "type": "number",
                    "required": False,
                    "description": "份数，正整数，默认 1",
                },
                "printer_name": {
                    "type": "string",
                    "required": False,
                    "description": (
                        "可选 CUPS 队列名；未传则用 MAC_EDGE_PRINTER_NAME，"
                        "再否则匹配名含 Mi_All_in_One_Inkjet 的队列"
                    ),
                },
                "color_mode": {
                    "type": "string",
                    "required": False,
                    "description": "bw（默认黑白）或 color（彩色）",
                },
            },
            output_schema={
                "status_text": {
                    "type": "string",
                    "required": True,
                    "description": "人类可读状态，如「已提交打印到 …」",
                },
                "job_id": {
                    "type": "string",
                    "required": True,
                    "description": "CUPS 任务号，如 Queue-123",
                },
                "printer_name": {
                    "type": "string",
                    "required": True,
                    "description": "实际使用的 CUPS 队列名",
                },
                "color_mode": {
                    "type": "string",
                    "required": False,
                    "description": "实际色彩：bw 或 color",
                },
            },
        ),
    ],
}

XIAODU_SPEAKER_SERVICE: dict[str, Any] = {
    "service_id": "xiaodu.speaker",
    "display_name": "小度音箱",
    "version": "0.1.0",
    "group": "notify",
    "capabilities": [
        attach(
            "xiaodu.speak",
            input_schema={
                "text": {
                    "type": "string",
                    "required": True,
                    "description": "要经小度音箱播报的原文",
                },
                "voice": {
                    "type": "string",
                    "required": False,
                    "description": "edge-tts 音色，默认 zh-CN-XiaoxiaoNeural",
                },
            },
            output_schema={},
        ),
    ],
}

NETEASE_MUSIC_SERVICE: dict[str, Any] = {
    "service_id": "netease.music",
    "display_name": "网易云音乐",
    "version": "0.5.0",
    "group": "music",
    "capabilities": [
        attach(
            "music.play",
            input_schema={
                "song": {
                    "type": "string",
                    "required": False,
                    "description": "歌名（本机 Mac 本轮必填）",
                },
                "artist": {
                    "type": "string",
                    "required": False,
                    "description": "作者，仅收窄搜索",
                },
                "album": {
                    "type": "string",
                    "required": False,
                    "description": "专辑（本轮忽略）",
                },
            },
            output_schema={
                "song": {
                    "type": "string",
                    "required": False,
                    "description": "正在播放的歌名",
                },
                "artist": {
                    "type": "string",
                    "required": False,
                    "description": "歌手",
                },
                "original_id": {
                    "type": "number",
                    "required": False,
                    "description": "网易云 original_id",
                },
            },
            planner_recognize=(
                "从用户话里拆出歌名 song、可选作者 artist；不要把整句当 keyword。"
                "本轮必须有 song，不能只按歌手或专辑点播。不负责暂停/切歌。"
            ),
            typical_triggers=["放十年", "播放陈奕迅的十年"],
            do_not_dispatch=["蓝牙连接", "TTS", "开灯", "暂停", "下一首", "下载", "缓存"],
        ),
        attach(
            "music.cache",
            input_schema={
                "song": {
                    "type": "string",
                    "required": False,
                    "description": "歌名或「xxx的歌/歌曲」",
                },
                "artist": {
                    "type": "string",
                    "required": False,
                    "description": "歌手",
                },
                "count": {
                    "type": "number",
                    "required": False,
                    "description": "预取条数，1–200，默认 100",
                },
                "fetch_audio": {
                    "type": "boolean",
                    "required": False,
                    "description": "本轮忽略；true 时仍只写索引并说明未下载音频",
                },
            },
            output_schema={
                "cached": {
                    "type": "number",
                    "required": False,
                    "description": "本次写入索引的歌曲数",
                },
            },
        ),
        attach("music.pause", input_schema={}, output_schema={}),
        attach("music.resume", input_schema={}, output_schema={}),
        attach("music.stop", input_schema={}, output_schema={}),
        attach("music.next", input_schema={}, output_schema={}),
        attach("music.previous", input_schema={}, output_schema={}),
    ],
}

MUSIC_RECOGNIZE_SERVICE: dict[str, Any] = {
    "service_id": "music.recognize",
    "display_name": "识曲（听歌识曲）",
    "version": "0.1.0",
    "group": "music",
    "capabilities": [
        attach(
            "music.recognize",
            input_schema={
                "min_sec": {
                    "type": "number",
                    "required": False,
                    "description": "最短收录/首次识曲窗口秒数，可选，默认环境值",
                },
                "max_sec": {
                    "type": "number",
                    "required": False,
                    "description": "最长收录秒数，可选，默认环境值（≤60）",
                },
            },
            output_schema={
                "answer_text": {
                    "type": "string",
                    "required": True,
                    "description": "给用户的一句话播报（歌名）；命中或超时都有",
                },
                "matched": {
                    "type": "boolean",
                    "required": False,
                    "description": "是否识别成功",
                },
                "song_title": {
                    "type": "string",
                    "required": False,
                    "description": "识别出的歌名",
                },
                "artist": {
                    "type": "string",
                    "required": False,
                    "description": "歌手",
                },
                "confidence": {
                    "type": "number",
                    "required": False,
                    "description": "置信度（可选）",
                },
            },
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

LOCAL_FILE_CONVERT_SERVICE: dict[str, Any] = {
    "service_id": "local.file.convert",
    "display_name": "文件格式转换器",
    "version": "0.1.0",
    "group": "convert",
    "capabilities": [
        attach(
            "file.convert",
            input_schema={
                "to_format": {
                    "type": "string",
                    "required": True,
                    "description": (
                        "目标格式；一期仅接受 pdf，其它值明确失败。"
                        "例 \"pdf\"。"
                    ),
                },
                "from_format": {
                    "type": "string",
                    "required": False,
                    "description": (
                        "源格式；缺省按 asset_refs 类型推断为 image。"
                        "显式传非 image 则明确失败。"
                    ),
                },
                "asset_refs": {
                    "type": "string",
                    "required": True,
                    "description": (
                        "必填 AssetRef JSON 数组，至少一张，type 必须为 image"
                        "（JPEG/PNG）。数组顺序 = PDF 页码顺序。"
                        "例 [{\"asset_id\":\"asset_…\",\"type\":\"image\"}]。"
                        "禁止 path / 永久 URL / base64。"
                    ),
                },
                "name": {
                    "type": "string",
                    "required": False,
                    "description": (
                        "可选生成的 PDF 展示名（不含或自动补 .pdf）；"
                        "不传则用 convert-<时间戳>.pdf。"
                    ),
                },
            },
            output_schema={
                "asset_ref": {
                    "type": "object",
                    "required": True,
                    "description": "新登记 document（PDF）Asset 的 AssetRef JSON",
                },
                "page_count": {
                    "type": "number",
                    "required": True,
                    "description": "PDF 页数（= 图片数）",
                },
                "status_text": {
                    "type": "string",
                    "required": True,
                    "description": "中文一句话结果，含页数与 asset_id",
                },
            },
        ),
    ],
}

LOCAL_PDF_ROTATE_SERVICE: dict[str, Any] = {
    "service_id": "local.pdf.rotate",
    "display_name": "PDF 旋转器",
    "version": "0.1.0",
    "group": "convert",
    "capabilities": [
        attach(
            "pdf.rotate",
            input_schema={
                "asset_ref": {
                    "type": "object",
                    "required": True,
                    "description": (
                        "必填 AssetRef JSON，type=document（PDF）。"
                        "例 {\"asset_id\":\"asset_…\",\"type\":\"document\"}。"
                        "禁止 path / 永久 URL；缺则本能力无效。"
                    ),
                },
                "orientation": {
                    "type": "string",
                    "required": True,
                    "description": (
                        "目标方向：portrait=竖版 / landscape=横版；"
                        "也接受 竖版/横版/竖向/横向 等中文别名。"
                    ),
                },
                "name": {
                    "type": "string",
                    "required": False,
                    "description": (
                        "可选生成的 PDF 展示名（不含或自动补 .pdf）；"
                        "不传则用 pdf-rotate-<时间戳>-<横版|竖版>.pdf。"
                    ),
                },
            },
            output_schema={
                "asset_ref": {
                    "type": "object",
                    "required": True,
                    "description": "旋转后新登记 document AssetRef；无需旋转时为原 asset_ref",
                },
                "page_count": {
                    "type": "number",
                    "required": True,
                    "description": "PDF 页数",
                },
                "source_orientation": {
                    "type": "string",
                    "required": True,
                    "description": "整份判出的原始方向：portrait / landscape / mixed / square",
                },
                "target_orientation": {
                    "type": "string",
                    "required": True,
                    "description": "请求的目标方向：portrait / landscape",
                },
                "rotated_pages": {
                    "type": "number",
                    "required": True,
                    "description": "实际旋转 90° 的页数（0=无需旋转，复用原 asset）",
                },
                "status_text": {
                    "type": "string",
                    "required": True,
                    "description": "中文一句话结果，含页数、方向与 asset_id",
                },
            },
        ),
    ],
}

LOCAL_WEB_SCRAPER_SERVICE: dict[str, Any] = {
    "service_id": "local.web.scraper",
    "display_name": "网页抓取器",
    "version": "0.1.0",
    "group": "convert",
    "capabilities": [
        attach(
            "web.scraper",
            input_schema={
                "url": {
                    "type": "string",
                    "required": True,
                    "description": (
                        "网页地址（http/https），与 asset_ref 二选一；"
                        "给了 asset_ref(type=url) 时可省。"
                    ),
                },
                "asset_ref": {
                    "type": "object",
                    "required": False,
                    "description": (
                        "已登记的 Brain url 资产（type=url）AssetRef；与 url 二选一，"
                        "填了就抓该链接。例 {\"asset_id\":\"asset_…\",\"type\":\"url\"}。"
                    ),
                },
                "mode": {
                    "type": "string",
                    "required": False,
                    "description": (
                        "article=抓核心正文（默认，剔除广告/导航）/ page=忠实整页；"
                        "也接受 正文/整页 等中文。"
                    ),
                },
                "format": {
                    "type": "string",
                    "required": False,
                    "description": "pdf=PDF 文档（默认）/ text=纯文本；也接受 文本。",
                },
                "renderer": {
                    "type": "string",
                    "required": False,
                    "description": (
                        "pdf 时生效：auto=自动（默认，article 优先 weasyprint、"
                        "page 优先 chrome，缺一自动回退）/ weasyprint / chrome。"
                    ),
                },
                "name": {
                    "type": "string",
                    "required": False,
                    "description": (
                        "可选产物展示名（自动补 .pdf/.txt）；"
                        "不传则 web-scraper-<时间戳>-<mode>.*。"
                    ),
                },
            },
            output_schema={
                "asset_ref": {
                    "type": "object",
                    "required": True,
                    "description": "抓取产物 document AssetRef（PDF application/pdf 或文本 text/plain）",
                },
                "title": {
                    "type": "string",
                    "required": True,
                    "description": "网页标题",
                },
                "url": {
                    "type": "string",
                    "required": True,
                    "description": "抓取到的最终 URL（跟随重定向后）",
                },
                "mode": {
                    "type": "string",
                    "required": True,
                    "description": "article / page",
                },
                "format": {
                    "type": "string",
                    "required": True,
                    "description": "pdf / text",
                },
                "renderer": {
                    "type": "string",
                    "required": False,
                    "description": "实际使用的渲染引擎（pdf 时）：weasyprint / chrome",
                },
                "page_count": {
                    "type": "number",
                    "required": False,
                    "description": "PDF 页数（pdf 时）",
                },
                "char_count": {
                    "type": "number",
                    "required": False,
                    "description": "导出文本字符数",
                },
                "status_text": {
                    "type": "string",
                    "required": True,
                    "description": "中文一句话结果，含页数/字数、引擎与 asset_id",
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

LOCAL_CHARACTER_SERVICE: dict[str, Any] = {
    "service_id": "local.character",
    "display_name": "Local Character Reading",
    "version": "0.3.0",
    "group": "reading",
    "capabilities": [
        attach(
            "reading.detect_finger",
            input_schema={
                "asset_ref": {
                    "type": "string",
                    "required": True,
                    "description": "AssetRef JSON {asset_id, type, mime_type?}。手指指向某字的图片。禁止 photo_url / path / 永久 URL。常为 $asset_ref。",
                },
            },
            output_schema={
                "finger": {
                    "type": "object",
                    "required": True,
                    "description": "食指 {tip:[x,y], direction:[dx,dy]}",
                },
                "status": {
                    "type": "string",
                    "required": False,
                    "description": "引擎状态",
                },
            },
        ),
        attach(
            "reading.ocr_at_finger",
            input_schema={
                "asset_ref": {
                    "type": "string",
                    "required": True,
                    "description": "AssetRef JSON {asset_id, type, mime_type?}。禁止 photo_url / path / 永久 URL。常为 $asset_ref。",
                },
                "finger": {
                    "type": "object",
                    "required": True,
                    "description": "食指 {tip:[x,y], direction:[dx,dy]}。由 reading.detect_finger 产出。",
                },
            },
            output_schema={
                "chars": {
                    "type": "array",
                    "required": True,
                    "description": "指尖附近 OCR 字框列表",
                },
                "status": {
                    "type": "string",
                    "required": False,
                    "description": "引擎状态",
                },
            },
        ),
        attach(
            "reading.rank_pointed",
            input_schema={
                "asset_ref": {
                    "type": "string",
                    "required": True,
                    "description": "AssetRef JSON {asset_id, type, mime_type?}。禁止 photo_url / path / 永久 URL。常为 $asset_ref。",
                },
                "finger": {
                    "type": "object",
                    "required": True,
                    "description": "食指 {tip:[x,y], direction:[dx,dy]}。由 reading.detect_finger 产出。",
                },
                "chars": {
                    "type": "array",
                    "required": True,
                    "description": "指尖附近 OCR 字框。由 reading.ocr_at_finger 产出。",
                },
            },
            output_schema={
                "character": {
                    "type": "string",
                    "required": True,
                    "description": "指尖指向的汉字；认不出时为空串",
                },
                "answer_text": {
                    "type": "string",
                    "required": True,
                    "description": "给人听/看的中文答案；认不出时直说不知道",
                },
                "status": {
                    "type": "string",
                    "required": False,
                    "description": "引擎状态：ok / ok_with_alternatives / 其它失败状态",
                },
            },
        ),
        attach(
            "reading.point_to_character",
            input_schema={
                "asset_ref": {
                    "type": "string",
                    "required": True,
                    "description": "已排好的 Image Asset。自己不拍照。禁止 photo_url / path / 永久 URL。常为 $asset_ref。",
                },
            },
            output_schema={
                "character": {
                    "type": "string",
                    "required": True,
                    "description": "指尖指向的汉字；认不出时为空串",
                },
                "answer_text": {
                    "type": "string",
                    "required": True,
                    "description": "给人听/看的中文答案；认不出时直说不知道",
                },
                "status": {
                    "type": "string",
                    "required": False,
                    "description": "引擎状态：ok / ok_with_alternatives / 其它失败状态",
                },
            },
        ),
    ],
}

LOCAL_PRONUNCIATION_SERVICE: dict[str, Any] = {
    "service_id": "local.pronunciation",
    "display_name": "Local Pronunciation Assessment",
    "version": "0.1.0",
    "group": "pronunciation",
    "capabilities": [
        attach(
            "pronunciation.assess",
            input_schema={
                "reference_audio": {
                    "type": "string",
                    "required": True,
                    "description": "AssetRef JSON {asset_id, type:audio, mime_type?}。标准英文朗读音频。禁止 path / 永久 URL / base64。常为 $reference_audio。",
                },
                "student_audio": {
                    "type": "string",
                    "required": True,
                    "description": "AssetRef JSON {asset_id, type:audio, mime_type?}。小朋友跟读的整段英文音频。禁止 path / 永久 URL / base64。常为 $student_audio。",
                },
            },
            output_schema={
                "overall_score": {
                    "type": "number",
                    "required": True,
                    "description": "整段朗读总体评分 0..100",
                },
                "accuracy_score": {
                    "type": "number",
                    "required": True,
                    "description": "发音准确度 0..100",
                },
                "fluency_score": {
                    "type": "number",
                    "required": True,
                    "description": "流利度 0..100",
                },
                "completeness_score": {
                    "type": "number",
                    "required": True,
                    "description": "完整度 0..100",
                },
                "prosody_score": {
                    "type": "number",
                    "required": True,
                    "description": "韵律/重音表现 0..100",
                },
                "duration": {
                    "type": "object",
                    "required": True,
                    "description": "{reference, student} 两段音频时长（秒）",
                },
                "problem_words": {
                    "type": "array",
                    "required": True,
                    "description": "重点问题单词 [{word, score, start, end, phoneme_errors, reason?}]",
                },
                "problem_phonemes": {
                    "type": "array",
                    "required": True,
                    "description": "重点问题音素 [{phoneme, word, start, end}]",
                },
                "fluency": {
                    "type": "object",
                    "required": True,
                    "description": "{speech_rate, pause_count, long_pause_count, repetition_count}",
                },
                "raw_alignment": {
                    "type": "array",
                    "required": True,
                    "description": "逐词对齐明细，供调试/UI 展开",
                },
                "feedback_text": {
                    "type": "string",
                    "required": True,
                    "description": "给人看的中文一句话总结，供 Brain 组装 presentation",
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
        attach(
            'camera.capture_and_upload',
            input_schema={
                'dest': {
                    'type': 'string',
                    'required': False,
                    'description': 'img_server（默认）| cloud。传给内部 asset.upload。',
                },
            },
            output_schema={
                'asset_ref': {
                    'type': 'string',
                    'required': True,
                    'description': '上传后的 AssetRef JSON。禁止 photo_url / path / capture_ref 当用户可见 identity。',
                },
                'dest': {
                    'type': 'string',
                    'required': False,
                    'description': 'img_server 或 cloud',
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


def _character_service_listening() -> bool:
    """True when the local character-service (reading.point_to_character) is up."""
    from mac_edge.plugins.point_to_character import DEFAULT_HEALTH_URL

    raw = (
        os.environ.get("MAC_EDGE_CHARACTER_HEALTH_URL") or DEFAULT_HEALTH_URL
    ).strip() or DEFAULT_HEALTH_URL
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


def _pronunciation_service_listening() -> bool:
    """True when the local pronunciation-service (pronunciation.assess) is up."""
    from mac_edge.plugins.pronunciation_assess import DEFAULT_HEALTH_URL

    raw = (
        os.environ.get("MAC_EDGE_PRONUNCIATION_HEALTH_URL") or DEFAULT_HEALTH_URL
    ).strip() or DEFAULT_HEALTH_URL
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
    LOCAL_PRINTER_SERVICE,
    XIAODU_SPEAKER_SERVICE,
    NETEASE_MUSIC_SERVICE,
    MUSIC_RECOGNIZE_SERVICE,
    LOCAL_VISION_SERVICE,
    LOCAL_CHARACTER_SERVICE,
    LOCAL_PRONUNCIATION_SERVICE,
    LOCAL_QUERY_SERVICE,
    LOCAL_SEARCH_SERVICE,
    LOCAL_CLOCK_SERVICE,
    LOCAL_MATH_SERVICE,
    LOCAL_FILE_CONVERT_SERVICE,
    LOCAL_PDF_ROTATE_SERVICE,
    LOCAL_WEB_SCRAPER_SERVICE,
    LOCAL_CHAT_SERVICE,
    LOCAL_ASSET_SERVICE,
    LOCAL_VOICE_SERVICE,
    LIVINGROOM_LIGHT_SERVICE,
    LIVINGROOM_CLIMATE_SERVICE,
    LIVINGROOM_AQUARIUM_SERVICE,
    ENTRY_LOCK_SERVICE,
    XIAOMI_TV_DISPLAY_SERVICE,
    GAME_HOST_SERVICE,
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
    if _allow_service(LOCAL_PRINTER_SERVICE["service_id"], allowed_set):
        from mac_edge.plugins.xiaomi_aio_printer import cups_available

        if cups_available():
            services.append(dict(LOCAL_PRINTER_SERVICE))
            log.info("advertise local.printer (lp/lpstat found)")
        else:
            log.info("skip local.printer — lp/lpstat not found")
    if _allow_service(XIAODU_SPEAKER_SERVICE["service_id"], allowed_set):
        from mac_edge.plugins.xiaodu_speaker import xiaodu_configured

        if xiaodu_configured():
            services.append(dict(XIAODU_SPEAKER_SERVICE))
            log.info("advertise xiaodu.speaker (MAC_EDGE_XIAODU_IP set)")
        else:
            log.info("skip xiaodu.speaker — MAC_EDGE_XIAODU_IP unset")
    if _allow_service(NETEASE_MUSIC_SERVICE["service_id"], allowed_set):
        from mac_edge.plugins.netease_music import ncm_cli_configured

        if ncm_cli_configured():
            services.append(dict(NETEASE_MUSIC_SERVICE))
            log.info("advertise netease.music (ncm-cli found)")
        else:
            log.info("skip netease.music — ncm-cli not found")
    if _allow_service(MUSIC_RECOGNIZE_SERVICE["service_id"], allowed_set):
        from mac_edge.plugins.music_recognize import configured as music_recognize_configured

        if music_recognize_configured():
            services.append(dict(MUSIC_RECOGNIZE_SERVICE))
            log.info(
                "advertise music.recognize (MAC_EDGE_MUSIC_RECOGNIZE_PROVIDER configured)"
            )
        else:
            log.info(
                "skip music.recognize — MAC_EDGE_MUSIC_RECOGNIZE_PROVIDER unset/none"
            )
    if _allow_service(LOCAL_VISION_SERVICE["service_id"], allowed_set):
        services.append(dict(LOCAL_VISION_SERVICE))
    if _allow_service(LOCAL_CHARACTER_SERVICE["service_id"], allowed_set):
        if _character_service_listening():
            services.append(dict(LOCAL_CHARACTER_SERVICE))
            log.info("advertise local.character (reading.point_to_character)")
        else:
            log.info("skip local.character — character-service :9189 not reachable")
    if _allow_service(LOCAL_PRONUNCIATION_SERVICE["service_id"], allowed_set):
        if _pronunciation_service_listening():
            services.append(dict(LOCAL_PRONUNCIATION_SERVICE))
            log.info("advertise local.pronunciation (pronunciation.assess)")
        else:
            log.info("skip local.pronunciation — pronunciation-service :9190 not reachable")
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
    if _allow_service(LOCAL_FILE_CONVERT_SERVICE["service_id"], allowed_set):
        # Pure-stdlib image→pdf: no extra availability dependency, always on laptop.
        services.append(dict(LOCAL_FILE_CONVERT_SERVICE))
        log.info("advertise local.file.convert (file.convert)")
    if _allow_service(LOCAL_PDF_ROTATE_SERVICE["service_id"], allowed_set):
        from mac_edge.plugins.pdf_rotate import pypdf_available

        if pypdf_available():
            services.append(dict(LOCAL_PDF_ROTATE_SERVICE))
            log.info("advertise local.pdf.rotate (pdf.rotate)")
        else:
            log.info("skip local.pdf.rotate — pypdf not installed")
    if _allow_service(LOCAL_WEB_SCRAPER_SERVICE["service_id"], allowed_set):
        from mac_edge.plugins.web_scraper import any_renderer_available

        if any_renderer_available():
            services.append(dict(LOCAL_WEB_SCRAPER_SERVICE))
            log.info("advertise local.web.scraper (web.scraper)")
        else:
            log.info(
                "skip local.web.scraper — no pdf renderer (weasyprint/pango or chrome/edge) available"
            )
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
    if _allow_service(GAME_HOST_SERVICE["service_id"], allowed_set):
        try:
            from mac_edge.plugins.game_host import ensure_running

            ensure_running()
            services.append(dict(GAME_HOST_SERVICE))
            log.info("advertise mac.game.host (coin-catcher :8102)")
        except Exception as e:
            log.warning("skip mac.game.host — %s", e)
    return services
