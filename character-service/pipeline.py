"""Still-image point-to-character. Hands + OCR + geometry. No Planner."""

from __future__ import annotations

import math
import os
import time
from typing import Any, Callable

from geometry import (
    AMBIGUOUS_FINGER_MSG,
    decide,
    explode_blocks,
    has_cjk,
    pointing_fingers,
    rank_characters,
)
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
# Half-size of the finger-region crop produced by detect_finger when the runtime
# asks for return_crop. Sized to cover every OCR window (max shift 260 + half
# 300 = 560 ahead of the fingertip), so ocr_at_finger's windows always fit
# inside the crop regardless of shift. Clamped to image edges downstream.
FINGER_CROP_HALF = int(os.environ.get("READING_FINGER_CROP_HALF") or "640")


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


def finger_crop_bytes(
    image_bgr: Any,
    origin: tuple[float, float],
    *,
    half: int = FINGER_CROP_HALF,
) -> tuple[bytes, tuple[int, int], tuple[int, int]] | None:
    """Crop a generous square around the fingertip, covering every OCR window.

    Returns (jpg_bytes, (x1, y1) crop origin in full-image coords,
    (w, h) full-image shape) or None. The crop is clamped to image edges; the
    caller uses (x1, y1) to translate full-image finger coords into the crop's
    own coordinate space, so ocr_at_finger/rank_pointed receive a self-
    consistent (small) image + finger pair with no per-step translation.
    """
    try:
        import cv2
    except Exception:
        return None
    try:
        h, w = image_bgr.shape[:2]
    except Exception:
        return None
    cx, cy = origin
    x1 = max(0, int(round(cx - half)))
    y1 = max(0, int(round(cy - half)))
    x2 = min(w, int(round(cx + half)))
    y2 = min(h, int(round(cy + half)))
    if x2 - x1 < 48 or y2 - y1 < 48:
        return None
    try:
        crop = image_bgr[y1:y2, x1:x2]
        ok, buf = cv2.imencode(".jpg", crop, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    except Exception:
        return None
    if not ok:
        return None
    return buf.tobytes(), (x1, y1), (w, h)


def _confirm_char_from_ocr(result: dict[str, Any]) -> str | None:
    chars = explode_blocks(blocks_from_ocr(result))
    cjk = [c for c in chars if has_cjk(str(c.get("text") or ""))]
    if len(cjk) == 1:
        return str(cjk[0].get("text") or "") or None
    return None


def _has_cjk_blocks(result: dict[str, Any]) -> bool:
    for b in blocks_from_ocr(result):
        if has_cjk(str(b.get("text") or "")):
            return True
    return False


def _ocr_fn(ocr: Callable[..., dict[str, Any]] | None):
    """Select the main OCR backend for line-level spotting (finding text).

    Standard: **找字用 VLM，认字用 Paddle**.
    - Main OCR (ocr_at_finger): VLM — crops may contain illustrations/noise,
      VLM's line-level spotting is needed to find text lines.
    - Confirm crop (rank_pointed): PaddleOCR — single-character recognition
      from a tight crop, Paddle is fast and sufficient.
    Override with READING_OCR_BACKEND=paddle to use Paddle for everything.
    """
    if ocr is not None:
        return ocr, (OcrClientError, HunyuanOcrError)
    backend = os.environ.get("READING_OCR_BACKEND", "hunyuan").strip().lower()
    if backend == "paddle":
        return ocr_recognize, (OcrClientError, HunyuanOcrError)
    return hunyuan_recognize, (OcrClientError, HunyuanOcrError)


def _decode_image(image_bytes: bytes, decode: Callable[[bytes], Any] | None):
    from hands import HandsError, decode_bgr

    decode_fn = decode or decode_bgr
    try:
        return decode_fn(image_bytes)
    except HandsError as e:
        raise PipelineError("failed", str(e)) from e


def parse_finger(raw: Any) -> tuple[tuple[float, float], tuple[float, float]]:
    if not isinstance(raw, dict):
        raise PipelineError("failed", "缺少 finger")
    tip = raw.get("tip") or raw.get("origin")
    direction = raw.get("direction")
    try:
        origin = (float(tip[0]), float(tip[1]))
        direc = (float(direction[0]), float(direction[1]))
    except (TypeError, ValueError, IndexError, KeyError) as e:
        raise PipelineError("failed", "finger.tip / finger.direction 无效") from e
    n = math.hypot(direc[0], direc[1])
    if n < 1e-6:
        raise PipelineError("no_hand", "手指方向不稳定。请让手指伸直、指尖对着目标字。")
    return origin, (direc[0] / n, direc[1] / n)


def finger_payload(origin: tuple[float, float], direction: tuple[float, float]) -> dict[str, Any]:
    return {
        "tip": [round(origin[0], 1), round(origin[1], 1)],
        "direction": [round(direction[0], 4), round(direction[1], 4)],
    }


def _as_hands(raw: Any) -> list[dict[int, tuple[float, float]]]:
    if raw is None:
        return []
    if isinstance(raw, dict):
        return [raw]
    if isinstance(raw, list):
        return [h for h in raw if isinstance(h, dict)]
    return []


def detect_finger(
    image_bytes: bytes,
    *,
    detect_hand: Callable[[Any], Any] | None = None,
    decode: Callable[[bytes], Any] | None = None,
    return_crop: bool = False,
) -> dict[str, Any]:
    from hands import detect_hands_landmarks

    detect_fn = detect_hand or detect_hands_landmarks
    t0 = time.perf_counter()
    image = _decode_image(image_bytes, decode)
    hands = _as_hands(detect_fn(image))
    pointing: list[dict[str, Any]] = []
    landmark_dump: dict[str, list[float]] = {}
    for hand_lm in hands:
        found = pointing_fingers(hand_lm)
        pointing.extend(found)
        if not landmark_dump:
            landmark_dump = {
                str(k): [round(v[0], 2), round(v[1], 2)] for k, v in hand_lm.items()
            }
    used_skin_fallback = False
    if not pointing and detect_hand is None:
        # MediaPipe (palm-first) misses when the palm is out of frame — only a
        # fingertip is visible. Fall back to skin segmentation, which works on
        # non-skin-colored backgrounds (white paper, dark surface). Wooden desk
        # is a known bad case (see eval/ALGORITHM_CHANGELOG.md intent 253).
        try:
            from skin_detect import detect_hands_landmarks as skin_detect
            skin_hands = _as_hands(skin_detect(image))
            for hand_lm in skin_hands:
                found = pointing_fingers(hand_lm)
                pointing.extend(found)
                if not landmark_dump:
                    landmark_dump = {
                        str(k): [round(v[0], 2), round(v[1], 2)] for k, v in hand_lm.items()
                    }
            used_skin_fallback = bool(pointing)
        except Exception:
            pass
    elapsed = round(time.perf_counter() - t0, 4)
    if not pointing:
        raise PipelineError(
            "no_hand",
            "图里没有检测到伸出的手指。请把手指指在书页或白纸上（不要指在桌面），"
            "让手指大部分进入画面，指尖对着那个字。",
        )
    if len(pointing) > 1:
        names = "、".join(str(p.get("name") or "") for p in pointing if p.get("name"))
        extra = f"（{names}）" if names else ""
        raise PipelineError("ambiguous_finger", AMBIGUOUS_FINGER_MSG + extra)
    chosen = pointing[0]
    origin, direction = chosen["origin"], chosen["direction"]
    payload = finger_payload(origin, direction)
    digit = str(chosen.get("name") or "").strip()
    if digit:
        payload["digit"] = digit
    out: dict[str, Any] = {
        "status": "ok",
        "finger": payload,
        "landmarks": landmark_dump,
        "timing": {"hand_detection_s": elapsed, "skin_fallback": used_skin_fallback},
    }
    if return_crop:
        import base64

        crop = finger_crop_bytes(image, origin)
        if crop is not None:
            crop_bytes, (cx1, cy1), (fw, fh) = crop
            out["finger_crop_b64"] = base64.b64encode(crop_bytes).decode("ascii")
            out["crop_origin"] = [int(cx1), int(cy1)]
            out["full_image_shape"] = [int(fw), int(fh)]
    return out


def ocr_at_finger(
    image_bytes: bytes,
    finger: Any,
    *,
    language: str = "zh",
    ocr: Callable[..., dict[str, Any]] | None = None,
    decode: Callable[[bytes], Any] | None = None,
) -> dict[str, Any]:
    origin, direction = parse_finger(finger)
    ocr_fn, ocr_errors = _ocr_fn(ocr)
    image = _decode_image(image_bytes, decode)
    parts: list[dict[str, Any]] = []
    last_error: Exception | None = None
    ocr_elapsed = 0.0
    t0 = time.perf_counter()
    try:
        for spec in OCR_WINDOWS:
            osize, oshift = (spec if isinstance(spec, tuple) else (spec, 0))
            window = finger_ocr_window(image, origin, direction, osize, shift=oshift)
            if not window:
                continue
            ocr_bytes, origin_xy, scale = window
            got_cjk = False
            for _pass in range(2):
                t_call = time.perf_counter()
                try:
                    part = ocr_fn(ocr_bytes, language=language)
                except ocr_errors as e:
                    last_error = e
                    ocr_elapsed += time.perf_counter() - t_call
                    continue
                ocr_elapsed += time.perf_counter() - t_call
                parts.append(shift_ocr_blocks(part, origin_xy[0], origin_xy[1], scale))
                if _has_cjk_blocks(part):
                    got_cjk = True
                    break
            if got_cjk:
                break
        if not parts:
            from hands import encode_jpeg

            encoded = encode_jpeg(image)
            ocr_bytes = encoded or image_bytes
            t_call = time.perf_counter()
            try:
                ocr_result = ocr_fn(ocr_bytes, language=language)
            except ocr_errors as e:
                ocr_elapsed += time.perf_counter() - t_call
                raise last_error or e
            ocr_elapsed += time.perf_counter() - t_call
        else:
            ocr_result = merge_ocr_results(parts)
    except ocr_errors as e:
        raise PipelineError("failed", str(e)) from e
    blocks = blocks_from_ocr(ocr_result)
    chars = explode_blocks(blocks)
    if not chars:
        raise PipelineError("no_text", "没有识别到文字。请俯拍、书页占画面主体、光线足够。")
    return {
        "status": "ok",
        "chars": chars,
        "blocks": [{"text": b.get("text"), "bbox": b.get("bbox")} for b in blocks],
        "ocr_blocks": len(blocks),
        "char_boxes": len(chars),
        "timing": {"ocr_vlm_s": round(ocr_elapsed or (time.perf_counter() - t0), 4)},
    }


def rank_pointed(
    image_bytes: bytes,
    finger: Any,
    chars: Any,
    *,
    language: str = "zh",
    ocr: Callable[..., dict[str, Any]] | None = None,
    decode: Callable[[bytes], Any] | None = None,
    return_debug: bool = False,
    full_image_shape: tuple[int, int] | list[int] | None = None,
) -> dict[str, Any]:
    origin, direction = parse_finger(finger)
    if not isinstance(chars, list) or not chars:
        raise PipelineError("no_text", "没有识别到文字。请俯拍、书页占画面主体、光线足够。")
    ocr_fn, ocr_errors = _ocr_fn(ocr)
    image = _decode_image(image_bytes, decode)
    h, w = image.shape[:2]
    # When the runtime passes a finger crop (not the full image), the crop's
    # own shape is smaller than the source photo. max_dist is calibrated as a
    # fraction of the *source* image diagonal, so prefer full_image_shape and
    # fall back to the (possibly cropped) image shape for standalone callers.
    if full_image_shape:
        try:
            fw, fh = int(full_image_shape[0]), int(full_image_shape[1])
        except (TypeError, IndexError, ValueError):
            fw, fh = w, h
    else:
        fw, fh = w, h
    max_angle = _env_float("READING_MAX_ANGLE_DEG", DEFAULT_MAX_ANGLE)
    min_score = _env_float("READING_MIN_SCORE", DEFAULT_MIN_SCORE)
    min_margin = _env_float("READING_MIN_MARGIN", DEFAULT_MIN_MARGIN)
    max_dist = _env_float("READING_MAX_DIST_FRAC", DEFAULT_MAX_DIST_FRAC) * math.hypot(fw, fh)
    t0 = time.perf_counter()
    ranked = rank_characters(
        chars,
        origin,
        direction,
        max_angle_deg=max_angle,
        max_distance=max_dist,
    )
    ocr_elapsed = 0.0
    if ranked:
        top0 = ranked[0]
        try:
            crop = crop_bbox(image, top0["bbox"], pad_frac=0.5)
            t_call = time.perf_counter()
            # Use PaddleOCR for the confirm crop — it is a small single-character
            # region where Paddle is fast (<1s) and sufficient.  The VLM is only
            # needed for the main OCR pass where full-line spotting matters.
            try:
                second = ocr_recognize(crop, language=language)
            except OcrClientError:
                second = ocr_fn(crop, language=language)
            ocr_elapsed += time.perf_counter() - t_call
            got = _confirm_char_from_ocr(second)
            if got and got != str(top0.get("text") or "") and has_cjk(got):
                ranked.append(
                    {
                        "text": got,
                        "bbox": top0["bbox"],
                        "score": float(top0["score"]) - 0.001,
                        "split": False,
                        "mode": "confirm",
                    }
                )
        except (ocr_errors, PipelineError):
            pass
    verdict = decide(ranked, min_score=min_score, min_margin=min_margin)
    geom_s = round(time.perf_counter() - t0, 4)
    debug_candidates = [
        {
            "text": r["text"],
            "bbox": r["bbox"],
            "score": round(float(r["score"]), 4),
            "split": bool(r.get("split")),
        }
        for r in ranked[:8]
    ]
    top3 = sorted(
        [{"text": r["text"], "bbox": r["bbox"], "score": round(float(r["score"]), 4)} for r in ranked],
        key=lambda r: r["score"],
        reverse=True,
    )[:3]
    payload: dict[str, Any] = {
        "engine": "reading.rank_pointed",
        "status": verdict["status"],
        "finger": finger_payload(origin, direction),
        "candidates": debug_candidates,
        "top3": top3,
        "timing": {"geometry_ranking_s": geom_s, "ocr_vlm_s": round(ocr_elapsed, 4)},
    }
    if verdict["status"] not in ("ok", "ok_with_alternatives"):
        payload["reason"] = verdict.get("reason")
        payload["character"] = None
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
    payload["character"] = str(top["text"])
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


def run_still(
    image_bytes: bytes,
    *,
    language: str = "zh",
    return_debug: bool = False,
    detect_hand: Callable[[Any], dict[int, tuple[float, float]] | None] | None = None,
    ocr: Callable[..., dict[str, Any]] | None = None,
    decode: Callable[[bytes], Any] | None = None,
    progress: Callable[[str, dict], None] | None = None,
) -> dict[str, Any]:
    t_total_start = time.perf_counter()
    hand = detect_finger(image_bytes, detect_hand=detect_hand, decode=decode)
    if progress:
        progress("detect_finger", {"status": hand.get("status"), "timing": hand.get("timing")})
    ocr_out = ocr_at_finger(
        image_bytes, hand["finger"], language=language, ocr=ocr, decode=decode
    )
    if progress:
        progress("ocr_at_finger", {"n_chars": len(ocr_out.get("chars") or []), "timing": ocr_out.get("timing")})
    ranked = rank_pointed(
        image_bytes,
        hand["finger"],
        ocr_out["chars"],
        language=language,
        ocr=ocr,
        decode=decode,
        return_debug=return_debug,
    )
    if progress:
        progress("rank_pointed", {"status": ranked.get("status"), "character": ranked.get("character"), "timing": ranked.get("timing")})
    timing = {
        "hand_detection_s": (hand.get("timing") or {}).get("hand_detection_s", 0.0),
        "ocr_vlm_s": round(
            float((ocr_out.get("timing") or {}).get("ocr_vlm_s") or 0)
            + float((ranked.get("timing") or {}).get("ocr_vlm_s") or 0),
            4,
        ),
        "geometry_ranking_s": (ranked.get("timing") or {}).get("geometry_ranking_s", 0.0),
        "total_s": round(time.perf_counter() - t_total_start, 4),
    }
    payload = dict(ranked)
    payload["engine"] = "reading.point_to_character"
    payload["ocr_blocks"] = ocr_out.get("ocr_blocks")
    payload["char_boxes"] = ocr_out.get("char_boxes")
    payload["timing"] = timing
    if return_debug:
        payload["replay"] = {
            "landmarks": hand.get("landmarks") or {},
            "origin": (hand.get("finger") or {}).get("tip"),
            "direction": (hand.get("finger") or {}).get("direction"),
            "blocks": ocr_out.get("blocks") or [],
            "chars": ocr_out.get("chars") or [],
            "ranked": ranked.get("candidates") or [],
            "verdict": {
                "status": ranked.get("status"),
                "reason": ranked.get("reason"),
            },
        }
    return payload
