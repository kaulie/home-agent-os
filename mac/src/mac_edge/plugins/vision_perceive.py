"""Mac Edge capability: vision.perceive — pluggable vision providers.

Contract:
  input:  photo_url (required)
  output: flat fields — summary / people / spatial / actions / posture / lighting
          (people & lighting are JSON strings; others plain text).

Runtime-owned skill (not Brain). Switch backends with:

  MAC_EDGE_VISION_PROVIDER=ark|openai   # default ark
  MAC_EDGE_VISION_API_BASE=...
  MAC_EDGE_VISION_API_KEY=...           # or ARK_API_KEY for ark
  MAC_EDGE_VISION_MODEL=...

Default provider is Volcengine Ark Responses (`input_image` + `input_text`).
New providers: implement VisionProvider + register_provider(...) in
mac_edge.plugins.vision_providers.registry.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from mac_edge.plugins.vision_providers import VisionProviderError
from mac_edge.plugins.vision_providers.registry import get_provider

log = logging.getLogger("mac_edge.vision_perceive")

DEFAULT_PROMPT = (
    "请只根据这张照片里实际看见的内容做分析，不要用记忆、常识或提示词里的示例去补全画面。"
    "图里没有的人、物、动作不要写。"
    "用中文给出结构化理解。重点：1) 真实可见的人（每人唯一 id）；"
    "2) 空间位置；3) 动作；4) 体态；"
    "5) 光线 whole + region（person_id 引用 people[].id）。"
    "只输出一层 JSON：summary 必须是普通中文短句，绝不能把整段 JSON 再放进 summary。"
)

STRUCTURE_HINT = """
你必须只输出一个 JSON 对象。禁止 Markdown 代码块。禁止在任何字段里再嵌套 JSON 字符串。
所有字段必须能在这张照片里找到依据。下面示例只说明 JSON 形状，禁止把示例的场景、人数、人物身份套到这张图上。

正确示例（仅字段形状；summary 是短句，不是字符串化的 JSON）：
{
  "summary": "客厅里一名孩童在沙发上，一名男子在窗边用电脑。",
  "people": [
    {"id": "p1", "description": "短发孩童，浅色上衣", "count": 1, "position": "左侧沙发"},
    {"id": "p2", "description": "成年男性，深色短袖", "count": 1, "position": "靠窗书桌后"}
  ],
  "spatial": "客餐厅连通，左侧沙发与茶几，右侧电视墙，远端靠窗书桌。",
  "actions": "p1 在沙发上操作手持设备；p2 坐在书桌前使用笔记本电脑。",
  "posture": "p1 半靠沙发低头；p2 坐姿前倾面向屏幕。",
  "lighting": {
    "whole": "整体偏暗，主光来自远端窗光，近景较暗。",
    "region": [
      {"person_id": "p1", "lighting": "沙发区偏暗，无局部灯", "summary": "靠漫反射补光"},
      {"person_id": "p2", "lighting": "窗边较亮但人物逆光", "summary": "桌面受光充足"}
    ]
  }
}

错误示例（禁止）：
{"summary": "{\\"summary\\":\\"...\\",\\"people\\":[...]}", "people": []}

字段约定：
- summary: 一句中文，禁止以 { 开头；只概括这张图
- people: 仅画面中可见的真人；无人则为 []；id 全局唯一，建议 p1、p2…
- lighting.region[].person_id: 必须对应 people[].id
- actions / posture: 中文短句，可用 p1/p2 指代；禁止 JSON 数组字符串
""".strip()


class VisionPerceiveError(Exception):
    pass


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def _normalize_people(people: Any) -> list[dict[str, Any]]:
    raw_items: list[Any]
    if not isinstance(people, list):
        if isinstance(people, str) and people.strip():
            raw_items = [people.strip()]
        else:
            return []
    else:
        raw_items = people

    used: set[str] = set()
    out: list[dict[str, Any]] = []
    auto_i = 1
    for p in raw_items:
        if isinstance(p, str):
            desc, count, position, pid = p.strip(), 1, "", ""
        elif isinstance(p, dict):
            desc = (
                str(p.get("description") or p.get("name") or "人").strip() or "人"
            )
            try:
                count = int(p.get("count") or 1)
            except (TypeError, ValueError):
                count = 1
            position = str(p.get("position") or "").strip()
            pid = str(p.get("id") or p.get("person_id") or "").strip()
        else:
            continue

        if pid and pid not in used:
            person_id = pid
        else:
            while f"p{auto_i}" in used:
                auto_i += 1
            person_id = f"p{auto_i}"
            auto_i += 1
        used.add(person_id)
        out.append(
            {
                "id": person_id,
                "description": desc,
                "count": count,
                "position": position,
            }
        )
    return out


def _normalize_lighting(
    lighting: Any,
    *,
    people: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Normalize to {whole, region:[{person_id, lighting, summary}]}."""
    people = people or []
    known_ids = {str(p.get("id") or "") for p in people if p.get("id")}

    def _empty() -> dict[str, Any]:
        return {"whole": "", "region": []}

    def _region_item(
        *,
        person_id: str = "",
        lighting_text: str = "",
        summary: str = "",
    ) -> dict[str, str]:
        return {
            "person_id": person_id.strip(),
            "lighting": lighting_text.strip(),
            "summary": summary.strip(),
        }

    if lighting is None:
        return _empty()

    if isinstance(lighting, str):
        return {"whole": lighting.strip(), "region": []}

    if isinstance(lighting, list):
        # Bare list of region entries
        regions: list[dict[str, str]] = []
        for item in lighting:
            if isinstance(item, dict):
                regions.append(
                    _region_item(
                        person_id=str(
                            item.get("person_id") or item.get("id") or ""
                        ),
                        lighting_text=str(
                            item.get("lighting")
                            or item.get("brightness")
                            or item.get("description")
                            or ""
                        ),
                        summary=str(item.get("summary") or item.get("detail") or ""),
                    )
                )
            elif isinstance(item, str) and item.strip():
                regions.append(_region_item(summary=item.strip()))
        return {"whole": "", "region": regions}

    if not isinstance(lighting, dict):
        return {"whole": str(lighting).strip(), "region": []}

    whole = str(
        lighting.get("whole")
        or lighting.get("overall")
        or lighting.get("global")
        or lighting.get("scene")
        or ""
    ).strip()

    region_raw = lighting.get("region")
    if region_raw is None:
        region_raw = lighting.get("regions")
    if region_raw is None:
        region_raw = lighting.get("activity_areas")

    regions_out: list[dict[str, str]] = []
    if isinstance(region_raw, list):
        for item in region_raw:
            if isinstance(item, dict):
                pid = str(
                    item.get("person_id") or item.get("id") or item.get("people_id") or ""
                ).strip()
                if pid and known_ids and pid not in known_ids:
                    # keep as-is; model may use alternate labels
                    pass
                regions_out.append(
                    _region_item(
                        person_id=pid,
                        lighting_text=str(
                            item.get("lighting")
                            or item.get("brightness")
                            or item.get("local")
                            or ""
                        ),
                        summary=str(
                            item.get("summary")
                            or item.get("detail")
                            or item.get("details")
                            or ""
                        ),
                    )
                )
            elif isinstance(item, str) and item.strip():
                regions_out.append(_region_item(summary=item.strip()))
    elif isinstance(region_raw, dict):
        # Map person_id -> text
        for pid, val in region_raw.items():
            if isinstance(val, dict):
                regions_out.append(
                    _region_item(
                        person_id=str(pid),
                        lighting_text=str(val.get("lighting") or ""),
                        summary=str(val.get("summary") or ""),
                    )
                )
            else:
                regions_out.append(
                    _region_item(person_id=str(pid), lighting_text=str(val or ""))
                )

    # Legacy: activity / activity as free text
    if not regions_out:
        activity = str(
            lighting.get("activity")
            or lighting.get("local")
            or lighting.get("people")
            or ""
        ).strip()
        if activity and people:
            # One shared note attached to each person if model didn't structure
            for p in people:
                regions_out.append(
                    _region_item(
                        person_id=str(p.get("id") or ""),
                        lighting_text=activity,
                        summary="",
                    )
                )
        elif activity:
            regions_out.append(_region_item(summary=activity))

    # If still no regions but we have people, ensure placeholders for ids
    if not regions_out and people:
        for p in people:
            regions_out.append(_region_item(person_id=str(p.get("id") or "")))

    return {"whole": whole, "region": regions_out}


def _parse_model_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise VisionPerceiveError(f"model output is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise VisionPerceiveError(
            f"model output JSON must be an object, got {type(data).__name__}"
        )
    return data


def _merge_provider_result(raw: dict[str, Any]) -> dict[str, Any]:
    """Parse provider raw_text as JSON object. No structure repair / unwrap."""
    text = _as_text(raw.get("_provider_text") or raw.get("raw_text"))
    timing_keys = (
        "api_latency_ms",
        "download_latency_ms",
        "prepare_latency_ms",
        "image_mode",
        "model",
    )
    if not text:
        # Allow providers that already return structured fields (placeholder mode).
        if any(
            k in raw and raw.get(k) not in (None, "", [], {})
            for k in ("summary", "people", "spatial", "actions", "posture", "lighting")
        ):
            merged = dict(raw)
            for k in timing_keys:
                if raw.get(k) not in (None, ""):
                    merged[k] = raw[k]
            return merged
        raise VisionPerceiveError("vision provider returned empty text")

    parsed = _parse_model_json(text)
    parsed["raw_text"] = text
    for k in timing_keys:
        if raw.get(k) not in (None, ""):
            parsed[k] = raw[k]
    return parsed


def _normalize_actions(actions: Any) -> str:
    """List → Chinese text joined by ；. Reject JSON-array-in-string without rewriting."""
    if actions is None:
        return ""
    if isinstance(actions, list):
        parts = [str(x).strip() for x in actions if str(x).strip()]
        return "；".join(parts)
    if isinstance(actions, str):
        return actions.strip()
    if isinstance(actions, dict):
        return _as_text(actions)
    return str(actions).strip()


def _to_outputs(result: dict[str, Any]) -> dict[str, str]:
    raw_summary = result.get("summary")
    if isinstance(raw_summary, (dict, list)):
        raise VisionPerceiveError(
            f"vision summary must be a plain string, got {type(raw_summary).__name__} "
            "(fix prompt — no unwrap)"
        )
    people = _normalize_people(result.get("people"))
    summary = _as_text(raw_summary)
    spatial = _as_text(result.get("spatial") or result.get("scene"))
    actions = _normalize_actions(result.get("actions") or result.get("activities"))
    posture = _as_text(result.get("posture"))
    lighting = _normalize_lighting(result.get("lighting"), people=people)

    # Fail loud: model stuffed JSON into summary — fix the prompt, do not unwrap.
    if not summary:
        raise VisionPerceiveError("vision returned empty summary")
    if summary.lstrip().startswith("{") or summary.lstrip().startswith("["):
        raise VisionPerceiveError(
            "vision summary looks like nested JSON; model output invalid "
            "(fix prompt — no unwrap)"
        )

    # Wire: flat string outputs (complex fields JSON-encoded).
    return {
        "summary": summary,
        "people": json.dumps(people, ensure_ascii=False),
        "spatial": spatial,
        "actions": actions,
        "posture": posture,
        "lighting": json.dumps(lighting, ensure_ascii=False),
    }


def perceive(
    *,
    photo_url: str,
    prompt: str | None = None,
    timeout_sec: float = 90.0,
    provider_name: str | None = None,
) -> dict[str, str]:
    """Run configured VisionProvider on a public photo_url."""
    url = (photo_url or "").strip()
    if not url:
        raise VisionPerceiveError("missing photo_url")
    if not (url.startswith("http://") or url.startswith("https://")):
        raise VisionPerceiveError("photo_url must be http(s)")

    extra = (prompt or "").strip()
    parts = [DEFAULT_PROMPT]
    if extra and extra != DEFAULT_PROMPT:
        parts.append(extra)
    parts.append(STRUCTURE_HINT)
    user_prompt = "\n\n".join(parts)
    t0 = time.perf_counter()
    try:
        provider = get_provider(provider_name)
        raw = provider.analyze(
            image_url=url, prompt=user_prompt, timeout_sec=timeout_sec
        )
    except VisionProviderError as e:
        total_ms = int((time.perf_counter() - t0) * 1000)
        log.warning(
            "vision.perceive failed provider=%s total_ms=%s err=%s",
            provider_name or "default",
            total_ms,
            e,
        )
        raise VisionPerceiveError(str(e)) from e
    except Exception as e:
        total_ms = int((time.perf_counter() - t0) * 1000)
        log.warning(
            "vision.perceive failed provider=%s total_ms=%s err=%s",
            provider_name or "default",
            total_ms,
            e,
        )
        raise VisionPerceiveError(f"{type(e).__name__}: {e}") from e

    if not isinstance(raw, dict):
        raise VisionPerceiveError("vision provider must return a dict")
    total_ms = int((time.perf_counter() - t0) * 1000)
    raw["latency_ms"] = total_ms
    merged = _merge_provider_result(raw)
    merged["latency_ms"] = total_ms
    outputs = _to_outputs(merged)
    summary_preview = str(outputs.get("summary") or "")[:80]
    log.info(
        "vision.perceive ok provider=%s model=%s image_mode=%s "
        "total_ms=%s api_ms=%s download_ms=%s prepare_ms=%s summary=%s",
        getattr(provider, "name", provider_name or "?"),
        merged.get("model", ""),
        merged.get("image_mode", ""),
        total_ms,
        merged.get("api_latency_ms", ""),
        merged.get("download_latency_ms", ""),
        merged.get("prepare_latency_ms", ""),
        summary_preview,
    )
    return outputs


def perceive_from_params(
    params: dict[str, Any],
    *,
    asset: "CapAsset",
    timeout_sec: float = 90.0,
) -> tuple[str, dict[str, str]]:
    from mac_edge.asset.sdk import CapAsset
    from mac_edge.asset.types import AssetError

    if not isinstance(asset, CapAsset):
        raise VisionPerceiveError("vision.perceive requires CapAsset (Runtime SDK)")
    try:
        ref = asset.require_ref(params, "asset_ref")
        photo_url = asset.http_url(ref)
    except AssetError as e:
        raise VisionPerceiveError(str(e)) from e
    prompt = str(params.get("prompt") or "").strip() or None
    outputs = perceive(photo_url=photo_url, prompt=prompt, timeout_sec=timeout_sec)
    summary = str(outputs.get("summary") or "")[:100]
    msg = f"perceived: {summary or 'ok'}"
    return msg, outputs
