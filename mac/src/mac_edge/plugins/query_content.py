"""Mac Edge capability: query.content — independent LLM / image stack.

Contract:
  input:  query (required); upload_dest optional (default lan)
  output: answer_text (required); asset_ref advertised (plugin still returns
  photo_url+saved_as for Runtime register); citations (JSON string)

Must not import vision_perceive / vision_providers / gopro_camera.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

from mac_edge.asset.img_upload import (
    ImgUploadError,
    normalize_upload_dest,
    upload_image_bytes,
)
from mac_edge.plugins.query_providers import QueryProviderError
from mac_edge.plugins.query_providers.registry import get_provider

log = logging.getLogger("mac_edge.query_content")

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
    "image_prompt 为适合电视展示的清晰画面（要图则画主体，拼写/卡片才用大字白底）。"
    "5) 用户说「来张图/来张图片/图片投到电视」是生图请求，不是知识问答；"
    "want_image=true、refused=false，按主题画图，不要因为不确定百科而拒答不配图。"
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

用户只要图（即使主题很短）：
{
  "answer_text": "这是一张战斗机示意图。",
  "want_image": true,
  "image_prompt": "写实风格，一架战斗机在蓝天上飞行，侧视清晰",
  "domain": "general",
  "refused": false,
  "citations": []
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
- want_image: 简单知识 false；示意/外观/步骤 true；用户点名要图或要投屏/电视展示则 true
- image_prompt: 出图时必填的画面描述
- domain: general | science | health | medicine | professional；笔顺/笔画用 professional
- refused: 无法作答的知识问题时为 true。用户只要图时不要 refused，也不要因此跳过生图
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
    "来张",
    "来一张",
    "图片",
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


def _should_draw_image(
    *,
    refused: bool,
    want_image: bool,
    query: str,
    force_image: bool = False,
) -> bool:
    """Draw when the user asked for a picture, even if the model refused facts.

    Stroke-order queries still skip drawing when refused (no fake 笔顺 diagram).
    """
    user_wants = force_image or _user_requested_image(query)
    if _is_stroke_order_query(query) and refused:
        return False
    if user_wants:
        return True
    if refused:
        return False
    if want_image:
        return True
    return _visual_helps_explain(query)


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


def _data_dir() -> Path:
    root = Path(__file__).resolve().parents[3]
    data = Path(_env("MAC_EDGE_DATA_DIR") or str(root / "data"))
    out = data / "query"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _upload_generated_image(
    image_bytes: bytes,
    *,
    upload_dest: str,
) -> dict[str, str]:
    dest = normalize_upload_dest(upload_dest)
    ts = time.strftime("%Y%m%d_%H%M%S")
    try:
        result = upload_image_bytes(
            image_bytes,
            filename=f"{ts}_query.png",
            preferred_dest=dest,
            allow_cloud_fallback=True,
            staging_dir=_data_dir(),
        )
    except ImgUploadError as e:
        raise QueryContentError(str(e)) from e
    out = {
        "photo_url": result.photo_url,
        "photo_local_path": result.local_path or "",
        "upload_dest": result.dest,
    }
    if result.saved_as:
        out["saved_as"] = result.saved_as
    if result.cloud_public_base:
        out["cloud_public_base"] = result.cloud_public_base
    if result.cloud_saved_as:
        out["cloud_saved_as"] = result.cloud_saved_as
    if result.cloud_photo_url:
        out["cloud_photo_url"] = result.cloud_photo_url
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
    force_image: bool = False,
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
    llm_ms = int((time.perf_counter() - t0) * 1000)
    timings: dict[str, int] = {"llm": llm_ms}

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

    draw = _should_draw_image(
        refused=refused,
        want_image=want_image,
        query=q,
        force_image=force_image,
    )
    if draw:
        draw_prompt = _illustration_prompt(image_prompt, q)
        t_img = time.perf_counter()
        try:
            image_bytes = prov.generate_image(
                prompt=draw_prompt, timeout_sec=timeout_sec
            )
        except QueryProviderError as e:
            raise QueryContentError(str(e)) from e
        timings["image_gen"] = int((time.perf_counter() - t_img) * 1000)
        t_up = time.perf_counter()
        try:
            uploaded = _upload_generated_image(
                image_bytes, upload_dest=upload_dest
            )
        except QueryProviderError as e:
            raise QueryContentError(str(e)) from e
        timings["upload"] = int((time.perf_counter() - t_up) * 1000)
        outputs["photo_url"] = uploaded["photo_url"]
        if uploaded.get("saved_as"):
            outputs["saved_as"] = uploaded["saved_as"]
        for k in (
            "cloud_public_base",
            "cloud_saved_as",
            "cloud_photo_url",
        ):
            if uploaded.get(k):
                outputs[k] = uploaded[k]

    total_ms = int((time.perf_counter() - t0) * 1000)
    timings["total"] = total_ms
    outputs["action_timings"] = json.dumps(timings, ensure_ascii=False)
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
    force_image = _as_bool(params.get("want_image"))
    outputs = query_content(
        query=q,
        upload_dest=dest,
        timeout_sec=timeout_sec,
        force_image=force_image,
    )
    # Register generated image via Asset Manager — identity is asset_ref only.
    if "photo_url" in outputs:
        try:
            ref = asset.register_from_upload_url(
                photo_url=str(outputs.get("photo_url") or ""),
                saved_as=str(outputs.get("saved_as") or "") or None,
                producer="query.content",
                mime_type="image/png",
                cloud_public_base=str(outputs.get("cloud_public_base") or "") or None,
                cloud_saved_as=str(outputs.get("cloud_saved_as") or "") or None,
            )
        except AssetError as e:
            raise QueryContentError(str(e)) from e
        drop = (
            "photo_url",
            "saved_as",
            "cloud_public_base",
            "cloud_saved_as",
            "cloud_photo_url",
            "photo_local_path",
            "upload_dest",
        )
        outputs = {k: v for k, v in outputs.items() if k not in drop}
        outputs["asset_ref"] = ref.to_dict()
    preview = str(outputs.get("answer_text") or "")[:100]
    return f"query: {preview or 'ok'}", outputs
