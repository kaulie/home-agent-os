"""Home Agent Brain control plane.

Source: volcengine/home_brain.py. Iterate on this file only.
"""
from __future__ import annotations

import threading
import secrets
import uuid
import string
import queue
import time
import random
import json
import hashlib
import re
import unicodedata
import os
import sqlite3
import logging
import traceback
from pathlib import Path
from logging.handlers import TimedRotatingFileHandler
import urllib
import urllib.error
import urllib.request
import mimetypes
from copy import deepcopy
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from flask import Flask, request, Blueprint, jsonify, send_file, Response, stream_with_context

try:
    import db as brain_db
except ImportError:  # pragma: no cover
    from server import db as brain_db  # type: ignore

try:
    from intent_complexity import classify as classify_intent_complexity
except ImportError:  # pragma: no cover
    from server.intent_complexity import classify as classify_intent_complexity  # type: ignore

try:
    from dev_task import (
        cancel_agent_task,
        ensure_poller_started,
        get_agent_task,
        get_agent_task_usage_stats,
        get_dev_task_categories,
        list_agent_tasks,
        set_agent_task_category,
        submit_agent_task,
    )
    from debug_gateway import (
        get_debug_issue,
        list_debug_issues,
        submit_debug_report,
    )
    from agent_fleet import get_fleet_view, wake_fleet_agent
    from release_pipeline import (
        approve_release,
        get_release,
        list_releases,
        reject_release,
        sync_from_chat as sync_releases_from_chat,
    )
    from agent_chat import (
        AgentChatError,
        ack_boss_message,
        fetch_chat_attachment_content,
        get_chat_view,
        promote_chat_to_dev_task,
        related_background_from_messages,
        send_boss_message,
        unack_boss_message,
        upload_chat_attachment,
    )
    from docs_browser import DocsBrowserError, docs_root, list_documents, read_document
except ImportError:  # pragma: no cover
    from server.dev_task import (  # type: ignore
        cancel_agent_task,
        ensure_poller_started,
        get_agent_task,
        get_agent_task_usage_stats,
        get_dev_task_categories,
        list_agent_tasks,
        set_agent_task_category,
        submit_agent_task,
    )
    from server.debug_gateway import (  # type: ignore
        get_debug_issue,
        list_debug_issues,
        submit_debug_report,
    )
    from server.agent_fleet import get_fleet_view, wake_fleet_agent  # type: ignore
    from server.release_pipeline import (  # type: ignore
        approve_release,
        get_release,
        list_releases,
        reject_release,
        sync_from_chat as sync_releases_from_chat,
    )
    from server.agent_chat import (  # type: ignore
        AgentChatError,
        ack_boss_message,
        get_chat_view,
        promote_chat_to_dev_task,
        related_background_from_messages,
        send_boss_message,
        unack_boss_message,
    )
    from server.docs_browser import DocsBrowserError, docs_root, list_documents, read_document  # type: ignore

try:
    from shortcut_mode import InterceptResult, apply_mode_event, intercept as shortcut_intercept
except ImportError:  # pragma: no cover
    from server.shortcut_mode import (  # type: ignore
        InterceptResult,
        apply_mode_event,
        intercept as shortcut_intercept,
    )

try:
    from system_capabilities import (
        SYSTEM_EDGE_ID,
        catalog_rows as system_capability_catalog_rows,
        is_system_capability,
        run_system_step,
        SystemCapabilityError,
    )
except ImportError:  # pragma: no cover
    from server.system_capabilities import (  # type: ignore
        SYSTEM_EDGE_ID,
        catalog_rows as system_capability_catalog_rows,
        is_system_capability,
        run_system_step,
        SystemCapabilityError,
    )

try:
    from capability_ads import composition_of
except ImportError:  # pragma: no cover
    from server.capability_ads import composition_of  # type: ignore

app = Flask(__name__)

# ====================== 配置区 Mock 内存缓存（本地测试不用Redis） ======================
# 模拟Redis内存缓存，生产替换为真实redis客户端
mock_cache = {}
# 缓存改为队列：key=sessionId，value=list(按顺序存储多条回答)
session_result_cache = {}
CACHE_TTL = 60 # 缓存30分钟
# 串行任务队列，最大50排队（Ark / 执行规划路径）
task_queue = queue.Queue(maxsize=50)
# Qwen 对照专用队列：不入执行路径，不得阻塞 Ark worker
qwen_task_queue = queue.Queue(maxsize=50)
# 单线程串行执行大模型，全局锁保证同一时间仅1次 Ark 调用（Qwen 不用这把锁）
llm_running_lock = threading.Lock()

# Legacy / model-invented ids → canonical capability_id for gap reports.
_CAPABILITY_ID_ALIASES = {
    "ac.set": "climate.set",
    "hvac.set": "climate.set",
    "air_conditioner.set": "climate.set",
}


# provider: []
# eg. neteasemusic: [a, b, c]
commands_queue = {}

# 火山方舟配置（密钥只读环境变量 / 同目录 .env，不要写进仓库）
_HERE = Path(__file__).resolve().parent


def _load_dotenv(path: Path) -> None:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return
    for line in raw.splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, _, val = text.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


_load_dotenv(_HERE / ".env")
if _HERE.name == "server":
    _load_dotenv(_HERE.parent / ".env")
MODEL_ID = os.environ.get("ARK_MODEL_ID", "ep-20260712174403-5jcgs")
ARK_API_KEY = os.environ.get("ARK_API_KEY", "")
ARK_URL = os.environ.get(
    "ARK_URL",
    "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
)
ARK_RESPONSES_URL = os.environ.get(
    "ARK_RESPONSES_URL",
    "https://ark.cn-beijing.volces.com/api/v3/responses",
)
PROMPT_FILE = _HERE / "prompts" / "task_planner_system_prompt.md.en"
QWEN_PROMPT_FILE = _HERE / "prompts" / "task_planner_system_prompt.qwen-small.md.en"
QWEN_PLANNER_URL = (
    os.environ.get("QWEN_PLANNER_URL") or "http://115.190.153.53:8090/chat"
).strip()
QWEN_PLANNER_MODEL = (os.environ.get("QWEN_PLANNER_MODEL") or "Qwen2.5-0.5B-Instruct").strip()
QWEN_PLANNER_TIMEOUT_SEC = float(os.environ.get("QWEN_PLANNER_TIMEOUT_SEC") or "180")


# DuerOS推送接口配置
DUEROS_PUSH_URL = "https://api.dueros.com/skill/v1/push"
SKILL_APP_ID = "25ca93b5-40b6-8ce7-8b37-78a03afb9606"
SKILL_ACCESS_TOKEN = "技能服务AccessToken" # DuerOS开发者后台获取


def _default_log_dir() -> Path:
    env = (os.environ.get("BRAIN_LOG_DIR") or "").strip()
    if env:
        return Path(env)
    parent_logs = _HERE.parent / "llm_logs"
    if _HERE.name == "server" and parent_logs.is_dir():
        return parent_logs
    return _HERE / "llm_logs"


LOG_DIR = _default_log_dir()


def init_brain_logger():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("brain")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if logger.handlers:
        return logger
    log_format = logging.Formatter(
        "%(asctime)s | %(levelname)s | thread:%(thread)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = TimedRotatingFileHandler(
        filename=str(LOG_DIR / "brain.log"),
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )
    file_handler.setFormatter(log_format)
    logger.addHandler(file_handler)
    return logger


def _attach_file_logger(name):
    other = logging.getLogger(name)
    other.setLevel(logging.INFO)
    other.propagate = False
    for handler in log.handlers:
        if handler not in other.handlers:
            other.addHandler(handler)


log = init_brain_logger()
llm_logger = log
_attach_file_logger("werkzeug")
_attach_file_logger("flask.app")
app.logger.handlers = list(log.handlers)
app.logger.setLevel(logging.INFO)
app.logger.propagate = False


# ====================== 文本清洗 & 缓存key生成 ======================
def clean_text(text: str) -> str:
    #text = re.sub(r"[^\u4e00-\u9fa5]", "", text)
    text = re.sub(r"[^\u4e00-\u9fa50-9]", "", text)
    drop_words = ["帮我", "给我", "麻烦", "能不能", "可以吗", "一下", "一份", "请给我", "请帮我"]
    for w in drop_words:
        text = text.replace(w, "")
    replace_dict = {"方案": "计划", "备赛": "训练", "慢跑": "轻松跑"}
    for old, new in replace_dict.items():
        text = text.replace(old, new)
    return text

def get_cache_key(raw_q: str, source: str = "", catalog_fingerprint: str = "") -> str:
    clean_q = clean_text(raw_q)
    fp = str(catalog_fingerprint or "").strip()
    md5_str = hashlib.md5(f"{source}|{clean_q}|{fp}".encode("utf-8")).hexdigest()
    return f"run_global:{md5_str}"

# Mock 缓存读写封装（替换真实Redis）
def get_cache(q, source="", *, catalog_fingerprint: str = ""):
    key = get_cache_key(q, source, catalog_fingerprint)
    item = mock_cache.get(key)
    if not item:
        return None
    # 判断缓存是否过期
    if time.time() > item["expire"]:
        del mock_cache[key]
        return None
    return item["data"]

def set_cache(q, ans, source="", *, catalog_fingerprint: str = ""):
    key = get_cache_key(q, source, catalog_fingerprint)
    expire_ts = time.time() + CACHE_TTL
    mock_cache[key] = {
        "data": ans,
        "expire": expire_ts
    }


_DELIVERY_CAPS = {"endpoint.present", "endpoint.feedback", "notify.speak"}
_DISPLAY_CAPS = {"display.photo", "display.slideshow"}
_SPOKEN_PRESENTATION_FIELDS = frozenset(
    {
        "time_text",
        "answer_text",
        "reply",
        "summary",
        "people",
        "state",
        "text",
        "status_text",
    }
)
WAKE_PLANNER = "voice.stream.wake"
WAKE_ECHO_CAPABILITY = "voicewakeup.echo"
_PRESENTATION_SCHEMA = {
    "type": "text | image | audio — audio means the user should hear the result spoken; the control plane turns that into an execution step on the issuing runtime",
    "from": "summary | answer_text | time_text | asset_ref | state — which execution field fills the payload",
    "channel": "iphone | kindle | android | speaker",
    "endpoint": "optional; only when the user/intent explicitly names a destination. Omit to use Input Source Affinity (default Response Target = Input Source). Never copy an Execution Target.",
    "text": "optional",
    "asset_ref": "optional AssetRef {asset_id, type, mime_type?} when from=asset_ref; never a URL or filesystem path",
    "audio_url": "optional",
}

# Planner-facing presentation fields (must match OUTPUT_SCHEMA; no extra keys).
_PLANNER_PRESENTATION_SCHEMA = {
    "type": "text | image | audio",
    "from": "optional execution field some plan step emits: time_text | answer_text | summary | state | status_text | asset_ref | …",
    "endpoint": "optional; only when the user explicitly names a destination; omit for Input Source Affinity",
}

_PLANNER_OUTPUT_SCHEMA = {
    "type": "object",
    "required": [
        "goal",
        "required_capabilities",
        "reason",
        "plan",
        "presentation",
        "missing_capabilities",
        "better_capabilities",
    ],
    "additionalProperties": False,
    "properties": {
        "goal": {"type": "string"},
        "required_capabilities": {
            "type": "array",
            "items": {"type": "string", "description": "capability_id copied from Available Capabilities"},
        },
        "reason": {"type": "string"},
        "plan": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["step", "capability", "input_constrict", "output_constrict", "execution_timing"],
                "additionalProperties": False,
                "properties": {
                    "step": {"type": "integer"},
                    "capability": {
                        "type": "string",
                        "description": "exact capability_id from a matching Available Capabilities row",
                    },
                    "input_constrict": {
                        "type": "object",
                        "description": "keys from that row's input_schema; $key references allowed",
                    },
                    "output_constrict": {
                        "type": "object",
                        "description": "keys this step exposes for later $key or presentation.from; value is {type, data_dest}",
                        "additionalProperties": {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string"},
                                "data_dest": {"type": "string", "enum": ["context"]},
                            },
                        },
                    },
                    "execution_timing": {
                        "type": "object",
                        "required": ["mode"],
                        "properties": {
                            "mode": {"type": "string", "enum": ["immediate", "delay", "interval", "cron"]},
                            "exec_time": {
                                "type": "integer",
                                "description": "Unix milliseconds for delay; from intent_base_time, not model time",
                            },
                            "first_exec_time": {
                                "type": "integer",
                                "description": "Unix milliseconds for interval/cron; from intent_base_time",
                            },
                            "interval_sec": {"type": "integer"},
                            "end_time": {"type": "integer"},
                            "count": {"type": "integer"},
                            "cron_expr": {"type": "string"},
                            "timezone": {"type": "string"},
                        },
                    },
                    "assigned_edge_id": {
                        "type": "string",
                        "description": "edge_id from the matching Available Capabilities row",
                    },
                },
            },
        },
        "presentation": {
            "type": "object",
            "required": ["type"],
            "additionalProperties": False,
            "properties": {
                "type": {"type": "string", "enum": ["text", "image", "audio"]},
                "from": {"type": "string"},
                "endpoint": {"type": "string"},
            },
        },
        "missing_capabilities": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["capability", "reason"],
                "properties": {
                    "capability": {"type": "string"},
                    "reason": {"type": "string"},
                },
            },
        },
        "better_capabilities": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["capability", "reason"],
                "properties": {
                    "capability": {"type": "string"},
                    "reason": {"type": "string"},
                },
            },
        },
    },
}


def _wake_ack_text() -> str:
    from voice_settings import get_wake_ack

    return get_wake_ack()


def _is_wake_ack_utterance(text):
    """True when the whole utterance is the wake reply — not a user intent."""
    from voice_settings import wake_ack_utterances

    compact = re.sub(r"[\s，。！？,.!?\"'“”‘’]", "", str(text or ""))
    return compact in wake_ack_utterances()


def _user_asked_tv(text):
    raw = str(text or "")
    keys = ("电视", "投屏", "投到", "chromecast", "Chromecast", "slideshow", "轮播")
    return any(k in raw for k in keys)


def _user_asked_photo(text):
    raw = str(text or "")
    keys = ("拍张", "拍照", "拍一张", "take_photo", "照相")
    return any(k in raw for k in keys)


def _intent_source_voice(intent) -> bool:
    return str((intent or {}).get("source") or "").strip().lower() == "voice"


def _user_asked_photo_count(text) -> bool:
    raw = str(text or "")
    if "照片" not in raw and "张" not in raw:
        return False
    return any(k in raw for k in ("多少", "几张", "几幅", "数量", "一共"))


def _user_asked_see_photo(text) -> bool:
    raw = str(text or "")
    if _user_asked_photo_count(raw):
        return False
    view_keys = ("看一下", "给我看", "看看", "显示", "瞧")
    photo_keys = ("照片", "图片", "那张", "这张")
    return any(v in raw for v in view_keys) and any(p in raw for p in photo_keys)


def _plan_wants_image_presentation(intent) -> bool:
    caps = _caps_in_plan(intent)
    if any(c in _DISPLAY_CAPS for c in caps):
        return True
    raw = intent.get("presentation")
    if isinstance(raw, dict) and str(raw.get("type") or "").strip().lower() == "image":
        return True
    text = str((intent or {}).get("text") or "")
    if _user_asked_tv(text):
        return True
    if _user_asked_see_photo(text):
        return True
    return False


def _voice_symmetric_presentation_kind(intent, kind: str, from_key: str) -> tuple[str, str]:
    """Voice in → spoken out: word-field delivery defaults to audio, not text."""
    pkind = str(kind or "").strip().lower()
    if pkind != "text":
        return pkind, from_key
    if not _intent_source_voice(intent):
        return pkind, from_key
    if _plan_wants_image_presentation(intent):
        return pkind, from_key
    fk = str(from_key or "").strip()
    if not fk or fk in _SPOKEN_PRESENTATION_FIELDS:
        return "audio", from_key
    return pkind, from_key


def _speak_delivery_text(intent):
    pres = intent.get("presentation") if isinstance(intent.get("presentation"), dict) else {}
    text = str(pres.get("text") or "").strip()
    if text:
        return text
    ctx = intent.get("ctx_param") or intent.get("context") or {}
    if not isinstance(ctx, dict):
        return ""
    for key in ("time_text", "answer_text", "summary", "state"):
        val = str(ctx.get(key) or "").strip()
        if val:
            return val
    return ""


def _edges_snapshot():
    """Copy of Runtime edge cache — heartbeats rebuild `_EDGES` concurrently."""
    return dict(_EDGES or {})


def _services_snapshot():
    """Copy of service map — rebuilt on heartbeat while planners iterate."""
    return dict(services_registered_mapping or {})


def _tts_delivery_edge_id():
    """System-policy TTS edge only (`PRESENTATION_TTS_EDGE_ID`).

    Do not pick an unrelated speaker just because it advertised notify.speak —
    that would break Input Source Affinity (iPhone in, living-room speaker out).
    """
    if not _EDGES:
        rebuild_capability_maps()
    explicit = (os.environ.get("PRESENTATION_TTS_EDGE_ID") or "").strip()
    if not explicit:
        return None
    for eid, view in _edges_snapshot().items():
        if not isinstance(view, dict):
            continue
        if str(eid) != explicit:
            continue
        if str(view.get("online_status") or "").lower() != "online":
            return None
        if view.get("schedule_eligible") is False:
            return None
        ok, _reason = can_participate(str(eid), capability="notify.speak", rec=view)
        return explicit if ok else None
    return None


def _planner_wants_speak(intent):
    """Spoken delivery is a planner Presentation decision (type=audio), not keywords."""
    planned = _normalize_presentation_plan(intent.get("presentation"))
    if planned.get("type") == "audio":
        return True
    return planned.get("channel") == "speaker"


def _maybe_attach_speak_delivery(intent):
    """Spoken delivery is a notify.speak plan step. Runtime executes it; no hook."""
    return


def _people_count_text(people):
    raw = people
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            return ""
    if not isinstance(raw, list) or not raw:
        return ""
    total = 0
    for item in raw:
        if isinstance(item, dict):
            try:
                total += int(item.get("count") or 1)
            except (TypeError, ValueError):
                total += 1
        else:
            total += 1
    return f"{total}个人"


def _endpoint_supported_types(rec):
    types = []
    raw = rec.get("endpoints") if isinstance(rec, dict) else None
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                for t in (
                    item.get("supported")
                    or item.get("types")
                    or item.get("supported_presentation")
                    or []
                ):
                    types.append(str(t))
                kind = item.get("type") or item.get("channel")
                if kind:
                    kind_s = str(kind)
                    if kind_s not in types:
                        types.append(kind_s)
                    # Functional display endpoint implies image/text presentation.
                    if kind_s == "display":
                        for implied in ("image", "text"):
                            if implied not in types:
                                types.append(implied)
            elif item:
                types.append(str(item))
    return types or ["text", "image"]


def _endpoint_ids_for_participant(rec, pres_type=None):
    """Stable endpoint_id values declared on a participant (Endpoint role)."""
    ids = []
    raw = rec.get("endpoints") if isinstance(rec, dict) else None
    if not isinstance(raw, list):
        return ids
    want = str(pres_type or "").strip().lower()
    for item in raw:
        if not isinstance(item, dict):
            continue
        eid = str(item.get("endpoint_id") or item.get("id") or "").strip()
        if not eid:
            continue
        if want:
            supported = [
                str(t).lower()
                for t in (
                    item.get("supported")
                    or item.get("types")
                    or item.get("supported_presentation")
                    or []
                )
            ]
            kind = str(item.get("type") or item.get("channel") or "").lower()
            if kind == "display" and want in ("image", "text", "video", "html", "audio"):
                ids.append(eid)
                continue
            if supported and want not in supported and want != kind:
                continue
        ids.append(eid)
    return ids


def _primary_endpoint_id(rec, pres_type=None):
    ids = _endpoint_ids_for_participant(rec, pres_type)
    return ids[0] if ids else ""


def _ncm_play_issuer_id(intent):
    """Intent Source participant for ncm_plays (not the Mac executor)."""
    intent = intent or {}
    ctx = intent.get("ctx_param") or intent.get("context") or {}
    if not isinstance(ctx, dict):
        ctx = {}
    src = ctx.get("source_context") or intent.get("source_context") or {}
    if isinstance(src, dict):
        for key in ("input_participant_id", "device_id"):
            pid = str(src.get(key) or "").strip()
            if pid:
                return pid
    return str(intent.get("edge_id") or intent.get("participant_id") or "").strip()


def _issuer_participant_id(intent):
    intent = intent or {}
    return str(intent.get("edge_id") or intent.get("participant_id") or "").strip()


def _is_endpoint_participant(rec):
    if not isinstance(rec, dict) or not rec:
        return False
    if rec.get("role_endpoint"):
        return True
    return "endpoint" in (rec.get("roles") or [])


def _declared_role(rec, role):
    role = str(role or "").strip()
    if not rec or not role:
        return False
    if rec.get(f"role_{role}"):
        return True
    return role in (rec.get("roles") or [])


def _declared_capability(rec, capability_id):
    want = str(capability_id or "").strip()
    if not rec or not want:
        return False
    for cap in _runtime_capabilities(rec):
        if cap.get("capability_id") == want:
            return True
    return False


def _participant_snapshot(pid, rec=None):
    pid = str(pid or "").strip()
    base = dict(rec) if isinstance(rec, dict) and rec else (brain_db.get_registration(pid) or {})
    beat = (brain_db.list_heartbeats().get(pid) or {})
    merged = dict(base)
    merged.update(beat)
    return merged


def _role_is_online(pid, rec, role):
    """Intent Source / Endpoint 用 5 分钟心跳窗；Runtime 用 30s online。"""
    if role in ("intent_source", "endpoint", "observer"):
        return _endpoint_is_live(pid, rec)
    view = _edge_public_view(dict(rec or {}))
    return str(view.get("online_status") or "").lower() == "online"


def _load_control_policy_index():
    """Soft dep: cloud db.py may not have control-policy APIs yet (@dba)."""
    fn = getattr(brain_db, "load_control_policy_index", None)
    if not callable(fn):
        return {}
    try:
        return fn() or {}
    except (sqlite3.OperationalError, AttributeError, TypeError):
        return {}


def _control_policy_allows(pid, kind, name, *, index=None):
    fn = getattr(brain_db, "control_policy_allows", None)
    if not callable(fn):
        return True
    try:
        return bool(fn(pid, kind, name, index=index))
    except (sqlite3.OperationalError, AttributeError, TypeError):
        return True


def _exposure_policy_allows(rec, capability_id):
    """P0 Capability Exposure Policy: runtime declares per-domain exposure.
    `exposure_policy` is {lan:[cap...], cloud:[cap...]} on the participant.
    No policy (None / missing / empty) = open by default (backward compatible).
    """
    cap = str(capability_id or "").strip()
    if not cap:
        return True
    policy = rec.get("exposure_policy") if isinstance(rec, dict) else None
    if not isinstance(policy, dict) or not policy:
        return True
    domain = str(rec.get("domain") or instance_intent_origin() or "").strip().lower()
    if not domain:
        return True
    allowed = policy.get(domain)
    if allowed is None:
        # domain not enumerated in policy → default open
        return True
    if not isinstance(allowed, (list, tuple)):
        return True
    return cap in {str(c or "").strip() for c in allowed}


def can_participate(pid, *, role=None, capability=None, rec=None, policy_index=None):
    """节点能否参与调度。三条全要满足：

    1. 管理员允许；没有干涉（无策略行）则跳过
    2. 当前在线
    3. 节点自己声明了该 Role 或 capability
    """
    pid = str(pid or "").strip()
    if not pid:
        return False, "unknown"
    snap = _participant_snapshot(pid, rec)
    index = policy_index if policy_index is not None else _load_control_policy_index()
    cap = str(capability or "").strip()
    role_name = str(role or "").strip()
    if cap:
        role_name = "runtime"
    if not role_name:
        return False, "unknown"
    if cap:
        if not _control_policy_allows(pid, "role", "runtime", index=index):
            return False, "admin_denied"
        if not _control_policy_allows(pid, "capability", cap, index=index):
            return False, "admin_denied"
    else:
        if not _control_policy_allows(pid, "role", role_name, index=index):
            return False, "admin_denied"
    if not _role_is_online(pid, snap, role_name):
        return False, "offline"
    if cap:
        if not _declared_capability(snap, cap):
            return False, "not_declared"
        if not _exposure_policy_allows(snap, cap):
            return False, "not_exposed"
    elif not _declared_role(snap, role_name):
        return False, "not_declared"
    return True, "ok"


def _list_endpoint_participants():
    out = []
    try:
        pids = brain_db.registration_ids()
        policy = _load_control_policy_index()
    except sqlite3.OperationalError:
        return []
    for pid in pids:
        rec = _participant_snapshot(pid)
        ok, _reason = can_participate(
            pid, role="endpoint", rec=rec, policy_index=policy
        )
        if ok:
            out.append((pid, rec))
    return out


def _endpoint_supports_type(rec, pres_type):
    if not pres_type:
        return True
    types = [str(t).lower() for t in _endpoint_supported_types(rec)]
    return str(pres_type).lower() in types


def _endpoint_received_at(pid, rec=None):
    rec = rec if isinstance(rec, dict) else {}
    received = rec.get("server_received_at")
    if received is None:
        stored = brain_db.get_registration(pid) or {}
        received = stored.get("server_received_at")
    if received is None:
        received = (brain_db.list_heartbeats().get(pid) or {}).get("server_received_at")
    if received is None:
        return None
    return float(received)


def _endpoint_is_live(pid, rec=None, now=None):
    received = _endpoint_received_at(pid, rec)
    if received is None:
        return False
    now = time.time() if now is None else now
    return (now - received) <= ENDPOINT_TTL_SEC


def _participant_is_registered(pid):
    pid = str(pid or "").strip()
    if not pid:
        return False
    if pid in _REGISTERED_edges:
        return True
    return brain_db.get_registration(pid) is not None


def _participant_schedule_eligible(pid):
    info = (brain_db.list_heartbeats().get(pid) or {})
    return info.get("schedule_eligible") is not False


def _issuer_post_reject(participant_id):
    """Reject POST/GET /intent unless the issuer may participate as Intent Source."""
    pid = str(participant_id or "").strip()
    if not pid:
        return (
            jsonify(
                ok=False,
                error="participant_id is required; register and heartbeat first",
            ),
            400,
        )
    if not _participant_is_registered(pid):
        return (
            jsonify(ok=False, error="unknown participant_id; register first"),
            401,
        )
    rec = _participant_snapshot(pid)
    ok, reason = can_participate(pid, role="intent_source", rec=rec)
    if not ok:
        if reason == "not_declared":
            return (
                jsonify(
                    ok=False,
                    error="participant did not declare intent_source; cannot post intent",
                ),
                403,
            )
        if reason == "admin_denied":
            return (
                jsonify(
                    ok=False,
                    error="intent_source role disabled by admin; cannot post intent",
                ),
                403,
            )
        return (
            jsonify(
                ok=False,
                error="participant heartbeat required; heartbeat before posting intent",
            ),
            403,
        )
    if not _participant_schedule_eligible(pid):
        return (
            jsonify(
                ok=False,
                error="participant not schedule_eligible; fix clock and heartbeat",
            ),
            403,
        )
    return None


def _voice_stream_wake_reject(participant_id):
    """Reject POST /voice/wake unless the issuer advertises live voice.stream."""
    pid = str(participant_id or "").strip()
    if not pid:
        return (
            jsonify(
                ok=False,
                error="participant_id is required; only voice.stream may post wake",
            ),
            400,
        )
    if not _participant_is_registered(pid):
        return (
            jsonify(ok=False, error="unknown participant_id; register first"),
            401,
        )
    rec = _participant_snapshot(pid)
    ok, reason = can_participate(pid, capability="voice.stream", rec=rec)
    if not ok:
        if reason == "not_declared":
            return (
                jsonify(
                    ok=False,
                    error="participant has no voice.stream; wake API is only for that input capability",
                ),
                403,
            )
        if reason == "admin_denied":
            return (
                jsonify(
                    ok=False,
                    error="voice.stream disabled by admin; cannot post wake",
                ),
                403,
            )
        return (
            jsonify(
                ok=False,
                error="participant heartbeat required; heartbeat before posting wake",
            ),
            403,
        )
    if not _participant_schedule_eligible(pid):
        return (
            jsonify(
                ok=False,
                error="participant not schedule_eligible; fix clock and heartbeat",
            ),
            403,
        )
    return None


def _issuer_has_notify_speak(pid):
    rec = _participant_snapshot(pid)
    ok, _reason = can_participate(pid, capability="notify.speak", rec=rec)
    return ok


def _issuer_has_wake_echo(pid):
    rec = _participant_snapshot(pid)
    ok, _reason = can_participate(pid, capability=WAKE_ECHO_CAPABILITY, rec=rec)
    return ok


def _notify_speak_plan_step(issuer_id, text, step=1):
    """One execution_plan step: notify.speak on the issuing edge."""
    return {
        "step": int(step),
        "capability": "notify.speak",
        "assigned_edge_id": str(issuer_id or "").strip(),
        "input_constrict": {"text": text},
        "output_constrict": {},
    }


def _wake_echo_plan_step(issuer_id, text, step=1):
    """Wake fast-path: voicewakeup.echo on the issuing voice.stream edge."""
    return {
        "step": int(step),
        "capability": WAKE_ECHO_CAPABILITY,
        "assigned_edge_id": str(issuer_id or "").strip(),
        "input_constrict": {"text": text},
        "output_constrict": {
            "echo_text": {"type": "string", "data_dest": "context"},
        },
    }


_SOURCE_INPUT_CAPABILITY = {
    "voice": "voice.input",
    "visual": "visual.input",
    "text": "text.input",
}
_SOURCE_INPUT_ENDPOINT = {
    "voice": "microphone",
    "visual": "camera",
    "text": "keyboard",
}


def _build_source_context(edge_id, source, inbound=None):
    """Persist Input Source Context on the intent (device / endpoint / capability)."""
    inbound = inbound if isinstance(inbound, dict) else {}
    raw = inbound.get("source_context") if isinstance(inbound.get("source_context"), dict) else {}
    source_l = str(source or "text").strip().lower() or "text"
    device_id = str(raw.get("device_id") or edge_id or "").strip()
    endpoint_id = str(raw.get("endpoint_id") or inbound.get("source_id") or "").strip()
    if not endpoint_id:
        endpoint_id = _SOURCE_INPUT_ENDPOINT.get(source_l, "keyboard")
    capability_id = str(raw.get("capability_id") or "").strip()
    if not capability_id:
        capability_id = _SOURCE_INPUT_CAPABILITY.get(source_l, "text.input")
    out = {}
    if device_id:
        out["device_id"] = device_id
    if endpoint_id:
        out["endpoint_id"] = endpoint_id
    if capability_id:
        out["capability_id"] = capability_id
    return out


def _resolve_endpoint_token(token, listed, listed_map):
    token = str(token or "").strip()
    if not token:
        return ""
    if token in listed_map:
        return token
    for pid, rec in listed:
        if _primary_endpoint_id(rec) == token:
            return pid
        raw = rec.get("endpoints") if isinstance(rec, dict) else None
        if not isinstance(raw, list):
            continue
        for item in raw:
            if not isinstance(item, dict):
                continue
            eid = str(item.get("endpoint_id") or item.get("id") or "").strip()
            if eid == token:
                return pid
    return ""


def _tv_response_participant(listed):
    for pid, rec in listed:
        dt = str((rec or {}).get("device_type") or "").lower()
        if dt in ("chromecast", "tv", "google_tv", "cast"):
            return pid
        raw = (rec or {}).get("endpoints") if isinstance(rec, dict) else None
        if not isinstance(raw, list):
            continue
        for item in raw:
            if not isinstance(item, dict):
                continue
            blob = " ".join(
                str(item.get(k) or "")
                for k in ("endpoint_id", "id", "type", "channel")
            ).lower()
            if any(mark in blob for mark in ("chromecast", "living_room_tv", "living-room-tv")):
                return pid
            if "tv" in blob.split() or blob.endswith(".tv") or blob.startswith("tv"):
                return pid
    return ""


def _explicit_response_participant(intent):
    """①②③: Intent / user / context named a Response Target. Not Execution Target."""
    intent = intent or {}
    listed = _list_endpoint_participants()
    listed_map = {pid: rec for pid, rec in listed}
    pres = intent.get("presentation") if isinstance(intent.get("presentation"), dict) else {}
    ctx = intent.get("ctx_param") if isinstance(intent.get("ctx_param"), dict) else {}
    tokens = [
        pres.get("endpoint"),
        pres.get("endpoint_id"),
        intent.get("output_target"),
        intent.get("response_target"),
    ]
    affinity = intent.get("output_affinity")
    if not isinstance(affinity, dict):
        affinity = ctx.get("output_affinity") if isinstance(ctx.get("output_affinity"), dict) else None
    if isinstance(affinity, dict):
        reason = str(affinity.get("reason") or "").strip()
        if reason and reason not in ("input_source", "source_affinity"):
            tokens.append(affinity.get("participant_id"))
    for tok in tokens:
        pid = _resolve_endpoint_token(tok, listed, listed_map)
        if pid:
            return pid
    if _user_asked_tv(intent.get("text")):
        return _tv_response_participant(listed)
    return ""


def _capability_output_fields(cid):
    """Declared output keys for a capability: wire catalog plus live ads."""
    names = set()
    cid = str(cid or "").strip()
    if not cid:
        return names
    try:
        from edge_services import KNOWN_CAPABILITIES
    except ImportError:  # pragma: no cover
        from server.edge_services import KNOWN_CAPABILITIES  # type: ignore
    spec = KNOWN_CAPABILITIES.get(cid) or {}
    schema = spec.get("output_schema") or {}
    if isinstance(schema, dict):
        names.update(str(k) for k in schema)
    for row in _list_schedulable_capabilities(capability_id=cid):
        live = row.get("output_schema") or {}
        if isinstance(live, dict):
            names.update(str(k) for k in live)
    return names


def _plan_emits_field(plan, field):
    """True if some non-speak step in the plan produces this context field."""
    key = str(field or "").strip().lstrip("$")
    if not key:
        return False
    for step in plan or []:
        if not isinstance(step, dict):
            continue
        cap = str(step.get("capability") or "").strip()
        if not cap or cap in ("notify.speak", WAKE_ECHO_CAPABILITY):
            continue
        out = step.get("output_constrict") or {}
        if isinstance(out, dict) and (key in out or f"${key}" in out):
            return True
        if key in _capability_output_fields(cap):
            return True
    return False


def _speak_text_token(step):
    ic = step.get("input_constrict") if isinstance(step.get("input_constrict"), dict) else {}
    return str(ic.get("text") or "").strip()


def _drop_unproducible_speak_steps(plan):
    """LLM often adds notify.speak $answer_text even when no step emits it (music.play)."""
    steps = [dict(s) for s in (plan or []) if isinstance(s, dict)]
    producers = [
        s
        for s in steps
        if str(s.get("capability") or "").strip()
        not in ("notify.speak", WAKE_ECHO_CAPABILITY)
    ]
    kept = []
    for step in steps:
        cap = str(step.get("capability") or "").strip()
        if cap == "notify.speak":
            token = _speak_text_token(step)
            if token.startswith("$") and not _plan_emits_field(producers, token):
                continue
        kept.append(step)
    for idx, step in enumerate(kept, start=1):
        step["step"] = idx
    return kept


def _append_issuer_speak_step(intent, plan):
    """Default voice presentation: notify.speak on the issuing edge, visible in execution_plan."""
    plan = _drop_unproducible_speak_steps(plan)
    if any(
        str(s.get("capability") or "").strip() in ("notify.speak", WAKE_ECHO_CAPABILITY)
        for s in plan
    ):
        return plan
    source = str((intent or {}).get("source") or "").strip().lower()
    pres = (intent or {}).get("presentation")
    if not isinstance(pres, dict):
        pres = {}
    ptype = str(pres.get("type") or "").strip().lower()
    if ptype == "image":
        return plan
    if source != "voice" and ptype != "audio":
        return plan
    explicit = _explicit_response_participant(intent)
    issuer = _issuer_participant_id(intent)
    target = ""
    if explicit and _issuer_has_notify_speak(explicit):
        target = explicit
    elif issuer and _issuer_has_notify_speak(issuer):
        target = issuer
    else:
        target = str(_tts_delivery_edge_id() or "").strip()
    if not target:
        return plan
    from_key = str(pres.get("from") or "").strip()
    if from_key and not _plan_emits_field(plan, from_key):
        from_key = ""
    if not from_key:
        scratch = dict(intent or {})
        scratch["execution_plan"] = plan
        kind, from_key = _presentation_kind_from_plan(scratch)
        from_key = str(from_key or "").strip()
        if kind == "image":
            return plan
    if not from_key or from_key == "asset_ref":
        return plan
    if not _plan_emits_field(plan, from_key):
        return plan
    text = from_key if from_key.startswith("$") else f"${from_key}"
    plan.append(_notify_speak_plan_step(target, text, step=len(plan) + 1))
    return plan


def _commit_voice_wake_plan(intent_id, issuer_id):
    """Fast-path understand: commit a normal intent whose plan is voicewakeup.echo."""
    pid = str(issuer_id or "").strip()
    if not _issuer_has_wake_echo(pid):
        msg = f"唤醒应答失败：发起端 {pid} 没有在线的 {WAKE_ECHO_CAPABILITY}"
        mark_intent_failed(intent_id, msg)
        return False, msg
    plan = [_wake_echo_plan_step(pid, _wake_ack_text(), step=1)]
    intent = get_intent(intent_id)
    if not intent:
        return False, "intent not exist"
    ctx = dict(intent.get("ctx_param") or intent.get("context") or {})
    ctx["wake_ack"] = True
    intent["ctx_param"] = ctx
    intent["context"] = ctx
    intent["execution_plan"] = plan
    intent.pop("presentation", None)
    _save_intent(intent)
    update_intent_status(intent_id, "intent_parsed")
    return True, None


def _match_endpoint_participant(intent, pres_type=None):
    """Pick the Presentation Response Target.

    Priority (Input–Output symmetry): explicit Intent/user/context target,
    then Input Source Affinity, then the newest live Endpoint that can render
    this type. Never copy an Execution Target (the edge that ran a capability).
    """
    listed = _list_endpoint_participants()
    listed_map = {pid: rec for pid, rec in listed}

    def _supports(pid):
        rec = listed_map.get(pid)
        if rec and _endpoint_supports_type(rec, pres_type):
            return True
        # Audio is spoken delivery of words. A display Endpoint that can show
        # text still has Source Affinity (the phone pulls presentation.text).
        if str(pres_type or "").lower() == "audio" and rec and _endpoint_supports_type(
            rec, "text"
        ):
            return True
        return False

    explicit = _explicit_response_participant(intent)
    if explicit and _supports(explicit):
        return explicit
    issuer = _issuer_participant_id(intent)
    if issuer and _supports(issuer):
        return issuer
    now = time.time()
    live = []
    for pid, rec in listed:
        if not _supports(pid):
            continue
        if not _endpoint_is_live(pid, rec, now=now):
            continue
        live.append((_endpoint_received_at(pid, rec), pid))
    if not live:
        return ""
    live.sort(key=lambda row: row[0], reverse=True)
    return live[0][1]


def _stamp_presentation_endpoint(pres, intent):
    if not isinstance(pres, dict):
        return pres
    out = dict(pres)
    # Boss: never leave URL identity on Presentation.
    for banned in ("image_url", "photo_url", "audio_url", "video_url"):
        out.pop(banned, None)
    pid = _match_endpoint_participant(intent, out.get("type"))
    out["endpoint"] = pid  # participant_id (compat)
    rec = brain_db.get_registration(pid) or {} if pid else {}
    if not rec and pid:
        rec = _participant_snapshot(pid)
    eid = _primary_endpoint_id(rec, out.get("type")) if rec else ""
    if eid:
        out["endpoint_id"] = eid
    elif pid:
        # Fallback: participant_id still addressable; prefer nested endpoint_id when declared.
        out["endpoint_id"] = pid
    else:
        out["endpoint_id"] = ""
    out["channel"] = _channel_for_participant(pid, intent)
    return out


def _channel_for_participant(pid, intent=None):
    if pid:
        rec = brain_db.get_registration(pid) or {}
        types = _endpoint_supported_types(rec)
        if rec.get("device_type") in ("iphone", "ios"):
            return "iphone"
        if rec.get("device_type") == "kindle":
            return "kindle"
        if rec.get("device_type") == "android":
            return "android"
        dt = str(rec.get("device_type") or "")
        if dt:
            return dt
        if "image" in types or "text" in types:
            return "iphone"
    if str((intent or {}).get("source") or "") == "voice":
        return "iphone"
    return "iphone"


def _presentation_channel(intent):
    matched = _match_endpoint_participant(intent)
    return _channel_for_participant(matched or _issuer_participant_id(intent), intent)


def _endpoint_registry(intent):
    """Registry view: functional Endpoints (type/capability), not vendor names."""
    out = []
    for pid, rec in _list_endpoint_participants():
        endpoints = []
        raw = rec.get("endpoints") if isinstance(rec, dict) else None
        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                eid = str(item.get("endpoint_id") or item.get("id") or "").strip()
                if not eid:
                    continue
                kind = str(item.get("type") or item.get("channel") or "display").strip() or "display"
                supported = item.get("supported") or item.get("types") or item.get("supported_presentation") or []
                endpoints.append(
                    {
                        "endpoint_id": eid,
                        "device_id": pid,
                        "type": kind,
                        "supported_presentation": list(supported) if isinstance(supported, list) else [],
                        "availability": "online" if _endpoint_is_live(pid, rec) else "offline",
                    }
                )
        out.append(
            {
                "participant_id": pid,
                "channel": _channel_for_participant(pid, intent),
                "supported_types": _endpoint_supported_types(rec),
                "endpoints": endpoints or (rec.get("endpoints") or []),
            }
        )
    return out


def _match_runtime_for_capability(capability_id, *, location=None):
    """Pick an online Runtime participant that advertises capability_id (no vendor branching)."""
    want = str(capability_id or "").strip()
    if not want:
        return ""
    loc = str(location or "").strip().lower()
    rebuild_capability_maps()
    candidates = []
    for edge_id, view in _edges_snapshot().items():
        if not _declared_capability(view, want):
            continue
        if not _role_is_online(edge_id, view, "runtime"):
            continue
        if loc:
            room = str(
                (view.get("location") or {}).get("room")
                if isinstance(view.get("location"), dict)
                else view.get("location") or view.get("room") or ""
            ).strip().lower()
            if room and room != loc and loc not in room:
                continue
        received = float(view.get("server_received_at") or view.get("reported_at") or 0)
        candidates.append((received, edge_id))
    if not candidates:
        return ""
    candidates.sort(key=lambda row: row[0], reverse=True)
    return candidates[0][1]


def _world_state_nodes():
    rebuild_capability_maps()
    nodes = []
    try:
        policy = _load_control_policy_index()
    except sqlite3.OperationalError:
        policy = {}
    for edge_id, view in _edges_snapshot().items():
        caps = []
        for svc in view.get("services") or []:
            if not isinstance(svc, dict):
                continue
            for cap in svc.get("capabilities") or []:
                if not isinstance(cap, dict) or not cap.get("capability_id"):
                    continue
                cid = str(cap.get("capability_id") or "")
                ok, _reason = can_participate(
                    edge_id, capability=cid, rec=view, policy_index=policy
                )
                if ok:
                    caps.append(cid)
        roles = [
            role
            for role in (view.get("roles") or [])
            if can_participate(
                edge_id, role=role, rec=view, policy_index=policy
            )[0]
        ]
        endpoint_ok, _ = can_participate(
            edge_id, role="endpoint", rec=view, policy_index=policy
        )
        nodes.append(
            {
                "participant_id": edge_id,
                "display_name": view.get("display_name"),
                "device_type": view.get("device_type"),
                "roles": roles,
                "online_status": view.get("online_status"),
                "schedule_eligible": view.get("schedule_eligible"),
                "capabilities": caps,
                "endpoints": view.get("endpoints") if endpoint_ok else [],
            }
        )
    return nodes


def _user_asked_generated_image(text):
    raw = str(text or "")
    keys = (
        "图片",
        "来张",
        "画一张",
        "画张",
        "出图",
        "配图",
        "生成图",
        "生图",
        "一张图",
        "photo",
        "picture",
        "image",
    )
    if any(k in raw for k in keys):
        return True
    lower = raw.lower()
    return "generate" in lower and "image" in lower


def _query_keeps_image_goal(query, intent_text):
    q = str(query or "")
    if _user_asked_generated_image(q) or _user_asked_tv(q):
        return True
    # Same full sentence (or longer paraphrase) already carries the goal.
    return bool(intent_text) and intent_text in q


def _repair_stripped_query_inputs(plan, intent=None):
    """If planner stripped query to a topic noun, restore full intent text.

    Downstream only sees this step's inputs; bare topics cause refuse-without-image.
    Also set want_image=true when this step expects asset_ref and the user asked
    for a picture / TV cast (Edge force-draws even if the text model refuses).
    """
    text = str((intent or {}).get("text") or "").strip()
    if not text:
        return plan
    wants_pic = _user_asked_generated_image(text) or _user_asked_tv(text)
    if not wants_pic:
        return plan
    repaired = []
    for step in plan or []:
        if not isinstance(step, dict):
            repaired.append(step)
            continue
        s = dict(step)
        ic = s.get("input_constrict")
        oc = s.get("output_constrict")
        if not isinstance(ic, dict) or "query" not in ic:
            repaired.append(s)
            continue
        expects_image = isinstance(oc, dict) and (
            "asset_ref" in oc or "image_ref" in oc or "capture_ref" in oc
        )
        if not expects_image:
            repaired.append(s)
            continue
        new_ic = dict(ic)
        q = str(new_ic.get("query") or "").strip()
        if not q or not _query_keeps_image_goal(q, text):
            new_ic["query"] = text
        if str(new_ic.get("want_image") or "").strip().lower() not in (
            "1",
            "true",
            "yes",
            "on",
        ):
            new_ic["want_image"] = "true"
        s["input_constrict"] = new_ic
        repaired.append(s)
    return repaired


_LEGACY_ASSET_ALIAS = {
    "image_ref": "asset_ref",
    "photo_url": "asset_ref",
}


def _rewrite_asset_token(value):
    """Map legacy $image_ref tokens to $asset_ref. $capture_ref is a local inbox handle, not an Asset."""
    if not isinstance(value, str):
        return value
    raw = value.strip()
    if not raw.startswith("$"):
        return value
    key = raw[1:].strip()
    mapped = _LEGACY_ASSET_ALIAS.get(key)
    if mapped:
        return "$" + mapped
    return value


def _normalize_plan_asset_refs(plan):
    """Force step I/O identity: image_ref/photo_url → asset_ref. Keep capture_ref."""
    out = []
    for step in plan or []:
        if not isinstance(step, dict):
            out.append(step)
            continue
        s = dict(step)
        ic = s.get("input_constrict")
        if isinstance(ic, dict):
            new_ic = {}
            for k, v in ic.items():
                nk = _LEGACY_ASSET_ALIAS.get(str(k), str(k))
                new_ic[nk] = _rewrite_asset_token(v)
            s["input_constrict"] = new_ic
        oc = s.get("output_constrict")
        if isinstance(oc, dict):
            new_oc = {}
            for k, v in oc.items():
                nk = _LEGACY_ASSET_ALIAS.get(str(k), str(k))
                if isinstance(v, dict):
                    new_oc[nk] = dict(v)
                else:
                    new_oc[nk] = v
            s["output_constrict"] = new_oc
        out.append(s)
    return out


def sanitize_execution_plan(plan, intent=None):
    """Strip delivery-as-capability and TV display unless the user asked for TV."""
    text = str((intent or {}).get("text") or "")
    asked_tv = _user_asked_tv(text)
    asked_photo = _user_asked_photo(text)
    cleaned = []
    for step in plan or []:
        if not isinstance(step, dict):
            continue
        cap = str(step.get("capability") or "").strip()
        if not cap:
            continue
        if cap in _DELIVERY_CAPS:
            continue
        if cap in _DISPLAY_CAPS and not asked_tv:
            continue
        cleaned.append(dict(step))
    has_capture = any(
        str(s.get("capability") or "") in ("camera.capture", "camera.capture_and_upload")
        for s in cleaned
    )
    if asked_photo and not asked_tv:
        drop = {"notify.speak", "query.content"}
        if not has_capture:
            drop.add("vision.ask")
        cleaned = [s for s in cleaned if str(s.get("capability") or "") not in drop]
    cleaned = _normalize_plan_asset_refs(cleaned)
    cleaned = _repair_stripped_query_inputs(cleaned, intent)
    cleaned = _fold_capture_upload_composite(cleaned)
    for idx, step in enumerate(cleaned, start=1):
        step["step"] = idx
    return cleaned


def _prepare_shortcut_execution_plan(plan, intent=None):
    """Shortcut plans are pre-built; do not strip notify.speak like LLM sanitize."""
    steps = []
    for step in plan or []:
        if not isinstance(step, dict):
            continue
        cap = str(step.get("capability") or "").strip()
        if not cap:
            continue
        steps.append(dict(step))
    steps = _normalize_plan_asset_refs(steps)
    steps = _repair_stripped_query_inputs(steps, intent)
    steps = _fold_capture_upload_composite(steps)
    for idx, step in enumerate(steps, start=1):
        step["step"] = idx
    return steps


_COMPOSITE_CAPTURE_UPLOAD = "camera.capture_and_upload"


def _step_uses_capture_ref_token(step) -> bool:
    ic = (step or {}).get("input_constrict")
    if not isinstance(ic, dict):
        return False
    return str(ic.get("capture_ref") or "").strip() == "$capture_ref"


def _fold_capture_upload_composite(plan):
    """Merge consecutive capture + upload($capture_ref) into one composite step.

    capture_ref is Runtime-local and cannot cross edges. Brain schedules the
    composite as a whole; Runtime expands it.
    """
    rows = [dict(s) for s in (plan or []) if isinstance(s, dict)]
    if not rows:
        return rows
    out = []
    i = 0
    while i < len(rows):
        cur = rows[i]
        nxt = rows[i + 1] if i + 1 < len(rows) else None
        cap = str(cur.get("capability") or "").strip()
        nxt_cap = str((nxt or {}).get("capability") or "").strip()
        if (
            cap == "camera.capture"
            and nxt_cap == "asset.upload"
            and _step_uses_capture_ref_token(nxt)
        ):
            providers = {
                str(row.get("edge_id") or "").strip()
                for row in online_capability_providers(_COMPOSITE_CAPTURE_UPLOAD)
            }
            providers.discard("")
            if not providers:
                out.append(cur)
                i += 1
                continue
            dest = {}
            ic = nxt.get("input_constrict")
            if isinstance(ic, dict):
                dest_val = ic.get("dest") or ic.get("upload_dest")
                if dest_val not in (None, "", "$capture_ref"):
                    dest["dest"] = dest_val
            oc = nxt.get("output_constrict")
            if not isinstance(oc, dict) or not oc:
                oc = {"asset_ref": {"type": "string", "data_dest": "context"}}
            merged = {
                "step": cur.get("step"),
                "capability": _COMPOSITE_CAPTURE_UPLOAD,
                "input_constrict": dest,
                "output_constrict": oc,
            }
            timing = cur.get("execution_timing") or (nxt or {}).get("execution_timing")
            if timing:
                merged["execution_timing"] = timing
            edge = str(cur.get("assigned_edge_id") or "").strip()
            nxt_edge = str((nxt or {}).get("assigned_edge_id") or "").strip()
            if edge and edge in providers:
                merged["assigned_edge_id"] = edge
            elif nxt_edge and nxt_edge in providers:
                merged["assigned_edge_id"] = nxt_edge
            elif len(providers) == 1:
                merged["assigned_edge_id"] = next(iter(providers))
            out.append(merged)
            i += 2
            continue
        out.append(cur)
        i += 1
    return out


def extract_llm_output(llm_answer):
    if not llm_answer:
        return {}
    try:
        output = json.loads(llm_answer) if isinstance(llm_answer, str) else llm_answer
    except (TypeError, ValueError):
        return {}
    return output if isinstance(output, dict) else {}


def extract_llm_output_relaxed(llm_answer):
    """Qwen shadow only: strip fences / leading junk. Doubao path stays strict."""
    got = extract_llm_output(llm_answer)
    if got:
        return got
    text = str(llm_answer or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, count=1, flags=re.IGNORECASE)
        text = re.sub(r"\s*```\s*$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        output = json.loads(text[start : end + 1])
    except (TypeError, ValueError):
        return {}
    return output if isinstance(output, dict) else {}


def _as_capability_notes(raw):
    if raw is None:
        return []
    if not isinstance(raw, list):
        raw = [raw]
    notes = []
    for item in raw:
        if isinstance(item, str):
            cap = item.strip()
            if cap:
                notes.append({"capability": cap, "reason": ""})
            continue
        if not isinstance(item, dict):
            continue
        cap = str(
            item.get("capability")
            or item.get("capability_id")
            or item.get("name")
            or ""
        ).strip()
        reason = str(item.get("reason") or item.get("why") or "").strip()
        if cap or reason:
            notes.append({"capability": cap, "reason": reason})
    return notes


def extract_llm_capability_notes(llm_answer, catalog=None):
    output = extract_llm_output(llm_answer)
    return {
        "missing_capabilities": _normalize_capability_notes(
            output.get("missing_capabilities"), catalog
        ),
        "better_capabilities": _normalize_capability_notes(
            output.get("better_capabilities"), catalog
        ),
    }


def extract_llm_presentation(llm_answer):
    """Planner-owned Presentation decision. Not a capability step."""
    if not llm_answer:
        return {}
    try:
        output = json.loads(llm_answer) if isinstance(llm_answer, str) else llm_answer
    except (TypeError, ValueError):
        return {}
    if not isinstance(output, dict):
        return {}
    return _normalize_presentation_plan(output.get("presentation"))


def _normalize_presentation_plan(raw):
    if not isinstance(raw, dict):
        return {}
    ptype = str(raw.get("type") or "").strip().lower()
    if ptype not in ("text", "image", "audio"):
        return {}
    src = str(raw.get("from") or raw.get("payload_from") or "").strip()
    out = {"type": ptype}
    if src:
        out["from"] = src
    channel = str(raw.get("channel") or "").strip().lower()
    if channel in ("iphone", "kindle", "android", "speaker"):
        out["channel"] = channel
    endpoint = str(raw.get("endpoint") or "").strip()
    if endpoint:
        out["endpoint"] = endpoint
    endpoint_id = str(raw.get("endpoint_id") or "").strip()
    if endpoint_id:
        out["endpoint_id"] = endpoint_id
    return out


def _caps_in_plan(intent):
    caps = []
    for step in intent.get("execution_plan") or []:
        if isinstance(step, dict) and step.get("capability"):
            caps.append(str(step.get("capability") or "").strip())
    return caps


def _presentation_kind_from_plan(intent):
    """Use the planner's Presentation decision, not keyword matching on user text.

    Assembled `{type, asset_ref|text}` is output, not the plan. Trust a skeleton
    that includes `from`, or type=audio (spoken delivery). Else infer from
    capabilities the planner already scheduled.
    """
    raw = intent.get("presentation")
    planned = {}
    raw_type = str((raw or {}).get("type") or "").strip().lower() if isinstance(raw, dict) else ""
    if isinstance(raw, dict) and (
        raw.get("from") or raw.get("payload_from") or raw_type == "audio"
    ):
        planned = _normalize_presentation_plan(raw)
    if not planned.get("type"):
        planned = _normalize_presentation_plan(intent.get("presentation_plan"))
    if planned.get("type"):
        src = planned.get("from")
        plan = intent.get("execution_plan") or []
        # Planner often names answer_text. Drop it when no step produces that field
        # (music.play has empty output_schema — speaking $answer_text would fail hydrate).
        if src and plan and not _plan_emits_field(plan, src):
            planned = {}
        else:
            return _voice_symmetric_presentation_kind(
                intent, planned["type"], src or ""
            )
    caps = _caps_in_plan(intent)
    if any(c in _DISPLAY_CAPS for c in caps):
        return "image", "asset_ref"
    if "music.recognize" in caps:
        return _voice_symmetric_presentation_kind(intent, "text", "answer_text")
    if "clock.now" in caps:
        return _voice_symmetric_presentation_kind(intent, "text", "time_text")
    if "map.route.estimate" in caps:
        return _voice_symmetric_presentation_kind(intent, "text", "answer_text")
    if "math.calculate" in caps:
        return _voice_symmetric_presentation_kind(intent, "text", "answer_text")
    if "chat.smalltalk" in caps:
        return _voice_symmetric_presentation_kind(intent, "text", "reply")
    if "asset.inventory" in caps:
        if _plan_wants_image_presentation(intent):
            return "image", "asset_ref"
        return _voice_symmetric_presentation_kind(intent, "text", "answer_text")
    if "image.ocr" in caps:
        return _voice_symmetric_presentation_kind(intent, "text", "text")
    if "capabilities.summary" in caps:
        return "audio", "answer_text"
    if "vision.ask" in caps:
        return _voice_symmetric_presentation_kind(intent, "text", "answer_text")
    if "query.content" in caps:
        return _voice_symmetric_presentation_kind(intent, "text", "answer_text")
    if "search.images" in caps:
        return "image", "asset_refs"
    if "vision.perceive" in caps:
        return _voice_symmetric_presentation_kind(intent, "text", "summary")
    if "light.set" in caps:
        return _voice_symmetric_presentation_kind(intent, "text", "state")
    if "climate.set" in caps:
        return _voice_symmetric_presentation_kind(intent, "text", "status_text")
    if "aquarium.set" in caps:
        return _voice_symmetric_presentation_kind(intent, "text", "status_text")
    if "lock.status" in caps:
        return _voice_symmetric_presentation_kind(intent, "text", "status_text")
    if "camera.capture" in caps or "camera.capture_and_upload" in caps:
        return "image", "asset_ref"
    if "document.scan" in caps or "visual.input" in caps:
        return "image", "asset_ref"
    return "", ""


def _as_asset_ref(raw):
    """Normalize an AssetRef. URLs and paths are not identity."""
    if isinstance(raw, str):
        aid = raw.strip()
        if not aid:
            return None
        if aid.startswith("{") or aid.startswith("["):
            try:
                parsed = json.loads(aid)
            except (TypeError, ValueError):
                parsed = None
            if isinstance(parsed, dict):
                return _as_asset_ref(parsed)
            if isinstance(parsed, list) and parsed:
                return _as_asset_ref(parsed[0])
        return {"asset_id": aid, "type": "image"}
    if not isinstance(raw, dict):
        return None
    nested = raw.get("asset_ref")
    if isinstance(nested, dict) and not str(raw.get("asset_id") or "").strip():
        return _as_asset_ref(nested)
    if isinstance(nested, str) and nested.strip().startswith("{") and not str(raw.get("asset_id") or "").strip():
        return _as_asset_ref(nested)
    aid = str(raw.get("asset_id") or "").strip()
    if not aid:
        return None
    if aid.startswith("{"):
        inner = _as_asset_ref(aid)
        if inner:
            return inner
    out = {
        "asset_id": aid,
        "type": str(raw.get("type") or "image").strip() or "image",
    }
    mime = str(raw.get("mime_type") or "").strip()
    if mime:
        out["mime_type"] = mime
    return out


def _asset_media_family(ref) -> str:
    """Best-effort media family of an AssetRef (image/audio/video/document/other)."""
    if not isinstance(ref, dict):
        return "other"
    asset_type = str(ref.get("type") or "").strip().lower()
    mime = str(ref.get("mime_type") or "").strip().lower()
    if asset_type == "image" or mime.startswith("image/"):
        return "image"
    if asset_type == "audio" or mime.startswith("audio/"):
        return "audio"
    if asset_type == "video" or mime.startswith("video/"):
        return "video"
    if asset_type == "document" or mime.startswith(("application/", "text/")):
        return "document"
    return "other"


def _enrich_asset_ref_from_catalog(ref):
    rec = brain_db.get_asset(ref["asset_id"])
    if not rec:
        return ref
    out = dict(ref)
    if rec.get("type"):
        out["type"] = rec["type"]
    mime = str(rec.get("mime_type") or "").strip()
    if mime:
        out["mime_type"] = mime
    return out


def _parse_asset_refs_list(raw):
    """Parse inventory-style asset_refs (JSON string or list) into AssetRef dicts."""
    data = raw
    if isinstance(data, str):
        text = data.strip()
        if not text:
            return []
        try:
            data = json.loads(text)
        except (TypeError, ValueError):
            return []
    if not isinstance(data, list):
        return []
    refs = []
    for item in data:
        ref = _as_asset_ref(item)
        if ref:
            refs.append(ref)
    return refs


def _collect_asset_ref(ctx, outputs):
    blobs = []
    if isinstance(ctx, dict):
        blobs.append(ctx)
    if isinstance(outputs, dict):
        blobs.extend(v for v in outputs.values() if isinstance(v, dict))
    for blob in blobs:
        for key in ("asset_ref", "image_ref"):
            ref = _as_asset_ref(blob.get(key))
            if ref:
                return _enrich_asset_ref_from_catalog(ref)
    # inventory returns asset_refs[]; pick one for image Presentation
    for blob in blobs:
        refs = _parse_asset_refs_list(blob.get("asset_refs"))
        if not refs:
            continue
        idx_raw = blob.get("asset_index")
        if idx_raw is None and isinstance(ctx, dict):
            idx_raw = ctx.get("asset_index")
        if idx_raw is not None and str(idx_raw).strip() != "":
            try:
                idx = int(str(idx_raw).strip())
            except (TypeError, ValueError):
                idx = 0
            if idx >= 1 and idx <= len(refs):
                return _enrich_asset_ref_from_catalog(refs[idx - 1])
        # Single ref, or limit=N intending the Nth of that page → last item
        pick = refs[0] if len(refs) == 1 else refs[-1]
        return _enrich_asset_ref_from_catalog(pick)
    return None


def assemble_presentation(intent):
    """Fill planner-decided Presentation from execution results. Asset is not a URL."""
    if not intent:
        return None
    if _normalize_status(str(intent.get("status") or "")) == "failed":
        fail_msg = str(intent.get("msg") or intent.get("error") or "").strip()
        if fail_msg:
            _apply_failure_presentation(intent, fail_msg)
            return intent.get("presentation")
    ctx = intent.get("ctx_param") or intent.get("context") or {}
    if not isinstance(ctx, dict):
        ctx = {}
    if ctx.get("wake_ack") or _is_wake_ack_utterance(intent.get("text")):
        intent.pop("presentation", None)
        return None
    time_text = ctx.get("time_text")
    answer = ctx.get("answer_text")
    reply = ctx.get("reply")
    summary = ctx.get("summary")
    people = ctx.get("people")
    state = ctx.get("state")
    ocr_text = ctx.get("text")
    outputs = intent.get("step_outputs") or {}
    if isinstance(outputs, dict):
        for blob in outputs.values():
            if not isinstance(blob, dict):
                continue
            time_text = time_text or blob.get("time_text")
            answer = answer or blob.get("answer_text")
            reply = reply or blob.get("reply")
            summary = summary or blob.get("summary")
            people = people or blob.get("people")
            state = state or blob.get("state")
            ocr_text = ocr_text or blob.get("text")
    ref = _collect_asset_ref(ctx, outputs)
    fields = {
        "time_text": str(time_text) if time_text else "",
        "answer_text": str(answer) if answer else "",
        "reply": str(reply) if reply else "",
        "summary": str(summary) if summary else "",
        "people": _people_count_text(people),
        "state": str(state) if state else "",
        "text": str(ocr_text) if ocr_text else "",
    }
    ptype, src = _presentation_kind_from_plan(intent)
    ptype, src = _voice_symmetric_presentation_kind(intent, ptype, src or "")
    # Audio assets must never be delivered as an image to an image-only endpoint.
    # When the plan picked an audio asset (e.g. asset.inventory returned a just
    # recorded voice memo — home-agent issue id=617), present it as audio so the
    # runtime plays the recording instead of trying to render audio bytes as a photo.
    if ptype == "image" and ref and _asset_media_family(ref) == "audio":
        ptype = "audio"
        src = src or "asset_ref"
    text_body = ""
    if src in ("time_text", "answer_text", "reply", "summary", "people", "state", "text") and fields.get(src):
        text_body = fields[src]
    else:
        text_body = (
            fields["time_text"]
            or fields["answer_text"]
            or fields["reply"]
            or fields["summary"]
            or fields["text"]
            or fields["people"]
            or fields["state"]
        )
    # If planner named a word field as `from`, that is the delivery product — do not
    # override with a capture artifact just because type was wrongly set to image.
    _word_from = src in _SPOKEN_PRESENTATION_FIELDS
    _audio_asset = (
        ptype == "audio"
        and not _word_from
        and bool(ref)
        and _asset_media_family(ref) == "audio"
    )
    if _audio_asset:
        # Real audio file to hear: hand the asset_ref to the audio presentation so
        # the console can play it, instead of speaking a summary or faking an image.
        payload = {"asset_ref": ref}
    elif ptype == "image" and _word_from and text_body:
        ptype, _ = _voice_symmetric_presentation_kind(intent, "text", src)
        payload = {"text": text_body}
    elif ptype == "image" and ref:
        payload = {"asset_ref": ref}
        src = src or "asset_ref"
    elif ptype in ("text", "audio") and text_body:
        payload = {"text": text_body}
    elif ptype == "image" and text_body:
        ptype = "text"
        payload = {"text": text_body}
    elif ptype == "text":
        existing = intent.get("presentation")
        if isinstance(existing, dict):
            if (
                existing.get("type") == "image"
                or existing.get("image_url")
                or existing.get("asset_ref")
            ):
                existing = {
                    k: v
                    for k, v in existing.items()
                    if k not in ("image_url", "audio_url", "asset_ref", "photo_url")
                }
                existing["type"] = "text"
                if src:
                    existing["from"] = src
            intent["presentation"] = _stamp_presentation_endpoint(existing, intent)
        _grant_presented_asset(intent)
        return intent.get("presentation")
    elif text_body:
        ptype, _ = _voice_symmetric_presentation_kind(intent, "text", src or "")
        payload = {"text": text_body}
    elif ref:
        ptype = "image"
        payload = {"asset_ref": ref}
        src = src or "asset_ref"
    else:
        existing = intent.get("presentation")
        if isinstance(existing, dict):
            intent["presentation"] = _stamp_presentation_endpoint(existing, intent)
        _grant_presented_asset(intent)
        return intent.get("presentation")
    endpoint_id = _match_endpoint_participant(intent, ptype)
    if not endpoint_id and ptype == "audio":
        endpoint_id = _match_endpoint_participant(intent, "text")
    assembled = {
        "type": ptype,
        "channel": _channel_for_participant(endpoint_id, intent),
        "endpoint": endpoint_id,
        **payload,
    }
    if src:
        assembled["from"] = src
    # Boss: presentation identity is asset_ref only — never image_url / photo_url.
    for banned in ("image_url", "photo_url", "audio_url", "video_url"):
        assembled.pop(banned, None)
    intent["presentation"] = _stamp_presentation_endpoint(assembled, intent)
    _grant_presented_asset(intent)
    return intent["presentation"]


def compact_prompt():
    """Sole planner instruction source: prompts/task_planner_system_prompt.md.en."""
    if PROMPT_FILE.is_file():
        return PROMPT_FILE.read_text(encoding="utf-8")
    fallback = _HERE / "task_planner_system_prompt.md.en"
    return fallback.read_text(encoding="utf-8")


def compact_qwen_prompt():
    if QWEN_PROMPT_FILE.is_file():
        return QWEN_PROMPT_FILE.read_text(encoding="utf-8")
    return compact_prompt()


def _capability_registry_for_prompt():
    """Flatten Runtime ads plus always-on kind=system catalog."""
    rows = []
    for row in _list_schedulable_capabilities():
        item = dict(row)
        item.pop("description", None)
        rows.append(item)
    return rows


def _capability_registry_fingerprint(catalog=None) -> str:
    """Stable hash of the schedulable catalog; planner cache keys include this."""
    rows = catalog if catalog is not None else _capability_registry_for_prompt()
    tokens: list[str] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        tokens.append(
            "|".join(
                [
                    str(row.get("capability_id") or ""),
                    str(row.get("edge_id") or ""),
                    str(row.get("service_id") or ""),
                    str(row.get("display_name") or ""),
                ]
            )
        )
    tokens.sort()
    digest = hashlib.md5("\n".join(tokens).encode("utf-8")).hexdigest()
    return digest[:16]


def _score_capability_row_for_text(user_text: str, row: dict) -> int:
    raw = str(user_text or "")
    if not raw or not isinstance(row, dict):
        return 0
    score = 0
    for trigger in row.get("typical_triggers") or []:
        token = str(trigger or "").strip()
        if token and token in raw:
            score += 3
    display = str(row.get("display_name") or "").strip()
    if display and display in raw:
        score += 5
    recognize = str(row.get("planner_recognize") or "")
    if display and display in recognize and any(
        kw in raw for kw in ("空调", "制冷", "制热", "扫风")
    ):
        score += 2
    return score


def _catalog_matches_utterance(user_text: str, catalog) -> bool:
    """True when the catalog clearly advertises a row for this utterance."""
    best = 0
    for row in catalog or []:
        if not isinstance(row, dict):
            continue
        best = max(best, _score_capability_row_for_text(user_text, row))
    return best >= 3


def _planner_empty_plan_unreliable(user_text: str, llm_answer: str, catalog) -> bool:
    """Empty plan is suspect when the live catalog already matches the utterance."""
    output = extract_llm_output(llm_answer)
    plan = output.get("plan") if isinstance(output, dict) else None
    if isinstance(plan, list) and plan:
        return False
    return _catalog_matches_utterance(user_text, catalog)


def _normalize_capability_id(cap: str, catalog_ids: set[str] | frozenset[str]) -> str:
    cid = str(cap or "").strip()
    if not cid:
        return ""
    if cid in catalog_ids:
        return cid
    aliased = _CAPABILITY_ID_ALIASES.get(cid)
    if aliased and aliased in catalog_ids:
        return aliased
    return aliased or cid


def _normalize_capability_notes(raw, catalog=None):
    catalog_ids = frozenset(
        str(row.get("capability_id") or "").strip()
        for row in (catalog or [])
        if isinstance(row, dict) and str(row.get("capability_id") or "").strip()
    )
    notes = _as_capability_notes(raw)
    out: list[dict[str, str]] = []
    for note in notes:
        cap = str(note.get("capability") or "").strip()
        reason = str(note.get("reason") or "").strip()
        if cap in catalog_ids:
            # Advertised capability cannot be "missing".
            continue
        normalized = _normalize_capability_id(cap, catalog_ids)
        if normalized in catalog_ids:
            continue
        if normalized or reason:
            out.append({"capability": normalized, "reason": reason})
    return out


def _persist_available_capabilities(intent_id, capabilities):
    """jobs.available_capabilities: exact planner catalog at plan time (replay)."""
    if intent_id in (None, ""):
        return
    stored = get_intent(intent_id)
    if not stored:
        return
    existing = stored.get("available_capabilities")
    if isinstance(existing, list) and existing:
        return
    stored["available_capabilities"] = deepcopy(list(capabilities or []))
    _save_intent(stored)


def _world_state_for_prompt():
    """Node presence only; Available Capabilities is the catalog."""
    nodes = []
    for node in _world_state_nodes():
        if not isinstance(node, dict):
            continue
        nodes.append(
            {
                "participant_id": node.get("participant_id"),
                "display_name": node.get("display_name"),
                "device_type": node.get("device_type"),
                "roles": node.get("roles") or [],
                "online_status": node.get("online_status"),
                "schedule_eligible": node.get("schedule_eligible"),
                "endpoints": node.get("endpoints") or [],
            }
        )
    return {"nodes": nodes}


def _planner_memory(intent):
    """Session-adjacent assets and last turn — not a capability."""
    memory = {"recent_assets": [], "last_turn": None}
    try:
        for row in brain_db.list_assets(limit=5, newest_first=True):
            ref = row.get("asset_ref") if isinstance(row, dict) else None
            if not isinstance(ref, dict) or not str(ref.get("asset_id") or "").strip():
                continue
            entry = {
                "asset_ref": {
                    "asset_id": str(ref.get("asset_id")),
                    "type": str(ref.get("type") or "image"),
                },
                "created_at": row.get("created_at"),
            }
            if ref.get("mime_type"):
                entry["asset_ref"]["mime_type"] = str(ref.get("mime_type"))
            memory["recent_assets"].append(entry)
    except Exception:
        log.exception("planner memory list_assets failed")
    session_id = str((intent or {}).get("session_id") or "").strip()
    if not session_id:
        ctx0 = (intent or {}).get("ctx_param") or (intent or {}).get("context") or {}
        if isinstance(ctx0, dict):
            session_id = str(ctx0.get("session_id") or "").strip()
    current_id = str(
        (intent or {}).get("id") or (intent or {}).get("intent_id") or ""
    ).strip()
    if not session_id:
        return memory
    try:
        jobs = brain_db.list_jobs()
    except Exception:
        log.exception("planner memory list_jobs failed")
        return memory
    for job in jobs or []:
        if not isinstance(job, dict):
            continue
        jid = str(job.get("intent_id") or job.get("id") or "").strip()
        if current_id and jid == current_id:
            continue
        job_sid = str(job.get("session_id") or "").strip()
        if not job_sid:
            jctx = job.get("ctx_param") or job.get("context") or {}
            if isinstance(jctx, dict):
                job_sid = str(jctx.get("session_id") or "").strip()
        if job_sid != session_id:
            continue
        last = {
            "intent_id": job.get("intent_id") or job.get("id"),
            "text": job.get("text") or "",
        }
        pres = job.get("presentation")
        if isinstance(pres, dict) and pres:
            last["presentation"] = {
                k: pres[k]
                for k in ("type", "from", "endpoint")
                if pres.get(k) is not None
            }
        ctx = job.get("ctx_param") or job.get("context") or {}
        if isinstance(ctx, dict):
            ref = _as_asset_ref(ctx.get("asset_ref"))
            if ref:
                last["asset_ref"] = ref
        memory["last_turn"] = last
        break
    return memory


def _candidate_capability_rows(user_text, rows, *, limit=4):
    """Hint rows whose typical_triggers overlap the utterance (user message only)."""
    raw = str(user_text or "")
    scored = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        score = _score_capability_row_for_text(raw, row)
        if score <= 0:
            continue
        scored.append(
            (
                score,
                {
                    "capability_id": row.get("capability_id"),
                    "role": row.get("role") or "",
                    "planner_recognize": row.get("planner_recognize") or "",
                    "typical_triggers": list(row.get("typical_triggers") or []),
                    "edge_id": row.get("edge_id") or "",
                    "display_name": row.get("display_name") or "",
                },
            )
        )
    scored.sort(
        key=lambda item: (-item[0], str(item[1].get("capability_id") or ""), str(item[1].get("edge_id") or ""))
    )
    out = []
    seen = set()
    for _score, item in scored:
        key = (item.get("capability_id"), item.get("edge_id"))
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= max(1, int(limit)):
            break
    return out


def _planner_user_message(
    *,
    user_intent,
    memory,
    world_state,
    capabilities,
    endpoints,
    presentation_schema,
    output_schema,
    candidates,
):
    """This-turn facts for the user role. Real capability_id values come from the catalog."""
    blocks = [
        "Plan this turn. Return only the JSON object defined by OUTPUT_SCHEMA.",
        "Copy capability_id, assigned_edge_id, and field names from Available Capabilities (or Candidate rows). Do not invent ids.",
        "",
        "<User Intent>",
        json.dumps(user_intent, ensure_ascii=False),
        "",
        "<Current Memory>",
        json.dumps(memory, ensure_ascii=False),
        "",
        "<Current World State>",
        json.dumps(world_state, ensure_ascii=False),
        "",
        "<Available Capabilities>",
        json.dumps(capabilities, ensure_ascii=False),
        "",
        "<Candidate rows whose ads overlap this utterance>",
        json.dumps(candidates, ensure_ascii=False),
        "",
        "<Available Endpoints>",
        json.dumps(endpoints, ensure_ascii=False),
        "",
        "<Presentation Schema>",
        json.dumps(presentation_schema, ensure_ascii=False),
        "",
        "<OUTPUT_SCHEMA>",
        json.dumps(output_schema, ensure_ascii=False),
    ]
    return "\n".join(blocks)


def _list_schedulable_capabilities(*, capability_id=None, edge_id=None):
    """Online Runtime ads plus always-on kind=system catalog (not bound to an edge)."""
    rebuild_capability_maps()
    rows = []
    want_cap = str(capability_id or "").strip()
    want_edge = str(edge_id or "").strip()
    for sid, svc in _services_snapshot().items():
        if not isinstance(svc, dict):
            continue
        svc_edge = str(svc.get("edge_id") or "").strip()
        if want_edge and svc_edge != want_edge:
            continue
        for cap in svc.get("capabilities") or []:
            if not isinstance(cap, dict):
                continue
            cid = str(cap.get("capability_id") or "").strip()
            if not cid:
                continue
            if is_system_capability(cid):
                continue
            if want_cap and cid != want_cap:
                continue
            triggers = cap.get("typical_triggers") or []
            if not isinstance(triggers, list):
                triggers = []
            do_not = cap.get("do_not_dispatch") or []
            if not isinstance(do_not, list):
                do_not = []
            composition = str(cap.get("composition") or "atomic").strip().lower() or "atomic"
            item = {
                "capability_id": cid,
                "kind": str(cap.get("kind") or "").strip().lower(),
                "composition": composition,
                "role": cap.get("role") or "",
                "planner_recognize": cap.get("planner_recognize") or "",
                "typical_triggers": list(triggers),
                "do_not_dispatch": list(do_not),
                # Non-authoritative; kept for legacy edges / admin display.
                "description": cap.get("description") or "",
                "input_schema": cap.get("input_schema") or {},
                "output_schema": cap.get("output_schema") or {},
                "service_id": svc.get("service_id") or sid,
                "display_name": svc.get("display_name") or "",
                "group": svc.get("group") or "",
                "edge_id": svc_edge,
                "edge_name": svc.get("edge_name") or "",
                "assigned_edge_id": svc_edge,
            }
            decomposes = (
                list(cap.get("decomposes_to") or [])
                if isinstance(cap.get("decomposes_to"), list)
                else []
            )
            prefer = str(cap.get("prefer_when") or "").strip()
            if decomposes:
                item["decomposes_to"] = decomposes
            if prefer:
                item["prefer_when"] = prefer
            rows.append(item)
    if not want_edge or want_edge == SYSTEM_EDGE_ID:
        for row in system_capability_catalog_rows():
            cid = str(row.get("capability_id") or "").strip()
            if want_cap and cid != want_cap:
                continue
            rows.append(row)
    rows.sort(key=lambda row: (row["capability_id"], row["edge_id"]))
    return rows

_ARK_SECRET_KEYS = frozenset({"authorization", "api_key", "ark_api_key", "bearer"})


def _without_secrets(value):
    if isinstance(value, dict):
        return {
            k: _without_secrets(v)
            for k, v in value.items()
            if str(k).lower() not in _ARK_SECRET_KEYS
        }
    if isinstance(value, list):
        return [_without_secrets(v) for v in value]
    return value


def _ark_result(*, ans="", cost_ms=0, request_payload=None, response_json=None, cache_hit=False):
    payload = _without_secrets(request_payload) if request_payload is not None else None
    return {
        "ans": ans,
        "cost_ms": int(cost_ms or 0),
        "request_payload": payload,
        "response_json": response_json,
        "cache_hit": bool(cache_hit),
    }


def _ark_http_error_json(exc):
    body = ""
    try:
        body = exc.read().decode("utf-8", errors="replace")
    except Exception:
        body = ""
    parsed = None
    if body:
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = None
    status = int(getattr(exc, "code", 0) or 0)
    if isinstance(parsed, dict):
        out = dict(parsed)
        out.setdefault("http_status", status)
        return out
    return {"http_status": status, "body": body[:8000]}


def _planner_prompt_pair(user_text, intent_id, intent_base_time, intent=None):
    """Same system + user strings Doubao and Qwen shadow both send."""
    intent = intent or {}
    source = str(intent.get("source") or "text")
    system_prompt = compact_prompt()
    rebuild_capability_maps()
    user_intent = {
        "id": intent_id,
        "source": source,
        "participant_id": str(intent.get("edge_id") or intent.get("participant_id") or ""),
        "intent_base_time": intent_base_time,
        "text": user_text,
    }
    src_ctx = intent.get("source_context")
    if isinstance(src_ctx, dict) and src_ctx:
        user_intent["source_context"] = src_ctx
    affinity = intent.get("output_affinity")
    if isinstance(affinity, dict) and affinity:
        user_intent["output_affinity"] = affinity
    session_id = str(intent.get("session_id") or "").strip()
    if session_id:
        user_intent["session_id"] = session_id
    ctx = intent.get("ctx_param") or intent.get("context") or {}
    if isinstance(ctx, dict):
        ref = _as_asset_ref(ctx.get("asset_ref"))
        if ref:
            user_intent["ctx_param"] = {"asset_ref": ref}
            user_intent["has_visual_input"] = True
        # Named audio inputs (pronunciation.assess): expose to planner so it can
        # wire $reference_audio / $student_audio into the assess step's input_constrict.
        audio_refs: dict[str, Any] = {}
        for _key in ("reference_audio", "student_audio"):
            _aref = _as_asset_ref(ctx.get(_key))
            if _aref:
                _aref["type"] = "audio"
                audio_refs[_key] = _aref
        if audio_refs:
            user_intent.setdefault("ctx_param", {}).update(audio_refs)
            user_intent["has_audio_input"] = True
    capabilities = _capability_registry_for_prompt()
    memory = _planner_memory(intent)
    world_state = _world_state_for_prompt()
    candidates = _candidate_capability_rows(user_text, capabilities)
    user_prompt = _planner_user_message(
        user_intent=user_intent,
        memory=memory,
        world_state=world_state,
        capabilities=capabilities,
        endpoints=_endpoint_registry(intent),
        presentation_schema=_PLANNER_PRESENTATION_SCHEMA,
        output_schema=_PLANNER_OUTPUT_SCHEMA,
        candidates=candidates,
    )
    # available_capabilities: exact catalog JSON the planner saw this turn.
    _persist_available_capabilities(intent_id, capabilities)
    if isinstance(intent, dict):
        intent.setdefault("available_capabilities", deepcopy(capabilities))
    return system_prompt, user_prompt


def _record_ark_planner_call(ok: bool) -> None:
    try:
        brain_db.record_cloud_call("ark.planner", ok, "brain")
    except Exception:
        log.exception("record_cloud_call ark.planner failed")


def call_ark(user_text, session_id, user_id, intent_id, intent_base_time, intent=None, *, _retry: int = 0):
    # 【核心优化】真正调用大模型前，二次检查缓存，避免重复生成
    intent = intent or get_intent(intent_id) or {}
    source = str(intent.get("source") or "text")
    catalog = _capability_registry_for_prompt()
    catalog_fp = _capability_registry_fingerprint(catalog)
    cache_hit = None if _retry > 0 else get_cache(user_text, source, catalog_fingerprint=catalog_fp)
    if cache_hit is not None:
        if _planner_empty_plan_unreliable(user_text, cache_hit, catalog):
            llm_logger.info(
                "planner cache stale (empty plan but catalog matches) question=%s",
                user_text,
            )
            cache_hit = None
        else:
            llm_logger.info(f"二次缓存校验命中，跳过LLM调用 question={user_text}")
            _persist_available_capabilities(intent_id, catalog)
            return _ark_result(ans=cache_hit, cost_ms=0, cache_hit=True)

    system_prompt, user_prompt = _planner_prompt_pair(
        user_text, intent_id, intent_base_time, intent=intent
    )
    log.info("planner system chars=%s user chars=%s", len(system_prompt), len(user_prompt))

    # Planner rules live only in task_planner_system_prompt.md.en (compact_prompt).
    # This-turn intent + catalog belong in the user message.
    headers = {"Content-Type":"application/json", "Authorization":f"Bearer {ARK_API_KEY}"}
    payload_obj = {
            "model":MODEL_ID,
             "messages":[
                 {
                     "role":"system",
                     "content": system_prompt,
                 },
                 {
                     "role":"user",
                     "content": user_prompt,
                 }
             ],
             "max_tokens":4096,
             "temperature": 0.2,
             "top_p": 0.1,
             "stream": False,
             "response_format": {"type": "json_object"},
             "extra_body": {
                "thinking": {
                    "type": "disabled"
                }
             },
             }
    payload = json.dumps(payload_obj).encode("utf-8")
    safe_payload = json.dumps(_without_secrets(payload_obj), ensure_ascii=False)
    if len(safe_payload) > 8000:
        safe_payload = safe_payload[:8000] + "...(truncated)"
    log.debug("ark payload: %s", safe_payload)
    log.info("ark request model=%s payload_bytes=%d", MODEL_ID, len(payload))
    ans = ""
    cost_ms = 0
    response_json = None
    start_time = time.time()
    try:
        log.info("invoke doubao api begin")
        req = urllib.request.Request(ARK_URL, data=payload, headers=headers)
        resp = urllib.request.urlopen(req, timeout=180)
        raw_body = resp.read().decode("utf-8")
        cost_ms = int((time.time() - start_time) * 1000)
        log.info("invoke doubao api end:%s", cost_ms)
        _record_ark_planner_call(True)
        resp_data = json.loads(raw_body)
        response_json = resp_data
        llm_logger.info(f"cost_ms={cost_ms} | question={user_text} | answer={resp_data}")
        log.info("get res:%s", resp_data)
        ans = resp_data["choices"][0]["message"]["content"]
        log.info("get ans: %s", ans)
        if _planner_empty_plan_unreliable(user_text, ans, catalog) and _retry < 1:
            llm_logger.info(
                "planner empty plan but catalog matches; retrying LLM question=%s",
                user_text,
            )
            return call_ark(
                user_text,
                session_id,
                user_id,
                intent_id,
                intent_base_time,
                intent=intent,
                _retry=_retry + 1,
            )
        if not _planner_empty_plan_unreliable(user_text, ans, catalog):
            set_cache(user_text, ans, source, catalog_fingerprint=catalog_fp)
            log.info("put into cache for user query:%s", user_text)
        else:
            log.info("skip planner cache (empty plan with matching catalog) question=%s", user_text)
    except urllib.error.HTTPError as e:
        cost_ms = int((time.time() - start_time) * 1000)
        _record_ark_planner_call(False)
        log.exception("call doubao api error: %s", e)
        response_json = _ark_http_error_json(e)
        if int(getattr(e, "code", 0) or 0) == 401:
            ans = "__ARK_HTTP_401__"
    except Exception as e:
        cost_ms = int((time.time() - start_time) * 1000)
        _record_ark_planner_call(False)
        log.exception("call doubao api error: %s", e)
    return _ark_result(
        ans=ans,
        cost_ms=cost_ms,
        request_payload=payload_obj,
        response_json=response_json,
    )


def get_model_answer(res_json):
    try:
        output_list = res_json.get("output", [])
        for block in output_list:
            if block.get("type") == "message":
                content_arr = block.get("content", [])
                if len(content_arr) > 0 and "text" in content_arr[0]:
                    return content_arr[0]["text"]
        return "暂时无法获取回答"
    except Exception:
        return "数据解析失败"


def qwen_planner_enabled():
    """Local Brain shadow: set QWEN_PLANNER=1. URL defaults to cloud :8090/chat."""
    raw = (os.environ.get("QWEN_PLANNER") or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _qwen_reply_text(response_json):
    """Parse model_server POST /chat JSON ({ok, text|answer|reply})."""
    if isinstance(response_json, str):
        return response_json
    if not isinstance(response_json, dict):
        return str(response_json or "")
    for key in ("reply", "answer", "text", "content", "output"):
        val = response_json.get(key)
        if isinstance(val, str) and val.strip():
            return val
        if isinstance(val, dict):
            nested = val.get("content") or val.get("text")
            if isinstance(nested, str) and nested.strip():
                return nested
    msg = response_json.get("message")
    if isinstance(msg, dict):
        nested = msg.get("content") or msg.get("text")
        if isinstance(nested, str) and nested.strip():
            return nested
    return ""


def call_qwen(user_text, intent=None):
    """Shadow planner: POST cloud /chat {system, text}. Never used for enqueue."""
    intent = intent or {}
    intent_id = intent.get("id") or intent.get("intent_id")
    system_prompt, user_prompt = _planner_prompt_pair(
        user_text, intent_id, intent.get("intent_base_time"), intent=intent
    )
    payload_obj = {"system": system_prompt, "text": user_prompt}
    body = json.dumps(payload_obj, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    started = time.time()
    response_json = None
    ans = ""
    error = None
    try:
        req = urllib.request.Request(
            QWEN_PLANNER_URL, data=body, headers=headers, method="POST"
        )
        with urllib.request.urlopen(req, timeout=QWEN_PLANNER_TIMEOUT_SEC) as resp:
            raw_body = resp.read().decode("utf-8")
        cost_ms = int((time.time() - started) * 1000)
        try:
            response_json = json.loads(raw_body)
        except (TypeError, ValueError):
            response_json = {"ok": False, "body": raw_body[:8000]}
            ans = raw_body
        else:
            ans = _qwen_reply_text(response_json)
    except urllib.error.HTTPError as e:
        cost_ms = int((time.time() - started) * 1000)
        err_body = ""
        try:
            err_body = e.read().decode("utf-8")
        except Exception:
            err_body = ""
        response_json = {
            "http_status": int(getattr(e, "code", 0) or 0),
            "body": err_body,
        }
        error = f"qwen HTTP {getattr(e, 'code', '')}"
        log.exception("call qwen planner error: %s", e)
    except Exception as e:
        cost_ms = int((time.time() - started) * 1000)
        error = f"{type(e).__name__}: {e}"
        log.exception("call qwen planner error: %s", e)
    return {
        "ans": ans,
        "cost_ms": cost_ms,
        "request_payload": _without_secrets(payload_obj),
        "response_json": response_json,
        "error": error,
        "model": QWEN_PLANNER_MODEL,
        "planner": "qwen",
    }


call_qwen_planner = call_qwen


def _record_qwen_shadow_review(
    intent_id,
    *,
    text,
    session_id,
    source,
    edge_id,
    intent,
    holder,
):
    qwen = holder.get("result")
    if holder.get("exc") and not qwen:
        qwen = {
            "ans": "",
            "cost_ms": 0,
            "error": holder["exc"],
            "model": QWEN_PLANNER_MODEL,
            "request_payload": None,
            "response_json": None,
        }
    if not qwen:
        return
    ans = qwen.get("ans") or ""
    llm_out = extract_llm_output_relaxed(ans)
    plan = llm_out.get("plan") if isinstance(llm_out.get("plan"), list) else []
    try:
        stored_plan = sanitize_execution_plan(plan, intent or {})
    except Exception:
        stored_plan = plan
    notes = {
        "missing_capabilities": _as_capability_notes(llm_out.get("missing_capabilities")),
        "better_capabilities": _as_capability_notes(llm_out.get("better_capabilities")),
    }
    parsed = {
        "goal": llm_out.get("goal"),
        "reason": llm_out.get("reason"),
        "required_capabilities": llm_out.get("required_capabilities") or [],
        "plan": plan,
        "presentation": llm_out.get("presentation") or {},
        "missing_capabilities": notes["missing_capabilities"],
        "better_capabilities": notes["better_capabilities"],
        "shadow": True,
        "request_payload": qwen.get("request_payload"),
        "response_json": qwen.get("response_json"),
    }
    _record_intent_review(
        intent_id,
        text=text,
        raw=ans,
        parsed=parsed,
        plan=stored_plan,
        session_id=session_id,
        source=source,
        edge_id=edge_id,
        cost_ms=qwen.get("cost_ms"),
        planner="qwen",
        model=qwen.get("model") or QWEN_PLANNER_MODEL,
        error=qwen.get("error"),
        request_payload=qwen.get("request_payload"),
        response_json=qwen.get("response_json"),
    )


def run_qwen_shadow_review(intent_id):
    """Backfill a Qwen shadow row. Does not enqueue or change job status."""
    intent = get_intent(intent_id)
    if not intent:
        return {"ok": False, "error": "unknown intent"}
    result = call_qwen_planner(str(intent.get("text") or ""), intent=intent)
    _record_qwen_shadow_review(
        intent_id,
        text=intent.get("text"),
        session_id=intent.get("session_id"),
        source=intent.get("source"),
        edge_id=intent.get("edge_id"),
        intent=intent,
        holder={"result": result},
    )
    return {
        "ok": True,
        "cost_ms": result.get("cost_ms"),
        "error": result.get("error"),
        "model": result.get("model"),
    }


def extract_llm_plan(llm_answer):
    output = extract_llm_output(llm_answer)
    log.info("output:%s", llm_answer)
    return output.get("plan") or []



def make_execution_plan(llm_plan):
    """
    make real world plan, make it work
    """
    return llm_plan


class AmbiguousCapabilityEdge(Exception):
    """Plan step omitted which named instance to use when several exist."""


class CaptureUploadSplitError(Exception):
    """camera.capture and asset.upload cannot run on different Runtimes."""


def _assert_capture_upload_colocation(plan) -> None:
    """Fail enqueue if capture/upload would split across edges or composite has no edge."""
    rows = [s for s in (plan or []) if isinstance(s, dict)]
    for step in rows:
        cid = str(step.get("capability") or "").strip()
        if composition_of(cid) != "composite":
            continue
        edge = str(step.get("assigned_edge_id") or "").strip()
        if not edge or edge == SYSTEM_EDGE_ID:
            raise CaptureUploadSplitError(
                "没有可用的拍照并上传设备。拍照和上传必须在同一台设备上完成。"
            )
    for i, cur in enumerate(rows[:-1]):
        nxt = rows[i + 1]
        cap = str(cur.get("capability") or "").strip()
        nxt_cap = str(nxt.get("capability") or "").strip()
        if cap != "camera.capture" or nxt_cap != "asset.upload":
            continue
        if not _step_uses_capture_ref_token(nxt):
            continue
        a = str(cur.get("assigned_edge_id") or "").strip()
        b = str(nxt.get("assigned_edge_id") or "").strip()
        if not a or not b or a != b:
            raise CaptureUploadSplitError(
                "拍照和上传被派到了不同设备，本机照片句柄不能跨机。"
            )


def _provider_display_name(svc, view, edge_id):
    for raw in (
        (svc or {}).get("display_name"),
        (view or {}).get("display_name"),
        (svc or {}).get("edge_name"),
        edge_id,
    ):
        name = str(raw or "").strip()
        if name:
            return name
    return str(edge_id or "")


def online_capability_providers(capability_id):
    """Online schedule-eligible ads for this capability (one row per service)."""
    cid = str(capability_id or "").strip()
    if not cid or is_system_capability(cid):
        return []
    try:
        policy = _load_control_policy_index()
    except sqlite3.OperationalError:
        policy = {}
    providers = []
    seen = set()
    for edge_id, view in _edges_snapshot().items():
        if not isinstance(view, dict):
            continue
        if str(view.get("online_status") or "").lower() != "online":
            continue
        if view.get("schedule_eligible") is False:
            continue
        for svc in view.get("services") or []:
            if not isinstance(svc, dict):
                continue
            sid = str(svc.get("service_id") or "").strip()
            for cap in svc.get("capabilities") or []:
                if not isinstance(cap, dict):
                    continue
                if str(cap.get("capability_id") or "").strip() != cid:
                    continue
                # P0: skip DECLARED-but-unavailable caps (Runtime IsAvailable()=false).
                if cap.get("available") is False:
                    continue
                ok, _reason = can_participate(
                    edge_id,
                    capability=cid,
                    rec=view,
                    policy_index=policy,
                )
                if not ok:
                    continue
                key = (str(edge_id), sid)
                if key in seen:
                    continue
                seen.add(key)
                providers.append(
                    {
                        "edge_id": str(edge_id),
                        "service_id": sid,
                        "display_name": _provider_display_name(svc, view, edge_id),
                        "edge_name": str(view.get("display_name") or "").strip(),
                        "device_type": str(view.get("device_type") or "").strip(),
                        "client_hint": str(view.get("client_hint") or "").strip(),
                    }
                )
    return providers


def _instance_key(row):
    name = str((row or {}).get("display_name") or "").strip()
    sid = str((row or {}).get("service_id") or "").strip()
    return name or sid


def _group_providers_by_instance(providers):
    groups = {}
    for row in providers or []:
        key = _instance_key(row)
        if not key:
            key = str((row or {}).get("edge_id") or "")
        groups.setdefault(key, []).append(row)
    return groups


def _ambiguous_capability_edge_msg(providers):
    names = []
    seen = set()
    for row in providers or []:
        name = _instance_key(row)
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    listed = "、".join(names) if names else "（未命名）"
    return (
        "家里有多台同能力设备，请说清楚要用哪一台。"
        f"候选：{listed}。"
    )


def _is_mac_runtime_row(row):
    dt = str((row or {}).get("device_type") or "").strip().lower()
    if dt == "mac":
        return True
    hint = str((row or {}).get("client_hint") or "").strip().lower()
    return "laptop" in hint or hint in ("living-room-mac", "livingroom-mac")


def _prefer_provider(candidates, intent, preferred_edge_id=None, capability_id=None):
    rows = [row for row in (candidates or []) if isinstance(row, dict)]
    if not rows:
        return None
    cid = str(capability_id or "").strip()
    if cid.startswith("music."):
        mac_rows = [row for row in rows if _is_mac_runtime_row(row)]
        if mac_rows:
            pref = str(preferred_edge_id or "").strip()
            if pref:
                for row in mac_rows:
                    if str(row.get("edge_id") or "").strip() == pref:
                        return row
            return mac_rows[0]
    issuer = _issuer_participant_id(intent)
    if issuer:
        for row in rows:
            if str(row.get("edge_id") or "").strip() == issuer:
                return row
    pref = str(preferred_edge_id or "").strip()
    if pref:
        for row in rows:
            if str(row.get("edge_id") or "").strip() == pref:
                return row
    return rows[0]


def _user_text_matches_instance(text, instance_key):
    blob = str(text or "").strip().casefold()
    key = str(instance_key or "").strip()
    if not blob or not key:
        return False
    folded_key = key.casefold()
    if folded_key in blob:
        return True
    for token in _instance_match_tokens(key):
        if token in blob:
            return True
    return False


_APPLIANCE_TOKEN_NOISE = frozenset(
    {
        "camera",
        "photo",
        "相机",
        "拍照",
        "cam",
        "the",
        "and",
        "or",
        "on",
        "ok",
    }
)


def _instance_match_tokens(instance_key: str) -> list[str]:
    key = str(instance_key or "").strip()
    if not key:
        return []
    tokens: list[str] = []
    seen: set[str] = set()
    for raw in (key, key.replace(".", " ").replace("_", " ")):
        folded = raw.casefold()
        if folded and folded not in seen:
            seen.add(folded)
            tokens.append(folded)
        for part in re.split(r"[\s_/·\-]+", raw):
            part = part.strip()
            if len(part) < 2:
                continue
            folded_part = part.casefold()
            if folded_part not in seen:
                seen.add(folded_part)
                tokens.append(folded_part)
    return [t for t in tokens if t not in _APPLIANCE_TOKEN_NOISE]


def _service_id_matches_text(service_id, text) -> bool:
    sid = str(service_id or "").strip()
    if not sid:
        return False
    return _user_text_matches_instance(text, sid.replace(".", " ").replace("_", " "))


def _matched_instance_groups(groups, text):
    hits = []
    for key, rows in (groups or {}).items():
        if _user_text_matches_instance(text, key):
            hits.append((key, rows))
            continue
        for row in rows:
            if _service_id_matches_text(row.get("service_id"), text):
                hits.append((key, rows))
                break
    if len(hits) > 1:
        hits.sort(key=lambda item: len(item[0]), reverse=True)
        longest = len(hits[0][0])
        hits = [item for item in hits if len(item[0]) == longest]
    return hits


def _step_appliance_name(step):
    inp = (step or {}).get("input_constrict")
    if not isinstance(inp, dict):
        return ""
    for field in ("appliance", "label", "device_id"):
        val = str(inp.get(field) or "").strip()
        if val:
            return val
    return ""


def _ensure_appliance_param(step, provider):
    name = str((provider or {}).get("display_name") or "").strip()
    if not name or not isinstance(step, dict):
        return
    inp = step.get("input_constrict")
    if not isinstance(inp, dict):
        inp = {}
        step["input_constrict"] = inp
    if not str(inp.get("appliance") or "").strip():
        inp["appliance"] = name


def _assign_runtime_edge_id(step, cid, intent=None):
    existing = str((step or {}).get("assigned_edge_id") or "").strip()
    providers = online_capability_providers(cid)
    groups = _group_providers_by_instance(providers)
    text = str((intent or {}).get("text") or "")
    appliance = _step_appliance_name(step)

    def _return_provider(row):
        _ensure_appliance_param(step, row)
        return str((row or {}).get("edge_id") or "").strip()

    def _pick(rows):
        return _prefer_provider(
            rows, intent, preferred_edge_id=existing, capability_id=cid
        )

    # Named instance is matched against every online ad. LLM assigned_edge_id
    # is only a preference among those rows — do not pin to an edge that does
    # not host that appliance (e.g. iPhone advertising climate.set with no bind).
    if appliance:
        matched = []
        for key, rows in groups.items():
            for row in rows:
                sid = str(row.get("service_id") or "").strip()
                if (
                    appliance == key
                    or appliance in key
                    or key in appliance
                    or _user_text_matches_instance(appliance, key)
                    or _service_id_matches_text(sid, appliance)
                ):
                    matched.append(row)
        if matched:
            picked = _pick(matched)
            if picked:
                return _return_provider(picked)

    if len(groups) == 1:
        _key, rows = next(iter(groups.items()))
        picked = _pick(rows)
        if picked:
            return _return_provider(picked)

    hits = _matched_instance_groups(groups, text)
    if len(hits) == 1:
        picked = _pick(hits[0][1])
        if picked:
            return _return_provider(picked)

    if len(groups) > 1:
        raise AmbiguousCapabilityEdge(_ambiguous_capability_edge_msg(providers))

    if existing:
        pool = [
            row
            for row in providers
            if str(row.get("edge_id") or "").strip() == existing
        ]
        if pool:
            picked = _pick(pool)
            if picked:
                return _return_provider(picked)
        return existing
    if len(providers) == 1:
        return _return_provider(providers[0])
    return capability_edge_mapping.get(cid) or ""


def do_execution_plan(intent_id, execution_plan):
    """
        dispatch command to edge node to execute
                    return {"commands": [
                {
                    "id" : idx,
                    "action" : "play_song",
                    "app": "netease",
                    "uri" : None,
                    "song": song_command,
                    "artist": "",
                    "created_at": ts
                }

            ]}
    """
    global commands_queue
    intent = get_intent(intent_id)
    if not intent:
        raise Exception("intent not exist")
    rebuild_capability_maps()
    execution_plan = _append_issuer_speak_step(intent, execution_plan)
    simple_plan = []
    for _step in execution_plan:
        log.info("_step:\n%s", json.dumps(_step))
        _simple_step = {}
        if not _step.get('step'):
            continue
        _simple_step['step'] = _step['step']
        _simple_step['capability'] = _step['capability']
        _simple_step['input_constrict'] = _step.get('input_constrict') or {}
        _simple_step['output_constrict'] = _step.get('output_constrict') or {}
        _simple_step['execution_timing'] = _step.get('execution_timing')


        # Keep an already-assigned edge (voice issuer notify.speak).
        # kind=system steps always bind to Brain, never a Runtime heartbeat.
        cid = str(_simple_step["capability"] or "").strip()
        if is_system_capability(cid):
            assigned_edge_id = SYSTEM_EDGE_ID
        else:
            if _step.get("assigned_edge_id"):
                _simple_step["assigned_edge_id"] = _step.get("assigned_edge_id")
            assigned_edge_id = _assign_runtime_edge_id(_simple_step, cid, intent)
        _simple_step["assigned_edge_id"] = assigned_edge_id
        filled = _simple_step.get("input_constrict")
        if isinstance(filled, dict):
            filled = dict(filled)
            if cid == "music.play":
                if not str(filled.get("participant_id") or "").strip():
                    issuer = _ncm_play_issuer_id(intent)
                    if issuer:
                        filled["participant_id"] = issuer
                if not str(filled.get("intent_id") or "").strip():
                    filled["intent_id"] = str(intent_id)
            _simple_step["input_constrict"] = filled

        simple_plan.append(_simple_step)
    _assert_capture_upload_colocation(simple_plan)
    intent["execution_plan"] = simple_plan
    # available_capabilities: planner catalog at plan/enqueue time (replay).
    if not (isinstance(intent.get("available_capabilities"), list) and intent.get("available_capabilities")):
        intent["available_capabilities"] = _capability_registry_for_prompt()
    pres = intent.get("presentation")
    if isinstance(pres, dict):
        src = str(pres.get("from") or "").strip()
        if src and not _plan_emits_field(simple_plan, src):
            pres = dict(pres)
            pres.pop("from", None)
            intent["presentation"] = pres
    _save_intent(intent)
    _grant_plan_input_assets(intent_id, simple_plan)
    try_run_system_steps(intent_id)

    #if commands_queue.get('gopro') is None:
    #    commands_queue['gopro'] = []
    #commands_queue['gopro'].append('shutter')



# Runtime / capability routing liveness. Design: ~2× edge heartbeat interval
# (iPhone LivingRoomEdge heartbeats every 30s → allow one missed beat).
ONLINE_TTL_SEC = 60
# Presentation Endpoint liveness is not Runtime online TTL.
# Phones/Kindles can miss beats; 5min = same window as clock-skew reject.
ENDPOINT_TTL_SEC = 5 * 60
_STATUS_ALIASES = {
    "uploaded": "intent_received",
    "waiting": "intent_waiting",
    "success": "succeeded",
    "completed": "succeeded",
    "error": "failed",
    "plan_failed": "failed",
}
_TERMINAL_STATUSES = frozenset({"succeeded", "failed"})
_TERMINAL_STEP_STATUSES = frozenset({2, 3})
_EMPTY_PLAN_MSG = "execution_plan 为空，无法调度"


def _empty_plan_failure_msg(notes=None, llm_out=None):
    missing = (notes or {}).get("missing_capabilities") or []
    if missing and isinstance(missing[0], dict):
        reason = str(missing[0].get("reason") or "").strip()
        if reason:
            return reason
    reason = str((llm_out or {}).get("reason") or "").strip()
    if reason:
        return reason
    return _EMPTY_PLAN_MSG


def _apply_failure_presentation(intent, msg):
    text = str(msg or "").strip()
    if not intent or not text:
        return
    pres = intent.get("presentation") if isinstance(intent.get("presentation"), dict) else {}
    pres_type = "text"
    if str((intent or {}).get("task_kind") or "") == "shortcut":
        if str((intent or {}).get("source") or "").strip().lower() == "voice":
            pres_type = "audio"
    intent["presentation"] = _stamp_presentation_endpoint(
        {
            **pres,
            "type": pres_type,
            "from": "msg",
            "text": text,
        },
        intent,
    )


def _normalize_status(raw):
    text = str(raw or "").strip()
    return _STATUS_ALIASES.get(text, text)


def _stringify_step_outputs(step_outputs):
    if not isinstance(step_outputs, dict):
        return {}
    return {str(k): v for k, v in step_outputs.items()}


def _append_steps_timeline(intent, status, detail=""):
    steps = list(intent.get("steps") or [])
    steps.append(
        {
            "status": status,
            "intent_status": status,
            "at": time.time(),
            "detail": detail or "",
        }
    )
    intent["steps"] = steps


def _job_visible_to_edge(job, edge_id):
    """Claim/list visibility: per-step assignee, or a real pending_delivery hook."""
    if not edge_id:
        return False
    pending = job.get("pending_delivery") or {}
    if isinstance(pending, dict) and str(pending.get("edge_id") or "") == edge_id:
        return True
    for step in job.get("execution_plan") or []:
        if isinstance(step, dict) and str(step.get("assigned_edge_id") or "") == edge_id:
            return True
    return False


def _job_to_intent(job):
    if not job:
        return {}
    intent = dict(job)
    ident = intent.get("id", intent.get("intent_id"))
    intent["id"] = ident
    intent["intent_id"] = ident
    if intent.get("outputs") is not None and "exposed_outputs" not in intent:
        intent["exposed_outputs"] = intent["outputs"]
    if intent.get("ctx_param") is None and intent.get("context") is not None:
        intent["ctx_param"] = intent["context"]
    ctx = intent.get("ctx_param")
    if isinstance(ctx, dict):
        cleaned = {k: v for k, v in ctx.items() if v is not None}
        intent["ctx_param"] = cleaned
        intent["context"] = cleaned
        if not intent.get("source_context") and isinstance(cleaned.get("source_context"), dict):
            intent["source_context"] = cleaned["source_context"]
        if not intent.get("output_affinity") and isinstance(cleaned.get("output_affinity"), dict):
            intent["output_affinity"] = cleaned["output_affinity"]
        if not intent.get("session_id") and cleaned.get("session_id"):
            intent["session_id"] = cleaned["session_id"]
        if not intent.get("task_kind") and cleaned.get("task_kind"):
            intent["task_kind"] = cleaned["task_kind"]
        if not intent.get("dev_task") and isinstance(cleaned.get("dev_task"), dict):
            intent["dev_task"] = cleaned["dev_task"]
    intent.setdefault("status_log", [])
    intent.setdefault("execution_plan", [])
    intent.setdefault("step_log", [])
    intent.setdefault("steps", [])
    assemble_presentation(intent)
    notes = _planner_notes_for_intent(ident)
    intent["missing_capabilities"] = notes["missing_capabilities"]
    intent["better_capabilities"] = notes["better_capabilities"]
    if notes.get("cost_ms") is not None:
        intent["planner_cost_ms"] = notes["cost_ms"]
    if notes.get("has_review"):
        intent["planner_has_request_payload"] = bool(notes.get("has_request_payload"))
    intent.pop("assigned_edge_id", None)
    intent.pop("scheduler_node", None)
    intent.pop("available_capabilities", None)
    if not str(intent.get("text") or "").strip():
        try:
            reviews = brain_db.list_intent_reviews(ident)
        except Exception:
            reviews = []
        for row in reversed(reviews or []):
            recovered = str((row or {}).get("text") or "").strip()
            if recovered:
                intent["text"] = recovered
                src = str((row or {}).get("source") or "").strip()
                if src and not str(intent.get("source") or "").strip():
                    intent["source"] = src
                break
    return intent


def _planner_notes_for_intent(intent_id):
    empty = {
        "missing_capabilities": [],
        "better_capabilities": [],
        "cost_ms": None,
        "has_request_payload": False,
        "has_review": False,
    }
    if intent_id in (None, ""):
        return empty
    try:
        rows = brain_db.list_intent_reviews(intent_id)
    except Exception:
        return empty
    if not rows:
        return empty
    latest = rows[-1]
    empty["has_review"] = True
    if latest.get("cost_ms") is not None:
        empty["cost_ms"] = int(latest["cost_ms"])
    empty["has_request_payload"] = latest.get("request_payload") is not None
    parsed = latest.get("parsed_json")
    if not isinstance(parsed, dict):
        parsed = extract_llm_output(latest.get("raw_response"))
    if not isinstance(parsed, dict):
        return empty
    empty["missing_capabilities"] = _as_capability_notes(parsed.get("missing_capabilities"))
    empty["better_capabilities"] = _as_capability_notes(parsed.get("better_capabilities"))
    return empty


def _save_intent(intent):
    if not intent:
        return
    now = time.time()
    intent.setdefault("created_at", now)
    intent["updated_at"] = now
    if intent.get("exposed_outputs") is not None:
        intent["outputs"] = intent["exposed_outputs"]
    if intent.get("ctx_param") is not None:
        intent["context"] = intent.get("ctx_param")
    elif intent.get("context") is not None:
        intent["ctx_param"] = intent["context"]
    if intent.get("step_outputs") is not None:
        intent["step_outputs"] = _stringify_step_outputs(intent["step_outputs"])
    intent.pop("assigned_edge_id", None)
    intent.pop("scheduler_node", None)
    ident = intent.get("intent_id") or intent.get("id")
    if ident is not None:
        intent["job_id"] = str(ident)
    if intent.get("intent_base_time") and not intent.get("base_time"):
        intent["base_time"] = intent["intent_base_time"]
    brain_db.put_job(intent)


def list_intents():
    out = []
    for job in brain_db.list_jobs():
        intent = _job_to_intent(job)
        if intent:
            ident = intent.get("intent_id") or intent.get("id")
            try:
                ident_int = int(ident)
            except (TypeError, ValueError):
                ident_int = ident
            _maybe_finalize_intent_after_step(ident_int, intent)
        out.append(intent)
    return out


def update_intent_status(intent_id, intent_status, msg=None):
    intent = get_intent(intent_id)
    if not intent:
        return
    intent_status = _normalize_status(intent_status)
    current = _normalize_status(str(intent.get("status") or ""))
    if current in _TERMINAL_STATUSES and intent_status not in _TERMINAL_STATUSES:
        return
    if intent.get("status_log") is None:
        intent["status_log"] = []
    if intent.get("status") != intent_status:
        intent["status"] = intent_status
        entry = {
            "status": intent_status,
            "ts": int(time.time() * 1000),
        }
        if msg:
            entry["msg"] = msg
            intent["msg"] = msg
            if intent_status == "failed":
                intent["error"] = msg
        intent["status_log"].append(entry)
        _append_steps_timeline(intent, intent_status, msg or "")
        _save_intent(intent)


def get_intent(intent_id):
    intent = _job_to_intent(brain_db.get_job(intent_id))
    if intent:
        ident = intent.get("intent_id") or intent.get("id")
        try:
            ident_int = int(ident)
        except (TypeError, ValueError):
            ident_int = ident
        _maybe_finalize_intent_after_step(ident_int, intent)
    return intent


def mark_intent_failed(intent_id, msg):
    update_intent_status(intent_id, "failed", msg=msg)


def _record_intent_review(
    intent_id,
    *,
    text=None,
    raw=None,
    plan=None,
    parsed=None,
    error=None,
    session_id=None,
    source=None,
    edge_id=None,
    cost_ms=None,
    planner=None,
    model=None,
    request_payload=None,
    response_json=None,
):
    try:
        planner_name = planner or "ark"
        if model is None:
            model = "" if planner_name != "ark" else MODEL_ID
        brain_db.put_intent_review(
            {
                "intent_id": intent_id,
                "session_id": session_id,
                "text": text,
                "source": source,
                "edge_id": edge_id,
                "planner": planner_name,
                "model": model,
                "cost_ms": cost_ms,
                "raw_response": raw,
                "parsed_json": parsed,
                "execution_plan": plan,
                "error": error,
                "request_payload": request_payload,
                "response_json": response_json,
            }
        )
    except Exception:
        log.exception("put_intent_review failed")


def _ark_call_fields(ark, *, started):
    if isinstance(ark, dict):
        ans = ark.get("ans")
        cost_ms = ark.get("cost_ms")
        if cost_ms is None:
            cost_ms = int((time.time() - started) * 1000)
        return {
            "ans": ans,
            "cost_ms": int(cost_ms),
            "request_payload": ark.get("request_payload"),
            "response_json": ark.get("response_json"),
        }
    return {
        "ans": ark,
        "cost_ms": int((time.time() - started) * 1000),
        "request_payload": None,
        "response_json": None,
    }


# ====================== 串行消费后台线程（核心排队逻辑） ======================
def _enqueue_qwen_shadow(task, intent):
    """Queue a compare-only Qwen job. Never used for execution enqueue."""
    if not qwen_planner_enabled():
        return
    try:
        qwen_task_queue.put_nowait(
            {
                "question": task.get("question") or "",
                "session_id": task.get("session_id"),
                "source": task.get("source"),
                "edge_id": task.get("edge_id"),
                "intent_id": task.get("intent_id"),
                "intent_snap": dict(intent or {}),
            }
        )
    except queue.Full:
        log.warning("qwen shadow queue full, skip intent=%s", task.get("intent_id"))


def _process_qwen_task(task):
    """Shadow planner only: call Qwen and write intent_reviews. Does not enqueue."""
    holder = {}
    user_q = str(task.get("question") or "")
    snap = task.get("intent_snap") if isinstance(task.get("intent_snap"), dict) else {}
    try:
        holder["result"] = call_qwen_planner(user_q, intent=snap)
    except Exception:
        log.exception("qwen shadow planner failed")
        holder["exc"] = traceback.format_exc()
    _record_qwen_shadow_review(
        task.get("intent_id"),
        text=user_q,
        session_id=task.get("session_id"),
        source=task.get("source"),
        edge_id=task.get("edge_id"),
        intent=snap,
        holder=holder,
    )


def _should_skip_llm_planner(intent) -> bool:
    if not intent:
        return False
    if _is_dev_task_job(intent):
        return True
    if str(intent.get("source") or "").strip().lower() == "dev":
        return True
    return False


def _process_llm_task(task):
    user_q, session_id, user_id, intent_id = task["question"], task["session_id"], task["user_id"], task["intent_id"]
    log.info("get question: %s %s %s %s", user_q, session_id, user_id, intent_id)
    intent = get_intent(intent_id)
    if _should_skip_llm_planner(intent):
        log.info("skip llm planner for dev_task intent=%s", intent_id)
        return
    started = time.time()
    ark = None
    try:
        _enqueue_qwen_shadow(task, intent)
    except Exception:
        log.exception("enqueue qwen shadow failed")
    try:
        with llm_running_lock:
            ark = call_ark(
                user_q,
                session_id,
                user_id,
                intent_id,
                intent.get("intent_base_time"),
                intent=intent,
            )
            fields = _ark_call_fields(ark, started=started)
            ans = fields["ans"]
            cost_ms = fields["cost_ms"]
            log.info("get ans:%s", ans)
            plan = sanitize_execution_plan(extract_llm_plan(ans), intent)
            log.info("get llm plan:%s", json.dumps(plan))
            execution_plan = make_execution_plan(plan)
            log.info("get execution plan:%s", json.dumps(execution_plan))
            stored = get_intent(intent_id)
            pres_plan = extract_llm_presentation(ans)
            if pres_plan:
                stored["presentation"] = pres_plan
                _save_intent(stored)
            do_execution_plan(intent_id, execution_plan)
            log.info("do execution plan")
            stored = get_intent(intent_id)
            stored_plan = stored.get("execution_plan") or []
            llm_out = extract_llm_output(ans)
            notes = extract_llm_capability_notes(ans, catalog=_capability_registry_for_prompt())
            fail_msg = None
            if not stored_plan:
                if str(ans).strip() == "__ARK_HTTP_401__":
                    fail_msg = "规划服务 401，检查 ARK_API_KEY"
                else:
                    fail_msg = _empty_plan_failure_msg(notes, llm_out)
                mark_intent_failed(intent_id, fail_msg)
                stored = get_intent(intent_id)
                _apply_failure_presentation(stored, fail_msg)
                _save_intent(stored)
            else:
                update_intent_status(intent_id, "intent_parsed")
            parsed = {
                "goal": llm_out.get("goal"),
                "reason": llm_out.get("reason"),
                "required_capabilities": llm_out.get("required_capabilities") or [],
                "plan": plan,
                "presentation": pres_plan or llm_out.get("presentation") or {},
                "missing_capabilities": notes["missing_capabilities"],
                "better_capabilities": notes["better_capabilities"],
            }
            _record_intent_review(
                intent_id,
                text=user_q,
                raw=ans,
                parsed=parsed,
                plan=stored_plan,
                session_id=session_id,
                source=task.get("source"),
                edge_id=task.get("edge_id"),
                cost_ms=cost_ms,
                error=fail_msg,
                request_payload=fields["request_payload"],
                response_json=fields["response_json"],
            )

    except Exception as e:
        log.exception("任务处理异常: %s", e)
        err_stack = traceback.format_exc()
        log.error("堆栈文本:\n%s", err_stack)

        mark_intent_failed(intent_id, str(e) or "plan failed")
        fields = _ark_call_fields(ark, started=started)
        _record_intent_review(
            intent_id,
            text=user_q,
            raw=fields["ans"],
            error=err_stack,
            session_id=session_id,
            source=task.get("source"),
            edge_id=task.get("edge_id"),
            cost_ms=fields["cost_ms"],
            request_payload=fields["request_payload"],
            response_json=fields["response_json"],
        )


def llm_worker():
    global capability_edge_mapping
    log.info("llm worker started, scan task begin..")
    while True:
        task = task_queue.get()
        try:
            _process_llm_task(task)
        finally:
            task_queue.task_done()


def qwen_llm_worker():
    log.info("qwen llm worker started, scan task begin..")
    while True:
        task = qwen_task_queue.get()
        try:
            _process_qwen_task(task)
        except Exception:
            log.exception("qwen shadow task failed")
        finally:
            qwen_task_queue.task_done()

# 启动后台工作线程（单测可 BRAIN_SKIP_LLM_WORKER=1 同时跳过 Ark 与 Qwen worker）
if os.environ.get("BRAIN_SKIP_LLM_WORKER") != "1":
    worker_thread = threading.Thread(target=llm_worker, daemon=True)
    worker_thread.start()
    qwen_worker_thread = threading.Thread(
        target=qwen_llm_worker, name="qwen-llm-worker", daemon=True
    )
    qwen_worker_thread.start()

ensure_poller_started()

# ====================== 构造DuerOS标准返回报文 ======================
def quick_speak(text, lazy_answer=True):
    if lazy_answer:
        return json.dumps({
            "response" : {
                "output" : "正在为你查询豆包，你可以稍后再次提问查看结果"
            }
        })
    else:
        return json.dumps({
            "response" : {
                "output" : f"以下是来自豆包的回答: {text}"
            }
        })


def push_speech_to_dueros(session_id, user_id, speech_text):
    """会话内主动推送语音给小度音箱"""
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + SKILL_ACCESS_TOKEN
    }
    push_body = {
        "applicationId": SKILL_APP_ID,
        "userId": user_id,
        "sessionId": session_id,
        "outputSpeech": {
            "type": "PlainText",
            "text": speech_text
        }
    }
    try:
        post_data = json.dumps(push_body).encode("utf-8")
        req = urllib.request.Request(DUEROS_PUSH_URL, data=post_data, headers=headers)
        resp = urllib.request.urlopen(req, timeout=3)
        return True
    except Exception as e:
        # 推送失败兜底，存入缓存让用户手动查询
        log.exception("推送失败：%s", e)
        return False


bp = Blueprint("gopro_photos", __name__)
UPLOAD_PATH = "/api/v1/photos/upload"
_default_upload = _HERE / "gopropics"
if not _default_upload.is_dir() and _HERE.name == "server":
    _default_upload = _HERE.parent / "gopropics"
if not _default_upload.is_dir():
    _default_upload = _HERE / "uploads" / "gopro"
UPLOAD_DIR = Path(os.environ.get("BRAIN_UPLOAD_DIR") or _default_upload)

_INTENT_ORIGINS = ("lan", "cloud")


def instance_intent_origin():
    """Which Brain this process is: lan (local/dev) or cloud (cloud-server)."""
    raw = (os.environ.get("BRAIN_ORIGIN") or "").strip().lower()
    if raw in _INTENT_ORIGINS:
        return raw
    try:
        here = str(_HERE.resolve())
    except OSError:
        here = ""
    if here.startswith("/root/chat-gateway") or "/root/chat-gateway/" in here:
        return "cloud"
    return "lan"


def resolve_intent_origin(value=None):
    """Receiving Brain origin is authoritative. Client hints are ignored."""
    return instance_intent_origin()


def _brain_public_base_url() -> str:
    """Base URL for this Brain as seen by phones / agent-bridge attachment fetch."""
    env = (os.environ.get("BRAIN_PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if env:
        return env
    try:
        root = str(request.url_root or "").strip().rstrip("/")
        if root:
            return root
    except RuntimeError:
        pass
    return ""


def update_intent(intent_id, intent_record):
    intent = get_intent(intent_id)
    if not intent:
        return
    intent.update(intent_record)
    _save_intent(intent)


def append_intent_step_log(intent_id, step_record):
    intent = get_intent(intent_id)
    if not intent:
        return
    step_log = intent.get("step_log") or []
    step_log.append(step_record)
    intent["step_log"] = step_log
    _save_intent(intent)


def new_intent(intent_record):
    intent_id = brain_db.next_intent_id()
    now = time.time()
    intent_record["id"] = intent_id
    intent_record["intent_id"] = intent_id
    intent_record["job_id"] = str(intent_id)
    intent_record["intent_origin"] = resolve_intent_origin(
        intent_record.get("intent_origin")
    )
    intent_record.setdefault("created_at", now)
    if intent_record.get("intent_base_time") and not intent_record.get("base_time"):
        intent_record["base_time"] = intent_record["intent_base_time"]
    if intent_record.get("status"):
        intent_record["status"] = _normalize_status(intent_record["status"])
    _append_steps_timeline(
        intent_record,
        intent_record.get("status") or "intent_received",
        intent_record.get("text") or "",
    )
    _save_intent(intent_record)
    return intent_id


def _observe_intent_complexity(text, intent_id=None):
    """Side-channel classify. Must never raise into intake / planner."""
    try:
        result = classify_intent_complexity(text, intent_id=intent_id)
    except Exception:
        log.exception("intent_complexity classify failed")
        return None
    log.info(
        "intent_complexity intent_id=%s class=%s score=%s",
        intent_id,
        result.get("classification"),
        result.get("score"),
    )
    try:
        put_event = getattr(brain_db, "put_intent_classification_event", None)
        if callable(put_event):
            put_event(result)
    except Exception:
        log.exception("put_intent_classification_event failed")
    return result


def _classification_public_payload(result):
    if not isinstance(result, dict):
        return None
    return {
        "classification": result.get("classification"),
        "score": result.get("score"),
        "features": result.get("features") or {},
        "candidates": result.get("candidates") or [],
        "classifier_version": result.get("classifier_version"),
        "timestamp": result.get("timestamp"),
    }


def _log_music_shortcut_timing(intent_id, plan, timing: dict) -> None:
    caps = [
        str(step.get("capability") or "")
        for step in (plan or [])
        if isinstance(step, dict)
    ]
    music_caps = [c for c in caps if c.startswith("music.")]
    if not music_caps:
        return
    log.info(
        "music.shortcut intent=%s cap=%s match_ms=%s plan_ms=%s enqueue_ms=%s",
        intent_id,
        music_caps[0],
        timing.get("match"),
        timing.get("plan"),
        timing.get("enqueue"),
    )


def _dispatch_shortcut_intent(
    intent_id,
    text,
    intercepted: InterceptResult,
    *,
    source,
    edge_id,
    intent_origin,
    ctx_param,
    reply,
):
    intent = get_intent(intent_id)
    if not intent:
        return jsonify(ok=False, error="intent not found"), 404
    intent["task_kind"] = "shortcut"
    if intercepted.mode:
        intent["shortcut_mode"] = intercepted.mode
    ctx = dict(intent.get("ctx_param") or intent.get("context") or {})
    ctx["task_kind"] = "shortcut"
    if intercepted.mode:
        ctx["shortcut_mode"] = intercepted.mode
    intent["ctx_param"] = ctx
    intent["context"] = ctx
    if intercepted.kind in ("enter_mode", "exit_mode"):
        apply_mode_event(intercepted, intent=intent)
    if isinstance(intercepted.presentation, dict) and intercepted.presentation:
        intent["presentation"] = intercepted.presentation
    _save_intent(intent)
    t_plan = time.perf_counter()
    plan = _prepare_shortcut_execution_plan(intercepted.plan, intent)
    execution_plan = make_execution_plan(plan)
    plan_ms = int(round((time.perf_counter() - t_plan) * 1000))
    meta = intercepted.planner_meta if isinstance(intercepted.planner_meta, dict) else {}
    timing_meta = meta.get("timing") if isinstance(meta.get("timing"), dict) else {}
    try:
        match_ms = int(timing_meta.get("match") or 0)
    except (TypeError, ValueError):
        match_ms = 0
    review_parsed = {
        "goal": meta.get("goal"),
        "reason": "shortcut intercept",
        "required_capabilities": [],
        "plan": plan,
        "presentation": intercepted.presentation,
        "missing_capabilities": [],
        "better_capabilities": [],
    }
    enqueue_ms = 0
    t_enq = time.perf_counter()
    try:
        do_execution_plan(intent_id, execution_plan)
        enqueue_ms = int(round((time.perf_counter() - t_enq) * 1000))
    except (CaptureUploadSplitError, AmbiguousCapabilityEdge) as e:
        enqueue_ms = int(round((time.perf_counter() - t_enq) * 1000))
        fail_msg = str(e)
        mark_intent_failed(intent_id, fail_msg)
        intent = get_intent(intent_id)
        if intent:
            _apply_failure_presentation(intent, fail_msg)
            _save_intent(intent)
        timing = {"match": match_ms, "plan": plan_ms, "enqueue": enqueue_ms}
        _log_music_shortcut_timing(intent_id, plan, timing)
        _record_intent_review(
            intent_id,
            plan=[],
            error=fail_msg,
            text=text,
            raw=json.dumps(meta, ensure_ascii=False),
            parsed=review_parsed,
            session_id=intent.get("session_id") if intent else None,
            source=source,
            edge_id=edge_id,
            cost_ms=0,
            planner="shortcut",
            request_payload={
                "shortcut": True,
                "kind": intercepted.kind,
                "mode": intercepted.mode,
                "timing": timing,
            },
            response_json=meta,
        )
        return jsonify(
            ok=True,
            text=text,
            source=source,
            edge_id=edge_id,
            intent_origin=intent_origin,
            reply=fail_msg,
            intent_id=intent_id,
            intent_status="failed",
            task_kind="shortcut",
            shortcut_mode=intercepted.mode,
            error=fail_msg,
            asset_ref=ctx_param.get("asset_ref"),
        )
    timing = {"match": match_ms, "plan": plan_ms, "enqueue": enqueue_ms}
    _log_music_shortcut_timing(intent_id, plan, timing)
    update_intent_status(intent_id, "intent_parsed")
    _record_intent_review(
        intent_id,
        plan=get_intent(intent_id).get("execution_plan") or [],
        error=None,
        text=text,
        raw=json.dumps(meta, ensure_ascii=False),
        parsed=review_parsed,
        session_id=intent.get("session_id"),
        source=source,
        edge_id=edge_id,
        cost_ms=0,
        planner="shortcut",
        request_payload={
            "shortcut": True,
            "kind": intercepted.kind,
            "mode": intercepted.mode,
            "timing": timing,
        },
        response_json=meta,
    )
    return jsonify(
        ok=True,
        text=text,
        source=source,
        edge_id=edge_id,
        intent_origin=intent_origin,
        reply=reply,
        intent_id=intent_id,
        intent_status="intent_parsed",
        task_kind="shortcut",
        shortcut_mode=intercepted.mode,
        asset_ref=ctx_param.get("asset_ref"),
    )


@app.route("/api/v1/mode", methods=["GET"])
def get_active_mode_api():
    mode = None
    try:
        resolve = getattr(brain_db, "resolve_active_mode", None)
        if callable(resolve):
            mode = resolve()
    except Exception:
        log.exception("resolve_active_mode failed")
    events = []
    try:
        list_events = getattr(brain_db, "list_global_events", None)
        if callable(list_events):
            raw_limit = request.args.get("limit", "10")
            try:
                limit = max(1, min(int(raw_limit), 100))
            except (TypeError, ValueError):
                limit = 10
            events = list_events(kind="mode", limit=limit)
    except Exception:
        log.exception("list_global_events failed")
    return jsonify(ok=True, mode=mode, active_mode=mode, events=events)


@app.route("/api/v1/intent", methods=["POST", "GET"])
def dispatch_intent():
    text = "default"
    source = "text"
    edge_id = "11111"
    session_id = ""
    ctx_param = {}
    data = {}
    intent_base_time = int(time.time() * 1000)
    if request.method == 'GET':
        text = request.args.get("command", "default")
        source = request.args.get("source", "text")
        edge_id = str(
            request.args.get("edge_id") or request.args.get("participant_id") or ""
        ).strip()
        session_id = request.args.get("session_id", "")
    else:
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return jsonify(ok=False, error="JSON object required"), 400

        text = str(data.get("text") or "").strip()
        if not text:
            return jsonify(ok=False, error="text is required"), 400

        source = str(data.get("source") or "text").strip().lower() or "text"
        if source not in ("text", "voice", "visual", "dev"):
            source = "text"
        edge_id = str(
            data.get("edge_id") or data.get("participant_id") or ""
        ).strip()
        session_id = str(data.get("session_id") or "").strip()

        # Optional Visual Input: Image Asset attached at issue time (Intent Source).
        raw_ref = data.get("asset_ref")
        if raw_ref is None and isinstance(data.get("context"), dict):
            raw_ref = data["context"].get("asset_ref")
        if raw_ref is None and isinstance(data.get("ctx_param"), dict):
            raw_ref = data["ctx_param"].get("asset_ref")
        ref = _as_asset_ref(raw_ref)
        if ref:
            ctx_param["asset_ref"] = ref
            if source == "text":
                source = "visual"

        # Optional named Audio Inputs (e.g. pronunciation.assess): reference_audio +
        # student_audio AssetRefs attached at issue time. Each is granted read access
        # so the executing Edge can materialize them. Surfaced to the planner via
        # ctx_param so it can wire $reference_audio / $student_audio into the step.
        for _audio_key in ("reference_audio", "student_audio"):
            _raw_audio = data.get(_audio_key)
            if _raw_audio is None and isinstance(data.get("context"), dict):
                _raw_audio = data["context"].get(_audio_key)
            if _raw_audio is None and isinstance(data.get("ctx_param"), dict):
                _raw_audio = data["ctx_param"].get(_audio_key)
            _audio_ref = _as_asset_ref(_raw_audio)
            if _audio_ref:
                _audio_ref["type"] = "audio"
                ctx_param[_audio_key] = _audio_ref

    rejected = _issuer_post_reject(edge_id)
    if rejected is not None:
        return rejected

    if _is_wake_ack_utterance(text):
        return (
            jsonify(
                ok=False,
                error="唤醒回复语不进入意图理解",
            ),
            400,
        )

    # TODO: 在这里接 doubao_chat / 你的大脑
    reply = f"已收到指令（{source}）：{text}"
    # 无缓存，加入排队队列
    if request.method == "GET":
        client_origin = request.args.get("intent_origin")
    else:
        client_origin = data.get("intent_origin")
    intent_origin = resolve_intent_origin(client_origin)
    intent_body = {
        "status": "intent_received",
        "text": text,
        "source": source,
        "edge_id": edge_id,
        "intent_origin": intent_origin,
        "intent_base_time": intent_base_time,
        "base_time": intent_base_time,
        "status_log": [
            {
                'status' : "intent_received",
                'ts': int(time.time() * 1000)
            }
        ]
    }
    source_context = _build_source_context(edge_id, source, data)
    if source_context:
        ctx_param["source_context"] = source_context
        intent_body["source_context"] = source_context
    if edge_id:
        affinity = {"participant_id": edge_id, "reason": "input_source"}
        ctx_param["output_affinity"] = affinity
        intent_body["output_affinity"] = affinity
    if session_id:
        ctx_param["session_id"] = session_id
        intent_body["session_id"] = session_id
    if ctx_param:
        intent_body["ctx_param"] = ctx_param
        intent_body["context"] = ctx_param
    if source == "dev":
        view = submit_agent_task(text)
        return jsonify(
            ok=True,
            text=text,
            source=source,
            edge_id=edge_id,
            intent_origin=intent_origin,
            reply=f"已下发开发任务：{text}",
            intent_id=view.get("task_id"),
            intent_status=view.get("status"),
            task_kind="dev_task",
            asset_ref=ctx_param.get("asset_ref"),
            **view,
        )
    intent_id = new_intent(intent_body)
    _observe_intent_complexity(text, intent_id=intent_id)
    if ctx_param.get("asset_ref") and callable(getattr(brain_db, "put_asset_grant", None)):
        aid = str((ctx_param["asset_ref"] or {}).get("asset_id") or "").strip()
        if aid:
            try:
                brain_db.put_asset_grant(
                    {
                        "asset_id": aid,
                        "intent_id": str(intent_id),
                        "execution_id": str(intent_id),
                        "capability_id": "visual.input",
                        "permission": "read",
                    }
                )
            except Exception:
                log.exception("visual input asset grant failed intent=%s asset=%s", intent_id, aid)
    # Grant read access for named audio inputs (pronunciation.assess etc.).
    if callable(getattr(brain_db, "put_asset_grant", None)):
        for _audio_key in ("reference_audio", "student_audio"):
            _audio_ref = ctx_param.get(_audio_key)
            if not isinstance(_audio_ref, dict):
                continue
            _aid = str((_audio_ref.get("asset_id") or "").strip())
            if not _aid:
                continue
            try:
                brain_db.put_asset_grant(
                    {
                        "asset_id": _aid,
                        "intent_id": str(intent_id),
                        "execution_id": str(intent_id),
                        "capability_id": "pronunciation.assess",
                        "permission": "read",
                    }
                )
            except Exception:
                log.exception(
                    "audio input asset grant failed intent=%s key=%s asset=%s",
                    intent_id, _audio_key, _aid,
                )
    intent_snap = get_intent(intent_id)
    intercepted = shortcut_intercept(text, intent=intent_snap)
    if intercepted is not None:
        return _dispatch_shortcut_intent(
            intent_id,
            text,
            intercepted,
            source=source,
            edge_id=edge_id,
            intent_origin=intent_origin,
            ctx_param=ctx_param,
            reply=reply,
        )
    try:
        task_queue.put_nowait({
            "question": text,
            "session_id": session_id,
            "user_id": "222222",
            "edge_id": edge_id,
            "source": source,
            "intent_id" : intent_id,
        })
        queue_size = task_queue.qsize()
        log.info("正在排队生成训练计划，当前排队%s条，稍后重新提问查看结果", queue_size)
    except queue.Full:
        log.warning("当前咨询人数较多，请稍后再试")

    return jsonify(
        ok=True,
        text=text,
        source=source,
        edge_id=edge_id,
        intent_origin=intent_origin,
        reply=reply,
        intent_id=intent_id,
        intent_status="intent_received",
        asset_ref=ctx_param.get("asset_ref"),
    )


@app.route("/api/v1/intent_classify", methods=["POST"])
def classify_intent_api():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify(ok=False, error="JSON object required"), 400
    text = str(data.get("text") or "").strip()
    if not text:
        return jsonify(ok=False, error="text is required"), 400
    intent_id = data.get("intent_id")
    result = _observe_intent_complexity(text, intent_id=intent_id)
    if result is None:
        return jsonify(ok=False, error="classification failed"), 500
    payload = _classification_public_payload(result) or {}
    body = {"ok": True, **payload}
    if result.get("intent_id") is not None:
        body["intent_id"] = result.get("intent_id")
    return jsonify(body)


@app.route("/api/v1/intent_classify/stats", methods=["GET"])
def classify_intent_stats_api():
    try:
        stats_fn = getattr(brain_db, "list_intent_classification_stats", None)
        stats = stats_fn() if callable(stats_fn) else {}
    except Exception:
        log.exception("list_intent_classification_stats failed")
        return jsonify(ok=False, error="stats unavailable"), 500
    if not isinstance(stats, dict):
        stats = {}
    return jsonify(ok=True, **stats)


@app.route("/api/v1/voice/wake", methods=["POST"])
def dispatch_voice_wake():
    """Wake reply is local TTS. Do not create an intent or run understand."""
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify(ok=False, error="JSON object required"), 400
    event = str(data.get("event") or "wake").strip().lower() or "wake"
    if event != "wake":
        return jsonify(ok=False, error="only event=wake is accepted"), 400
    edge_id = str(
        data.get("edge_id") or data.get("participant_id") or ""
    ).strip()
    rejected = _voice_stream_wake_reject(edge_id)
    if rejected is not None:
        return rejected

    ack = _wake_ack_text()
    log.info("voice wake ack is local echo; no intent edge=%s ack=%r", edge_id, ack)
    return jsonify(
        ok=True,
        text=ack,
        source="voice",
        edge_id=edge_id,
        local=True,
        intent_id=None,
        echo=ack,
    )


@app.route("/api/v1/voice/settings", methods=["GET"])
def voice_settings_view():
    from voice_settings import public_settings

    return jsonify(public_settings())


@app.route("/api/v1/admin/voice/settings", methods=["GET"])
def admin_get_voice_settings():
    denied = _admin_auth_error()
    if denied:
        return denied
    from voice_settings import public_settings

    return jsonify(public_settings())


@app.route("/api/v1/admin/voice/settings", methods=["PUT", "POST"])
def admin_put_voice_settings():
    denied = _admin_auth_error()
    if denied:
        return denied
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return jsonify(ok=False, error="JSON object required"), 400
    ack = str(body.get("wake_ack") or "").strip()
    if not ack:
        return jsonify(ok=False, error="wake_ack required"), 400
    from voice_settings import set_wake_ack

    try:
        saved = set_wake_ack(ack)
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 400
    except RuntimeError as exc:
        return jsonify(ok=False, error=str(exc)), 501
    _record_admin_op(
        action="voice_settings_update",
        extra={"wake_ack": saved},
        summary=f"唤醒应答改为「{saved}」",
    )
    return jsonify(ok=True, wake_ack=saved)


@app.route("/api/v1/intent_detail", methods=["GET"])
def get_intent_detail():
    intent_id_str = request.args.get("intent_id", "")
    try:
        intent_id = int(intent_id_str)
    except:
        intent_id = 0
    intent = get_intent(intent_id)
    log.info(
        "intent_detail intent_id=%s status=%s",
        intent_id,
        (intent or {}).get("status"),
    )

    if not intent:
        return jsonify(
            err_msg="intent not exist"
        ), 404

    return jsonify(intent)


INTENTS_LIST_MAX = 5


def _list_jobs_for_issuer(pid, before_id, limit):
    fn = getattr(brain_db, "list_jobs_for_participant", None)
    if callable(fn):
        return fn(pid, before_id=before_id, limit=limit)
    rows = []
    for job in brain_db.list_jobs():
        if str(job.get("edge_id") or "").strip() != pid:
            continue
        try:
            iid = int(job.get("intent_id") if job.get("intent_id") is not None else job.get("id"))
        except (TypeError, ValueError):
            continue
        if before_id is not None and iid >= before_id:
            continue
        rows.append(job)
        if len(rows) >= limit:
            break
    return rows


@app.route("/api/v1/intents", methods=["GET"])
def list_intents_for_participant():
    pid = str(
        request.args.get("participant_id") or request.args.get("edge_id") or ""
    ).strip()
    if not pid:
        return jsonify(ok=False, error="participant_id is required"), 400
    before_raw = request.args.get("before_id")
    before_id = None
    if before_raw not in (None, ""):
        try:
            before_id = int(before_raw)
        except (TypeError, ValueError):
            return jsonify(ok=False, error="before_id must be an integer"), 400
        if before_id < 1:
            return jsonify(ok=False, error="before_id must be >= 1"), 400
    limit = INTENTS_LIST_MAX
    if request.args.get("limit") not in (None, ""):
        try:
            limit = int(request.args.get("limit"))
        except (TypeError, ValueError):
            return jsonify(ok=False, error="limit must be an integer"), 400
    limit = max(1, min(limit, INTENTS_LIST_MAX))
    jobs = _list_jobs_for_issuer(pid, before_id, limit)
    intents = [_job_to_intent(job) for job in jobs]
    ids = []
    for item in intents:
        try:
            ids.append(int(item.get("intent_id") or item.get("id")))
        except (TypeError, ValueError):
            pass
    next_before = min(ids) if ids else None
    return jsonify(
        ok=True,
        intents=intents,
        participant_id=pid,
        before_id=before_id,
        limit=limit,
        next_before_id=next_before,
        exhausted=len(intents) < limit,
    )


@app.route("/api/v1/intent/<intent_id>", methods=["GET"])
def get_intent_by_path(intent_id):
    try:
        intent_id_int = int(intent_id)
    except Exception:
        intent_id_int = intent_id
    intent = get_intent(intent_id_int)
    if not intent:
        return jsonify(err_msg="intent not exist"), 404
    return jsonify(intent)


@app.route("/api/v1/intent_feedback", methods=["GET", "POST"])
def intent_user_feedback():
    if request.method == "GET":
        intent_raw = request.args.get("intent_id", "")
        pid = str(
            request.args.get("participant_id") or request.args.get("edge_id") or ""
        ).strip()
        if not pid:
            return jsonify(ok=False, error="participant_id is required"), 400
        try:
            intent_id = int(intent_raw)
        except (TypeError, ValueError):
            return jsonify(ok=False, error="intent_id must be an integer"), 400
        row = brain_db.get_intent_user_feedback(intent_id, pid)
        if not row:
            return jsonify(ok=True, feedback=None)
        return jsonify(ok=True, feedback=row)

    body = request.get_json(silent=True) or {}
    try:
        row = brain_db.upsert_intent_user_feedback(body)
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 400
    except sqlite3.OperationalError as exc:
        if "intent_user_feedback" in str(exc):
            return jsonify(ok=False, error="intent_user_feedback table missing; run DB migration 015"), 503
        raise
    return jsonify(ok=True, feedback=row)


@app.route("/health", methods=["GET"])
def health():
    return jsonify(
        {
            "ok": True,
            "app": "brain",
            "brain_origin": instance_intent_origin(),
            "db": str(brain_db.db_path()),
            "registered": brain_db.registration_count(),
            "jobs": brain_db.job_count(),
            "pending_intents": brain_db.queue_count(),
        }
    )


@app.route("/api/v1/ping", methods=["GET", "HEAD"])
@app.route("/ping", methods=["GET", "HEAD"])
def ping():
    """Lightweight reachability probe for Runtime edges; also exposes server clock for sync.

    Optional ``client_time_ms`` (query) echoes and returns ``skew_ms`` = server − client.
    """
    now = time.time()
    server_time_ms = int(now * 1000)
    payload = {
        "ok": True,
        "app": "brain",
        "server_time_ms": server_time_ms,
        "server_time": now,
    }
    raw = request.args.get("client_time_ms")
    if raw is not None and str(raw).strip() != "":
        try:
            client_time_ms = int(raw)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "client_time_ms must be an integer"}), 400
        payload["client_time_ms"] = client_time_ms
        payload["skew_ms"] = server_time_ms - client_time_ms
    if request.method == "HEAD":
        return "", 200
    return jsonify(payload)


_PENDING_STEP_ABANDONED_MSG = "未执行：前序步骤失败"

# Capture produces a local capture_ref; upload (asset.upload) turns it into an Asset.
_UPLOAD_STEP_CAPABILITIES = frozenset({"asset.upload"})
_CAPTURE_STEP_CAPABILITIES = frozenset(
    {
        "camera.capture",
        "camera.take_video",
        "take_video",
        "document.scan",
        "visual.input",
        "camera.capture_and_upload",
    }
)


def _step_status_int(step) -> int:
    try:
        return int((step or {}).get("status") or 0)
    except (TypeError, ValueError):
        return 0


def _capture_succeeded_before(plan, failed_step) -> bool:
    """True if a capture/scan step succeeded (status=2) before the failed step."""
    try:
        fail_n = int((failed_step or {}).get("step") or 0)
    except (TypeError, ValueError):
        return False
    for step in plan or []:
        if not isinstance(step, dict):
            continue
        try:
            n = int(step.get("step") or 0)
        except (TypeError, ValueError):
            continue
        if n >= fail_n:
            continue
        cap = str(step.get("capability") or "").strip()
        if cap in _CAPTURE_STEP_CAPABILITIES and _step_status_int(step) == 2:
            return True
    return False


def _upload_failure_msg(plan, failed_step, msg):
    """Upload failed after a successful capture: say so honestly.

    The capture already landed in the device inbox, so the user should hear
    "拍照成功，已存本机" plus the real upload failure — never "拍照失败".
    """
    text = str(msg or "").strip()
    if not _capture_succeeded_before(plan, failed_step):
        return text
    if text.startswith("拍照成功"):
        return text
    if "上传" in text or "upload" in text.lower():
        return f"拍照成功，照片已保存在本机；但{text}"
    return f"拍照成功，照片已保存在本机；但上传失败：{text}"


def _plan_steps_all_terminal(plan) -> bool:
    if not plan:
        return False
    for step in plan:
        if _step_status_int(step) not in _TERMINAL_STEP_STATUSES:
            return False
    return True


def _abandon_pending_plan_steps(intent, *, reason: str) -> None:
    """Mark non-terminal successor steps failed so the job cannot hang waiting on them."""
    ts = int(time.time() * 1000)
    step_log = list(intent.get("step_log") or [])
    for step in intent.get("execution_plan") or []:
        if not isinstance(step, dict):
            continue
        if _step_status_int(step) in _TERMINAL_STEP_STATUSES:
            continue
        step["status"] = 3
        step["msg"] = reason
        rec = {
            "step": step.get("step"),
            "status": 3,
            "ts": ts,
            "msg": reason,
        }
        actor = str(step.get("assigned_edge_id") or "").strip()
        if actor:
            rec["edge_id"] = actor
        step_log.append(rec)
    intent["step_log"] = step_log


def _maybe_finalize_intent_after_step(intent_id_int, intent) -> None:
    """Fail-fast on any failed step; succeed only when every step is terminal."""
    if not intent:
        return
    current = _normalize_status(str(intent.get("status") or ""))
    if current in _TERMINAL_STATUSES:
        return
    plan = [s for s in (intent.get("execution_plan") or []) if isinstance(s, dict)]
    failed = sorted(
        (s for s in plan if _step_status_int(s) == 3),
        key=lambda s: int(s.get("step") or 0),
    )
    if failed:
        msg = str(failed[0].get("msg") or "").strip() or "step failed"
        failed_cap = str(failed[0].get("capability") or "").strip()
        if failed_cap in _UPLOAD_STEP_CAPABILITIES:
            msg = _upload_failure_msg(plan, failed[0], msg)
        _abandon_pending_plan_steps(intent, reason=_PENDING_STEP_ABANDONED_MSG)
        _apply_failure_presentation(intent, msg)
        if intent.get("presentation") is not None:
            intent["exposed_outputs"] = intent["presentation"]
        intent["status"] = "failed"
        intent["msg"] = msg
        intent["error"] = msg
        entry = {
            "status": "failed",
            "ts": int(time.time() * 1000),
            "msg": msg,
        }
        status_log = list(intent.get("status_log") or [])
        status_log.append(entry)
        intent["status_log"] = status_log
        _append_steps_timeline(intent, "failed", msg)
        _save_intent(intent)
        log.info("intent %s → failed (step failed, remaining steps abandoned)", intent_id_int)
        return
    if not _plan_steps_all_terminal(plan):
        return
    intent["status"] = "succeeded"
    entry = {
        "status": "succeeded",
        "ts": int(time.time() * 1000),
    }
    status_log = list(intent.get("status_log") or [])
    status_log.append(entry)
    intent["status_log"] = status_log
    _append_steps_timeline(intent, "succeeded", "")
    assemble_presentation(intent)
    if intent.get("presentation") is not None:
        intent["exposed_outputs"] = intent["presentation"]
    _maybe_attach_speak_delivery(intent)
    _save_intent(intent)
    log.info("intent %s → succeeded (all steps complete)", intent_id_int)


def _system_predecessors_succeeded(plan, step_n) -> bool:
    for step in plan or []:
        if not isinstance(step, dict):
            continue
        try:
            n = int(step.get("step") or 0)
        except (TypeError, ValueError):
            continue
        if n <= 0 or n >= int(step_n):
            continue
        try:
            st = int(step.get("status") or 0)
        except (TypeError, ValueError):
            return False
        if st != 2:
            return False
    return True


def _resolve_system_params(raw, intent):
    params = dict(raw) if isinstance(raw, dict) else {}
    ctx = intent.get("ctx_param") or intent.get("context") or {}
    if not isinstance(ctx, dict):
        ctx = {}
    out = {}
    for key, val in params.items():
        if isinstance(val, str) and val.startswith("$") and len(val) > 1:
            name = val[1:]
            if name in ctx and ctx[name] is not None:
                out[key] = ctx[name]
            else:
                out[key] = val
        else:
            out[key] = val
    return out


def _apply_step_status_record(
    intent,
    *,
    intent_id_int,
    step_id_int,
    step_status,
    outputs=None,
    msg=None,
    ts=None,
    edge_node_id="",
    step_status_str="",
):
    """Write one step's status/outputs and maybe finalize. Mutates and saves intent."""
    outputs = outputs if isinstance(outputs, dict) else {}
    cur_step = {}
    for step in intent.get("execution_plan") or []:
        if step.get("step") == step_id_int:
            cur_step = step
            break
    if not intent.get("step_outputs"):
        intent["step_outputs"] = {}
    intent["step_outputs"][str(step_id_int)] = outputs

    if step_status_str in ("succeeded", "failed") or step_status in (2, 3):
        present_step_id = intent["execution_plan"][-1]["step"]
        present_outputs = intent["step_outputs"].get(str(present_step_id))
        if present_outputs is None:
            present_outputs = intent["step_outputs"].get(present_step_id)
        if present_outputs is not None:
            intent["exposed_outputs"] = present_outputs

    intent_ctx = intent.get("ctx_param") or {}
    _record = {
        "step": step_id_int,
        "status": step_status,
        "ts": ts,
        "msg": msg,
    }
    actor = str(edge_node_id or "").strip() or str(cur_step.get("assigned_edge_id") or "").strip()
    if actor:
        _record["edge_id"] = actor
    if edge_node_id:
        intent["edge_node_id"] = edge_node_id

    for step in intent.get("execution_plan") or []:
        if step.get("step") == step_id_int:
            step["status"] = int(step_status)
            if msg:
                step["msg"] = msg
            output_constrict = step.get("output_constrict") or {}
            for k in output_constrict.keys():
                dest = (
                    (output_constrict.get(k) or {}).get("data_dest")
                    if isinstance(output_constrict.get(k), dict)
                    else None
                )
                if dest == "context" or dest is None:
                    val = outputs.get(k)
                    if val is not None:
                        intent_ctx[k] = val
            break
    if step_status == 2:
        for key in ("time_text", "answer_text", "state", "asset_ref", "capture_ref", "image_ref"):
            if outputs.get(key):
                intent_ctx[key] = outputs[key]

    intent["ctx_param"] = intent_ctx
    intent["context"] = intent_ctx
    if step_status == 3 and msg:
        intent["msg"] = msg
        intent["error"] = msg
    assemble_presentation(intent)
    if intent.get("presentation") is not None:
        intent["exposed_outputs"] = intent["presentation"]
    step_log = list(intent.get("step_log") or [])
    step_log.append(_record)
    intent["step_log"] = step_log
    _save_intent(intent)
    _maybe_finalize_intent_after_step(intent_id_int, intent)


def try_run_system_steps(intent_id) -> None:
    """Execute ready kind=system steps in-process. Idempotent."""
    try:
        intent_id_int = int(intent_id)
    except (TypeError, ValueError):
        return
    for _ in range(32):
        intent = get_intent(intent_id_int)
        if not intent:
            return
        if _normalize_status(str(intent.get("status") or "")) in _TERMINAL_STATUSES:
            return
        plan = intent.get("execution_plan") or []
        ready = None
        for step in sorted(
            (s for s in plan if isinstance(s, dict)),
            key=lambda s: int(s.get("step") or 0),
        ):
            cid = str(step.get("capability") or "").strip()
            assigned = str(step.get("assigned_edge_id") or "").strip()
            if assigned != SYSTEM_EDGE_ID and not is_system_capability(cid):
                continue
            try:
                st = int(step.get("status") or 0)
            except (TypeError, ValueError):
                st = 0
            if st in _TERMINAL_STEP_STATUSES:
                continue
            n = int(step.get("step") or 0)
            if not _system_predecessors_succeeded(plan, n):
                continue
            ready = step
            break
        if ready is None:
            return
        n = int(ready.get("step") or 0)
        cid = str(ready.get("capability") or "").strip()
        params = _resolve_system_params(ready.get("input_constrict") or {}, intent)
        runtime_rows = [
            row
            for row in _list_schedulable_capabilities()
            if str(row.get("kind") or "").strip().lower() != "system"
        ]
        try:
            msg, outputs = run_system_step(cid, params, capability_rows=runtime_rows)
            _apply_step_status_record(
                intent,
                intent_id_int=intent_id_int,
                step_id_int=n,
                step_status=2,
                outputs=outputs,
                msg=msg,
                ts=int(time.time() * 1000),
                edge_node_id=SYSTEM_EDGE_ID,
            )
        except SystemCapabilityError as e:
            _apply_step_status_record(
                intent,
                intent_id_int=intent_id_int,
                step_id_int=n,
                step_status=3,
                outputs={},
                msg=str(e) or "system capability failed",
                ts=int(time.time() * 1000),
                edge_node_id=SYSTEM_EDGE_ID,
            )
        except Exception as e:
            log.exception("system step %s %s failed", intent_id_int, cid)
            _apply_step_status_record(
                intent,
                intent_id_int=intent_id_int,
                step_id_int=n,
                step_status=3,
                outputs={},
                msg=str(e) or "system capability failed",
                ts=int(time.time() * 1000),
                edge_node_id=SYSTEM_EDGE_ID,
            )


@app.route("/api/v1/intent/<intent_id>/step/<step_id>/status", methods=["POST"])
def notify_step_status_update(intent_id, step_id):

    data = request.get_json(silent=True) or {}
    log.info("update step status data: %s", json.dumps(data))
    step_status_str = str(data.get("step_status") or "").strip()
    if step_status_str == "":
        return jsonify(
            err_msg="missing step status"
        )
    step_status = 0
    try:
        step_status = int(step_status_str)
    except:
        return jsonify(
            err_msg="illegal step status:" + step_status_str
        )

    edge_node_id = str(data.get("edge_node_id") or "").strip()

    try:
        intent_id_int = int(intent_id)
    except:
        intent_id_int = 0
    intent = get_intent(intent_id_int)
    if not intent:
        return jsonify(
            err_msg="intent not exist"
        ), 404
    log.info("intent:%s", json.dumps(intent))

    try:
        step_id_int = int(step_id)
    except:
        step_id_int = 0
 

    cur_step = {}
    for _step in intent['execution_plan']:
        if _step['step'] == step_id_int:
            cur_step = _step
            break

    if not cur_step:
        return jsonify(
            err_msg="illegal step"
        )

    try:
        current_step_status = int(cur_step.get("status") or 0)
    except (TypeError, ValueError):
        current_step_status = 0
    intent_status = _normalize_status(str(intent.get("status") or "").strip())
    if current_step_status in _TERMINAL_STEP_STATUSES and step_status not in _TERMINAL_STEP_STATUSES:
        return jsonify(
            err_msg="terminal step status cannot regress",
            status=current_step_status,
        )
    if intent_status in _TERMINAL_STATUSES and step_status not in _TERMINAL_STEP_STATUSES:
        return jsonify(
            err_msg="intent is terminal; step cannot return to running",
            status=intent_status,
        )

    _apply_step_status_record(
        intent,
        intent_id_int=intent_id_int,
        step_id_int=step_id_int,
        step_status=step_status,
        outputs=data.get("outputs") or {},
        msg=data.get("msg"),
        ts=data.get("ts"),
        edge_node_id=edge_node_id,
        step_status_str=step_status_str,
    )
    try_run_system_steps(intent_id_int)
    intent = get_intent(intent_id_int) or intent

    return jsonify(
        id=intent["id"],
        step=step_id_int,
        status=step_status,
    )





@app.route("/api/v1/intent/<intent_id>/status", methods=["POST"])
def notify_intent_status_update(intent_id):

    data = request.get_json(silent=True) or {}
    log.info("update status data: %s", json.dumps(data))
    intent_status = _normalize_status(str(data.get("intent_status") or "").strip())
    edge_node_id = str(data.get("edge_node_id") or "").strip()

    try:
        intent_id_int = int(intent_id)
    except:
        intent_id_int = 0
    intent = get_intent(intent_id_int)
    if not intent:
        return jsonify(
            err_msg="intent not exist"
        ), 404
    log.info("intent:%s", json.dumps(intent))

    current = _normalize_status(str(intent.get("status") or "").strip())
    if current in _TERMINAL_STATUSES and intent_status not in _TERMINAL_STATUSES:
        return jsonify(
            err_msg="terminal status cannot regress",
            status=current,
        )

    if intent['status'] == intent_status:
        return jsonify(
            err_msg="status already updated before"
        )

    _record = {}
    _record['status'] = intent_status
    if edge_node_id:
        _record['edge_node_id'] = edge_node_id
    msg = data.get('msg')
    if not msg and intent_status == "failed":
        msg = intent.get("msg") or intent.get("error")
    if msg:
        _record['msg'] = msg
        _record['detail'] = msg
        if intent_status in ("failed", "intent_waiting"):
            _record['error'] = msg
    status_log = list(intent.get("status_log") or [])
    log_entry = {
        "status": intent_status,
        "ts": int(time.time() * 1000),
    }
    if msg:
        log_entry["msg"] = msg
    status_log.append(log_entry)
    _record['status_log'] = status_log
    steps = list(intent.get("steps") or [])
    steps.append(
        {
            "status": intent_status,
            "intent_status": intent_status,
            "at": time.time(),
            "detail": msg or "",
        }
    )
    _record["steps"] = steps
    assemble_presentation(intent)
    if intent.get("presentation") is not None:
        _record["presentation"] = intent["presentation"]
        _record["exposed_outputs"] = intent["presentation"]
    if intent_status == "succeeded":
        _maybe_attach_speak_delivery(intent)
        if intent.get("pending_delivery") is not None:
            _record["pending_delivery"] = intent["pending_delivery"]

    update_intent(intent_id_int, _record)

    return jsonify(
        id=intent["id"],
        status=intent_status,
        execution_plan=intent.get("execution_plan") or [],
    )


@app.route("/api/v1/intent/<intent_id>/delivery_complete", methods=["POST"])
def notify_delivery_complete(intent_id):
    data = request.get_json(silent=True) or {}
    edge_id = str(
        data.get("edge_node_id") or data.get("edge_id") or ""
    ).strip()
    try:
        intent_id_int = int(intent_id)
    except (TypeError, ValueError):
        intent_id_int = 0
    intent = get_intent(intent_id_int)
    if not intent:
        return jsonify(ok=False, error="intent not exist"), 404
    pending = intent.get("pending_delivery")
    if isinstance(pending, dict):
        want = str(pending.get("edge_id") or "").strip()
        if not edge_id or want == edge_id:
            intent["pending_delivery"] = None
            _save_intent(intent)
    return jsonify(ok=True, intent_id=intent.get("id"), pending_delivery=None)


@app.route("/api/v1/photos/upload", methods=["POST"])
def upload_handler():
    """Accept one image from Edge; save under uploads/gopro/."""
    if "file" not in request.files:
        return jsonify(ok=False, error='expected multipart field name "file"'), 400
    f = request.files["file"]
    data = f.read()
    if not data:
        return jsonify(ok=False, error="empty file"), 400
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    try:
        original = _validate_asset_filename(f.filename or "photo.jpg")
        saved_as = _safe_on_disk_name(original, prefix=uuid.uuid4().hex[:8])
    except AssetFilenameError as e:
        return jsonify(ok=False, error=str(e)), 400
    dest = UPLOAD_DIR / saved_as
    dest.write_bytes(data)
    return jsonify(
        ok=True,
        filename=original,
        saved_as=saved_as,
        bytes=len(data),
        path=str(dest),
    )


_ASSET_UPLOAD_TYPES = frozenset({"image", "audio", "video", "document"})
_ASSET_UPLOAD_DIR = None  # resolved lazily under UPLOAD_DIR / "assets"


def _asset_upload_dir() -> Path:
    global _ASSET_UPLOAD_DIR
    if _ASSET_UPLOAD_DIR is None:
        _ASSET_UPLOAD_DIR = UPLOAD_DIR / "assets"
    return _ASSET_UPLOAD_DIR


_ASSET_NAME_ERROR = "文件名含非法字符。只允许字母、数字、中文、-、_。"
_ASSET_STEM_RE = re.compile(r"^[A-Za-z0-9\u4e00-\u9fff_-]+$")
_ASSET_EXT_RE = re.compile(r"^[A-Za-z0-9]{1,8}$")


class AssetFilenameError(ValueError):
    """Upload filename failed charset / path cleaning."""


def _clean_upload_filename(raw: str) -> str:
    """Drop directories and normalize Unicode. Does not rewrite charset."""
    name = Path(str(raw or "").replace("\\", "/")).name.strip()
    return unicodedata.normalize("NFC", name)


def _validate_asset_filename(raw: str) -> str:
    """Return cleaned basename, or raise AssetFilenameError."""
    cleaned = _clean_upload_filename(raw)
    if not cleaned or cleaned in {".", ".."}:
        raise AssetFilenameError(_ASSET_NAME_ERROR)
    stem = Path(cleaned).stem
    suffix = Path(cleaned).suffix.lower()
    if not stem or not _ASSET_STEM_RE.fullmatch(stem):
        raise AssetFilenameError(_ASSET_NAME_ERROR)
    if len(stem) > 80:
        raise AssetFilenameError(_ASSET_NAME_ERROR)
    if suffix:
        ext = suffix.lstrip(".")
        if not _ASSET_EXT_RE.fullmatch(ext):
            raise AssetFilenameError(_ASSET_NAME_ERROR)
        return f"{stem}.{ext}"
    return stem


def _safe_on_disk_name(original: str, *, prefix: str) -> str:
    """Filesystem key: {prefix}_{validated_basename}."""
    validated = _validate_asset_filename(original)
    token = str(prefix or "").strip() or uuid.uuid4().hex[:12]
    return f"{token}_{validated}"


def _infer_asset_type(*, mime_type: str, filename: str, explicit: str) -> str:
    raw = str(explicit or "").strip().lower()
    if raw in _ASSET_UPLOAD_TYPES:
        return raw
    mime = str(mime_type or "").strip().lower()
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("audio/"):
        return "audio"
    if mime.startswith("video/"):
        return "video"
    name = str(filename or "").strip().lower()
    if name.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".bmp")):
        return "image"
    if name.endswith((".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac")):
        return "audio"
    if name.endswith((".mp4", ".mov", ".m4v", ".webm", ".mkv")):
        return "video"
    if name.endswith((".pdf", ".doc", ".docx", ".txt", ".rtf")):
        return "document"
    return "image"


def _guess_mime(filename: str, fallback: str = "application/octet-stream") -> str:
    mime, _ = mimetypes.guess_type(filename or "")
    return (mime or "").strip() or fallback


def _explicit_img_server_upload_url() -> str:
    return (
        os.environ.get("BRAIN_IMG_UPLOAD_URL")
        or os.environ.get("PHOTO_UPLOAD_URL")
        or ""
    ).strip().rstrip("/")


def _img_server_upload_url() -> str:
    return _explicit_img_server_upload_url() or "http://127.0.0.1:8080/api/v1/photos/upload"


def _img_server_internal_base() -> str:
    """Host prefix of the img-server this Brain writes to (loopback by default).

    Used when the Brain itself must fetch asset bytes (content proxy,
    materialization). img-server is co-located, so this endpoint is reachable
    regardless of the LAN IP — the LAN-facing `public_base` is DHCP-volatile
    and is therefore never persisted; it is only resolved fresh when a direct
    LAN URL is needed at use time.
    """
    try:
        parsed = urllib.parse.urlsplit(_img_server_upload_url())
        if parsed.netloc:
            return "%s://%s" % ((parsed.scheme or "http"), parsed.netloc)
    except Exception:
        pass
    return "http://127.0.0.1:8080"


def _use_local_upload_store() -> bool:
    """Cloud Brain keeps bytes under gopropics/; it has no sidecar img-server :8080.

    LAN always uses img-server. Ops can still point cloud Brain at a real
    img-server by setting BRAIN_IMG_UPLOAD_URL or PHOTO_UPLOAD_URL.
    """
    if instance_intent_origin() != "cloud":
        return False
    return not _explicit_img_server_upload_url()


def _put_bytes_on_local_upload(
    data: bytes,
    *,
    filename: str,
    mime_type: str,
) -> dict:
    """Write bytes under gopropics/assets. Catalog identity stays asset_ref."""
    upload_dir = _asset_upload_dir()
    upload_dir.mkdir(parents=True, exist_ok=True)
    saved_as = _safe_on_disk_name(filename, prefix=uuid.uuid4().hex[:8])
    dest = upload_dir / saved_as
    dest.write_bytes(data)
    return {
        "backend": "local_upload",
        "saved_as": saved_as,
        "public_base": "",
        "url": "",
    }


def _store_uploaded_asset_bytes(
    data: bytes,
    *,
    filename: str,
    mime_type: str,
) -> dict:
    if _use_local_upload_store():
        stored = _put_bytes_on_local_upload(
            data, filename=filename, mime_type=mime_type
        )
        stored.setdefault("backend", "local_upload")
        return stored
    stored = _put_bytes_on_img_server(
        data, filename=filename, mime_type=mime_type
    )
    stored.setdefault("backend", "img_server")
    return stored


def _img_server_health_public_base() -> str:
    """Ask the co-located img-server for its own LAN public_base.

    img-server is the single source of truth for the LAN URL it advertises
    (it runs the same auto-detection, and `PHOTO_PUBLIC_BASE` can pin it).
    We query its /health before falling back to our own LAN-IP detection so a
    manually pinned value there can never diverge from what we store in DB.
    """
    upload_url = _img_server_upload_url().rstrip("/")
    if not upload_url:
        return ""
    try:
        parsed = urllib.parse.urlsplit(upload_url)
        health_url = f"{parsed.scheme}://{parsed.netloc}/health"
        with urllib.request.urlopen(health_url, timeout=2.0) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        payload = json.loads(raw) if raw.strip() else {}
        base = str((payload or {}).get("public_base") or "").strip().rstrip("/")
        if base.startswith("http://") or base.startswith("https://"):
            return base
    except Exception:
        pass
    return ""


def _lan_img_server_public_base() -> str:
    """LAN public base for this host's co-located img-server — auto-detected."""
    try:
        from mdns_service import lan_ipv4

        ip = (lan_ipv4() or "127.0.0.1").strip()
        if ip.startswith("127."):
            ip = "127.0.0.1"
        return f"http://{ip}:8080"
    except Exception:
        return "http://127.0.0.1:8080"


def _img_server_public_base() -> str:
    explicit = (
        os.environ.get("BRAIN_IMG_PUBLIC_BASE")
        or os.environ.get("PHOTO_PUBLIC_BASE")
        or ""
    ).strip().rstrip("/")
    if explicit:
        return explicit
    if instance_intent_origin() == "cloud":
        return "http://115.190.153.53:8080"
    return _img_server_health_public_base() or _lan_img_server_public_base()


def _put_bytes_on_img_server(
    data: bytes,
    *,
    filename: str,
    mime_type: str,
    timeout_sec: float = 20.0,
) -> dict:
    """POST multipart file to img-server. Catalog identity stays asset_ref."""
    upload_url = _img_server_upload_url()
    if not upload_url:
        raise RuntimeError("img-server upload URL is empty")
    safe_name = Path(filename or "upload.bin").name or "upload.bin"
    boundary = f"----BrainAsset{uuid.uuid4().hex}"
    mime = (mime_type or "application/octet-stream").strip() or "application/octet-stream"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{safe_name}"\r\n'
        f"Content-Type: {mime}\r\n\r\n"
    ).encode("utf-8") + data + f"\r\n--{boundary}--\r\n".encode("utf-8")
    req = urllib.request.Request(
        upload_url,
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=float(timeout_sec)) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            code = int(resp.getcode() or 0)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"img-server HTTP {e.code}: {raw[:300]}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise RuntimeError(f"img-server unreachable: {e}") from e
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as e:
        raise RuntimeError(f"img-server response not JSON (http={code}): {raw[:200]}") from e
    if not isinstance(payload, dict) or not payload.get("ok"):
        raise RuntimeError(f"img-server rejected upload: {payload!r}"[:300])
    saved_as = str(payload.get("saved_as") or "").strip()
    if not saved_as:
        raise RuntimeError("img-server ok but missing saved_as")
    public_base = _img_server_public_base()
    url = str(payload.get("url") or "").strip()
    if url.startswith("http://127.") or url.startswith("http://localhost"):
        url = f"{public_base}/{Path(saved_as).name}"
    elif not (url.startswith("http://") or url.startswith("https://")):
        url = f"{public_base}/{Path(saved_as).name}"
    return {
        "saved_as": saved_as,
        "public_base": public_base,
        "url": url,
    }


@app.route("/api/v1/assets/upload", methods=["POST"])
def upload_asset_with_intent():
    """Multipart upload with explicit upload_intent, then Asset catalog.

    LAN: bytes go to img-server. Cloud: bytes go to gopropics/assets
    (backend=local_upload) unless BRAIN_IMG_UPLOAD_URL / PHOTO_UPLOAD_URL is set.

    Does not use POST /api/v1/photos/upload as the client contract. Clients must not call
    POST /api/v1/assets afterward for the same file.
    """
    upload_intent = str(
        request.form.get("upload_intent") or request.form.get("intent") or ""
    ).strip()
    if not upload_intent:
        return jsonify(ok=False, error="upload_intent is required"), 400
    if "file" not in request.files:
        return jsonify(ok=False, error='expected multipart field name "file"'), 400
    f = request.files["file"]
    data = f.read()
    if not data:
        return jsonify(ok=False, error="empty file"), 400

    try:
        original = _validate_asset_filename(f.filename or "upload.bin")
    except AssetFilenameError as e:
        return jsonify(ok=False, error=str(e)), 400
    mime_type = str(request.form.get("mime_type") or f.mimetype or "").strip()
    if not mime_type or mime_type == "application/octet-stream":
        mime_type = _guess_mime(original, "application/octet-stream")
    asset_type = _infer_asset_type(
        mime_type=mime_type,
        filename=original,
        explicit=str(request.form.get("type") or ""),
    )
    producer = str(request.form.get("producer") or upload_intent).strip() or upload_intent
    edge_id = str(
        request.form.get("edge_id")
        or request.form.get("participant_id")
        or ""
    ).strip()
    intent_id = str(
        request.form.get("intent_id") or request.form.get("execution_id") or ""
    ).strip()

    put = getattr(brain_db, "put_asset", None)
    if not callable(put):
        return jsonify(ok=False, error="assets catalog not available"), 503

    try:
        stored = _store_uploaded_asset_bytes(
            data, filename=original, mime_type=mime_type
        )
    except Exception as e:
        log.warning("assets/upload store failed: %s", e)
        if _use_local_upload_store():
            return jsonify(ok=False, error=f"本地图床写入失败: {e}"), 502
        return jsonify(ok=False, error=f"img-server upload failed: {e}"), 502

    saved_as = stored["saved_as"]
    aid = "asset_" + secrets.token_hex(12)
    backend = str(stored.get("backend") or "img_server").strip() or "img_server"
    storage = {
        "backend": backend,
        "key": saved_as,
        "saved_as": saved_as,
    }
    # `public_base` is deliberately NOT persisted: it is a DHCP-volatile runtime
    # value, independent of the asset's storage address (backend+key). Consumers
    # resolve the current public_base from img-server each time they need a URL.
    if edge_id:
        storage["edge_id"] = edge_id
    record = {
        "asset_id": aid,
        "type": asset_type,
        "mime_type": mime_type,
        "status": "ready",
        "producer": producer,
        "producer_capability": producer,
        "edge_id": edge_id or None,
        "producer_edge_id": edge_id or None,
        "size_bytes": len(data),
        "metadata": {
            "upload_intent": upload_intent,
            "original_filename": original,
        },
        "storage": storage,
    }
    if intent_id:
        record["intent_id"] = intent_id
        record["origin_intent_id"] = intent_id
    try:
        put(record)
    except ValueError as e:
        return jsonify(ok=False, error=str(e)), 400
    except Exception:
        log.exception("assets/upload put_asset failed")
        return jsonify(ok=False, error="register_asset failed"), 500

    grant = getattr(brain_db, "put_asset_grant", None)
    if intent_id and callable(grant):
        try:
            grant(
                {
                    "asset_id": aid,
                    "intent_id": intent_id,
                    "execution_id": intent_id,
                    "capability_id": producer,
                    "permission": "read",
                }
            )
        except Exception:
            log.exception("assets/upload grant failed asset=%s intent=%s", aid, intent_id)

    getter = getattr(brain_db, "get_asset", None)
    rec = getter(aid) if callable(getter) else None
    rec = rec or {"asset_id": aid, "type": asset_type, "mime_type": mime_type}
    if intent_id and _asset_client_may_read(rec, intent_id):
        asset = _asset_endpoint_view(rec, intent_id)
    else:
        asset = _asset_public_view(rec)
    return jsonify(
        ok=True,
        asset_id=aid,
        asset=asset,
        upload_intent=upload_intent,
        type=asset_type,
        mime_type=mime_type,
        asset_ref={
            "asset_id": aid,
            "type": asset_type,
            "mime_type": mime_type,
        },
    )


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".heic", ".webp", ".gif"}
def _latest_image(directory: Path):
    if not directory.is_dir():
        return None
    candidates = [
        p for p in directory.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES and not p.name.startswith(".")
    ]
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None

@app.route("/api/v1/photos/download_latest", methods=["GET"])
def download_latest_photos():
    latest = _latest_image(UPLOAD_DIR)
    if latest is None:
        return jsonify(ok=False, error="no photos on server"), 404
    mime, _ = mimetypes.guess_type(latest.name)
    return send_file(
        latest,
        mimetype=mime or "image/jpeg",
        as_attachment=True,
        download_name=latest.name,
    )

@app.route("/api/v1/services", methods=["GET"])
def list_services_view():
    rebuild_capability_maps()
    services = list(services_registered_mapping.values())
    return jsonify(ok=True, services=services, count=len(services))


@app.route("/api/v1/capabilities", methods=["GET"])
def list_capabilities_view():
    """Flat catalog of online Runtime capabilities plus always-on kind=system."""
    cap_id = str(request.args.get("capability_id") or "").strip() or None
    edge_id = str(request.args.get("edge_id") or "").strip() or None
    caps = _list_schedulable_capabilities(capability_id=cap_id, edge_id=edge_id)
    return jsonify(ok=True, capabilities=caps, count=len(caps))


def _admin_auth_error():
    token = (os.environ.get("BRAIN_ADMIN_TOKEN") or "").strip()
    if not token:
        return None
    got = (request.headers.get("X-Admin-Token") or "").strip()
    if got == token:
        return None
    auth = str(request.headers.get("Authorization") or "")
    if auth.startswith("Bearer ") and auth[7:].strip() == token:
        return None
    return jsonify(ok=False, error="admin token required"), 401


def _admin_request_ok() -> bool:
    return _admin_auth_error() is None and bool(
        (os.environ.get("BRAIN_ADMIN_TOKEN") or "").strip()
    )


_ADMIN_ROLE_LABELS = {
    "intent_source": "发出 Intent",
    "runtime": "执行 Runtime",
    "endpoint": "呈现 Endpoint",
    "observer": "观察 Observer",
}


def _admin_actor():
    got = (request.headers.get("X-Admin-Token") or "").strip()
    auth = str(request.headers.get("Authorization") or "")
    bearer = auth[7:].strip() if auth.startswith("Bearer ") else ""
    if got or bearer:
        return "admin"
    return ""


def _admin_node_title(rec, pid=""):
    rec = rec if isinstance(rec, dict) else {}
    name = str(rec.get("display_name") or "").strip()
    loc = str(rec.get("location") or rec.get("room") or "").strip()
    if loc and name and loc not in name:
        return f"{loc} · {name}"
    return name or str(pid or rec.get("participant_id") or rec.get("edge_id") or "").strip()


def _admin_target_title(target_kind, target_id):
    kind = str(target_kind or "").strip().lower()
    tid = str(target_id or "").strip()
    if kind == "role":
        return _ADMIN_ROLE_LABELS.get(tid, tid)
    return tid


def _admin_policy_summary(
    *,
    participant_id="",
    target_kind="",
    target_id="",
    enabled=None,
    rec=None,
    error=None,
    action="",
):
    title = _admin_node_title(rec, participant_id) or participant_id or "节点"
    target = _admin_target_title(target_kind, target_id)
    if action == "policy_replace":
        line = f"改写 {title} 的调度策略"
    elif enabled is True:
        line = f"打开 {title} 的 {target}".strip()
    elif enabled is False:
        line = f"关掉 {title} 的 {target}".strip()
    elif target:
        line = f"改 {title} 的 {target}".strip()
    else:
        line = f"管理 {title}"
    if error:
        return f"{line} 失败：{error}"
    return line


def _record_admin_op(
    *,
    action,
    participant_id="",
    target_kind="",
    target_id="",
    extra=None,
    result="ok",
    summary="",
):
    writer = getattr(brain_db, "insert_admin_op_log", None)
    if not callable(writer):
        return
    try:
        writer(
            actor=_admin_actor(),
            action=str(action or "").strip() or "policy_toggle",
            participant_id=str(participant_id or "").strip(),
            target_kind=str(target_kind or "").strip(),
            target_id=str(target_id or "").strip(),
            extra=extra if isinstance(extra, (dict, list)) else None,
            result=result,
            summary=str(summary or ""),
        )
    except (TypeError, ValueError, sqlite3.OperationalError):
        return


def _runtime_capabilities(rec):
    out = []
    for svc in rec.get("services") or []:
        if not isinstance(svc, dict):
            continue
        service_id = str(svc.get("service_id") or "").strip()
        group = str(svc.get("group") or "").strip()
        for cap in svc.get("capabilities") or []:
            if not isinstance(cap, dict):
                continue
            cid = str(cap.get("capability_id") or "").strip()
            if not cid:
                continue
            out.append(
                {
                    "capability_id": cid,
                    "service_id": service_id,
                    "group": group,
                    "kind": str(cap.get("kind") or "").strip().lower(),
                    "role": cap.get("role") or "",
                    "planner_recognize": cap.get("planner_recognize") or "",
                    "typical_triggers": list(cap.get("typical_triggers") or [])
                    if isinstance(cap.get("typical_triggers"), list)
                    else [],
                    "do_not_dispatch": list(cap.get("do_not_dispatch") or [])
                    if isinstance(cap.get("do_not_dispatch"), list)
                    else [],
                    "description": cap.get("description") or "",
                }
            )
    return out


def _admin_node_view(rec, *, policy_index):
    view = _edge_public_view(dict(rec))
    pid = str(view.get("participant_id") or view.get("edge_id") or "").strip()
    roles = []
    for role in ("intent_source", "runtime", "endpoint", "observer"):
        registered = _declared_role(view, role)
        allowed = _control_policy_allows(
            pid, "role", role, index=policy_index
        )
        schedulable, _reason = can_participate(
            pid, role=role, rec=view, policy_index=policy_index
        )
        roles.append(
            {
                "id": role,
                "registered": registered,
                "enabled": allowed,
                "schedulable": schedulable,
            }
        )
    capabilities = []
    for cap in _runtime_capabilities(view):
        allowed = _control_policy_allows(
            pid, "capability", cap["capability_id"], index=policy_index
        ) and _control_policy_allows(
            pid, "role", "runtime", index=policy_index
        )
        schedulable, _reason = can_participate(
            pid,
            capability=cap["capability_id"],
            rec=view,
            policy_index=policy_index,
        )
        capabilities.append(
            {
                **cap,
                "registered": True,
                "enabled": allowed,
                "schedulable": schedulable,
            }
        )
    last_active = view.get("server_received_at")
    return {
        "participant_id": pid,
        "edge_id": pid,
        "display_name": view.get("display_name") or "",
        "device_type": view.get("device_type") or "",
        "location": view.get("location") or view.get("room") or "",
        "client_hint": view.get("client_hint") or "",
        "status": view.get("status") or "approved",
        "online_status": view.get("online_status") or "never",
        "online_status_note": view.get("online_status_note") or "",
        "last_active_at": last_active,
        "registered_at": view.get("registered_at"),
        "schedule_eligible": view.get("schedule_eligible"),
        "roles": roles,
        "runtime_capabilities": capabilities,
    }


def _policy_items_from_body(body):
    items = []
    roles = body.get("roles") if isinstance(body.get("roles"), dict) else {}
    for role, enabled in roles.items():
        items.append(
            {
                "target_kind": "role",
                "target_id": str(role),
                "enabled": bool(enabled),
            }
        )
    caps = body.get("capabilities") if isinstance(body.get("capabilities"), dict) else {}
    for cap, enabled in caps.items():
        items.append(
            {
                "target_kind": "capability",
                "target_id": str(cap),
                "enabled": bool(enabled),
            }
        )
    extra = body.get("items") if isinstance(body.get("items"), list) else []
    items.extend(item for item in extra if isinstance(item, dict))
    return items


def _list_admin_participants():
    """Prefer db.list_participants; cloud db.py may not have it yet (@dba)."""
    fn = getattr(brain_db, "list_participants", None)
    if callable(fn):
        try:
            rows = fn(include_heartbeat=True)
            if isinstance(rows, list):
                return rows
        except (TypeError, sqlite3.OperationalError, AttributeError):
            pass
    beats = brain_db.list_heartbeats() if hasattr(brain_db, "list_heartbeats") else {}
    ids = set(beats)
    if hasattr(brain_db, "registration_ids"):
        ids.update(brain_db.registration_ids() or [])
    out = []
    for pid in sorted(str(x) for x in ids if str(x).strip()):
        rec = {}
        getter = getattr(brain_db, "get_registration", None)
        if callable(getter):
            rec = dict(getter(pid) or {})
        rec.update(beats.get(pid) or {})
        rec.setdefault("participant_id", pid)
        rec.setdefault("edge_id", pid)
        out.append(rec)
    return out


@app.route("/api/v1/admin/nodes", methods=["GET"])
def admin_list_nodes():
    denied = _admin_auth_error()
    if denied:
        return denied
    policy = _load_control_policy_index()
    nodes = [
        _admin_node_view(rec, policy_index=policy)
        for rec in _list_admin_participants()
    ]
    return jsonify({"ok": True, "nodes": nodes})


@app.route("/api/v1/admin/nodes/<participant_id>/exposure-policy", methods=["GET"])
def admin_get_exposure_policy(participant_id):
    denied = _admin_auth_error()
    if denied:
        return denied
    pid = str(participant_id or "").strip()
    rec = brain_db.get_registration(pid)
    if rec is None:
        return jsonify(ok=False, error="unknown participant_id"), 404
    return jsonify(
        {
            "ok": True,
            "participant_id": pid,
            "domain": rec.get("domain"),
            "exposure_policy": rec.get("exposure_policy") or {},
        }
    )


@app.route("/api/v1/admin/nodes/<participant_id>/exposure-policy", methods=["PUT", "POST"])
def admin_put_exposure_policy(participant_id):
    denied = _admin_auth_error()
    if denied:
        return denied
    pid = str(participant_id or "").strip()
    rec = brain_db.get_registration(pid)
    if rec is None:
        return jsonify(ok=False, error="unknown participant_id"), 404
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(ok=False, error="JSON object required"), 400
    policy = body.get("exposure_policy")
    if not isinstance(policy, dict):
        return jsonify(ok=False, error="exposure_policy must be an object {lan:[...], cloud:[...]}"), 400
    # Normalize: only lan/cloud keys, values are lists of capability_id strings.
    norm = {}
    for dom in ("lan", "cloud"):
        if dom in policy:
            vals = policy.get(dom)
            if vals is None:
                norm[dom] = None
            elif isinstance(vals, (list, tuple)):
                norm[dom] = [str(c or "").strip() for c in vals if str(c or "").strip()]
            else:
                return jsonify(ok=False, error=f"exposure_policy.{dom} must be a list or null"), 400
    updated = dict(rec)
    updated["exposure_policy"] = norm or None
    brain_db.put_registration(updated, domain=rec.get("domain") or instance_intent_origin())
    rebuild_capability_maps(force=True)
    _record_admin_op(
        action="exposure_policy_replace",
        participant_id=pid,
        target_kind="capability",
        target_id="",
        extra={"exposure_policy": norm},
        result="ok",
        summary=f"设置 {rec.get('display_name') or pid} 的 Capability Exposure Policy",
    )
    return jsonify(
        {
            "ok": True,
            "participant_id": pid,
            "domain": rec.get("domain"),
            "exposure_policy": norm,
        }
    )


@app.route("/api/v1/admin/nodes/<participant_id>/policy", methods=["PUT", "POST"])
def admin_put_node_policy(participant_id):
    denied = _admin_auth_error()
    if denied:
        return denied
    pid = str(participant_id or "").strip()
    rec = brain_db.get_registration(pid)
    items = []
    body = request.get_json(silent=True)
    if isinstance(body, dict):
        items = _policy_items_from_body(body)
    extra = {"items": items} if items else None

    def _fail(error, status):
        _record_admin_op(
            action="policy_replace",
            participant_id=pid,
            extra=({"error": error, **(extra or {})} if extra else {"error": error}),
            result="error",
            summary=_admin_policy_summary(
                participant_id=pid,
                rec=rec,
                error=error,
                action="policy_replace",
            ),
        )
        return jsonify(ok=False, error=error), status

    if rec is None:
        return _fail("unknown participant_id", 404)
    if not isinstance(body, dict):
        return _fail("JSON object required", 400)
    writer = getattr(brain_db, "replace_edge_control_policies", None)
    if not callable(writer):
        return _fail("edge_control_policy not on this Brain db yet", 501)
    try:
        rows = writer(pid, items)
    except ValueError as exc:
        return _fail(str(exc), 400)
    except sqlite3.OperationalError as exc:
        return _fail(str(exc), 501)
    rebuild_capability_maps(force=True)
    policy = _load_control_policy_index()
    rec = dict(rec)
    beats = brain_db.list_heartbeats()
    if pid in beats:
        rec = {**rec, **beats[pid]}
    _record_admin_op(
        action="policy_replace",
        participant_id=pid,
        extra=extra,
        result="ok",
        summary=_admin_policy_summary(
            participant_id=pid,
            rec=rec,
            action="policy_replace",
        ),
    )
    return jsonify(
        {
            "ok": True,
            "policy": rows,
            "node": _admin_node_view(rec, policy_index=policy),
        }
    )


@app.route("/api/v1/admin/policy", methods=["POST"])
def admin_toggle_policy():
    denied = _admin_auth_error()
    if denied:
        return denied
    body = request.get_json(silent=True)
    pid = ""
    kind = ""
    tid = ""
    enabled = None
    rec = None
    if isinstance(body, dict):
        pid = str(body.get("participant_id") or body.get("edge_id") or "").strip()
        kind = str(body.get("target_kind") or "").strip()
        tid = str(body.get("target_id") or "").strip()
        enabled = body.get("enabled")
        rec = brain_db.get_registration(pid) if pid else None
    action = (
        "policy_enable"
        if enabled
        else "policy_disable"
        if enabled is False
        else "policy_toggle"
    )

    def _fail(error, status):
        _record_admin_op(
            action=action,
            participant_id=pid,
            target_kind=kind,
            target_id=tid,
            extra={"error": error},
            result="error",
            summary=_admin_policy_summary(
                participant_id=pid,
                target_kind=kind,
                target_id=tid,
                enabled=enabled,
                rec=rec,
                error=error,
                action=action,
            ),
        )
        return jsonify(ok=False, error=error), status

    if not isinstance(body, dict):
        return _fail("JSON object required", 400)
    if rec is None:
        return _fail("unknown participant_id", 404)
    if enabled is None:
        return _fail("enabled required", 400)
    deleter = getattr(brain_db, "delete_edge_control_policy", None)
    putter = getattr(brain_db, "put_edge_control_policy", None)
    if not callable(deleter) or not callable(putter):
        return _fail("edge_control_policy not on this Brain db yet", 501)
    try:
        if enabled:
            deleter(
                participant_id=pid,
                target_kind=kind,
                target_id=tid,
            )
            row = {
                "participant_id": pid,
                "target_kind": kind,
                "target_id": tid,
                "enabled": True,
            }
        else:
            row = putter(
                participant_id=pid,
                target_kind=kind,
                target_id=tid,
                enabled=False,
            )
    except ValueError as exc:
        return _fail(str(exc), 400)
    except sqlite3.OperationalError as exc:
        return _fail(str(exc), 501)
    rebuild_capability_maps(force=True)
    _record_admin_op(
        action=action,
        participant_id=pid,
        target_kind=kind,
        target_id=tid,
        result="ok",
        summary=_admin_policy_summary(
            participant_id=pid,
            target_kind=kind,
            target_id=tid,
            enabled=enabled,
            rec=rec,
            action=action,
        ),
    )
    return jsonify({"ok": True, "policy": row})


@app.route("/api/v1/admin/logs", methods=["GET"])
def admin_list_logs():
    denied = _admin_auth_error()
    if denied:
        return denied
    reader = getattr(brain_db, "list_admin_op_logs", None)
    if not callable(reader):
        return jsonify(ok=False, error="admin_op_log not on this Brain db yet"), 501
    raw_limit = request.args.get("limit")
    try:
        limit = int(raw_limit) if raw_limit not in (None, "") else 100
    except (TypeError, ValueError):
        limit = 100
    try:
        logs = reader(limit=limit)
    except sqlite3.OperationalError as exc:
        return jsonify(ok=False, error=str(exc)), 501
    return jsonify({"ok": True, "logs": logs})


ADMIN_INTENTS_DEFAULT = 50
ADMIN_INTENTS_MAX = 100
_ADMIN_INTENTS_SCAN_BATCH = 100


def _job_runtime_edge_ids(job):
    found = []
    seen = set()
    for step in job.get("execution_plan") or []:
        if not isinstance(step, dict):
            continue
        eid = str(step.get("assigned_edge_id") or "").strip()
        if not eid or eid == SYSTEM_EDGE_ID or eid in seen:
            continue
        seen.add(eid)
        found.append(eid)
    exec_id = str(job.get("edge_node_id") or "").strip()
    if exec_id and exec_id != SYSTEM_EDGE_ID and exec_id not in seen:
        found.append(exec_id)
    return found


def _admin_intent_matches(job):
    if _job_runtime_edge_ids(job):
        return True
    status = _normalize_status(str(job.get("status") or job.get("intent_status") or ""))
    return status not in _TERMINAL_STATUSES


def _step_status_text(step):
    raw = step.get("status") if isinstance(step, dict) else None
    if raw in (2, "2", "succeeded", "success", "completed"):
        return "succeeded"
    if raw in (3, "3", "failed", "error"):
        return "failed"
    if raw in (1, "1", "running"):
        return "running"
    if raw in (0, "0", None, ""):
        return ""
    return str(raw)


def _admin_intent_view(intent):
    plan = intent.get("execution_plan") or []
    step_outputs = intent.get("step_outputs") if isinstance(intent.get("step_outputs"), dict) else {}
    runtime_ids = _job_runtime_edge_ids(intent)
    steps = []
    for step in plan:
        if not isinstance(step, dict):
            continue
        step_n = step.get("step")
        outputs = {}
        if step_n is not None:
            outputs = step_outputs.get(str(step_n))
            if outputs is None:
                outputs = step_outputs.get(step_n)
        if not isinstance(outputs, dict):
            outputs = step.get("outputs") if isinstance(step.get("outputs"), dict) else {}
        steps.append(
            {
                "capability": str(step.get("capability") or "").strip(),
                "assigned_edge_id": str(step.get("assigned_edge_id") or "").strip(),
                "status": _step_status_text(step),
                "msg": str(step.get("msg") or "").strip(),
                "outputs": outputs,
            }
        )
    pres = intent.get("presentation") if isinstance(intent.get("presentation"), dict) else {}
    ident = intent.get("intent_id", intent.get("id"))
    try:
        ident = int(ident)
    except (TypeError, ValueError):
        pass
    view = {
        "intent_id": ident,
        "text": str(intent.get("text") or ""),
        "status": str(intent.get("status") or ""),
        "created_at": intent.get("created_at"),
        "updated_at": intent.get("updated_at"),
        "issuer_id": str(intent.get("edge_id") or intent.get("participant_id") or "").strip(),
        "runtime_edge_ids": runtime_ids,
        "msg": str(intent.get("msg") or ""),
        "presentation": {
            "type": str(pres.get("type") or ""),
            "text": str(pres.get("text") or ""),
            "from": str(pres.get("from") or ""),
        },
        "execution_plan": steps,
        "status_log": list(intent.get("status_log") or []),
    }
    if intent.get("planner_cost_ms") is not None:
        view["planner_cost_ms"] = intent["planner_cost_ms"]
    if "planner_has_request_payload" in intent:
        view["planner_has_request_payload"] = bool(intent.get("planner_has_request_payload"))
    return view


def _list_admin_intent_jobs(before_id, limit):
    fn = getattr(brain_db, "list_jobs_page", None)
    collected = []
    cursor = before_id
    scanned_end = False
    while len(collected) < limit:
        batch = _ADMIN_INTENTS_SCAN_BATCH
        if callable(fn):
            rows = fn(before_id=cursor, limit=batch)
        else:
            rows = []
            for job in brain_db.list_jobs():
                try:
                    iid = int(job.get("intent_id") if job.get("intent_id") is not None else job.get("id"))
                except (TypeError, ValueError):
                    continue
                if cursor is not None and iid >= cursor:
                    continue
                rows.append(job)
                if len(rows) >= batch:
                    break
        if not rows:
            scanned_end = True
            break
        ids = []
        for job in rows:
            try:
                ids.append(int(job.get("intent_id") if job.get("intent_id") is not None else job.get("id")))
            except (TypeError, ValueError):
                continue
            if _admin_intent_matches(job):
                collected.append(job)
                if len(collected) >= limit:
                    break
        if len(rows) < batch:
            scanned_end = True
            break
        cursor = min(ids) if ids else None
        if cursor is None:
            scanned_end = True
            break
    return collected[:limit], scanned_end


@app.route("/api/v1/admin/intents", methods=["GET"])
def admin_list_intents():
    denied = _admin_auth_error()
    if denied:
        return denied
    before_raw = request.args.get("before_id")
    before_id = None
    if before_raw not in (None, ""):
        try:
            before_id = int(before_raw)
        except (TypeError, ValueError):
            return jsonify(ok=False, error="before_id must be an integer"), 400
        if before_id < 1:
            return jsonify(ok=False, error="before_id must be >= 1"), 400
    limit = ADMIN_INTENTS_DEFAULT
    if request.args.get("limit") not in (None, ""):
        try:
            limit = int(request.args.get("limit"))
        except (TypeError, ValueError):
            return jsonify(ok=False, error="limit must be an integer"), 400
    limit = max(1, min(limit, ADMIN_INTENTS_MAX))
    jobs, scanned_end = _list_admin_intent_jobs(before_id, limit)
    intents = [_admin_intent_view(_job_to_intent(job)) for job in jobs]
    ids = []
    for item in intents:
        try:
            ids.append(int(item.get("intent_id")))
        except (TypeError, ValueError):
            pass
    next_before = min(ids) if ids else None
    exhausted = len(intents) < limit
    return jsonify(
        {
            "ok": True,
            "intents": intents,
            "limit": limit,
            "before_id": before_id,
            "next_before_id": next_before,
            "exhausted": exhausted,
        }
    )


def _is_dev_task_job(job):
    if not isinstance(job, dict):
        return False
    if str(job.get("source") or "").strip().lower() == "dev":
        return True
    if str(job.get("task_kind") or "").strip() == "dev_task":
        return True
    ctx = job.get("ctx_param") or job.get("context") or {}
    if isinstance(ctx, dict) and str(ctx.get("task_kind") or "").strip() == "dev_task":
        return True
    return False


def _admin_dev_task_view(intent):
    view = _admin_intent_view(intent if isinstance(intent, dict) else {})
    dev = {}
    if isinstance(intent, dict):
        raw = intent.get("dev_task")
        if isinstance(raw, dict):
            dev = dict(raw)
        ctx = intent.get("ctx_param") or intent.get("context") or {}
        if isinstance(ctx, dict) and isinstance(ctx.get("dev_task"), dict):
            dev = {**ctx.get("dev_task"), **dev}
    pres = view.get("presentation") if isinstance(view.get("presentation"), dict) else {}
    result_text = str(pres.get("text") or view.get("msg") or "").strip()
    ctx_param = intent.get("ctx_param") if isinstance(intent, dict) else {}
    if isinstance(ctx_param, dict):
        answer = str(ctx_param.get("answer_text") or "").strip()
        if answer:
            result_text = answer
    view["task_kind"] = "dev_task"
    view["dev_task"] = dev
    view["result_text"] = result_text
    return view


def _list_admin_dev_task_jobs(before_id, limit):
    fn = getattr(brain_db, "list_jobs_page", None)
    collected = []
    cursor = before_id
    scanned_end = False
    while len(collected) < limit:
        batch = _ADMIN_INTENTS_SCAN_BATCH
        if callable(fn):
            rows = fn(before_id=cursor, limit=batch)
        else:
            rows = []
            for job in brain_db.list_jobs():
                try:
                    iid = int(job.get("intent_id") if job.get("intent_id") is not None else job.get("id"))
                except (TypeError, ValueError):
                    continue
                if cursor is not None and iid >= cursor:
                    continue
                rows.append(job)
                if len(rows) >= batch:
                    break
        if not rows:
            scanned_end = True
            break
        ids = []
        for job in rows:
            try:
                ids.append(int(job.get("intent_id") if job.get("intent_id") is not None else job.get("id")))
            except (TypeError, ValueError):
                continue
            if _is_dev_task_job(job):
                collected.append(job)
                if len(collected) >= limit:
                    break
        if not ids:
            scanned_end = True
            break
        cursor = min(ids)
        if len(rows) < batch:
            scanned_end = True
            break
    return collected[:limit], scanned_end


@app.route("/api/v1/admin/dev_task", methods=["POST"])
def admin_post_dev_task():
    denied = _admin_auth_error()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify(ok=False, error="JSON object required"), 400
    text = str(data.get("text") or "").strip()
    attachments_raw = data.get("attachments")
    if attachments_raw is None:
        attachments_raw = data.get("attachment_asset_ids")
    if attachments_raw is not None and not isinstance(attachments_raw, list):
        return jsonify(ok=False, error="attachments must be an array"), 400
    if not text and not attachments_raw:
        return jsonify(ok=False, error="text or attachments required"), 400
    parent_raw = data.get("parent_task_id") or data.get("continue_task_id")
    parent_task_id = None
    if parent_raw not in (None, ""):
        try:
            parent_task_id = int(parent_raw)
        except (TypeError, ValueError):
            return jsonify(ok=False, error="parent_task_id must be an integer"), 400
    thread_raw = data.get("thread_id")
    thread_id = None
    if thread_raw not in (None, ""):
        try:
            thread_id = int(thread_raw)
        except (TypeError, ValueError):
            return jsonify(ok=False, error="thread_id must be an integer"), 400
    category_raw = data.get("category")
    category = None
    if category_raw not in (None, ""):
        category = str(category_raw).strip()
    target_raw = data.get("target_handle") or data.get("suggested_handle")
    target_handle = None
    if target_raw not in (None, ""):
        target_handle = str(target_raw).strip()
    view = submit_agent_task(
        text,
        parent_task_id=parent_task_id,
        thread_id=thread_id,
        category=category,
        attachments=attachments_raw,
        target_handle=target_handle,
        brain_url=_brain_public_base_url(),
    )
    return jsonify(ok=True, **view)


@app.route("/api/v1/admin/agent_fleet", methods=["GET"])
def admin_get_agent_fleet():
    denied = _admin_auth_error()
    if denied:
        return denied
    view = get_fleet_view()
    status_code = 200 if view.get("ok") else 503
    return jsonify(view), status_code


@app.route("/api/v1/admin/agent_fleet/<handle>/wake", methods=["POST"])
def admin_wake_agent_fleet(handle: str):
    denied = _admin_auth_error()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify(ok=False, error="JSON object required"), 400
    text = str(data.get("text") or data.get("task") or "").strip()
    result = wake_fleet_agent(handle, text=text)
    if not result.get("ok"):
        return jsonify(result), 400
    return jsonify(result), 202


@app.route("/api/v1/admin/releases", methods=["GET"])
def admin_list_releases():
    """Deploy tab: release candidates (git → test → approve → deploy)."""
    denied = _admin_auth_error()
    if denied:
        return denied
    limit = request.args.get("limit", 50, type=int) or 50
    status = str(request.args.get("status") or "").strip()
    return jsonify(list_releases(limit=limit, status=status))


@app.route("/api/v1/admin/releases/sync", methods=["POST"])
def admin_sync_releases():
    denied = _admin_auth_error()
    if denied:
        return denied
    return jsonify(sync_releases_from_chat())


@app.route("/api/v1/admin/releases/<int:release_id>", methods=["GET"])
def admin_get_release(release_id: int):
    denied = _admin_auth_error()
    if denied:
        return denied
    row = get_release(release_id)
    if not row:
        return jsonify(ok=False, error="release not found"), 404
    return jsonify(ok=True, release=row)


@app.route("/api/v1/admin/releases/<int:release_id>/approve", methods=["POST"])
def admin_approve_release(release_id: int):
    """Deploy Authority: approve and wake @deploy."""
    denied = _admin_auth_error()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        data = {}
    note = str(data.get("note") or "").strip()
    result = approve_release(release_id, by="boss", note=note)
    if not result.get("ok"):
        return jsonify(result), 400
    return jsonify(result), 202


@app.route("/api/v1/admin/releases/<int:release_id>/reject", methods=["POST"])
def admin_reject_release(release_id: int):
    denied = _admin_auth_error()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        data = {}
    note = str(data.get("note") or "").strip()
    result = reject_release(release_id, by="boss", note=note)
    if not result.get("ok"):
        return jsonify(result), 400
    return jsonify(result)


@app.route("/api/v1/admin/agent_chat", methods=["GET"])
def admin_get_agent_chat():
    denied = _admin_auth_error()
    if denied:
        return denied
    since_id = request.args.get("since_id", 0, type=int) or 0
    since_ack_at = request.args.get("since_ack_at", 0.0, type=float) or 0.0
    view = get_chat_view(since_id=since_id, since_ack_at=since_ack_at)
    status = 200 if view.get("ok") else 503
    return jsonify(view), status


@app.route("/api/v1/admin/agent_chat/send", methods=["POST"])
def admin_post_agent_chat_send():
    denied = _admin_auth_error()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify(ok=False, error="JSON object required"), 400
    body = str(data.get("body") or data.get("text") or "").strip()
    attachments_raw = data.get("attachments")
    if attachments_raw is not None and not isinstance(attachments_raw, list):
        return jsonify(ok=False, error="attachments must be an array"), 400
    attachments = None
    if isinstance(attachments_raw, list):
        attachments = []
        for item in attachments_raw:
            if not isinstance(item, dict):
                continue
            aid = str(item.get("attachment_id") or item.get("id") or "").strip()
            if not aid:
                continue
            row = {"attachment_id": aid, "kind": str(item.get("kind") or "image")}
            mime = str(item.get("mime_type") or item.get("mime") or "").strip()
            if mime:
                row["mime_type"] = mime
            name = str(item.get("filename") or item.get("name") or "").strip()
            if name:
                row["filename"] = name
            attachments.append(row)
    if not body and not attachments:
        return jsonify(ok=False, error="body or attachments required"), 400
    try:
        msg = send_boss_message(body, attachments=attachments)
    except AgentChatError as err:
        return jsonify(ok=False, error=str(err)), 400
    return jsonify(ok=True, message=msg)


@app.route("/api/v1/admin/agent_chat/attachment/upload", methods=["POST"])
def admin_upload_agent_chat_attachment():
    denied = _admin_auth_error()
    if denied:
        return denied
    if "file" not in request.files:
        return jsonify(ok=False, error='expected multipart field name "file"'), 400
    f = request.files["file"]
    data = f.read()
    if not data:
        return jsonify(ok=False, error="empty file"), 400
    mime_type = str(request.form.get("mime_type") or f.mimetype or "image/jpeg").strip()
    filename = str(f.filename or "chat.jpg").strip() or "chat.jpg"
    try:
        attachment = upload_chat_attachment(data, filename=filename, mime_type=mime_type)
    except AgentChatError as err:
        return jsonify(ok=False, error=str(err)), 502
    return jsonify(ok=True, attachment=attachment)


@app.route("/api/v1/admin/agent_chat/attachments/<attachment_id>/content", methods=["GET"])
def admin_get_agent_chat_attachment_content(attachment_id: str):
    denied = _admin_auth_error()
    if denied:
        return denied
    try:
        data, mime = fetch_chat_attachment_content(attachment_id)
    except AgentChatError as err:
        return jsonify(ok=False, error=str(err)), 404
    except FileNotFoundError:
        return jsonify(ok=False, error="attachment not found"), 404
    return Response(data, mimetype=mime)


@app.route("/api/v1/admin/agent_chat/ack", methods=["POST"])
def admin_post_agent_chat_ack():
    denied = _admin_auth_error()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify(ok=False, error="JSON object required"), 400
    raw_id = data.get("message_id") if data.get("message_id") is not None else data.get("id")
    try:
        message_id = int(raw_id)
    except (TypeError, ValueError):
        return jsonify(ok=False, error="message_id is required"), 400
    ack_type = str(data.get("ack_type") or "ok")
    try:
        msg = ack_boss_message(message_id, ack_type=ack_type)
    except AgentChatError as err:
        return jsonify(ok=False, error=str(err)), 400
    return jsonify(ok=True, message=msg)


@app.route("/api/v1/admin/agent_chat/unack", methods=["POST"])
def admin_post_agent_chat_unack():
    denied = _admin_auth_error()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify(ok=False, error="JSON object required"), 400
    raw_id = data.get("message_id") if data.get("message_id") is not None else data.get("id")
    try:
        message_id = int(raw_id)
    except (TypeError, ValueError):
        return jsonify(ok=False, error="message_id is required"), 400
    try:
        msg = unack_boss_message(message_id)
    except AgentChatError as err:
        return jsonify(ok=False, error=str(err)), 400
    return jsonify(ok=True, message=msg)


@app.route("/api/v1/admin/agent_chat/promote", methods=["POST"])
def admin_post_agent_chat_promote():
    denied = _admin_auth_error()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify(ok=False, error="JSON object required"), 400
    text = str(data.get("text") or data.get("body") or "").strip()
    target_handle = str(data.get("target_handle") or data.get("handle") or "").strip() or None
    category = str(data.get("category") or "").strip() or None
    background_ids_raw = data.get("background_message_ids") or data.get("message_ids") or []
    background_ids: list[int] = []
    if isinstance(background_ids_raw, list):
        for item in background_ids_raw:
            try:
                background_ids.append(int(item))
            except (TypeError, ValueError):
                continue
    anchor_raw = data.get("anchor_message_id")
    anchor_id = None
    if anchor_raw is not None:
        try:
            anchor_id = int(anchor_raw)
        except (TypeError, ValueError):
            anchor_id = None
    chat_view = get_chat_view(since_id=0)
    messages = chat_view.get("messages") or []
    if not isinstance(messages, list):
        messages = []
    if background_ids:
        background = related_background_from_messages(messages, message_ids=background_ids)
    else:
        background = related_background_from_messages(
            messages,
            anchor_id=anchor_id,
            limit=8,
        )
    try:
        result = promote_chat_to_dev_task(
            task_text=text,
            target_handle=target_handle,
            category=category,
            background_messages=background,
        )
    except AgentChatError as err:
        return jsonify(ok=False, error=str(err)), 400
    return jsonify(result), 202


@app.route("/api/v1/admin/dev_task/attachment/upload", methods=["POST"])
def admin_upload_dev_task_attachment():
    """Multipart upload for Dev Task attachments (extensible beyond images)."""
    denied = _admin_auth_error()
    if denied:
        return denied
    from dev_task_attachments import DEV_TASK_UPLOAD_INTENT

    if "file" not in request.files:
        return jsonify(ok=False, error='expected multipart field name "file"'), 400
    f = request.files["file"]
    data = f.read()
    if not data:
        return jsonify(ok=False, error="empty file"), 400
    try:
        original = _validate_asset_filename(f.filename or "upload.bin")
    except AssetFilenameError as e:
        return jsonify(ok=False, error=str(e)), 400
    mime_type = str(request.form.get("mime_type") or f.mimetype or "").strip()
    if not mime_type or mime_type == "application/octet-stream":
        mime_type = _guess_mime(original, "application/octet-stream")
    kind = str(request.form.get("kind") or request.form.get("type") or "").strip().lower()
    asset_type = _infer_asset_type(
        mime_type=mime_type,
        filename=original,
        explicit=kind,
    )
    put = getattr(brain_db, "put_asset", None)
    if not callable(put):
        return jsonify(ok=False, error="assets catalog not available"), 503
    try:
        stored = _store_uploaded_asset_bytes(data, filename=original, mime_type=mime_type)
    except Exception as e:
        log.warning("admin dev_task attachment store failed: %s", e)
        if _use_local_upload_store():
            return jsonify(ok=False, error=f"本地图床写入失败: {e}"), 502
        return jsonify(ok=False, error=f"img-server upload failed: {e}"), 502
    saved_as = stored["saved_as"]
    aid = "asset_" + secrets.token_hex(12)
    backend = str(stored.get("backend") or "img_server").strip() or "img_server"
    storage = {
        "backend": backend,
        "key": saved_as,
        "saved_as": saved_as,
    }
    # `public_base` is deliberately NOT persisted (same rationale as
    # /api/v1/assets/upload): it is resolved fresh from img-server at use time.
    record = {
        "asset_id": aid,
        "type": asset_type,
        "mime_type": mime_type,
        "status": "ready",
        "producer": DEV_TASK_UPLOAD_INTENT,
        "producer_capability": DEV_TASK_UPLOAD_INTENT,
        "size_bytes": len(data),
        "metadata": {
            "upload_intent": DEV_TASK_UPLOAD_INTENT,
            "original_filename": original,
        },
        "storage": storage,
    }
    try:
        put(record)
    except ValueError as e:
        return jsonify(ok=False, error=str(e)), 400
    except Exception:
        log.exception("admin dev_task attachment put_asset failed")
        return jsonify(ok=False, error="register_asset failed"), 500
    from debug_attachments import normalize_attachments

    attachment = normalize_attachments(
        [
            {
                "asset_id": aid,
                "kind": kind or asset_type,
                "mime_type": mime_type,
                "filename": original,
            }
        ]
    )[0]
    return jsonify(ok=True, attachment=attachment)


@app.route("/api/v1/admin/dev_task/usage", methods=["GET"])
def admin_dev_task_usage():
    denied = _admin_auth_error()
    if denied:
        return denied
    period = (request.args.get("period") or "").strip().lower()
    days_raw = request.args.get("days")
    if period:
        return jsonify(ok=True, usage=get_agent_task_usage_stats(period=period))
    if days_raw is not None:
        try:
            days = int(days_raw)
        except (TypeError, ValueError):
            days = 7
        if days <= 0:
            days = None
        return jsonify(ok=True, usage=get_agent_task_usage_stats(days=days))
    return jsonify(ok=True, usage=get_agent_task_usage_stats(period="week"))


@app.route("/api/v1/admin/dev_task/categories", methods=["GET"])
def admin_dev_task_categories():
    denied = _admin_auth_error()
    if denied:
        return denied
    return jsonify(ok=True, categories=get_dev_task_categories())


@app.route("/api/v1/admin/dev_task/<task_id>/category", methods=["PATCH"])
def admin_patch_dev_task_category(task_id):
    denied = _admin_auth_error()
    if denied:
        return denied
    try:
        task_id_int = int(task_id)
    except (TypeError, ValueError):
        return jsonify(ok=False, error="task_id must be an integer"), 400
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify(ok=False, error="JSON object required"), 400
    category_raw = data.get("category")
    if category_raw in (None, ""):
        return jsonify(ok=False, error="category is required"), 400
    view = set_agent_task_category(task_id_int, str(category_raw))
    if not view:
        return jsonify(ok=False, error="dev task not found"), 404
    return jsonify(ok=True, **view)


@app.route("/api/v1/admin/dev_task/<task_id>/cancel", methods=["POST"])
def admin_cancel_dev_task(task_id):
    denied = _admin_auth_error()
    if denied:
        return denied
    try:
        task_id_int = int(task_id)
    except (TypeError, ValueError):
        return jsonify(ok=False, error="task_id must be an integer"), 400
    view = cancel_agent_task(task_id_int)
    if not view:
        return jsonify(ok=False, error="dev task not found"), 404
    return jsonify(ok=True, **view)


@app.route("/api/v1/admin/dev_task/<task_id>", methods=["GET"])
def admin_get_dev_task(task_id):
    denied = _admin_auth_error()
    if denied:
        return denied
    try:
        task_id_int = int(task_id)
    except (TypeError, ValueError):
        return jsonify(ok=False, error="task_id must be an integer"), 400
    view = get_agent_task(task_id_int)
    if not view:
        return jsonify(ok=False, error="dev task not found"), 404
    return jsonify(ok=True, **view)


@app.route("/api/v1/admin/dev_tasks", methods=["GET"])
def admin_list_dev_tasks():
    denied = _admin_auth_error()
    if denied:
        return denied
    before_raw = request.args.get("before_id")
    before_id = None
    if before_raw not in (None, ""):
        try:
            before_id = int(before_raw)
        except (TypeError, ValueError):
            return jsonify(ok=False, error="before_id must be an integer"), 400
        if before_id < 1:
            return jsonify(ok=False, error="before_id must be >= 1"), 400
    limit = ADMIN_INTENTS_DEFAULT
    if request.args.get("limit") not in (None, ""):
        try:
            limit = int(request.args.get("limit"))
        except (TypeError, ValueError):
            return jsonify(ok=False, error="limit must be an integer"), 400
    limit = max(1, min(limit, ADMIN_INTENTS_MAX))
    thread_raw = request.args.get("thread_id")
    thread_id = None
    if thread_raw not in (None, ""):
        try:
            thread_id = int(thread_raw)
        except (TypeError, ValueError):
            return jsonify(ok=False, error="thread_id must be an integer"), 400
    roots_only = request.args.get("roots_only", "1") not in ("0", "false", "no")
    category_raw = request.args.get("category")
    category = None
    if category_raw not in (None, ""):
        category = str(category_raw).strip()
    page = list_agent_tasks(
        before_id=before_id,
        limit=limit,
        thread_id=thread_id,
        roots_only=roots_only if thread_id is None else False,
        category=category,
    )
    return jsonify(ok=True, **page)


@app.route("/api/v1/debug/report", methods=["POST"])
def post_debug_report():
    """User/Business Console: one-tap bug report with auto-collected execution context."""
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify(ok=False, error="JSON object required"), 400
    source = str(data.get("source") or "user_console").strip() or "user_console"
    raw_intent = data.get("intent_id")
    if raw_intent in (None, ""):
        intent_id = 0
    else:
        try:
            intent_id = int(raw_intent)
        except (TypeError, ValueError):
            return jsonify(ok=False, error="intent_id must be an integer"), 400
    participant_id = str(
        data.get("participant_id") or data.get("edge_id") or ""
    ).strip()
    if not participant_id:
        return jsonify(ok=False, error="participant_id is required"), 400
    user_summary = str(data.get("user_summary") or data.get("summary") or "").strip()
    problem_type = str(data.get("problem_type") or data.get("feedback_type") or "").strip()
    attachments_raw = data.get("attachments")
    if attachments_raw is None:
        attachments_raw = data.get("attachment_asset_ids")
    client_snapshot = data.get("client_snapshot")
    if client_snapshot is not None and not isinstance(client_snapshot, dict):
        return jsonify(ok=False, error="client_snapshot must be an object"), 400
    if attachments_raw is not None and not isinstance(attachments_raw, list):
        return jsonify(ok=False, error="attachments must be an array"), 400
    result = submit_debug_report(
        intent_id=intent_id,
        participant_id=participant_id,
        source=source,
        user_summary=user_summary,
        problem_type=problem_type,
        attachments=attachments_raw,
        client_snapshot=client_snapshot,
        get_intent=lambda iid: get_intent(iid),
    )
    if not result.get("ok"):
        return jsonify(ok=False, **{k: v for k, v in result.items() if k != "ok"}), 400
    return jsonify(ok=True, **{k: v for k, v in result.items() if k != "ok"})


@app.route("/api/v1/admin/debug/issues", methods=["GET"])
def admin_list_debug_issues():
    denied = _admin_auth_error()
    if denied:
        return denied
    before_raw = request.args.get("before_id")
    before_id = None
    if before_raw not in (None, ""):
        try:
            before_id = int(before_raw)
        except (TypeError, ValueError):
            return jsonify(ok=False, error="before_id must be an integer"), 400
    intent_raw = request.args.get("intent_id")
    intent_id = None
    if intent_raw not in (None, ""):
        try:
            intent_id = int(intent_raw)
        except (TypeError, ValueError):
            return jsonify(ok=False, error="intent_id must be an integer"), 400
    limit = ADMIN_INTENTS_DEFAULT
    if request.args.get("limit") not in (None, ""):
        try:
            limit = int(request.args.get("limit"))
        except (TypeError, ValueError):
            return jsonify(ok=False, error="limit must be an integer"), 400
    limit = max(1, min(limit, ADMIN_INTENTS_MAX))
    page = list_debug_issues(before_id=before_id, limit=limit, intent_id=intent_id)
    return jsonify(ok=True, **page)


@app.route("/api/v1/admin/debug/issue/<issue_id>", methods=["GET"])
def admin_get_debug_issue(issue_id):
    denied = _admin_auth_error()
    if denied:
        return denied
    try:
        issue_id_int = int(issue_id)
    except (TypeError, ValueError):
        return jsonify(ok=False, error="issue_id must be an integer"), 400
    view = get_debug_issue(issue_id_int)
    if not view:
        return jsonify(ok=False, error="issue not found"), 404
    return jsonify(ok=True, issue=view)


@app.route("/api/v1/admin/docs", methods=["GET"])
def admin_list_docs():
    denied = _admin_auth_error()
    if denied:
        return denied
    docs = list_documents()
    return jsonify(ok=True, docs=docs, count=len(docs), root=str(docs_root()))


@app.route("/api/v1/admin/docs/<path:rel_path>", methods=["GET"])
def admin_get_doc(rel_path):
    denied = _admin_auth_error()
    if denied:
        return denied
    try:
        doc = read_document(rel_path)
    except DocsBrowserError as e:
        return jsonify(ok=False, error=str(e)), 400
    return jsonify(ok=True, doc=doc)


@app.route("/api/v1/edges", methods=["GET"])
def list_edges_view():
    out = []
    for info in brain_db.list_heartbeats().values():
        out.append(_edge_public_view(info))
    return jsonify({"edges": out})


@app.route("/api/v1/edges/<edge_id>", methods=["GET"])
def get_edge_view(edge_id):
    rec = brain_db.get_registration(edge_id)
    if rec is None:
        return jsonify(ok=False, error="unknown edge_id"), 404
    beats = brain_db.list_heartbeats()
    if edge_id in beats:
        merged = dict(rec)
        merged.update(beats[edge_id])
        rec = merged
    return jsonify(_edge_public_view(rec))


def _asset_representation_storage(storage: dict, representation: str) -> dict:
    """Map logical representation → img_server keys (original vs preview thumbnail)."""
    base = dict(storage or {})
    rep = str(representation or "original").strip().lower()
    if rep not in ("preview", "thumbnail"):
        return base
    preview_key = str(base.get("preview_key") or base.get("cloud_preview_key") or "").strip()
    if not preview_key:
        return base
    out = dict(base)
    out["key"] = preview_key
    cloud_preview = str(base.get("cloud_preview_key") or preview_key).strip()
    if cloud_preview:
        out["cloud_key"] = cloud_preview
    return out


def _asset_media_urls(storage: dict, request_url: str) -> list:
    """Candidate HTTP URLs the Brain can fetch img_server bytes from.

    The Brain proxies bytes (it never hands out storage URLs), so it must reach
    the img-server it itself uploads to — co-located loopback by default, which
    is valid no matter what LAN IP DHCP assigns today. The LAN-facing
    `public_base` is NOT read from storage: it is a volatile runtime value and
    is not persisted with the asset (storage keeps only backend+key).
    """
    urls = []
    seen = set()

    def add(url):
        u = str(url or "").strip()
        if u and u not in seen:
            seen.add(u)
            urls.append(u)

    def add_base_key(base, key):
        b = str(base or "").strip().rstrip("/")
        k = str(key or "").strip()
        if not k:
            return
        if k.startswith("http://") or k.startswith("https://"):
            add(k)
            return
        if not b:
            return
        path = k if k.startswith("/") else f"/{k}"
        add(b + path)

    # Cloud mirror first so Intent Source / phone can load AssetRef off-LAN.
    add_base_key(storage.get("cloud_public_base"), storage.get("cloud_key") or storage.get("key"))
    key = str(storage.get("key") or storage.get("saved_as") or "").strip()
    # Co-located img-server this Brain writes to (loopback default) — always
    # current and reachable regardless of LAN re-IP.
    if key and not (key.startswith("http://") or key.startswith("https://")):
        add_base_key(_img_server_internal_base(), key)
        try:
            brain = urllib.parse.urlparse(request_url)
            if brain.hostname:
                add("%s://%s:8080/%s" % (brain.scheme or "http", brain.hostname, key.lstrip("/")))
        except Exception:
            pass
    return urls


_ASSET_META_KEYS = (
    "asset_id",
    "type",
    "mime_type",
    "size_bytes",
    "size",
    "status",
    "metadata",
    "created_at",
    "updated_at",
    "expires_at",
)

_STORAGE_URL_KEYS = frozenset({"url", "photo_url", "image_url"})


def _asset_metadata_only(record: dict) -> dict:
    record = record or {}
    out = {k: record[k] for k in _ASSET_META_KEYS if record.get(k) is not None}
    aid = str(record.get("asset_id") or "").strip()
    if aid:
        out["asset_id"] = aid
    return out


def _asset_stream_href(asset_id: str, intent_id: str, *, representation: str = "original") -> str:
    params = {"intent_id": str(intent_id or "").strip()}
    rep = str(representation or "original").strip().lower()
    if rep and rep != "original":
        params["representation"] = rep
    qs = urllib.parse.urlencode(params)
    return "/api/v1/assets/%s/content?%s" % (urllib.parse.quote(str(asset_id), safe=""), qs)


def _asset_runtime_storage(storage: dict) -> dict:
    if not isinstance(storage, dict):
        return {}
    return {k: v for k, v in storage.items() if k not in _STORAGE_URL_KEYS}


def _asset_endpoint_view(record: dict, intent_id: str) -> dict:
    out = _asset_metadata_only(record)
    aid = str((record or {}).get("asset_id") or "").strip()
    iid = str(intent_id or "").strip()
    if aid and iid:
        storage = (record or {}).get("storage")
        rep = "original"
        if isinstance(storage, dict):
            has_preview = bool(
                str(storage.get("preview_key") or storage.get("cloud_preview_key") or "").strip()
            )
            has_original = bool(str(storage.get("key") or storage.get("cloud_key") or "").strip())
            if has_preview and not has_original:
                rep = "preview"
            elif has_preview:
                rep = "preview"
        out["stream"] = {"href": _asset_stream_href(aid, iid, representation=rep)}
    return out


def _asset_runtime_view(record: dict) -> dict:
    out = _asset_metadata_only(record)
    storage = _asset_runtime_storage((record or {}).get("storage"))
    if storage:
        out["storage"] = storage
    return out


def _asset_public_view(record: dict, *, include_storage: bool = False) -> dict:
    """Metadata-only snapshot (no storage URLs). Legacy include_storage ignored."""
    return _asset_metadata_only(record)


def _caller_is_runtime(edge_id: str) -> bool:
    pid = str(edge_id or "").strip()
    if not pid or not _participant_is_registered(pid):
        return False
    if not _participant_schedule_eligible(pid):
        return False
    rec = _participant_snapshot(pid)
    ok, _reason = can_participate(pid, role="runtime", rec=rec)
    return ok


def _proxy_asset_upstream(url: str, default_mime: str):
    """Stream bytes from img_server; prefer Content-Length for weak clients."""
    upstream = urllib.request.urlopen(url, timeout=20)
    raw_ct = upstream.headers.get("Content-Type") or default_mime
    content_type = str(raw_ct).split(";", 1)[0].strip() or default_mime
    content_length = upstream.headers.get("Content-Length")
    headers = {"Cache-Control": "no-store"}

    def generate():
        try:
            while True:
                chunk = upstream.read(65536)
                if not chunk:
                    break
                yield chunk
        finally:
            upstream.close()

    if content_length:
        try:
            cl = int(content_length)
            if cl >= 0:
                return Response(
                    stream_with_context(generate()),
                    mimetype=content_type,
                    headers=headers,
                    content_length=cl,
                )
        except (TypeError, ValueError):
            pass
    return Response(stream_with_context(generate()), mimetype=content_type, headers=headers)


def _serve_asset_bytes(record: dict, *, representation: str, request_url: str):
    storage = record.get("storage") if isinstance(record.get("storage"), dict) else {}
    storage = _asset_representation_storage(storage, representation)
    mime = str(record.get("mime_type") or "").strip() or "image/jpeg"
    backend = str(storage.get("backend") or "").strip().lower()
    if backend == "local_upload":
        key = str(storage.get("key") or storage.get("saved_as") or "").strip()
        if key and ".." not in key and not key.startswith("/"):
            path = _asset_upload_dir() / Path(key).name
            if path.is_file():
                return (
                    send_file(
                        path,
                        mimetype=mime,
                        as_attachment=False,
                        download_name=path.name,
                        max_age=0,
                    ),
                    None,
                )
        return None, "local_upload file missing"
    urls = _asset_media_urls(storage, request_url)
    last_error = "no storage locator"
    for url in urls:
        try:
            return _proxy_asset_upstream(url, mime), None
        except Exception as exc:
            last_error = str(exc)
            continue
    return None, last_error


def _asset_producer_may_read(record: dict, edge_id: str) -> bool:
    """Allow producer edge to read local Input uploads without an intent grant."""
    pid = str(edge_id or "").strip()
    if not pid:
        return False
    producer = str(
        (record or {}).get("producer_edge_id")
        or (record or {}).get("edge_id")
        or ""
    ).strip()
    return bool(producer) and producer == pid


def _grant_asset_read(asset_id, intent_id) -> None:
    """Record that this intent may fetch bytes for asset_id."""
    aid = str(asset_id or "").strip()
    iid = str(intent_id or "").strip()
    grant = getattr(brain_db, "put_asset_grant", None)
    if not aid or not iid or not callable(grant):
        return
    try:
        grant({"asset_id": aid, "intent_id": iid})
    except Exception:
        log.exception("asset grant failed asset=%s intent=%s", aid, iid)


def _iter_plan_input_asset_ids(plan) -> list[str]:
    """Concrete asset_id values in plan step input_constrict (skip $hydrate tokens)."""
    ids: list[str] = []
    seen: set[str] = set()
    for step in plan or []:
        if not isinstance(step, dict):
            continue
        inp = step.get("input_constrict") or {}
        if not isinstance(inp, dict):
            continue
        refs = []
        ref = _as_asset_ref(inp.get("asset_ref"))
        if ref:
            refs.append(ref)
        refs.extend(_parse_asset_refs_list(inp.get("asset_refs")))
        for item in refs:
            aid = str((item or {}).get("asset_id") or "").strip()
            if not aid or aid.startswith("$") or aid in seen:
                continue
            seen.add(aid)
            ids.append(aid)
    return ids


def _grant_plan_input_assets(intent_id, plan) -> None:
    """Grant read on assets the planner bound into this intent's steps.

    iPhone photo uploads are catalogued without origin_intent_id. A later
    「最新照片里这个字」plan copies that asset_ref into input_constrict.
    Runtime fetch only sees storage if this intent has a grant; otherwise
    Brain returns the public metadata view and Mac reports no storage locator.
    """
    iid = str(intent_id or "").strip()
    if not iid:
        return
    for aid in _iter_plan_input_asset_ids(plan):
        _grant_asset_read(aid, iid)


def _grant_presented_asset(intent) -> None:
    """If Brain put asset_ref on this intent's presentation, the issuer may fetch bytes."""
    if not isinstance(intent, dict):
        return
    iid = str(intent.get("id") or intent.get("intent_id") or "").strip()
    pres = intent.get("presentation")
    if not iid or not isinstance(pres, dict):
        return
    ref = _as_asset_ref(pres.get("asset_ref"))
    if not ref:
        return
    _grant_asset_read(ref.get("asset_id"), iid)


def _intent_job_presents_asset(intent_id: str, asset_id: str) -> bool:
    """True if this intent's stored presentation (or ctx) names the asset."""
    iid = str(intent_id or "").strip()
    aid = str(asset_id or "").strip()
    getter = getattr(brain_db, "get_job", None)
    if not iid or not aid or not callable(getter):
        return False
    try:
        job = getter(iid)
    except Exception:
        return False
    if not isinstance(job, dict):
        return False
    blobs = []
    pres = job.get("presentation")
    if isinstance(pres, dict):
        blobs.append(pres)
    ctx = job.get("ctx_param") or job.get("context")
    if isinstance(ctx, dict):
        blobs.append(ctx)
    outputs = job.get("step_outputs")
    if isinstance(outputs, dict):
        blobs.extend(v for v in outputs.values() if isinstance(v, dict))
    for blob in blobs:
        ref = _as_asset_ref(blob.get("asset_ref"))
        if ref and str(ref.get("asset_id") or "").strip() == aid:
            return True
    plan = job.get("execution_plan")
    if isinstance(plan, list) and aid in _iter_plan_input_asset_ids(plan):
        return True
    return False


def _asset_client_may_read(record: dict, intent_id: str) -> bool:
    iid = str(intent_id or "").strip()
    aid = str((record or {}).get("asset_id") or "").strip()
    if not iid or not aid:
        return False
    checker = getattr(brain_db, "has_asset_grant", None)
    if callable(checker) and checker(aid, iid):
        return True
    origin = str((record or {}).get("origin_intent_id") or "").strip()
    if origin and origin == iid:
        return True
    # asset.inventory reuses an older photo: presentation.asset_ref is the grant.
    if _intent_job_presents_asset(iid, aid):
        _grant_asset_read(aid, iid)
        return True
    return False


def _asset_has_read_grant(asset_id: str, intent_id: str) -> bool:
    rec = {"asset_id": asset_id}
    getter = getattr(brain_db, "get_asset", None)
    if callable(getter):
        found = getter(asset_id)
        if isinstance(found, dict):
            rec = found
    return _asset_client_may_read(rec, intent_id)


def _parse_asset_day_window(day: str, timezone_name: str | None) -> tuple[float, float] | None:
    """Return [start, end) unix seconds for day=today|yesterday|YYYY-MM-DD in timezone."""
    raw = str(day or "").strip().lower()
    if not raw:
        return None
    tz_name = str(timezone_name or "").strip() or "Asia/Shanghai"
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("Asia/Shanghai")
    now = datetime.now(tz)
    if raw in ("today", "今天"):
        start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif raw in ("yesterday", "昨天"):
        start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    else:
        try:
            y, m, d = [int(p) for p in raw.split("-", 2)]
            start_dt = datetime(y, m, d, tzinfo=tz)
        except (TypeError, ValueError):
            return None
    end_dt = start_dt + timedelta(days=1)
    return start_dt.timestamp(), end_dt.timestamp()


def _parse_asset_time_bound(raw: str | None) -> float | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    try:
        # ISO-8601; treat naive as local/Asia/Shanghai wall time.
        if text.endswith("Z"):
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
        return dt.timestamp()
    except ValueError:
        return None


@app.route("/api/v1/assets", methods=["GET"])
def list_assets_view():
    """Inventory Brain-registered assets (filters). Not the phone camera roll."""
    lister = getattr(brain_db, "list_assets", None)
    counter = getattr(brain_db, "count_assets", None)
    if not callable(lister) or not callable(counter):
        return jsonify(ok=False, error="assets catalog not available"), 503

    asset_type = str(request.args.get("type") or "").strip() or None
    producer = (
        str(request.args.get("producer_capability") or request.args.get("producer") or "").strip()
        or None
    )
    day = str(request.args.get("day") or "").strip()
    timezone_name = str(request.args.get("timezone") or "").strip() or None
    created_since = _parse_asset_time_bound(request.args.get("since"))
    created_until = _parse_asset_time_bound(request.args.get("until"))
    if day:
        window = _parse_asset_day_window(day, timezone_name)
        if window is None:
            return jsonify(ok=False, error="invalid day (use today, yesterday, or YYYY-MM-DD)"), 400
        created_since, created_until = window

    limit_raw = str(request.args.get("limit") or "").strip()
    limit = None
    if limit_raw:
        try:
            limit = max(0, min(500, int(limit_raw)))
        except ValueError:
            return jsonify(ok=False, error="limit must be an integer"), 400

    offset_raw = str(request.args.get("offset") or "").strip()
    offset = 0
    if offset_raw:
        try:
            offset = max(0, int(offset_raw))
        except ValueError:
            return jsonify(ok=False, error="offset must be an integer"), 400

    order_raw = str(request.args.get("order") or "").strip().lower()
    # Default newest_first for inventory lists; oldest_first for「第 N 张」index walks.
    newest_first = order_raw not in (
        "oldest_first",
        "oldest",
        "asc",
        "created_asc",
    )

    filt = dict(
        asset_type=asset_type,
        producer_capability=producer,
        created_since=created_since,
        created_until=created_until,
    )
    try:
        total = int(counter(**filt))
        rows = lister(
            **filt, limit=limit, offset=offset, newest_first=newest_first
        )
    except Exception:
        log.exception("list_assets failed")
        return jsonify(ok=False, error="list_assets failed"), 500

    intent_id = str(request.args.get("intent_id") or "").strip()
    grant = getattr(brain_db, "put_asset_grant", None)
    items = []
    for rec in rows:
        if not isinstance(rec, dict):
            continue
        aid = str(rec.get("asset_id") or "").strip()
        if not aid:
            continue
        if intent_id and callable(grant):
            try:
                grant({"asset_id": aid, "intent_id": intent_id})
            except ValueError:
                pass
        ref = rec.get("asset_ref") if isinstance(rec.get("asset_ref"), dict) else None
        if not isinstance(ref, dict):
            ref = {"asset_id": aid, "type": str(rec.get("type") or "other")}
            if rec.get("mime_type"):
                ref["mime_type"] = rec["mime_type"]
        items.append(
            {
                "asset_ref": ref,
                "type": rec.get("type"),
                "mime_type": rec.get("mime_type"),
                "created_at": rec.get("created_at"),
                "producer_capability": rec.get("producer_capability"),
                "origin_intent_id": rec.get("origin_intent_id"),
            }
        )

    return jsonify(
        ok=True,
        count=total,
        assets=items,
        filters={
            "type": asset_type,
            "producer_capability": producer,
            "day": day or None,
            "timezone": timezone_name,
            "since": created_since,
            "until": created_until,
            "limit": limit,
        },
    )


def _entity_public(rec: dict[str, Any]) -> dict[str, Any]:
    return {
        "entity_id": rec.get("entity_id"),
        "type": rec.get("type"),
        "name": rec.get("name"),
        "metadata": rec.get("metadata") if isinstance(rec.get("metadata"), dict) else {},
        "state": rec.get("state") if isinstance(rec.get("state"), dict) else {},
        "references": rec.get("references")
        if isinstance(rec.get("references"), dict)
        else {},
        "created_at_ms": rec.get("created_at_ms"),
        "updated_at_ms": rec.get("updated_at_ms"),
    }


@app.route("/api/v1/entities", methods=["GET"])
def list_entities_view():
    """Entity Registry V1 — World Model device anchors (not participants/assets)."""
    lister = getattr(brain_db, "list_entities", None)
    if not callable(lister):
        return jsonify(ok=False, error="entities registry not available"), 503
    entity_type = str(request.args.get("type") or "").strip().lower() or None
    limit_raw = str(request.args.get("limit") or "").strip()
    limit = None
    if limit_raw:
        try:
            limit = max(0, min(500, int(limit_raw)))
        except ValueError:
            return jsonify(ok=False, error="limit must be an integer"), 400
    try:
        rows = lister(entity_type=entity_type, limit=limit)
    except Exception:
        log.exception("list_entities failed")
        return jsonify(ok=False, error="list_entities failed"), 500
    items = [_entity_public(r) for r in rows if isinstance(r, dict)]
    return jsonify(
        ok=True,
        count=len(items),
        entities=items,
        filters={"type": entity_type, "limit": limit},
    )


@app.route("/api/v1/entities/<entity_id>", methods=["GET"])
def get_entity_view(entity_id: str):
    getter = getattr(brain_db, "get_entity", None)
    if not callable(getter):
        return jsonify(ok=False, error="entities registry not available"), 503
    eid = str(entity_id or "").strip()
    if not eid:
        return jsonify(ok=False, error="entity_id required"), 400
    try:
        rec = getter(eid)
    except Exception:
        log.exception("get_entity failed")
        return jsonify(ok=False, error="get_entity failed"), 500
    if not isinstance(rec, dict):
        return jsonify(ok=False, error="entity not found"), 404
    return jsonify(ok=True, entity=_entity_public(rec))


@app.route("/api/v1/entities/<entity_id>", methods=["PUT"])
def put_entity_view(entity_id: str):
    """Upsert Entity (admin/seed). Not for capability plugins to invent world objects."""
    putter = getattr(brain_db, "upsert_entity", None)
    if not callable(putter):
        return jsonify(ok=False, error="entities registry not available"), 503
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify(ok=False, error="JSON object required"), 400
    eid = str(entity_id or "").strip()
    if not eid:
        return jsonify(ok=False, error="entity_id required"), 400
    body = dict(data)
    body["entity_id"] = eid
    try:
        rec = putter(body)
    except ValueError as e:
        return jsonify(ok=False, error=str(e)), 400
    except Exception:
        log.exception("upsert_entity failed")
        return jsonify(ok=False, error="upsert_entity failed"), 500
    return jsonify(ok=True, entity=_entity_public(rec))


@app.route("/api/v1/assets", methods=["POST"])
def register_asset_view():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify(ok=False, error="JSON object required"), 400
    put = getattr(brain_db, "put_asset", None)
    if not callable(put):
        return jsonify(ok=False, error="assets catalog not available"), 503
    aid = str(data.get("asset_id") or "").strip()
    if not aid:
        aid = "asset_" + secrets.token_hex(12)
        data = dict(data)
        data["asset_id"] = aid
    try:
        put(data)
    except ValueError as e:
        return jsonify(ok=False, error=str(e)), 400
    except Exception:
        log.exception("register_asset failed")
        return jsonify(ok=False, error="register_asset failed"), 500
    intent_id = str(data.get("intent_id") or data.get("execution_id") or "").strip()
    grant = getattr(brain_db, "put_asset_grant", None)
    if intent_id and callable(grant):
        try:
            grant(
                {
                    "asset_id": aid,
                    "intent_id": intent_id,
                    "execution_id": intent_id,
                    "capability_id": data.get("producer") or data.get("creator"),
                    "permission": "read",
                }
            )
        except ValueError as e:
            return jsonify(ok=False, error=str(e)), 400
    rec = None
    getter = getattr(brain_db, "get_asset", None)
    if callable(getter):
        rec = getter(aid)
    rec = rec or {"asset_id": aid}
    if intent_id and _asset_client_may_read(rec, intent_id):
        asset = _asset_endpoint_view(rec, intent_id)
    else:
        asset = _asset_public_view(rec)
    return jsonify(ok=True, asset_id=aid, asset=asset)


@app.route("/api/v1/assets/<asset_id>", methods=["GET"])
def get_asset_view(asset_id):
    getter = getattr(brain_db, "get_asset", None)
    if not callable(getter):
        return jsonify(ok=False, error="assets catalog not available"), 503
    rec = getter(asset_id)
    if rec is None or str(rec.get("status") or "").lower() == "deleted":
        return jsonify(ok=False, error="not found"), 404
    intent_id = str(request.args.get("intent_id") or "").strip()
    edge_id = str(request.args.get("edge_id") or "").strip()
    if _asset_client_may_read(rec, intent_id):
        if edge_id and _caller_is_runtime(edge_id):
            asset = _asset_runtime_view(rec)
        else:
            asset = _asset_endpoint_view(rec, intent_id)
    else:
        asset = _asset_public_view(rec)
    return jsonify(
        ok=True,
        asset=asset,
    )


def _get_asset_content_handler(asset_id):
    getter = getattr(brain_db, "get_asset", None)
    if not callable(getter):
        return jsonify(ok=False, error="assets catalog not available"), 503
    rec = getter(asset_id)
    if rec is None or str(rec.get("status") or "").lower() == "deleted":
        return jsonify(ok=False, error="not found"), 404
    intent_id = str(request.args.get("intent_id") or "").strip()
    edge_id = str(request.args.get("edge_id") or "").strip()
    if not (
        _asset_client_may_read(rec, intent_id)
        or _asset_producer_may_read(rec, edge_id)
        or _admin_request_ok()
    ):
        return jsonify(ok=False, error="asset_ref grant required"), 403
    representation = str(request.args.get("representation") or "original").strip().lower()
    body, err = _serve_asset_bytes(
        rec,
        representation=representation,
        request_url=request.url,
    )
    if body is not None:
        return body
    return jsonify(ok=False, error="asset_ref bytes unavailable: %s" % err), 502


@app.route("/api/v1/assets/<asset_id>/content", methods=["GET"])
def get_asset_content(asset_id):
    """Endpoint bytes for an AssetRef. Presentation still carries only asset_ref."""
    return _get_asset_content_handler(asset_id)


@app.route("/api/v1/assets/<asset_id>/stream", methods=["GET"])
def get_asset_stream(asset_id):
    """Alias of /content — asset.stream() HTTP mapping."""
    return _get_asset_content_handler(asset_id)


@app.route("/api/v1/devices/living-room/intents", methods=["GET", "POST"])
def command_handler():
    global commands_queue
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return jsonify(ok=False, error="JSON object required"), 400
        plan = data.get("execution_plan") or []
        raw_id = data.get("intent_id") or data.get("id")
        if raw_id in (None, ""):
            intent_id = brain_db.next_intent_id()
        else:
            try:
                intent_id = int(raw_id)
            except (TypeError, ValueError):
                intent_id = raw_id
            try:
                brain_db.notice_intent_id(int(intent_id))
            except (TypeError, ValueError):
                pass
        status = _normalize_status(data.get("status") or data.get("intent_status") or "intent_parsed")
        msg = data.get("msg")
        if not plan:
            status = "failed"
            msg = msg or _EMPTY_PLAN_MSG
        job = {
            "id": intent_id,
            "intent_id": intent_id,
            "status": status,
            "text": data.get("text"),
            "source": data.get("source"),
            "intent_origin": resolve_intent_origin(data.get("intent_origin")),
            "edge_id": data.get("edge_id"),
            "execution_plan": plan,
            "msg": msg,
            "error": msg if status == "failed" else data.get("error"),
        }
        stored = brain_db.upsert_queue(job)
        return jsonify(_job_to_intent(stored))

    fetch_num = 0
    max_fetch_num = 10
    edge_id = request.args.get('edge_id', "")
    if edge_id.strip() == "":
        return jsonify(intents=[])
    status = request.args.get('intent_status', "")
    if status:
        filtered_intents = []
        want = _normalize_status(status)
        for _intent in list_intents():
            if _intent.get('status') == want and _job_visible_to_edge(_intent, edge_id):
                filtered_intents.append(_intent)
    else:
        filtered_intents = [
            _job_to_intent(job)
            for job in brain_db.list_queue()
            if _job_visible_to_edge(job, edge_id)
        ]

    fetch_num_arg = request.args.get('last', "5")
    if fetch_num_arg:
        fetch_num = int(fetch_num_arg)

    fetch_num = min(fetch_num, max_fetch_num)

    sorted_intents = sorted(filtered_intents, key=lambda v: v["id"], reverse=True)

    return jsonify(intents=sorted_intents[0:fetch_num])
 


# ====================== 小度WebService接口 ======================
@app.route("/dueros_skill", methods=["POST", "GET"])
def skill_handler():
    global session_result_cache
    global commands_queue
    if request.method == 'POST':
        try:
            req_data = request.get_json()
        except Exception:
            return quick_speak("请求数据格式错误", False)

        llm_logger.info(f"duos request: {req_data}")
        log.info("dueros request: %s", req_data)

        user_msg = req_data["msg"]
        user_id = req_data["user_id"]
        session_id = req_data["session_id"]
    else:
        user_msg = request.args.get("msg", "")
        session_id = '00000000'
        user_id = '11111111'


    if user_msg.startswith("音频") or user_msg.startswith("音讯"):
        if commands_queue.get('neteasemusic') is None:
            commands_queue['neteasemusic'] = []
        song = user_msg[2:-2]
        log.info("song:%s", song)
        commands_queue['neteasemusic'].append(song)
        return quick_speak("歌曲即将播放", False)


    log.info("该问题[%s]放入大模型请求队列", user_msg)
    # 无缓存，加入排队队列
    try:
        task_queue.put_nowait({
            "question": user_msg,
            "session_id": session_id,
            "user_id": user_id,
        })
        queue_size = task_queue.qsize()
        tip = f"正在排队生成训练计划，当前排队{queue_size}条，稍后重新提问查看结果"
        return quick_speak(tip, True)
    except queue.Full:
        return quick_speak("当前咨询人数较多，请稍后再试", False)



@app.route("/doubao_chat", methods=["GET"])
def chat():
    user_msg = request.args.get("msg", "")
    log.info("get user msg: %s", user_msg)
    if not user_msg.strip():
        return jsonify(error="缺少提问内容"), 400
    full_prompt = SYS_PROMPT_RUNNER.format(user_question=user_msg)

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {ARK_API_KEY}"
    }
    req_body = json.dumps({
        "model": MODEL_ID,
        "messages": [{"role": "user", "content": full_prompt}],
        "temperature": 0.7,
        "max_tokens": 120
    }).encode("utf-8")

    try:
        req = urllib.request.Request(ARK_URL, data=req_body, headers=headers)
        resp = urllib.request.urlopen(req, timeout=120)
        resp_data = json.loads(resp.read().decode("utf-8"))
        _record_ark_planner_call(True)
        log.info("%s", resp_data)
        ans = resp_data["choices"][0]["message"]["content"]
        log.info("%s", ans)
        return jsonify(reply=ans)
    except urllib.error.URLError as e:
        _record_ark_planner_call(False)
        err_msg = f"网络读取超时，模型生成内容较长，当前网络不稳定"
        return jsonify(reply=err_msg)
    except Exception as e:
        _record_ark_planner_call(False)
        err_msg = f"服务异常：{str(e)}"
        return jsonify(reply=err_msg)

ALPHABET = string.ascii_letters + string.digits  # a-zA-Z0-9
def random_edge_token(length: int = 8) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def _find_by_client_hint(hint):
    hint = str(hint or "").strip()
    if not hint:
        return None
    for pid in brain_db.registration_ids():
        rec = brain_db.get_registration(pid)
        if rec and str(rec.get("client_hint") or "") == hint:
            return rec
    return None


def _registration_from_body(body, edge_id, *, client_hint=None, existing=None):
    rec = dict(existing or {})
    rec["participant_id"] = edge_id
    rec["edge_id"] = edge_id
    rec["status"] = rec.get("status") or "approved"
    rec["device_type"] = body.get("device_type") or rec.get("device_type") or "edge"
    hint = client_hint or body.get("client_hint") or rec.get("client_hint")
    if hint:
        rec["client_hint"] = hint
    for key in (
        "display_name",
        "app_version",
        "services",
        "intent_sources",
        "endpoints",
        "roles",
        "exposure_policy",
        "runtime_id",
    ):
        if body.get(key) is not None:
            rec[key] = body.get(key)
    if isinstance(body.get("roles"), (list, tuple)):
        names = {str(item or "").strip().lower() for item in body.get("roles") or []}
        rec["role_intent_source"] = "intent_source" in names
        rec["role_runtime"] = "runtime" in names
        rec["role_endpoint"] = "endpoint" in names
        rec["role_observer"] = "observer" in names
    if body.get("location") is not None:
        rec["location"] = body.get("location")
    elif body.get("room") is not None:
        rec["location"] = body.get("room")
    return rec


_REGISTERED_edges = []

@app.route("/api/v1/edge-register", methods=["GET", "POST"])
def node_register():
    global _REGISTERED_edges
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            body = {}
    else:
        body = request.args.to_dict()
    domain = instance_intent_origin()
    # P0: Runtime Identity is client-supplied and stable across Brains.
    # When the client supplies runtime_id / participant_id, it is authoritative:
    # create or update that exact id. Do NOT fall back to client_hint rebind
    # (legacy mechanism for clients that don't supply a runtime_id).
    supplied_id = str(
        body.get("runtime_id") or body.get("participant_id") or ""
    ).strip()
    client_hint = str(body.get("client_hint") or body.get("edge_id") or "").strip()
    existing = None
    if supplied_id:
        existing = brain_db.get_registration(supplied_id)
    elif client_hint:
        existing = _find_by_client_hint(client_hint)
    if existing:
        edge_id = existing["participant_id"]
        rec = _registration_from_body(
            body, edge_id, client_hint=client_hint or existing.get("client_hint"), existing=existing
        )
        brain_db.put_registration(rec, domain=domain)
        d = {
            "ts": time.time(),
            "edge_id": edge_id,
            "participant_id": edge_id,
            "runtime_id": rec.get("runtime_id") or edge_id,
            "ok": True,
            "status": "approved",
            "message": "ok",
        }
        return jsonify(d)

    edge_id = supplied_id or ("edge-node-" + random_edge_token(8))
    rec = _registration_from_body(body, edge_id, client_hint=client_hint or None)
    brain_db.put_registration(rec, domain=domain)
    if edge_id not in _REGISTERED_edges:
        _REGISTERED_edges.append(edge_id)
    d = {
        "ts": time.time(),
        "edge_id": edge_id,
        "participant_id": edge_id,
        "runtime_id": rec.get("runtime_id") or edge_id,
        "ok": True,
        "status": "approved",
        "message": "ok"
    }
    return jsonify(d)


# 最新心跳快照
_EDGES = {}
# stub：True = 注册即签发；False = 返回 pending（需另接审批）
AUTO_APPROVE = True


def upsert_edge_heartbeat(edge_id, body):
    global _EDGES
    global services_registered_mapping
    global capability_edge_mapping
    info = deepcopy(body) if isinstance(body, dict) else {}
    info["edge_id"] = edge_id
    status = str(info.get("online_status") or "online").strip().lower()
    if status not in ("online", "offline"):
        status = "online"
    info["online_status"] = status
    info["server_received_at"] = time.time()
    for _service in info.get("services") or []:
        _service['edge_id'] = edge_id
        _service['edge_name'] = body.get('display_name')
        sid = _service.get('service_id')
        if sid:
            services_registered_mapping[sid] = _service

        for cap in _service.get("capabilities") or []:
            if not isinstance(cap, dict):
                continue
            cid = cap.get("capability_id")
            if cid and not is_system_capability(str(cid)):
                # DECLARED but unavailable caps do not enter the schedulable map.
                if cap.get("available") is False:
                    continue
                # Unique mapping is rebuilt from all heartbeats in rebuild_capability_maps.
                capability_edge_mapping.setdefault(cid, edge_id)

    if "reported_at" not in info:
        info["reported_at"] = info["server_received_at"]
    _EDGES[edge_id] = info


    return info


services_registered = []
services_registered_mapping = {}
capabilities_registered = []
edge_capability_mapping = {}
capability_edge_mapping = {}

@app.route("/api/v1/edge-heartbeat", methods=["POST"])
def node_heartbeat():
    """后续心跳：必须带已签发的 edgeId。"""
    brain_time_ms = int(time.time() * 1000)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"ok": False, "error": "JSON object required"}), 400
    services = body.get("services") if isinstance(body.get("services"), list) else []
    log.info(
        "heartbeat edge_id=%s name=%s services=%s",
        body.get("edge_id"),
        body.get("display_name"),
        len(services),
    )
    log.info("client_time_ms: %s, brain_time_ms: %s", body.get("client_time_ms"), brain_time_ms)
    ts_diff = abs(brain_time_ms-int(body.get('client_time_ms') or 0))
    schedule_eligible = ts_diff < 5 * 60 * 1000
    reject_reason = None
    if not schedule_eligible:
        reject_reason = "time diff exceeded max value: " + str(ts_diff)
        log.warning("%s", reject_reason)

    global capabilities_registered
    edge_id = (body.get("edge_id") or "").strip()
    if not edge_id:
        return (
            jsonify({"ok": False, "error": "edge_id required; register first"}),
            400,
        )
    if edge_id not in _REGISTERED_edges and brain_db.get_registration(edge_id) is None:
        return jsonify({"ok": False, "error": "unknown edge_id; register first"}), 401
    delta = body.get("cloud_usage_delta")
    if isinstance(delta, list) and delta:
        try:
            brain_db.ingest_cloud_usage_delta(f"edge:{edge_id}", delta)
        except Exception:
            log.exception("cloud_usage_delta ingest failed edge_id=%s", edge_id)
    existing = brain_db.get_registration(edge_id) or {}
    domain = instance_intent_origin()
    brain_db.put_registration(
        _registration_from_body(
            {
                "display_name": body.get("display_name") or existing.get("display_name"),
                "device_type": body.get("device_type") or existing.get("device_type"),
                "app_version": body.get("app_version") or existing.get("app_version"),
                "location": body.get("location") or body.get("room") or existing.get("location"),
                "services": body.get("services") if body.get("services") is not None else existing.get("services"),
                "intent_sources": body.get("intent_sources") if body.get("intent_sources") is not None else existing.get("intent_sources"),
                "endpoints": body.get("endpoints") if body.get("endpoints") is not None else existing.get("endpoints"),
                "roles": body.get("roles"),
                "exposure_policy": body.get("exposure_policy") or existing.get("exposure_policy"),
                "runtime_id": body.get("runtime_id") or existing.get("runtime_id") or edge_id,
                "client_hint": existing.get("client_hint"),
            },
            edge_id,
            client_hint=existing.get("client_hint"),
            existing=existing,
        ),
        domain=domain,
    )
    info = upsert_edge_heartbeat(edge_id, body)
    info["brain_time_ms"] = brain_time_ms
    info["client_time_ms"] = body.get("client_time_ms")
    info["clock_skew_ms"] = ts_diff
    info["schedule_eligible"] = schedule_eligible
    if reject_reason:
        info["schedule_reject_reason"] = reject_reason
    try:
        brain_db.put_heartbeat(edge_id, info, domain=domain)
    except KeyError:
        return jsonify({"ok": False, "error": "unknown edge_id; register first"}), 401
    rebuild_capability_maps(force=True)
    payload = {
        "ok": schedule_eligible,
        "edge_id": edge_id,
        "online_status": info.get("online_status"),
        "server_received_at": info.get("server_received_at"),
        "edge": info,
        "brain_time_ms": brain_time_ms,
        "schedule_eligible": schedule_eligible,
    }
    if reject_reason:
        payload["error"] = reject_reason
        payload["ok"] = False
        return jsonify(payload), 400
    return jsonify(payload)


def _edge_public_view(info):
    out = dict(info)
    if out.get("online_status") == "online":
        received = out.get("server_received_at")
        if received is not None and (time.time() - float(received)) > ONLINE_TTL_SEC:
            out["online_status"] = "offline"
            out["online_status_note"] = "ttl"
    return out


_CAP_MAPS_LOCK = threading.Lock()
# Capability→edge map only changes on heartbeat/registration. Rebuilding from
# scratch (list_heartbeats + per-cap policy filter) is ~1-2s, and it was called
# on every dispatch AND every heartbeat — a constant, contended cost. Cache it
# and invalidate via brain_db.heartbeat_version() (bumped on every heartbeat/
# registration write). Heartbeat/policy handlers pass force=True; dispatch and
# read paths use the cache. Concurrent dispatches coalesce on the lock.
_CAP_MAPS_BUILT_GEN = -1


def rebuild_capability_maps(force: bool = False):
    """Rebuild capability→edge maps. Cached unless `force` (heartbeat/state change)
    or brain_db.heartbeat_version() advanced since the last build. Read paths
    pass force=False."""
    global _CAP_MAPS_BUILT_GEN
    gen = brain_db.heartbeat_version()
    if not force and _CAP_MAPS_BUILT_GEN == gen:
        return
    with _CAP_MAPS_LOCK:
        gen = brain_db.heartbeat_version()
        if not force and _CAP_MAPS_BUILT_GEN == gen:
            return
        _do_rebuild_capability_maps()
        _CAP_MAPS_BUILT_GEN = gen


def _do_rebuild_capability_maps():
    global services_registered_mapping, capability_edge_mapping, _EDGES
    services_registered_mapping = {}
    capability_edge_mapping = {}
    _EDGES = {}
    now = time.time()
    try:
        policy = _load_control_policy_index()
    except sqlite3.OperationalError:
        policy = {}
    cap_edges = {}
    for edge_id, info in brain_db.list_heartbeats().items():
        view = _edge_public_view(info)
        _EDGES[edge_id] = view
        if view.get("schedule_eligible") is False:
            continue
        if str(view.get("online_status") or "").lower() != "online":
            continue
        received = info.get("server_received_at")
        if received is not None and (now - float(received)) > ONLINE_TTL_SEC:
            continue
        for _service in info.get("services") or []:
            svc = dict(_service)
            allowed_caps = []
            for cap in svc.get("capabilities") or []:
                if not isinstance(cap, dict):
                    continue
                cid = cap.get("capability_id")
                if not cid or is_system_capability(str(cid)):
                    continue
                # P0: Availability filter. `available` comes from the Runtime's
                # IsAvailable() probe in the heartbeat snapshot. Absent = treat as
                # available (legacy clients / declaration-only). DECLARED but
                # unavailable caps stay in participants.services (Declaration) but
                # do not enter the schedulable map.
                if cap.get("available") is False:
                    continue
                ok, _reason = can_participate(
                    edge_id,
                    capability=str(cid),
                    rec=view,
                    policy_index=policy,
                )
                if not ok:
                    continue
                allowed_caps.append(cap)
            if not allowed_caps:
                continue
            svc["capabilities"] = allowed_caps
            svc["edge_id"] = edge_id
            svc["edge_name"] = info.get("display_name")
            sid = svc.get("service_id")
            if sid:
                services_registered_mapping[f"{edge_id}::{sid}"] = svc
            for cap in allowed_caps:
                cid = cap.get("capability_id")
                if cid:
                    cap_edges.setdefault(str(cid), [])
                    row_key = (str(edge_id), str(sid or ""))
                    if row_key not in cap_edges[str(cid)]:
                        cap_edges[str(cid)].append(row_key)
    capability_edge_mapping = {}
    for cid, rows in cap_edges.items():
        if len(rows) == 1:
            capability_edge_mapping[cid] = rows[0][0]


def _requeue_unplanned_jobs():
    if os.environ.get("BRAIN_SKIP_LLM_WORKER") == "1":
        return
    for job in brain_db.list_jobs():
        if str(job.get("status") or "") != "intent_received":
            continue
        if _should_skip_llm_planner(job):
            continue
        try:
            task_queue.put_nowait(
                {
                    "question": job.get("text") or "",
                    "session_id": "",
                    "user_id": "",
                    "edge_id": job.get("edge_id") or "",
                    "source": job.get("source") or "text",
                    "intent_id": job.get("id"),
                }
            )
        except queue.Full:
            break


# Non-terminal jobs past planning that a Brain restart leaves orphaned: the
# in-flight dispatch/execution state is in-memory and dies with the process.
# `intent_received` is re-queued above; these statuses have no resume path.
_ORPHAN_STATUSES = frozenset(
    {"intent_parsed", "intent_scheduled", "intent_dispatched", "running"}
)
# Only fail orphans older than the grace window so we don't race a fresh
# dispatch whose Edge may still report back right after a restart.
_ORPHAN_GRACE_SEC = 5 * 60


def _reconcile_orphan_jobs() -> int:
    """Fail non-terminal jobs orphaned by a prior Brain restart. Boot-only."""
    now = time.time()
    closed = 0
    for job in brain_db.list_jobs():
        status = _normalize_status(str(job.get("status") or ""))
        if status not in _ORPHAN_STATUSES:
            continue
        updated_at = job.get("updated_at")
        try:
            age = now - float(updated_at) if updated_at is not None else now
        except (TypeError, ValueError):
            age = now
        if age < _ORPHAN_GRACE_SEC:
            continue
        iid = int(job.get("intent_id") or job.get("id") or 0)
        if not iid:
            continue
        msg = f"Brain 重启收口：任务在 {status} 状态超过 {_ORPHAN_GRACE_SEC}s 未完成（Brain 重启导致在途派发孤儿）"
        try:
            mark_intent_failed(iid, msg)
            closed += 1
            log.warning("reconcile orphan intent=%s status=%s age=%.0fs", iid, status, age)
        except Exception:
            log.exception("reconcile orphan intent=%s failed", iid)
    if closed:
        log.warning("reconcile orphan jobs closed=%d", closed)
    return closed


def _boot_from_existing_schema():
    """Load runtime caches. Schema/migrate is @dba (`python db.py init`)."""
    global _REGISTERED_edges
    _REGISTERED_edges = brain_db.registration_ids()
    rebuild_capability_maps()
    _requeue_unplanned_jobs()
    _reconcile_orphan_jobs()


try:
    _boot_from_existing_schema()
except sqlite3.OperationalError as exc:
    log.warning(
        "SQLite schema missing (%s); Brain will not migrate. DBA: python db.py init",
        exc,
    )


# ====================== Mock测试入口（本地调试专用） ======================
if __name__ == "__main__":
    # 本地Mock启动，仅用于测试，线上替换ssl证书443端口
    # use_reloader=False：避免 debug 热重载再起一条 llm_worker
    try:
        _boot_from_existing_schema()
    except sqlite3.OperationalError:
        log.error("SQLite schema missing. DBA must run: python db.py init")
        raise SystemExit(1)
    try:
        from mdns_service import BRAIN_TYPE, lan_ipv4, publish_service

        _BRAIN_MDNS = publish_service(
            name="Home Agent Brain",
            type_=BRAIN_TYPE,
            port=9527,
            txt={
                "role": "brain",
                "origin": os.environ.get("BRAIN_ORIGIN", "lan"),
                "lan_ip": lan_ipv4(),
            },
            hostname="brain.local",
        )
    except Exception:
        log.warning("mdns brain publish skipped; LAN discovery unavailable", exc_info=True)
    log.info("Brain home_brain.py on :9527")
    log.info("%s", app.url_map)
    app.run(host="0.0.0.0", port=9527, debug=False, use_reloader=False, threaded=True)
