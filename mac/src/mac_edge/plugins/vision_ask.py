"""Mac Edge capability: vision.ask — image + question → answer_text.

Contract:
  input:  photo_url (required), query (required)
  output: answer_text (required)

Must not import vision_perceive / query_content / gopro_camera.
May use vision_providers (same vision model) with this capability's schema.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from mac_edge.plugins.vision_providers import VisionProviderError
from mac_edge.plugins.vision_providers.registry import get_provider

log = logging.getLogger("mac_edge.vision_ask")

DEFAULT_PROMPT = (
    "你在根据一张照片回答用户的一句提问。"
    "只根据图里实际看见的内容作答；图里没有的人、物、字不要写。"
    "用户说「这个 / 那个 / 手指指的 / 这个字」时，必须落到被指向或被问到的那一个对象，"
    "不要把画面里所有文字整页念出来当答案。"
    "问读音、读啥、怎么读：给出该字或词和读音。"
    "看不清、无法判定指向、超出图中可见时，answer_text 必须直说「我不知道」。"
    "禁止猜测。禁止输出客厅场景结构（people / lighting / spatial 等）。"
    "只输出一层 JSON。answer_text 必须是普通中文，绝不能把整段 JSON 再放进 answer_text。"
)

STRUCTURE_HINT = """
你必须只输出一个 JSON 对象。禁止 Markdown 代码块。禁止在任何字段里再嵌套 JSON 字符串。

手指指向一个汉字：
{
  "answer_text": "这个字是「喵」，读 miāo。",
  "refused": false
}

看不清时：
{
  "answer_text": "我不知道手指指的是哪一个字。",
  "refused": true
}

字段约定：
- answer_text: 中文回答；不确定时必须包含「我不知道」
- refused: 看不清或不能判定指向时为 true
""".strip()

ASK_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answer_text", "refused"],
    "properties": {
        "answer_text": {
            "type": "string",
            "description": "对用户问题的中文回答；不确定时必须直说「我不知道」",
        },
        "refused": {
            "type": "boolean",
            "description": "看不清、无法判定指向、超出图中可见时为 true",
        },
    },
}

TEXT_FORMAT_JSON_SCHEMA: dict[str, Any] = {
    "format": {
        "type": "json_schema",
        "name": "home_vision_ask",
        "strict": True,
        "schema": ASK_JSON_SCHEMA,
    }
}


class VisionAskError(Exception):
    pass


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
    raise VisionAskError(f"refused must be boolean, got {value!r}")


def _parse_model_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise VisionAskError(f"model output is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise VisionAskError(
            f"model output JSON must be an object, got {type(data).__name__}"
        )
    return data


def _to_model_result(raw: dict[str, Any]) -> dict[str, Any]:
    text = _as_text(raw.get("_provider_text") or raw.get("raw_text"))
    if not text:
        raise VisionAskError("vision ask provider returned empty text")
    parsed = _parse_model_json(text)
    parsed["raw_text"] = text
    if raw.get("model"):
        parsed["model"] = raw["model"]
    if raw.get("api_latency_ms") not in (None, ""):
        parsed["api_latency_ms"] = raw["api_latency_ms"]
    return parsed


def ask(
    *,
    photo_url: str,
    query: str,
    timeout_sec: float = 90.0,
    provider_name: str | None = None,
    provider: Any = None,
) -> dict[str, str]:
    url = (photo_url or "").strip()
    q = (query or "").strip()
    if not url:
        raise VisionAskError("missing photo_url")
    if not (url.startswith("http://") or url.startswith("https://")):
        raise VisionAskError("photo_url must be http(s)")
    if not q:
        raise VisionAskError("missing query")

    user_prompt = "\n\n".join([DEFAULT_PROMPT, f"用户问题：{q}", STRUCTURE_HINT])
    t0 = time.perf_counter()
    try:
        prov = provider if provider is not None else get_provider(provider_name)
        raw = prov.analyze(
            image_url=url,
            prompt=user_prompt,
            timeout_sec=timeout_sec,
            text_format=TEXT_FORMAT_JSON_SCHEMA,
        )
    except VisionProviderError as e:
        raise VisionAskError(str(e)) from e
    except VisionAskError:
        raise
    except Exception as e:
        raise VisionAskError(f"{type(e).__name__}: {e}") from e

    if not isinstance(raw, dict):
        raise VisionAskError("vision ask provider must return a dict")

    merged = _to_model_result(raw)
    answer_raw = merged.get("answer_text")
    if isinstance(answer_raw, (dict, list)):
        raise VisionAskError(
            f"answer_text must be a plain string, got {type(answer_raw).__name__} "
            "(fix prompt — no unwrap)"
        )
    answer_text = _as_text(answer_raw)
    if not answer_text:
        raise VisionAskError("vision ask returned empty answer_text")
    if answer_text.lstrip().startswith("{") or answer_text.lstrip().startswith("["):
        raise VisionAskError(
            "answer_text looks like nested JSON; model output invalid "
            "(fix prompt — no unwrap)"
        )

    refused = _as_bool(merged.get("refused"))
    if refused and "不知道" not in answer_text:
        raise VisionAskError(
            "refused=true but answer_text does not say 我不知道 (fix prompt)"
        )

    total_ms = int((time.perf_counter() - t0) * 1000)
    log.info(
        "vision.ask ok refused=%s total_ms=%s answer=%s",
        refused,
        total_ms,
        answer_text[:80],
    )
    return {"answer_text": answer_text}


def ask_from_params(
    params: dict[str, Any],
    *,
    asset: "CapAsset",
    timeout_sec: float = 90.0,
) -> tuple[str, dict[str, str]]:
    from mac_edge.asset.sdk import CapAsset
    from mac_edge.asset.types import AssetError

    if not isinstance(asset, CapAsset):
        raise VisionAskError("vision.ask requires CapAsset (Runtime SDK)")
    try:
        ref = asset.require_ref(params, "asset_ref")
        photo_url = asset.http_url(ref)
    except AssetError as e:
        raise VisionAskError(str(e)) from e
    query = str(params.get("query") or "").strip()
    outputs = ask(photo_url=photo_url, query=query, timeout_sec=timeout_sec)
    preview = str(outputs.get("answer_text") or "")[:100]
    return f"ask: {preview or 'ok'}", outputs
