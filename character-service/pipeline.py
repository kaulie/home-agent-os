"""Still-image point-to-character. Hands + OCR + geometry. No Planner."""

from __future__ import annotations

import math
import os
import time
from typing import Any, Callable

from geometry import decide, explode_blocks, finger_ray, has_cjk, rank_characters
from hunyuan_ocr import HunyuanOcrError, recognize as hunyuan_recognize
from ocr_client import OcrClientError, blocks_from_ocr, recognize as ocr_recognize

DEFAULT_MAX_ANGLE = 30.0
DEFAULT_MIN_SCORE = 0.28
DEFAULT_MIN_MARGIN = 0.06
DEFAULT_MAX_DIST_FRAC = 0.55
CROP_PAD = 0.18
# (size, shift_along_ray): a centered window plus a smaller one shifted ahead of
# the fingertip in the finger direction, where the pointed-at character sits.
OCR_WINDOWS = ((600, 0), (600, 260))
OCR_UPSCALE = 1.0


class PipelineError(Exception):
    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _env_float(name: str, default: float) -> float:
    import os

    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    return float(raw)


def crop_bbox(image_bgr: Any, bbox: list[Any], pad_frac: float = CROP_PAD) -> bytes:
    import cv2

    h, w = image_bgr.shape[:2]
    x1, y1, x2, y2 = [float(v) for v in bbox]
    pw, ph = (x2 - x1) * pad_frac, (y2 - y1) * pad_frac
    xa = max(0, int(math.floor(x1 - pw)))
    ya = max(0, int(math.floor(y1 - ph)))
    xb = min(w, int(math.ceil(x2 + pw)))
    yb = min(h, int(math.ceil(y2 + ph)))
    if xb <= xa or yb <= ya:
        raise PipelineError("uncertain", "裁剪区域无效")
    crop = image_bgr[ya:yb, xa:xb]
    ok, buf = cv2.imencode(".png", crop)
    if not ok:
        raise PipelineError("uncertain", "裁剪编码失败")
    return buf.tobytes()


def shift_ocr_blocks(result: dict[str, Any], dx: int, dy: int, scale: float = 1.0) -> dict[str, Any]:
    blocks = result.get("blocks") or []
    if not isinstance(blocks, list):
        return result
    out = []
    inv = 1.0 / scale if scale else 1.0
    for item in blocks:
        if not isinstance(item, dict):
            continue
        copied = dict(item)
        bbox = copied.get("bbox")
        if isinstance(bbox, list) and len(bbox) == 4:
            try:
                x1, y1, x2, y2 = (float(n) for n in bbox)
                copied["bbox"] = [
                    x1 * inv + dx,
                    y1 * inv + dy,
                    x2 * inv + dx,
                    y2 * inv + dy,
                ]
            except (TypeError, ValueError):
                pass
        out.append(copied)
    result = dict(result)
    result["blocks"] = out
    return result


def merge_ocr_results(parts: list[dict[str, Any]]) -> dict[str, Any]:
    blocks: list[dict[str, Any]] = []
    texts: list[str] = []
    for part in parts:
        texts.append(str(part.get("text") or ""))
        for item in part.get("blocks") or []:
            if isinstance(item, dict):
                blocks.append(item)
    merged = dict(parts[0]) if parts else {}
    merged["blocks"] = blocks
    merged["text"] = "".join(texts)
    return merged


def finger_ocr_window(
    image_bgr: Any,
    origin: tuple[float, float],
    direction: tuple[float, float],
    size: int,
    upscale: float = OCR_UPSCALE,
    shift: float = 0.0,
) -> tuple[bytes, tuple[int, int], float] | None:
    """Crop around the fingertip. ``shift`` moves the crop center forward along the
    finger direction so the pointed-at glyph (ahead of the nail, not under it) is
    captured even when it sits just outside a fingertip-centered window."""
    try:
        import cv2
    except Exception:
        return None
    try:
        h, w = image_bgr.shape[:2]
    except Exception:
        return None
    cx = origin[0] + direction[0] * shift
    cy = origin[1] + direction[1] * shift
    half = size / 2.0
    x1 = max(0, int(round(cx - half)))
    y1 = max(0, int(round(cy - half)))
    x2 = min(w, int(round(cx + half)))
    y2 = min(h, int(round(cy + half)))
    if x2 - x1 < 48 or y2 - y1 < 48:
        return None
    try:
        crop = image_bgr[y1:y2, x1:x2]
        if upscale and upscale != 1.0:
            crop = cv2.resize(
                crop,
                (max(32, int(round(crop.shape[1] * upscale))), max(32, int(round(crop.shape[0] * upscale)))),
                interpolation=cv2.INTER_CUBIC,
            )
        ch, cw = crop.shape[:2]
        pad_h = (32 - ch % 32) % 32
        pad_w = (32 - cw % 32) % 32
        if pad_h or pad_w:
            crop = cv2.copyMakeBorder(
                crop, 0, pad_h, 0, pad_w, cv2.BORDER_CONSTANT, value=(255, 255, 255)
            )
        ok, buf = cv2.imencode(".jpg", crop, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    except Exception:
        return None
    if not ok:
        return None
    return buf.tobytes(), (x1, y1), float(upscale)


def _confirm_char_from_ocr(result: dict[str, Any]) -> str | None:
    chars = explode_blocks(blocks_from_ocr(result))
    cjk = [c for c in chars if has_cjk(str(c.get("text") or ""))]
    if len(cjk) == 1:
        return str(cjk[0].get("text") or "") or None
    return None


def run_still(
    image_bytes: bytes,
    *,
    language: str = "zh",
    return_debug: bool = False,
    detect_hand: Callable[[Any], dict[int, tuple[float, float]] | None] | None = None,
    ocr: Callable[..., dict[str, Any]] | None = None,
    decode: Callable[[bytes], Any] | None = None,
) -> dict[str, Any]:
    from hands import HandsError, decode_bgr, detect_index_landmarks

    decode_fn = decode or decode_bgr
    detect_fn = detect_hand or detect_index_landmarks
    _ocr_backend = os.environ.get("READING_OCR_BACKEND", "hunyuan").strip().lower()
    if ocr is not None:
        ocr_fn = ocr
    elif _ocr_backend == "paddle":
        ocr_fn = ocr_recognize
    else:
        ocr_fn = hunyuan_recognize
    _OcrError = (OcrClientError, HunyuanOcrError)

    t_total_start = time.perf_counter()
    timing = {
        "hand_detection_s": 0.0,
        "ocr_vlm_s": 0.0,
        "geometry_ranking_s": 0.0,
    }

    try:
        image = decode_fn(image_bytes)
    except HandsError as e:
        raise PipelineError("failed", str(e)) from e

    h, w = image.shape[:2]
    max_angle = _env_float("READING_MAX_ANGLE_DEG", DEFAULT_MAX_ANGLE)
    min_score = _env_float("READING_MIN_SCORE", DEFAULT_MIN_SCORE)
    min_margin = _env_float("READING_MIN_MARGIN", DEFAULT_MIN_MARGIN)
    max_dist = _env_float("READING_MAX_DIST_FRAC", DEFAULT_MAX_DIST_FRAC) * math.hypot(w, h)

    t_hand_start = time.perf_counter()
    landmarks = detect_fn(image)
    t_hand_end = time.perf_counter()
    timing["hand_detection_s"] = round(t_hand_end - t_hand_start, 4)
    if not landmarks:
        timing["total_s"] = round(time.perf_counter() - t_total_start, 4)
        raise PipelineError(
            "no_hand", "图里没有检测到手，或看不见食指。请俯拍书页、手指完整入画。"
        )
    ray = finger_ray(landmarks)
    if ray is None:
        timing["total_s"] = round(time.perf_counter() - t_total_start, 4)
        raise PipelineError("no_hand", "食指方向不稳定。请让食指伸直、指尖对着目标字。")
    origin, direction = ray

    window = None
    ocr_elapsed = 0.0
    try:
        parts: list[dict[str, Any]] = []
        last_error: Exception | None = None
        t_ocr_start = time.perf_counter()
        for spec in OCR_WINDOWS:
            osize, oshift = (spec if isinstance(spec, tuple) else (spec, 0))
            window = finger_ocr_window(image, origin, direction, osize, shift=oshift)
            if not window:
                continue
            ocr_bytes, origin_xy, scale = window
            # Run each window twice and merge: the VLM is non-deterministic, so a
            # second pass often recovers glyphs the first pass missed.
            for _pass in range(2):
                t_call_start = time.perf_counter()
                try:
                    part = ocr_fn(ocr_bytes, language=language)
                except _OcrError as e:
                    last_error = e
                    ocr_elapsed += time.perf_counter() - t_call_start
                    continue
                ocr_elapsed += time.perf_counter() - t_call_start
                parts.append(shift_ocr_blocks(part, origin_xy[0], origin_xy[1], scale))
        if not parts:
            from hands import encode_jpeg

            encoded = encode_jpeg(image)
            ocr_bytes = encoded or image_bytes
            t_call_start = time.perf_counter()
            try:
                ocr_result = ocr_fn(ocr_bytes, language=language)
            except _OcrError as e:
                ocr_elapsed += time.perf_counter() - t_call_start
                raise last_error or e
            ocr_elapsed += time.perf_counter() - t_call_start
            window = None
        else:
            ocr_result = merge_ocr_results(parts)
        timing["ocr_vlm_s"] = round(ocr_elapsed, 4)
    except _OcrError as e:
        timing["ocr_vlm_s"] = round(ocr_elapsed, 4)
        timing["total_s"] = round(time.perf_counter() - t_total_start, 4)
        raise PipelineError("failed", str(e)) from e
    blocks = blocks_from_ocr(ocr_result)
    chars = explode_blocks(blocks)
    if not chars:
        timing["total_s"] = round(time.perf_counter() - t_total_start, 4)
        raise PipelineError("no_text", "没有识别到文字。请俯拍、书页占画面主体、光线足够。")

    t_geom_start = time.perf_counter()
    ranked = rank_characters(
        chars,
        origin,
        direction,
        max_angle_deg=max_angle,
        max_distance=max_dist,
    )
    # Confirmation re-OCR: re-read the top candidate's box with large padding.
    # If the VLM returns a different single CJK glyph, add it as a high-score
    # candidate so it can appear in top-3 (acceptance: correct answer in top-3).
    # Additive (never replaces the original); short timeout to avoid hangs.
    if ranked:
        _top0 = ranked[0]
        try:
            _crop = crop_bbox(image, _top0["bbox"], pad_frac=0.5)
            t_call_start = time.perf_counter()
            _second = ocr_fn(_crop, language=language)
            ocr_elapsed += time.perf_counter() - t_call_start
            _got = _confirm_char_from_ocr(_second)
            if _got and _got != str(_top0.get("text") or "") and has_cjk(_got):
                ranked.append({
                    "text": _got,
                    "bbox": _top0["bbox"],
                    "score": float(_top0["score"]) - 0.001,
                    "split": False,
                    "mode": "confirm",
                })
        except (_OcrError, PipelineError):
            pass
    verdict = decide(ranked, min_score=min_score, min_margin=min_margin)
    t_geom_end = time.perf_counter()
    timing["geometry_ranking_s"] = round(t_geom_end - t_geom_start, 4)
    debug_candidates = [
        {
            "text": r["text"],
            "bbox": r["bbox"],
            "score": round(float(r["score"]), 4),
            "split": bool(r.get("split")),
        }
        for r in ranked[:8]
    ]
    # top-3 by score (confidence), for acceptance: correct answer in top-3 passes.
    top3 = sorted(
        [{"text": r["text"], "bbox": r["bbox"], "score": round(float(r["score"]), 4)} for r in ranked],
        key=lambda r: r["score"],
        reverse=True,
    )[:3]

    # Full per-stage I/O for replay/debug: landmarks, finger ray, raw OCR blocks,
    # exploded chars, and the complete ranked list (with mode). Attached only when
    # return_debug — lets geometry be re-run offline against the saved finger/chars
    # without re-calling the VLM.
    replay: dict[str, Any] | None = None
    if return_debug:
        replay = {
            "landmarks": {
                str(k): [round(v[0], 2), round(v[1], 2)] for k, v in landmarks.items()
            },
            "origin": [round(origin[0], 2), round(origin[1], 2)],
            "direction": [round(direction[0], 6), round(direction[1], 6)],
            "max_distance": round(max_dist, 2),
            "max_angle_deg": max_angle,
            "min_score": min_score,
            "min_margin": min_margin,
            "blocks": [
                {"text": b.get("text"), "bbox": b.get("bbox")} for b in blocks
            ],
            "chars": [
                {
                    "text": c.get("text"),
                    "bbox": c.get("bbox"),
                    "split": bool(c.get("split")),
                    "source_text": c.get("source_text"),
                }
                for c in chars
            ],
            "ranked": [
                {
                    "text": r.get("text"),
                    "bbox": r.get("bbox"),
                    "score": round(float(r.get("score") or 0), 6),
                    "mode": r.get("mode"),
                    "split": bool(r.get("split")),
                }
                for r in ranked
            ],
            "verdict": verdict,
        }

    payload: dict[str, Any] = {
        "engine": "reading.point_to_character",
        "status": verdict["status"],
        "finger": {
            "tip": [round(origin[0], 1), round(origin[1], 1)],
            "direction": [round(direction[0], 4), round(direction[1], 4)],
        },
        "candidates": debug_candidates,
        "top3": top3,
        "ocr_blocks": len(blocks),
        "char_boxes": len(chars),
        "timing": dict(timing),
    }
    if replay is not None:
        payload["replay"] = replay

    if verdict["status"] not in ("ok", "ok_with_alternatives"):
        payload["reason"] = verdict.get("reason")
        payload["character"] = None
        payload["timing"]["total_s"] = round(time.perf_counter() - t_total_start, 4)
        if return_debug:
            from debug_draw import overlay_png

            payload["debug_png_base64"] = overlay_png(
                image,
                origin=origin,
                direction=direction,
                chars=chars,
                chosen=verdict.get("top"),
                max_distance=max_dist,
            )
        return payload

    top = verdict["top"]
    character = str(top["text"])
    confirmed = character
    timing["ocr_vlm_s"] = round(ocr_elapsed, 4)

    payload["status"] = verdict["status"]
    payload["character"] = confirmed
    payload["bbox"] = top["bbox"]
    payload["score"] = round(float(top["score"]), 4)
    payload["split_from_line"] = bool(top.get("split"))

    if verdict["status"] == "ok_with_alternatives":
        alts = verdict.get("alternatives") or []
        payload["alternatives"] = [
            {
                "text": str(a["text"]),
                "bbox": a["bbox"],
                "score": round(float(a["score"]), 4),
            }
            for a in alts
        ]
        payload["margin"] = round(float(verdict.get("margin") or 0), 4)
    payload["timing"]["total_s"] = round(time.perf_counter() - t_total_start, 4)
    if return_debug:
        from debug_draw import overlay_png

        payload["debug_png_base64"] = overlay_png(
            image,
            origin=origin,
            direction=direction,
            chars=chars,
            chosen=top,
            max_distance=max_dist,
        )
    return payload
