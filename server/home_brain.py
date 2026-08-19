"""Home Agent Brain control plane.

Source: volcengine/home_brain.py. Iterate on this file only.
"""
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
import os
import sqlite3
import logging
import traceback
from pathlib import Path
from logging.handlers import TimedRotatingFileHandler
import urllib
import urllib.request
import mimetypes
from copy import deepcopy
from flask import Flask, request, Blueprint, jsonify, send_file

try:
    import db as brain_db
except ImportError:  # pragma: no cover
    from server import db as brain_db  # type: ignore

app = Flask(__name__)

# ====================== 配置区 Mock 内存缓存（本地测试不用Redis） ======================
# 模拟Redis内存缓存，生产替换为真实redis客户端
mock_cache = {}
# 缓存改为队列：key=sessionId，value=list(按顺序存储多条回答)
session_result_cache = {}
CACHE_TTL = 60 # 缓存30分钟
# 串行任务队列，最大50排队
task_queue = queue.Queue(maxsize=50)
# 单线程串行执行大模型，全局锁保证同一时间仅1次LLM调用
llm_running_lock = threading.Lock()


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

def get_cache_key(raw_q: str, source: str = "") -> str:
    clean_q = clean_text(raw_q)
    md5_str = hashlib.md5(f"{source}|{clean_q}".encode("utf-8")).hexdigest()
    return f"run_global:{md5_str}"

# Mock 缓存读写封装（替换真实Redis）
def get_cache(q, source=""):
    key = get_cache_key(q, source)
    item = mock_cache.get(key)
    if not item:
        return None
    # 判断缓存是否过期
    if time.time() > item["expire"]:
        del mock_cache[key]
        return None
    return item["data"]

def set_cache(q, ans, source=""):
    key = get_cache_key(q, source)
    expire_ts = time.time() + CACHE_TTL
    mock_cache[key] = {
        "data": ans,
        "expire": expire_ts
    }


_DELIVERY_CAPS = {"endpoint.present", "endpoint.feedback"}
_DISPLAY_CAPS = {"display.photo", "display.slideshow"}
_PRESENTATION_SCHEMA = {
    "type": "text | image | audio",
    "from": "summary | answer_text | time_text | asset_ref | state — which execution field fills the payload",
    "channel": "iphone | kindle | android | speaker",
    "endpoint": "participant_id of the Endpoint role that renders this Presentation (not Intent Source; they may share an id, e.g. iPhone)",
    "text": "optional",
    "asset_ref": "optional AssetRef {asset_id, type, mime_type?} when from=asset_ref; never a URL or filesystem path",
    "audio_url": "optional",
}


def _user_asked_tv(text):
    raw = str(text or "")
    keys = ("电视", "投屏", "投到", "chromecast", "Chromecast", "slideshow", "轮播")
    return any(k in raw for k in keys)


def _user_asked_photo(text):
    raw = str(text or "")
    keys = ("拍张", "拍照", "拍一张", "take_photo", "照相")
    return any(k in raw for k in keys)


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
                if kind and str(kind) not in types:
                    types.append(str(kind))
            elif item:
                types.append(str(item))
    return types or ["text", "image"]


def _issuer_participant_id(intent):
    intent = intent or {}
    return str(intent.get("edge_id") or intent.get("participant_id") or "").strip()


def _is_endpoint_participant(rec):
    if not isinstance(rec, dict) or not rec:
        return False
    if rec.get("role_endpoint"):
        return True
    return "endpoint" in (rec.get("roles") or [])


def _list_endpoint_participants():
    out = []
    try:
        pids = brain_db.registration_ids()
    except sqlite3.OperationalError:
        return []
    for pid in pids:
        rec = brain_db.get_registration(pid) or {}
        if _is_endpoint_participant(rec):
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


def _match_endpoint_participant(intent, pres_type=None):
    """Endpoint-role participant_id that should render this Presentation.

    Only live endpoints (heartbeat within ENDPOINT_TTL_SEC, not Runtime 30s).
    Issuer is used only when that same participant is a live Endpoint.
    Otherwise pick the most recently heartbeated live Endpoint. Never copy
    issuer id just because they posted the intent.
    """
    listed = _list_endpoint_participants()
    now = time.time()
    live = []
    for pid, rec in listed:
        if not _endpoint_supports_type(rec, pres_type):
            continue
        if not _endpoint_is_live(pid, rec, now=now):
            continue
        live.append((_endpoint_received_at(pid, rec), pid))
    if not live:
        return ""
    issuer = _issuer_participant_id(intent)
    if issuer and any(pid == issuer for _, pid in live):
        return issuer
    live.sort(key=lambda row: row[0], reverse=True)
    return live[0][1]


def _stamp_presentation_endpoint(pres, intent):
    if not isinstance(pres, dict):
        return pres
    out = dict(pres)
    out["endpoint"] = _match_endpoint_participant(intent, out.get("type"))
    out["channel"] = _channel_for_participant(out["endpoint"], intent)
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
    out = []
    for pid, rec in _list_endpoint_participants():
        out.append(
            {
                "participant_id": pid,
                "channel": _channel_for_participant(pid, intent),
                "supported_types": _endpoint_supported_types(rec),
                "endpoints": rec.get("endpoints") or [],
            }
        )
    return out


def _world_state_nodes():
    rebuild_capability_maps()
    nodes = []
    for edge_id, view in (_EDGES or {}).items():
        caps = []
        for svc in view.get("services") or []:
            if not isinstance(svc, dict):
                continue
            for cap in svc.get("capabilities") or []:
                if isinstance(cap, dict) and cap.get("capability_id"):
                    caps.append(cap["capability_id"])
        nodes.append(
            {
                "participant_id": edge_id,
                "display_name": view.get("display_name"),
                "device_type": view.get("device_type"),
                "roles": view.get("roles") or [],
                "online_status": view.get("online_status"),
                "schedule_eligible": view.get("schedule_eligible"),
                "capabilities": caps,
                "endpoints": view.get("endpoints"),
            }
        )
    return nodes


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
    has_capture = any(str(s.get("capability") or "") == "camera.capture" for s in cleaned)
    if asked_photo and not asked_tv:
        drop = {"notify.speak", "query.content"}
        if not has_capture:
            drop.add("vision.ask")
        cleaned = [s for s in cleaned if str(s.get("capability") or "") not in drop]
    for idx, step in enumerate(cleaned, start=1):
        step["step"] = idx
    return cleaned


def extract_llm_output(llm_answer):
    if not llm_answer:
        return {}
    try:
        output = json.loads(llm_answer) if isinstance(llm_answer, str) else llm_answer
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


def extract_llm_capability_notes(llm_answer):
    output = extract_llm_output(llm_answer)
    return {
        "missing_capabilities": _as_capability_notes(output.get("missing_capabilities")),
        "better_capabilities": _as_capability_notes(output.get("better_capabilities")),
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
    that includes `from`, else infer from capabilities the planner already scheduled.
    """
    raw = intent.get("presentation")
    planned = {}
    if isinstance(raw, dict) and (raw.get("from") or raw.get("payload_from")):
        planned = _normalize_presentation_plan(raw)
    if not planned.get("type"):
        planned = _normalize_presentation_plan(intent.get("presentation_plan"))
    if planned.get("type"):
        return planned["type"], planned.get("from")
    caps = _caps_in_plan(intent)
    if "clock.now" in caps:
        return "text", "time_text"
    if "vision.ask" in caps:
        return "text", "answer_text"
    if "query.content" in caps:
        return "text", "answer_text"
    if "vision.perceive" in caps:
        return "text", "summary"
    if "light.set" in caps:
        return "text", "state"
    if "camera.capture" in caps:
        return "image", "asset_ref"
    return "", ""


def _as_asset_ref(raw):
    """Normalize an AssetRef. URLs and paths are not identity."""
    if isinstance(raw, str):
        aid = raw.strip()
        if aid:
            return {"asset_id": aid, "type": "image"}
        return None
    if not isinstance(raw, dict):
        return None
    nested = raw.get("asset_ref")
    if isinstance(nested, dict) and not str(raw.get("asset_id") or "").strip():
        return _as_asset_ref(nested)
    aid = str(raw.get("asset_id") or "").strip()
    if not aid:
        return None
    out = {
        "asset_id": aid,
        "type": str(raw.get("type") or "image").strip() or "image",
    }
    mime = str(raw.get("mime_type") or "").strip()
    if mime:
        out["mime_type"] = mime
    return out


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


def _collect_asset_ref(ctx, outputs):
    blobs = []
    if isinstance(ctx, dict):
        blobs.append(ctx)
    if isinstance(outputs, dict):
        blobs.extend(v for v in outputs.values() if isinstance(v, dict))
    for blob in blobs:
        for key in ("asset_ref", "capture_ref", "image_ref"):
            ref = _as_asset_ref(blob.get(key))
            if ref:
                return _enrich_asset_ref_from_catalog(ref)
    return None


def assemble_presentation(intent):
    """Fill planner-decided Presentation from execution results. Asset is not a URL."""
    if not intent:
        return None
    ctx = intent.get("ctx_param") or intent.get("context") or {}
    if not isinstance(ctx, dict):
        ctx = {}
    time_text = ctx.get("time_text")
    answer = ctx.get("answer_text")
    summary = ctx.get("summary")
    people = ctx.get("people")
    state = ctx.get("state")
    outputs = intent.get("step_outputs") or {}
    if isinstance(outputs, dict):
        for blob in outputs.values():
            if not isinstance(blob, dict):
                continue
            time_text = time_text or blob.get("time_text")
            answer = answer or blob.get("answer_text")
            summary = summary or blob.get("summary")
            people = people or blob.get("people")
            state = state or blob.get("state")
    ref = _collect_asset_ref(ctx, outputs)
    fields = {
        "time_text": str(time_text) if time_text else "",
        "answer_text": str(answer) if answer else "",
        "summary": str(summary) if summary else "",
        "people": _people_count_text(people),
        "state": str(state) if state else "",
    }
    ptype, src = _presentation_kind_from_plan(intent)
    text_body = ""
    if src in ("time_text", "answer_text", "summary", "people", "state") and fields.get(src):
        text_body = fields[src]
    else:
        text_body = (
            fields["time_text"]
            or fields["answer_text"]
            or fields["summary"]
            or fields["people"]
            or fields["state"]
        )
    if ptype == "image" and ref:
        payload = {"asset_ref": ref}
        src = src or "asset_ref"
    elif ptype == "text" and text_body:
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
        return intent.get("presentation")
    elif text_body:
        ptype = "text"
        payload = {"text": text_body}
    elif ref:
        ptype = "image"
        payload = {"asset_ref": ref}
        src = src or "asset_ref"
    else:
        existing = intent.get("presentation")
        if isinstance(existing, dict):
            intent["presentation"] = _stamp_presentation_endpoint(existing, intent)
        return intent.get("presentation")
    endpoint_id = _match_endpoint_participant(intent, ptype)
    assembled = {
        "type": ptype,
        "channel": _channel_for_participant(endpoint_id, intent),
        "endpoint": endpoint_id,
        **payload,
    }
    if src:
        assembled["from"] = src
    intent["presentation"] = assembled
    return intent["presentation"]


def compact_prompt():
    if PROMPT_FILE.is_file():
        return PROMPT_FILE.read_text(encoding="utf-8")
    fallback = _HERE / "task_planner_system_prompt.md.en"
    return fallback.read_text(encoding="utf-8")


PLANNER_SYSTEM_PROMPT = (
    "你是Home Agent的Task Planner，仅生成可执行任务计划，不执行任务。"
    "规则：1.识别真实目标，不机械理解字面；"
    "2.只用Available Capabilities里出现的capability_id，禁止虚构进plan；"
    "3.没有匹配的已广告能力则plan=[]，禁止用其他能力顶替；"
    "4.禁止把交付/呈现类步骤写入plan；必须在JSON里给出presentation.type与from，按用户真实目标和各能力自描述的产出字段决定，不要把中间执行产物默认当用户可见结果；用户可见的资源身份用AssetRef（from=asset_ref），禁止用URL或路径当呈现身份；"
    "5.选用哪条能力、填什么入参、会不会产出可选字段，只依据该能力自己的description与input_schema/output_schema；description写了能做的就当它能做，写了不能做的禁止当成它能做；用户目标需要某项可选产出时，按description的触发条件写进本步input_constrict；description未承诺本次会产出时，禁止后续步骤用$引用该可选字段；"
    "6.必须给出missing_capabilities与better_capabilities（数组，均可[]）：缺能力无法满足请求填前者，已有能力不够好填后者；这两项可以点名尚未广告的能力，但不得写入plan；"
    "7.仅输出标准JSON。"
)


def _capability_registry_for_prompt():
    """Flatten Runtime-advertised capabilities; description is self-describing."""
    rebuild_capability_maps()
    rows = []
    for sid, svc in services_registered_mapping.items():
        if not isinstance(svc, dict):
            continue
        for cap in svc.get("capabilities") or []:
            if not isinstance(cap, dict):
                continue
            cid = str(cap.get("capability_id") or "").strip()
            if not cid:
                continue
            rows.append(
                {
                    "capability_id": cid,
                    "description": cap.get("description") or "",
                    "input_schema": cap.get("input_schema") or {},
                    "output_schema": cap.get("output_schema") or {},
                    "service_id": svc.get("service_id") or sid,
                    "group": svc.get("group") or "",
                    "edge_id": svc.get("edge_id") or "",
                }
            )
    return rows

def call_ark(user_text, session_id, user_id, intent_id, intent_base_time, intent=None):
    # 【核心优化】真正调用大模型前，二次检查缓存，避免重复生成
    intent = intent or get_intent(intent_id) or {}
    source = str(intent.get("source") or "text")
    cache_hit = get_cache(user_text, source)
    if cache_hit is not None:
        llm_logger.info(f"二次缓存校验命中，跳过LLM调用 question={user_text}")
        return cache_hit

    start_time = time.time()
    # 方舟调用逻辑不变
    # 拼接统一约束prompt

    prompt_fmt = compact_prompt()
    log.info(prompt_fmt)
    rebuild_capability_maps()

    user_intent = {
      "id": intent_id,
      "source": source,
      "participant_id": str(intent.get("edge_id") or intent.get("participant_id") or ""),
      "intent_base_time": intent_base_time,
      "text": user_text,
    }

    world_state = {
      "nodes": _world_state_nodes(),
    }

    memory = {}

    output_schema = {
      "goal": "string",
      "required_capabilities": [
        "string"
      ],
      "reason": "string",
      "plan": [
        {
          "step": 1,
          "capability": "string",
          "input_constrict" : {
              "required_key": "required_value"
          },
          "output_constrict": {
              "output_attribute_name" : {
                  "type": "string",
                  "data_dest": "context"
              }
          },
          "execution_timing": {
              "mode": "immediate/delay/interval/cron, required",
              "exec_time": "the exection time in millseconds, for delay mode, based on [intent_base_time], not your time",
              "first_exec_time": "the first exection time in millseconds, for interval/cron mode, based on [intent_base_time], not your time",
              "interval_sec": "for interval mode",
              "end_time": "for interval mode",
              "count": "for interval mode",
              "cron_expr": "for cron mode",
              "timezone": "for cron mode"
          }
        }
      ],
      "presentation": {
        "type": "text | image | audio",
        "from": "summary | answer_text | time_text | asset_ref | state"
      },
      "missing_capabilities": [
        {
          "capability": "proposed id or short name of a capability that is not advertised but this request needs",
          "reason": "why the request cannot be fulfilled without it"
        }
      ],
      "better_capabilities": [
        {
          "capability": "what a better capability would be",
          "reason": "why the currently advertised capabilities are not good enough"
        }
      ]
    }


    global services_registered_mapping
    

    # Prompt 正文含大量 JSON `{}`，不能用 str.format。只替换具名占位符。
    replacements = {
        "USER_INTENT": json.dumps(user_intent, ensure_ascii=False),
        "WORLD_STATE": json.dumps(world_state, ensure_ascii=False),
        "CAPABILITY_REGISTRY": json.dumps(_capability_registry_for_prompt(), ensure_ascii=False),
        "MEMORY": json.dumps(memory, ensure_ascii=False),
        "OUPUT_SCHEMA": json.dumps(output_schema, ensure_ascii=False),
        "ENDPOINT_REGISTRY": json.dumps(_endpoint_registry(intent), ensure_ascii=False),
        "PRESENTATION_SCHEMA": json.dumps(_PRESENTATION_SCHEMA, ensure_ascii=False),
    }
    full_prompt = prompt_fmt
    for key, val in replacements.items():
        full_prompt = full_prompt.replace("{" + key + "}", val)
    log.info("组装完整prompt：%s", full_prompt)


    system_prompt=PLANNER_SYSTEM_PROMPT

    headers = {"Content-Type":"application/json", "Authorization":f"Bearer {ARK_API_KEY}"}
    payload = json.dumps(
            {"model":MODEL_ID,
             "messages":[
                 {
                     "role":"system",
                     "content":system_prompt,
                     #"cache_control": {
                     #   "type": "ephemeral"
                     #}
                 },
                 {
                     "role":"user",
                     "content": full_prompt,
                 }
             ], 
             "max_tokens":1024,
             "temperature": 0,
             "top_p": 0.1,
             "stream": False,
             "response_format": {"type": "json_object"},
             "extra_body": {
                "thinking": {
                    "type": "disabled"
                }
             },
             }
            ).encode("utf-8")
    log.info("full payload:\n%s", payload.decode("utf-8"))
    ans = ""
    try:
        log.info("invoke doubao api begin")
        req = urllib.request.Request(ARK_URL, data=payload, headers=headers)
        resp = urllib.request.urlopen(req, timeout=180)
        cost_ms = int((time.time() - start_time) * 1000)
        log.info("invoke doubao api end:%s", cost_ms)
        resp_data = json.loads(resp.read().decode("utf-8"))
        llm_logger.info(f"cost_ms={cost_ms} | question={user_text} | answer={resp_data}")
        log.info("get res:%s", resp_data)
        ans = resp_data["choices"][0]["message"]["content"]
        log.info("get ans: %s", ans)
        set_cache(user_text, ans, source)
        log.info("put into cache for user query:%s", user_text)
    except Exception as e:
        log.exception("call doubao api error: %s", e)
    return ans


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


def extract_llm_plan(llm_answer):
    output = extract_llm_output(llm_answer)
    log.info("output:%s", llm_answer)
    return output.get("plan") or []



def make_execution_plan(llm_plan):
    """
    make real world plan, make it work
    """
    return llm_plan


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
    simple_plan = []
    scheduler_node = ""
    for _step in execution_plan:
        log.info("_step:\n%s", json.dumps(_step))
        _simple_step = {}
        if not _step.get('step'):
            continue
        _simple_step['step'] = _step['step']
        _simple_step['capability'] = _step['capability']
        _simple_step['input_constrict'] = _step['input_constrict']
        _simple_step['output_constrict'] = _step['output_constrict']
        _simple_step['execution_timing'] = _step['execution_timing']


        # set edge id
        assigned_edge_id = capability_edge_mapping.get(_simple_step['capability']) or ""
        _simple_step['assigned_edge_id'] = assigned_edge_id
        if scheduler_node == "":
            scheduler_node = assigned_edge_id

        simple_plan.append(_simple_step)
    intent["execution_plan"] = simple_plan
    intent["scheduler_node"] = scheduler_node
    _save_intent(intent)

    #if commands_queue.get('gopro') is None:
    #    commands_queue['gopro'] = []
    #commands_queue['gopro'].append('shutter')



ONLINE_TTL_SEC = 30
# Presentation Endpoint liveness is not Runtime online TTL (30s).
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
    if not edge_id:
        return False
    if str(job.get("assigned_edge_id") or "") == edge_id:
        return True
    if str(job.get("scheduler_node") or "") == edge_id:
        return True
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
    intent.setdefault("status_log", [])
    intent.setdefault("execution_plan", [])
    intent.setdefault("step_log", [])
    intent.setdefault("steps", [])
    assemble_presentation(intent)
    notes = _planner_notes_for_intent(ident)
    intent["missing_capabilities"] = notes["missing_capabilities"]
    intent["better_capabilities"] = notes["better_capabilities"]
    return intent


def _planner_notes_for_intent(intent_id):
    empty = {"missing_capabilities": [], "better_capabilities": []}
    if intent_id in (None, ""):
        return empty
    try:
        rows = brain_db.list_intent_reviews(intent_id)
    except Exception:
        return empty
    if not rows:
        return empty
    parsed = rows[-1].get("parsed_json")
    if not isinstance(parsed, dict):
        parsed = extract_llm_output(rows[-1].get("raw_response"))
    if not isinstance(parsed, dict):
        return empty
    return {
        "missing_capabilities": _as_capability_notes(parsed.get("missing_capabilities")),
        "better_capabilities": _as_capability_notes(parsed.get("better_capabilities")),
    }


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
    if not intent.get("assigned_edge_id"):
        assigned = str(intent.get("scheduler_node") or "").strip()
        if not assigned:
            plan = intent.get("execution_plan") or []
            if plan and isinstance(plan[0], dict):
                assigned = str(plan[0].get("assigned_edge_id") or "").strip()
        if assigned:
            intent["assigned_edge_id"] = assigned
    ident = intent.get("intent_id") or intent.get("id")
    if ident is not None:
        intent["job_id"] = str(ident)
    if intent.get("intent_base_time") and not intent.get("base_time"):
        intent["base_time"] = intent["intent_base_time"]
    brain_db.put_job(intent)


def list_intents():
    return [_job_to_intent(job) for job in brain_db.list_jobs()]


def update_intent_status(intent_id, intent_status, msg=None):
    intent = get_intent(intent_id)
    if not intent:
        return
    intent_status = _normalize_status(intent_status)
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
    return _job_to_intent(brain_db.get_job(intent_id))


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
):
    try:
        brain_db.put_intent_review(
            {
                "intent_id": intent_id,
                "session_id": session_id,
                "text": text,
                "source": source,
                "edge_id": edge_id,
                "planner": "ark",
                "model": MODEL_ID,
                "cost_ms": cost_ms,
                "raw_response": raw,
                "parsed_json": parsed,
                "execution_plan": plan,
                "error": error,
            }
        )
    except Exception:
        log.exception("put_intent_review failed")


# ====================== 串行消费后台线程（核心排队逻辑） ======================
def llm_worker():
    global capability_edge_mapping
    log.info("llm worker started, scan task begin..")
    while True:
        task = task_queue.get()
        user_q, session_id, user_id, intent_id = task["question"], task["session_id"], task["user_id"], task["intent_id"]
        log.info("get question: %s %s %s %s", user_q, session_id, user_id, intent_id)
        intent = get_intent(intent_id)
        try:
            with llm_running_lock:
                started = time.time()
                ans = call_ark(
                    user_q,
                    session_id,
                    user_id,
                    intent_id,
                    intent.get("intent_base_time"),
                    intent=intent,
                )
                cost_ms = int((time.time() - started) * 1000)
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
                if not stored_plan:
                    mark_intent_failed(intent_id, _EMPTY_PLAN_MSG)
                else:
                    update_intent_status(intent_id, "intent_parsed")
                llm_out = extract_llm_output(ans)
                notes = extract_llm_capability_notes(ans)
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
                    error=None if stored_plan else _EMPTY_PLAN_MSG,
                )

        except Exception as e:
            log.exception("任务处理异常: %s", e)
            err_stack = traceback.format_exc()
            log.error("堆栈文本:\n%s", err_stack)

            mark_intent_failed(intent_id, str(e) or "plan failed")
            _record_intent_review(
                intent_id,
                text=user_q,
                error=err_stack,
                session_id=session_id,
                source=task.get("source"),
                edge_id=task.get("edge_id"),
            )
        finally:
            task_queue.task_done()

# 启动后台工作线程（单测可 BRAIN_SKIP_LLM_WORKER=1 跳过）
if os.environ.get("BRAIN_SKIP_LLM_WORKER") != "1":
    worker_thread = threading.Thread(target=llm_worker, daemon=True)
    worker_thread.start()

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

@app.route("/api/v1/intent", methods=["POST", "GET"])
def dispatch_intent():
    text = "default"
    source = "text"
    edge_id = "11111"
    session_id = ""
    intent_base_time = int(time.time() * 1000)
    if request.method == 'GET':
        text = request.args.get("command", "default")
        source = request.args.get("source", "text")
        edge_id = request.args.get("edge_id", "11111")
        session_id = request.args.get("session_id", "")
    else:
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return jsonify(ok=False, error="JSON object required"), 400

        text = str(data.get("text") or "").strip()
        if not text:
            return jsonify(ok=False, error="text is required"), 400

        source = str(data.get("source") or "text").strip().lower() or "text"
        if source not in ("text", "voice"):
            source = "text"
        edge_id = str(
            data.get("edge_id") or data.get("participant_id") or ""
        ).strip()
        session_id = str(data.get("session_id") or "").strip()

    # TODO: 在这里接 doubao_chat / 你的大脑
    reply = f"已收到指令（{source}）：{text}"
    # 无缓存，加入排队队列
    intent_id = new_intent({
        "status": "intent_received",
        "text": text,
        "source": source,
        "edge_id": edge_id,
        "intent_base_time": intent_base_time,
        "base_time": intent_base_time,
        "status_log": [
            {
                'status' : "intent_received",
                'ts': int(time.time() * 1000)
            }
        ]
    })
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
        reply=reply,
        intent_id=intent_id,
        intent_status="intent_received"
    )

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
        )

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


@app.route("/health", methods=["GET"])
def health():
    return jsonify(
        {
            "ok": True,
            "app": "brain",
            "db": str(brain_db.db_path()),
            "registered": brain_db.registration_count(),
            "jobs": brain_db.job_count(),
            "pending_intents": brain_db.queue_count(),
        }
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
        )
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

    outputs = data.get('outputs') or {}
    if not intent.get('step_outputs'):
        intent['step_outputs'] = {}
    intent['step_outputs'][str(step_id_int)] = outputs


    # fill exposed_outputs for endpoint
    if step_status_str == "succeeded" or step_status_str == "failed":
        # find last step
        present_step_id = intent['execution_plan'][-1]["step"]
        present_outputs = intent['step_outputs'].get(str(present_step_id))
        if present_outputs is None:
            present_outputs = intent['step_outputs'].get(present_step_id)
        if present_outputs is not None:
            intent["exposed_outputs"] = present_outputs


    intent_ctx = intent.get('ctx_param') or {}

    _record = {}
    _record['step'] = step_id_int
    _record['status'] = step_status
    _record['ts'] = data.get('ts')
    _record['msg'] = data.get('msg')
    #_record['start_time'] = data['start_time']
    #_record['end_time'] = data['end_time']

    if edge_node_id:
        intent["edge_node_id"] = edge_node_id

    for step in intent.get("execution_plan") or []:
        if step['step'] == step_id_int:
            step['status'] = int(step_status)
            if data.get('msg'):
                step['msg'] = data.get('msg')
            # put useful fields into context 
            output_constrict = step.get('output_constrict') or {}
            for k in output_constrict.keys():
                dest = (output_constrict.get(k) or {}).get("data_dest") if isinstance(output_constrict.get(k), dict) else None
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
    if step_status == 3 and data.get("msg"):
        intent["msg"] = data.get("msg")
        intent["error"] = data.get("msg")
    assemble_presentation(intent)
    if intent.get("presentation") is not None:
        intent["exposed_outputs"] = intent["presentation"]
    _save_intent(intent)
    append_intent_step_log(intent_id_int, _record)

    return {
        "id" : intent['id'],
        "step" : step_id_int,
        "status" : step_status,
    }





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
        )
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

    update_intent(intent_id_int, _record)

    return {
        "id" : intent['id'],
        "status" : intent_status,
        'execution_plan' : intent.get('execution_plan') or []
    }


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
    original = Path(f.filename or "photo.jpg").name.replace("/", "_") or "photo.jpg"
    saved_as = f"{uuid.uuid4().hex[:8]}_{original}"
    dest = UPLOAD_DIR / saved_as
    dest.write_bytes(data)
    return jsonify(
        ok=True,
        filename=original,
        saved_as=saved_as,
        bytes=len(data),
        path=str(dest),
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
def cap_handler():
    rebuild_capability_maps()
    return list(services_registered_mapping.values())


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


def _asset_public_view(record: dict, *, include_storage: bool = False) -> dict:
    out = {k: v for k, v in record.items() if k != "storage"}
    if include_storage and isinstance(record.get("storage"), dict):
        out["storage"] = record["storage"]
    return out


def _asset_has_read_grant(asset_id: str, intent_id: str) -> bool:
    iid = str(intent_id or "").strip()
    if not iid:
        return False
    lister = getattr(brain_db, "list_asset_grants", None)
    if not callable(lister):
        return False
    for grant in lister(asset_id):
        grant_intent = str(
            grant.get("execution_id") or grant.get("intent_id") or ""
        )
        if grant_intent != iid:
            continue
        perm = str(grant.get("permission") or "read").strip().lower()
        if perm == "read":
            return True
    return False


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
    return jsonify(ok=True, asset_id=aid, asset=_asset_public_view(rec or {"asset_id": aid}))


@app.route("/api/v1/assets/<asset_id>", methods=["GET"])
def get_asset_view(asset_id):
    getter = getattr(brain_db, "get_asset", None)
    if not callable(getter):
        return jsonify(ok=False, error="assets catalog not available"), 503
    rec = getter(asset_id)
    if rec is None or str(rec.get("status") or "").lower() == "deleted":
        return jsonify(ok=False, error="not found"), 404
    intent_id = str(request.args.get("intent_id") or "").strip()
    include_storage = bool(intent_id) and _asset_has_read_grant(asset_id, intent_id)
    return jsonify(
        ok=True,
        asset=_asset_public_view(rec, include_storage=include_storage),
    )

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
            "edge_id": data.get("edge_id"),
            "assigned_edge_id": data.get("assigned_edge_id"),
            "scheduler_node": data.get("scheduler_node"),
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
        return {"intents" : []}
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

    return {
            "intents": sorted_intents[0:fetch_num]
    }
 


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
        return json.dumps({"error": "缺少提问内容"}), 400
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
        log.info("%s", resp_data)
        ans = resp_data["choices"][0]["message"]["content"]
        log.info("%s", ans)
        return json.dumps({"reply" : ans})
    except urllib.error.URLError as e:
        err_msg = f"网络读取超时，模型生成内容较长，当前网络不稳定"
        return json.dumps({"reply": err_msg})
    except Exception as e:
        err_msg = f"服务异常：{str(e)}"
        return json.dumps({"reply": err_msg})

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
    ):
        if body.get(key) is not None:
            rec[key] = body.get(key)
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
    client_hint = str(body.get("client_hint") or body.get("edge_id") or "").strip()
    existing = _find_by_client_hint(client_hint) if client_hint else None
    if existing:
        edge_id = existing["participant_id"]
        rec = _registration_from_body(
            body, edge_id, client_hint=client_hint or existing.get("client_hint"), existing=existing
        )
        brain_db.put_registration(rec)
        d = {
            "ts": time.time(),
            "edge_id": edge_id,
            "participant_id": edge_id,
            "ok": True,
            "status": "approved",
            "message": "ok",
        }
        return jsonify(d)

    edge_id = "edge-node-"+random_edge_token(8)
    rec = _registration_from_body(body, edge_id, client_hint=client_hint or None)
    brain_db.put_registration(rec)
    if edge_id not in _REGISTERED_edges:
        _REGISTERED_edges.append(edge_id)
    d = {
        "ts": time.time(),
        "edge_id": edge_id,
        "participant_id": edge_id,
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
            if cid:
                capability_edge_mapping[cid] = edge_id

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
    existing = brain_db.get_registration(edge_id) or {}
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
                "client_hint": existing.get("client_hint"),
            },
            edge_id,
            client_hint=existing.get("client_hint"),
            existing=existing,
        )
    )
    info = upsert_edge_heartbeat(edge_id, body)
    info["brain_time_ms"] = brain_time_ms
    info["client_time_ms"] = body.get("client_time_ms")
    info["clock_skew_ms"] = ts_diff
    info["schedule_eligible"] = schedule_eligible
    if reject_reason:
        info["schedule_reject_reason"] = reject_reason
    try:
        brain_db.put_heartbeat(edge_id, info)
    except KeyError:
        return jsonify({"ok": False, "error": "unknown edge_id; register first"}), 401
    rebuild_capability_maps()
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


def rebuild_capability_maps():
    global services_registered_mapping, capability_edge_mapping, _EDGES
    services_registered_mapping = {}
    capability_edge_mapping = {}
    _EDGES = {}
    now = time.time()
    for edge_id, info in brain_db.list_heartbeats().items():
        view = _edge_public_view(info)
        _EDGES[edge_id] = view
        if view.get("schedule_eligible") is False:
            continue
        if view.get("online_status") != "online":
            continue
        received = info.get("server_received_at")
        if received is not None and (now - float(received)) > ONLINE_TTL_SEC:
            continue
        for _service in info.get("services") or []:
            svc = dict(_service)
            svc["edge_id"] = edge_id
            svc["edge_name"] = info.get("display_name")
            sid = svc.get("service_id")
            if sid:
                services_registered_mapping[sid] = svc
            for cap in svc.get("capabilities") or []:
                if not isinstance(cap, dict):
                    continue
                cid = cap.get("capability_id")
                if cid:
                    capability_edge_mapping[cid] = edge_id


def _requeue_unplanned_jobs():
    if os.environ.get("BRAIN_SKIP_LLM_WORKER") == "1":
        return
    for job in brain_db.list_jobs():
        if str(job.get("status") or "") != "intent_received":
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


def _boot_from_existing_schema():
    """Load runtime caches. Schema/migrate is @dba (`python db.py init`)."""
    global _REGISTERED_edges
    _REGISTERED_edges = brain_db.registration_ids()
    rebuild_capability_maps()
    _requeue_unplanned_jobs()


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
    log.info("Brain home_brain.py on :9527")
    log.info("%s", app.url_map)
    app.run(host="0.0.0.0", port=9527, debug=False, use_reloader=False, threaded=True)
