"""Mac Edge reading atomics — finger-pointed character recognition.

Atomic capabilities (independently registered):
  reading.detect_finger   asset_ref → finger
  reading.ocr_at_finger   asset_ref + finger → chars
  reading.rank_pointed    asset_ref + finger + chars → character / answer_text

Composite reading.point_to_character decomposes to those three on this Runtime.
Input is an already-arranged Image Asset. This plugin does not capture photos.

Bridges the Asset contract to character-service HTTP
(http://127.0.0.1:9189/v1/{detect_finger,ocr_at_finger,rank_pointed}).
character-service itself knows nothing about HomeAgent Asset / Brain / Planner.

Must not import vision_ask / query_content / gopro_camera.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from typing import Any
from urllib.request import Request, urlopen

log = logging.getLogger("mac_edge.point_to_character")

DEFAULT_CHARACTER_BASE = "http://127.0.0.1:9189"
DEFAULT_HEALTH_URL = "http://127.0.0.1:9189/health"

READING_STAGE_CAPS = frozenset(
    {
        "reading.detect_finger",
        "reading.ocr_at_finger",
        "reading.rank_pointed",
    }
)

_STAGE_PATH = {
    "reading.detect_finger": "/v1/detect_finger",
    "reading.ocr_at_finger": "/v1/ocr_at_finger",
    "reading.rank_pointed": "/v1/rank_pointed",
}

_LEGACY_URL_SUFFIXES = (
    "/v1/point_to_character",
    "/point_to_character",
    "/v1/detect_finger",
    "/v1/ocr_at_finger",
    "/v1/rank_pointed",
)


class PointToCharacterError(Exception):
    pass


def _base_url() -> str:
    raw = (os.environ.get("MAC_EDGE_CHARACTER_URL") or DEFAULT_CHARACTER_BASE).strip()
    for suffix in _LEGACY_URL_SUFFIXES:
        if raw.endswith(suffix):
            raw = raw[: -len(suffix)]
            break
    return (raw or DEFAULT_CHARACTER_BASE).rstrip("/")


def _health_url() -> str:
    raw = (os.environ.get("MAC_EDGE_CHARACTER_HEALTH_URL") or DEFAULT_HEALTH_URL).strip()
    return raw or DEFAULT_HEALTH_URL


def is_available(_config: Any = None) -> Any:
    """Cheap liveness probe so the executor fails fast instead of timing out."""
    from mac_edge.capability_availability import Availability

    url = _health_url()
    try:
        req = Request(url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=1.0) as resp:
            if 200 <= resp.status < 300:
                return Availability.available()
            return Availability.unavailable(f"character-service health {resp.status}")
    except Exception as e:  # noqa: BLE001 — availability must never hang
        return Availability.unavailable(f"character-service 不可达：{e}")


def _fetch_image_bytes(url: str, *, timeout_sec: float = 30.0) -> bytes:
    if not (url.startswith("http://") or url.startswith("https://")):
        raise PointToCharacterError(f"asset http_url must be http(s): {url}")
    req = Request(url)
    try:
        with urlopen(req, timeout=timeout_sec) as resp:
            if resp.status != 200:
                raise PointToCharacterError(f"fetch asset {resp.status}: {url}")
            return resp.read()
    except PointToCharacterError:
        raise
    except Exception as e:
        raise PointToCharacterError(f"取图失败：{type(e).__name__}: {e}") from e


def _post_stage(
    cap: str,
    image_b64: str,
    extra: dict[str, Any],
    *,
    timeout_sec: float = 120.0,
) -> dict[str, Any]:
    path = _STAGE_PATH.get(cap)
    if not path:
        raise PointToCharacterError(f"unknown reading stage: {cap}")
    url = f"{_base_url()}{path}"
    body_obj: dict[str, Any] = {"image_base64": image_b64, "return_debug": False}
    body_obj.update(extra)
    body = json.dumps(body_obj).encode("utf-8")
    req = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read()
    except Exception as e:
        raise PointToCharacterError(f"character-service 调用失败：{type(e).__name__}: {e}") from e
    try:
        data = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise PointToCharacterError(f"character-service 返回非 JSON：{e}") from e
    if not isinstance(data, dict):
        raise PointToCharacterError("character-service 返回不是对象")
    if "error" in data and "character" not in data and "finger" not in data and "chars" not in data:
        raise PointToCharacterError(f"character-service 报错：{data['error']}")
    return data


def _build_answer(result: dict[str, Any]) -> tuple[str, str, str]:
    """Return (character, answer_text, status)."""
    status = str(result.get("status") or "").strip()
    character = result.get("character")
    char_text = str(character) if character is not None else ""
    reason = str(result.get("reason") or "").strip()
    if status == "ambiguous_finger":
        return "", reason or "图里有多根手指，系统无法判断你指的是哪个字。", status
    if char_text:
        answer_text = f"手指指的是「{char_text}」。"
    elif reason:
        answer_text = f"没认出来：{reason}"
    else:
        answer_text = "我不知道手指指的是哪个字。"
    return char_text, answer_text, status


def _image_b64_from_params(
    params: dict[str, Any],
    *,
    asset: "CapAsset",
    cap: str,
    timeout_sec: float,
) -> str:
    from mac_edge.asset.sdk import CapAsset
    from mac_edge.asset.types import AssetError

    if not isinstance(asset, CapAsset):
        raise PointToCharacterError(f"{cap} requires CapAsset (Runtime SDK)")
    try:
        ref = asset.require_ref(params, "asset_ref")
        # materialize_file downloads once and caches by asset_id (AssetManager).
        # Later atoms in the composite that reuse the same asset_ref read the
        # local copy instead of re-downloading from Brain — this removes the
        # per-atom remote fetch. For a locally-registered crop (produced by a
        # prior atom) the local path is returned directly with no download.
        local_path = asset.materialize_file(ref)
    except AssetError as e:
        raise PointToCharacterError(str(e)) from e
    try:
        image_bytes = local_path.read_bytes()
    except OSError as e:
        raise PointToCharacterError(f"读本地图失败：{type(e).__name__}: {e}") from e
    if not image_bytes:
        raise PointToCharacterError("asset image is empty")
    return base64.b64encode(image_bytes).decode("ascii")


def _stage_fail_reason(result: dict[str, Any], fallback: str) -> str:
    reason = str(result.get("reason") or "").strip()
    status = str(result.get("status") or "").strip()
    if reason:
        return reason
    if status:
        return f"{fallback}（{status}）"
    return fallback


def _finger_in_crop_space(
    finger: dict[str, Any], crop_origin: Any
) -> dict[str, Any] | None:
    """Translate a full-image finger payload into the finger-crop's coordinate
    space by subtracting the crop's top-left origin. Direction is unchanged
    (it's a unit vector). Returns None if the translation can't be applied."""
    if not isinstance(crop_origin, (list, tuple)) or len(crop_origin) < 2:
        return None
    try:
        ox, oy = float(crop_origin[0]), float(crop_origin[1])
    except (TypeError, ValueError):
        return None
    tip = finger.get("tip")
    if not isinstance(tip, (list, tuple)) or len(tip) < 2:
        return None
    try:
        tx, ty = float(tip[0]) - ox, float(tip[1]) - oy
    except (TypeError, ValueError):
        return None
    out = dict(finger)
    out["tip"] = [round(tx, 1), round(ty, 1)]
    return out


def _register_finger_crop(
    asset: "CapAsset", result: dict[str, Any], finger: dict[str, Any]
) -> "AssetRef | None":
    """Persist char-svc's finger crop (base64 jpg) to a local file and register
    it as a local asset, so ocr/rank atoms read the small crop via the Asset
    Manager's local path instead of re-fetching the full photo. Returns the new
    asset_ref or None if char-svc didn't return a crop (older char-svc)."""
    import base64
    import os
    import tempfile
    from pathlib import Path

    from mac_edge.asset.types import AssetRef

    crop_b64 = result.get("finger_crop_b64")
    if not isinstance(crop_b64, str) or not crop_b64:
        return None
    try:
        crop_bytes = base64.b64decode(crop_b64)
    except Exception as e:
        log.warning("detect_finger crop b64 decode failed: %s", e)
        return None
    if not crop_bytes:
        return None
    root = (os.environ.get("MAC_EDGE_DATA_DIR") or "").strip()
    staging = Path(root) / "reading-crops" if root else Path(
        tempfile.gettempdir()
    ) / "mac-edge-reading-crops"
    try:
        staging.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        log.warning("detect_finger crop staging dir failed: %s", e)
        return None
    import time as _time
    import uuid

    dest = staging / f"crop-{int(_time.time() * 1000)}-{uuid.uuid4().hex[:8]}.jpg"
    try:
        dest.write_bytes(crop_bytes)
    except OSError as e:
        log.warning("detect_finger crop write failed: %s", e)
        return None
    try:
        ref = asset.register_local_file(
            str(dest),
            producer="reading.detect_finger",
            mime_type="image/jpeg",
            type="image",
            metadata={"role": "finger_crop"},
        )
    except Exception as e:
        log.warning("detect_finger crop register failed: %s", e)
        return None
    return ref


def reading_stage_from_params(
    cap: str,
    params: dict[str, Any],
    *,
    asset: "CapAsset",
    timeout_sec: float = 120.0,
) -> tuple[str, dict[str, Any]]:
    cid = str(cap or "").strip()
    if cid not in READING_STAGE_CAPS:
        raise PointToCharacterError(f"unknown reading stage: {cid}")
    extra: dict[str, Any] = {}
    if cid == "reading.detect_finger":
        # Ask char-svc to also crop a generous finger region covering every
        # OCR window. We register that crop as a local asset and hand it on as
        # the next atoms' asset_ref, so ocr/rank read the small local crop
        # instead of re-fetching the full photo.
        extra["return_crop"] = True
    if cid in ("reading.ocr_at_finger", "reading.rank_pointed"):
        finger = params.get("finger")
        if not isinstance(finger, dict):
            raise PointToCharacterError(f"{cid} 需要 finger")
        extra["finger"] = finger
    if cid == "reading.rank_pointed":
        chars = params.get("chars")
        if not isinstance(chars, list) or not chars:
            raise PointToCharacterError(f"{cid} 需要 chars")
        extra["chars"] = chars
        # max_dist is calibrated on the *source* image diagonal, but rank now
        # receives a finger crop, so char-svc needs the original shape.
        full_shape = params.get("full_image_shape")
        if full_shape:
            extra["full_image_shape"] = full_shape
    image_b64 = _image_b64_from_params(params, asset=asset, cap=cid, timeout_sec=timeout_sec)
    t0 = time.perf_counter()
    result = _post_stage(cid, image_b64, extra, timeout_sec=timeout_sec)
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    if cid == "reading.detect_finger":
        status = str(result.get("status") or "").strip()
        finger = result.get("finger")
        if status == "ambiguous_finger" or not isinstance(finger, dict):
            _char, answer_text, _st = _build_answer(result)
            raise PointToCharacterError(
                answer_text
                or _stage_fail_reason(result, "图里有多根手指，系统无法判断你指的是哪个字。")
            )
        outputs: dict[str, Any] = {"finger": finger, "status": str(result.get("status") or "ok")}
        crop_ref = _register_finger_crop(asset, result, finger)
        if crop_ref is not None:
            outputs["asset_ref"] = crop_ref
            crop_origin = result.get("crop_origin")
            full_shape = result.get("full_image_shape")
            rel_finger = _finger_in_crop_space(finger, crop_origin)
            if rel_finger is not None:
                outputs["finger"] = rel_finger
            if crop_origin is not None:
                outputs["crop_origin"] = crop_origin
            if full_shape is not None:
                outputs["full_image_shape"] = full_shape
            log.info(
                "detect_finger ok crop_registered total_ms=%s", elapsed_ms
            )
        else:
            log.info("detect_finger ok total_ms=%s (no crop)", elapsed_ms)
        return "detect_finger: ok", outputs
    if cid == "reading.ocr_at_finger":
        chars = result.get("chars")
        if not isinstance(chars, list) or not chars:
            raise PointToCharacterError(_stage_fail_reason(result, "没有识别到文字"))
        log.info("ocr_at_finger ok chars=%s total_ms=%s", len(chars), elapsed_ms)
        return "ocr_at_finger: ok", {"chars": chars, "status": str(result.get("status") or "ok")}
    char_text, answer_text, status = _build_answer(result)
    log.info(
        "rank_pointed ok status=%s char=%s total_ms=%s",
        status,
        char_text or "<none>",
        elapsed_ms,
    )
    return f"point_to_character: {answer_text[:100] or 'ok'}", {
        "character": char_text,
        "answer_text": answer_text,
        "status": status,
    }
