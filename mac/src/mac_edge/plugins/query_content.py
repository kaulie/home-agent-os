"""Mac Edge capability: query.content — independent LLM / image stack.

Contract:
  input:  query (required); upload_dest optional (default lan)
  output: answer_text (required); image_ref advertised (plugin still returns
  photo_url+saved_as for Runtime register); citations (JSON string)

Must not import vision_perceive / vision_providers / gopro_camera.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from mac_edge.plugins.query_providers import QueryProviderError
from mac_edge.plugins.query_providers.registry import get_provider

log = logging.getLogger("mac_edge.query_content")

DEFAULT_LAN_UPLOAD_URL = "http://192.168.3.65:8080/api/v1/photos/upload"
DEFAULT_LAN_PUBLIC_BASE = "http://192.168.3.65:8080"
DEFAULT_CLOUD_UPLOAD_URL = "http://115.190.153.53:9527/api/v1/photos/upload"
DEFAULT_CLOUD_PUBLIC_BASE = "http://115.190.153.53:8080"

PROFESSIONAL_DOMAINS = frozenset(
    {"science", "health", "medicine", "professional"}
)

DEFAULT_PROMPT = (
    "你在回答用户的一句话提问。"
    "不确定、没有依据、超出所知时，answer_text 必须直说「我不知道」，可以补一句缺什么信息。"
    "禁止猜测、补全、用「一般来说」「可能是」「据我所知大概」装作知道。"
    "科普、百科、汉字笔顺/笔画、健康、医药、用药、诊断、营养、法律等专业域：不得用记忆编造；"
    "有具体可点名的来源才答，并写入 citations；否则 refused=true，直说不知道。"
    "禁止虚构论文、指南、剂量、诊断、假 URL。"
    "配图原则（want_image）："
    "1) 简单知识/事实问答（能否、是否、几点、叫什么）默认 want_image=false，不要配图；"
    "2) 图片或动态示意能更好解释（外观长什么样、结构、对比、步骤、笔顺、过程）则 want_image=true，并写具体 image_prompt；"
    "3) 用户明确要求出图/画一张/配图/看图，尽量 want_image=true；"
    "4) 用户要把结果投屏/投到电视/做成电视上展示的画面，want_image=true，"
    "image_prompt 为适合电视展示的清晰大字卡片（白底、少字、远看可读）。"
    "汉字笔顺/笔画怎么写/几画：domain=professional；image_prompt 为规范笔顺示意图（白底黑字、带笔画序号）；"
    "citations 必须引用汉语字典（如汉典 zdic.net、新华字典、教育部《通用规范汉字笔顺规范》），"
    "正文点名来源；没有字典依据则 refused=true，不生图。"
    "闲聊、家居、故事等 domain=general，不强制 citations，但仍适用「不知道就说不知道」。"
    "只输出一层 JSON。answer_text 必须是普通中文，绝不能把整段 JSON 再放进 answer_text。"
)

STRUCTURE_HINT = """
你必须只输出一个 JSON 对象。禁止 Markdown 代码块。禁止在任何字段里再嵌套 JSON 字符串。

简单知识，不出图：
{
  "answer_text": "客厅朝南，白天适合看书。",
  "want_image": false,
  "image_prompt": "",
  "domain": "general",
  "refused": false,
  "citations": []
}

外观/示意更能说明时，出图：
{
  "answer_text": "大象有长鼻、大耳和粗壮四肢。",
  "want_image": true,
  "image_prompt": "写实风格，一头非洲象侧面站在草原上，长鼻、大耳、象牙清晰",
  "domain": "general",
  "refused": false,
  "citations": []
}

笔顺须配图+字典来源：
{
  "answer_text": "据汉典，「晋」字10画，笔顺为横、竖、竖、点、撇、横、竖、横折、横、横。",
  "want_image": true,
  "image_prompt": "白底黑字，汉字「晋」的规范笔顺示意图，逐步笔画并标注1至10序号",
  "domain": "professional",
  "refused": false,
  "citations": [{"name": "汉典", "url": "https://www.zdic.net/"}]
}

不确定时不生图：
{
  "answer_text": "我不知道明天会不会下雨。",
  "want_image": false,
  "image_prompt": "",
  "domain": "general",
  "refused": true,
  "citations": []
}

字段约定：
- answer_text: 中文回答；不确定时必须包含「我不知道」
- want_image: 简单知识 false；示意/外观/步骤 true；用户点名要图或要投屏/电视展示则 true；拒答 false
- image_prompt: 出图时必填的画面描述
- domain: general | science | health | medicine | professional；笔顺/笔画用 professional
- refused: 不知道或不能答时为 true；此时禁止生图
- citations: [{name, url}, …]；专业域与笔顺作答时必须非空，笔顺须为字典来源
""".strip()

_STROKE_ORDER_MARKERS = ("笔顺", "笔画", "几画")
_USER_WANTS_IMAGE_MARKERS = (
    "出图",
    "配图",
    "画一张",
    "画个",
    "画一",
    "画图",
    "看图",
    "示意图",
    "照片",
    "图示",
    "动画",
    "给我图",
    "投屏",
    "投到电视",
    "投电视",
    "电视上",
)
_VISUAL_HELPS_MARKERS = (
    "长什么样子",
    "长什么样",
    "什么样子",
    "怎么写",
)


class QueryContentError(Exception):
    pass


def _is_stroke_order_query(query: str) -> bool:
    q = (query or "").strip()
    return any(m in q for m in _STROKE_ORDER_MARKERS)


def _user_requested_image(query: str) -> bool:
    q = (query or "").strip()
    return any(m in q for m in _USER_WANTS_IMAGE_MARKERS)


def _visual_helps_explain(query: str) -> bool:
    q = (query or "").strip()
    if _is_stroke_order_query(q):
        return True
    return any(m in q for m in _VISUAL_HELPS_MARKERS)


def _should_draw_image(*, refused: bool, want_image: bool, query: str) -> bool:
    if refused:
        return False
    if want_image:
        return True
    # Principle 2/3: appearance / stroke / user asked for a picture.
    return _user_requested_image(query) or _visual_helps_explain(query)


def _illustration_prompt(image_prompt: str, query: str) -> str:
    return image_prompt.strip() or f"配图说明：{query.strip()}"


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    raw = str(value).strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off", ""):
        return False
    raise QueryContentError(f"want_image/refused must be boolean, got {value!r}")


def _normalize_citations(raw: Any) -> list[dict[str, str]]:
    if raw is None:
        return []
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        raise QueryContentError(
            "citations must be a JSON array, not a string (fix prompt — no unwrap)"
        )
    if not isinstance(raw, list):
        raise QueryContentError(
            f"citations must be an array, got {type(raw).__name__}"
        )
    out: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise QueryContentError("citations items must be objects")
        name = str(item.get("name") or "").strip()
        url = str(item.get("url") or "").strip()
        out.append({"name": name, "url": url})
    return out


def _parse_model_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise QueryContentError(f"model output is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise QueryContentError(
            f"model output JSON must be an object, got {type(data).__name__}"
        )
    return data


def _normalize_upload_dest(raw: str | None) -> str:
    v = (raw or "").strip().lower()
    if v in ("cloud",):
        return "cloud"
    if v in ("lan", "local", "home", ""):
        return "lan"
    log.warning("unknown upload_dest=%r — using lan", raw)
    return "lan"


def _upload_endpoints(dest: str) -> tuple[str, str]:
    if dest == "lan":
        upload = _env("MAC_EDGE_LAN_PHOTO_UPLOAD_URL") or DEFAULT_LAN_UPLOAD_URL
        public = _env("MAC_EDGE_LAN_PHOTO_PUBLIC_BASE") or DEFAULT_LAN_PUBLIC_BASE
        return upload, public.rstrip("/")
    upload = _env("MAC_EDGE_PHOTO_UPLOAD_URL") or DEFAULT_CLOUD_UPLOAD_URL
    public = _env("MAC_EDGE_PHOTO_PUBLIC_BASE") or DEFAULT_CLOUD_PUBLIC_BASE
    return upload, public.rstrip("/")


def _data_dir() -> Path:
    root = Path(__file__).resolve().parents[3]
    data = Path(_env("MAC_EDGE_DATA_DIR") or str(root / "data"))
    out = data / "query"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _multipart_upload(path: Path, upload_url: str) -> dict[str, Any]:
    boundary = f"----MacEdgeQuery{int(time.time() * 1000)}"
    filename = path.name
    file_bytes = path.read_bytes()
    parts: list[bytes] = [
        f"--{boundary}\r\n".encode(),
        (
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode(),
        file_bytes,
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    body = b"".join(parts)
    req = urllib.request.Request(
        upload_url,
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120.0) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            code = int(resp.getcode() or 0)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        raise QueryContentError(f"upload HTTP {e.code}: {raw[:300]}") from e
    except urllib.error.URLError as e:
        raise QueryContentError(f"upload failed: {e}") from e

    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as e:
        raise QueryContentError(
            f"upload response not JSON (http={code}): {raw[:200]}"
        ) from e
    if not isinstance(data, dict):
        raise QueryContentError("upload response must be object")
    return data


def _resolve_photo_url(
    upload_json: dict[str, Any],
    *,
    public_base: str,
) -> tuple[str, str]:
    saved_as = str(upload_json.get("saved_as") or "").strip()
    url = str(upload_json.get("url") or "").strip()
    base = public_base.rstrip("/")
    if url.startswith("http://") or url.startswith("https://"):
        if saved_as and url.startswith("http://127."):
            return f"{base}/{Path(saved_as).name}", saved_as
        return url, saved_as
    if saved_as:
        return f"{base}/{Path(saved_as).name}", saved_as
    raise QueryContentError(f"upload ok but no photo_url/saved_as: {upload_json}")


def _upload_generated_image(
    image_bytes: bytes,
    *,
    upload_dest: str,
) -> dict[str, str]:
    if not image_bytes:
        raise QueryContentError("generated image is empty")
    dest = _normalize_upload_dest(upload_dest)
    upload_url, public_base = _upload_endpoints(dest)
    ts = time.strftime("%Y%m%d_%H%M%S")
    path = _data_dir() / f"{ts}_query.png"
    path.write_bytes(image_bytes)
    upload_json = _multipart_upload(path, upload_url)
    photo_url, saved_as = _resolve_photo_url(upload_json, public_base=public_base)
    if not photo_url.startswith("http://") and not photo_url.startswith("https://"):
        raise QueryContentError(f"refusing non-http photo_url: {photo_url}")
    out = {"photo_url": photo_url, "photo_local_path": str(path)}
    if saved_as:
        out["saved_as"] = saved_as
    return out


def _to_model_result(raw: dict[str, Any]) -> dict[str, Any]:
    text = _as_text(raw.get("_provider_text") or raw.get("raw_text"))
    if not text:
        raise QueryContentError("query provider returned empty text")
    parsed = _parse_model_json(text)
    parsed["raw_text"] = text
    if raw.get("model"):
        parsed["model"] = raw["model"]
    if raw.get("api_latency_ms") not in (None, ""):
        parsed["api_latency_ms"] = raw["api_latency_ms"]
    return parsed


def query_content(
    *,
    query: str,
    upload_dest: str = "lan",
    timeout_sec: float = 90.0,
    provider_name: str | None = None,
    provider: Any = None,
) -> dict[str, str]:
    q = (query or "").strip()
    if not q:
        raise QueryContentError("missing query")

    user_prompt = "\n\n".join([DEFAULT_PROMPT, f"用户问题：{q}", STRUCTURE_HINT])
    t0 = time.perf_counter()
    try:
        prov = provider if provider is not None else get_provider(provider_name)
        raw = prov.complete(prompt=user_prompt, timeout_sec=timeout_sec)
    except QueryProviderError as e:
        raise QueryContentError(str(e)) from e
    except QueryContentError:
        raise
    except Exception as e:
        raise QueryContentError(f"{type(e).__name__}: {e}") from e

    if not isinstance(raw, dict):
        raise QueryContentError("query provider must return a dict")

    merged = _to_model_result(raw)
    answer_raw = merged.get("answer_text")
    if isinstance(answer_raw, (dict, list)):
        raise QueryContentError(
            f"answer_text must be a plain string, got {type(answer_raw).__name__} "
            "(fix prompt — no unwrap)"
        )
    answer_text = _as_text(answer_raw)
    if not answer_text:
        raise QueryContentError("query returned empty answer_text")
    if answer_text.lstrip().startswith("{") or answer_text.lstrip().startswith("["):
        raise QueryContentError(
            "answer_text looks like nested JSON; model output invalid "
            "(fix prompt — no unwrap)"
        )

    refused = _as_bool(merged.get("refused"))
    want_image = _as_bool(merged.get("want_image"))
    domain = _as_text(merged.get("domain") or "general").lower() or "general"
    citations = _normalize_citations(merged.get("citations"))
    image_prompt = _as_text(merged.get("image_prompt"))

    if refused and "不知道" not in answer_text:
        raise QueryContentError(
            "refused=true but answer_text does not say 我不知道 (fix prompt)"
        )
    if domain in PROFESSIONAL_DOMAINS and not refused and not citations:
        raise QueryContentError(
            f"professional domain={domain} answered without citations "
            "(fix prompt — no fake citations)"
        )
    if _is_stroke_order_query(q) and not refused and not citations:
        raise QueryContentError(
            "stroke-order query requires dictionary citations (fix prompt)"
        )

    outputs: dict[str, str] = {
        "answer_text": answer_text,
        "citations": json.dumps(citations, ensure_ascii=False),
    }

    if not refused:
        draw = _should_draw_image(
            refused=refused, want_image=want_image, query=q
        )
        if draw:
            draw_prompt = _illustration_prompt(image_prompt, q)
            try:
                image_bytes = prov.generate_image(
                    prompt=draw_prompt, timeout_sec=timeout_sec
                )
                uploaded = _upload_generated_image(
                    image_bytes, upload_dest=upload_dest
                )
            except QueryProviderError as e:
                raise QueryContentError(str(e)) from e
            outputs["photo_url"] = uploaded["photo_url"]
            if uploaded.get("saved_as"):
                outputs["saved_as"] = uploaded["saved_as"]

    total_ms = int((time.perf_counter() - t0) * 1000)
    log.info(
        "query.content ok refused=%s domain=%s want_image=%s has_photo=%s "
        "total_ms=%s answer=%s",
        refused,
        domain,
        want_image,
        "photo_url" in outputs,
        total_ms,
        answer_text[:80],
    )
    return outputs


def query_from_params(
    params: dict[str, Any],
    *,
    asset: "CapAsset",
    timeout_sec: float = 90.0,
) -> tuple[str, dict[str, Any]]:
    from mac_edge.asset.sdk import CapAsset
    from mac_edge.asset.types import AssetError

    if not isinstance(asset, CapAsset):
        raise QueryContentError("query.content requires CapAsset (Runtime SDK)")
    q = str(params.get("query") or "").strip()
    dest = str(params.get("upload_dest") or "lan").strip() or "lan"
    outputs = query_content(query=q, upload_dest=dest, timeout_sec=timeout_sec)
    # Register generated image via Asset Manager — identity is image_ref only.
    if "photo_url" in outputs:
        try:
            ref = asset.register_from_upload_url(
                photo_url=str(outputs.get("photo_url") or ""),
                saved_as=str(outputs.get("saved_as") or "") or None,
                producer="query.content",
                mime_type="image/png",
            )
        except AssetError as e:
            raise QueryContentError(str(e)) from e
        outputs = {k: v for k, v in outputs.items() if k not in ("photo_url", "saved_as")}
        outputs["image_ref"] = ref.to_dict()
    preview = str(outputs.get("answer_text") or "")[:100]
    return f"query: {preview or 'ok'}", outputs
