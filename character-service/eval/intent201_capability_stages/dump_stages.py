#!/usr/bin/env python3
"""Dump reading.point_to_character stages for intent 201. Does not change the algorithm."""

from __future__ import annotations

import base64
import json
import math
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # character-service/
sys.path.insert(0, str(ROOT))

from geometry import (  # noqa: E402
    INDEX_DIP,
    INDEX_MCP,
    INDEX_PIP,
    INDEX_TIP,
    bbox_center,
    bbox_wh,
    decide,
    explode_blocks,
    finger_ray,
    has_cjk,
    lateral_score,
    rank_characters,
    score_character,
)
from hands import decode_bgr, jpeg_exif_orientation  # noqa: E402
from ocr_client import blocks_from_ocr  # noqa: E402
from pipeline import OCR_WINDOWS, crop_bbox, finger_ocr_window  # noqa: E402

IMG = Path(
    "/Users/gaolei/Projects/smart_home_control/img-server/img/3f089bec_upload_1787701987925.jpg"
)
OUT = Path(__file__).resolve().parent
ASSET_ID = "asset_e080b636a5e20a0d4786e710"
CHARACTER_URL = "http://127.0.0.1:9189/v1/point_to_character"
FOCUS = ("崭", "的", "力", "新", "倾", "协")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    data = IMG.read_bytes()
    orient = jpeg_exif_orientation(data)
    t0 = time.perf_counter()
    image = decode_bgr(data)
    decode_s = time.perf_counter() - t0
    h, w = image.shape[:2]
    ingest = {
        "asset_id": ASSET_ID,
        "image_path": str(IMG),
        "bytes": len(data),
        "exif_orientation": orient,
        "decoded_wh": [int(w), int(h)],
        "decoded_hw": [int(h), int(w)],
        "decode_s": round(decode_s, 4),
        "upright": bool(h > w),
    }
    (OUT / "01_ingest.json").write_text(
        json.dumps(ingest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    import cv2

    cv2.imwrite(str(OUT / "01_decoded.jpg"), image, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    print("ingest", ingest)

    print("POST", CHARACTER_URL, "return_debug=true …")
    body = json.dumps(
        {"image_base64": base64.b64encode(data).decode("ascii"), "return_debug": True}
    ).encode("utf-8")
    req = urllib.request.Request(
        CHARACTER_URL, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    t_post = time.perf_counter()
    with urllib.request.urlopen(req, timeout=180) as resp:
        raw = resp.read()
    post_s = time.perf_counter() - t_post
    result = json.loads(raw.decode("utf-8"))
    print("POST done in", round(post_s, 2), "s status", result.get("status"), "char", result.get("character"))

    png_b64 = result.pop("debug_png_base64", None)
    if png_b64:
        (OUT / "06_overlay.png").write_bytes(base64.b64decode(png_b64))
    (OUT / "00_live_replay.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    replay = result.get("replay") or {}
    lm_raw = replay.get("landmarks") or {}
    landmarks = {int(k): (float(v[0]), float(v[1])) for k, v in lm_raw.items()}
    origin = tuple(replay.get("origin") or result.get("finger", {}).get("tip") or (0, 0))
    direction = tuple(replay.get("direction") or result.get("finger", {}).get("direction") or (0, 0))
    ray = finger_ray(landmarks) if landmarks else None

    hand = {
        "landmarks_px": {str(k): [round(v[0], 2), round(v[1], 2)] for k, v in landmarks.items()},
        "named": {
            "MCP_5": landmarks.get(INDEX_MCP),
            "PIP_6": landmarks.get(INDEX_PIP),
            "DIP_7": landmarks.get(INDEX_DIP),
            "TIP_8": landmarks.get(INDEX_TIP),
        },
        "origin_tip": [round(origin[0], 2), round(origin[1], 2)],
        "direction": [round(direction[0], 6), round(direction[1], 6)],
        "finger_ray_recomputed": None
        if ray is None
        else {
            "origin": [round(ray[0][0], 2), round(ray[0][1], 2)],
            "direction": [round(ray[1][0], 6), round(ray[1][1], 6)],
        },
        "angle_from_horizontal_deg": round(
            math.degrees(math.atan2(abs(direction[1]), max(abs(direction[0]), 1e-9))), 2
        ),
        "max_distance": replay.get("max_distance"),
        "max_angle_deg": replay.get("max_angle_deg"),
        "live_finger": result.get("finger"),
        "post_s": round(post_s, 3),
        "live_timing": result.get("timing"),
    }
    (OUT / "02_hand.json").write_text(json.dumps(hand, ensure_ascii=False, indent=2, default=list), encoding="utf-8")

    windows = []
    for i, spec in enumerate(OCR_WINDOWS):
        osize, oshift = spec if isinstance(spec, tuple) else (spec, 0)
        win = finger_ocr_window(image, origin, direction, osize, shift=oshift)
        rec = {"index": i, "size": osize, "shift_along_ray": oshift, "ok": bool(win)}
        if win:
            ocr_bytes, origin_xy, scale = win
            rec["origin_xy"] = list(origin_xy)
            rec["scale"] = scale
            rec["jpeg_bytes"] = len(ocr_bytes)
            crop_path = OUT / f"03_ocr_window_{i}_size{osize}_shift{oshift}.jpg"
            crop_path.write_bytes(ocr_bytes)
            rec["path"] = str(crop_path)
            cx = origin[0] + direction[0] * oshift
            cy = origin[1] + direction[1] * oshift
            rec["center"] = [round(cx, 1), round(cy, 1)]
            rec["bbox_full"] = [
                origin_xy[0],
                origin_xy[1],
                origin_xy[0] + osize,
                origin_xy[1] + osize,
            ]
        windows.append(rec)
    (OUT / "03_ocr_windows.json").write_text(
        json.dumps(windows, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    blocks = replay.get("blocks") or []
    chars = replay.get("chars") or explode_blocks(blocks_from_ocr({"blocks": blocks}))
    ranked = replay.get("ranked") or []
    max_angle = float(replay.get("max_angle_deg") or 30)
    max_dist = float(replay.get("max_distance") or (0.55 * math.hypot(w, h)))

    focus_rows = []
    for ch in chars:
        text = str(ch.get("text") or "")
        if text not in FOCUS:
            continue
        bbox = ch.get("bbox")
        sc = score_character(
            origin=origin, direction=direction, bbox=bbox, max_angle_deg=max_angle, max_distance=max_dist
        )
        lat = lateral_score(
            origin=origin,
            direction=direction,
            bbox=bbox,
            max_angle_deg=max_angle,
            max_distance=max_dist,
            body_size=48.0,
        )
        cx, cy = bbox_center(bbox)
        ww, hh = bbox_wh(bbox)
        focus_rows.append(
            {
                "text": text,
                "bbox": bbox,
                "center": [round(cx, 1), round(cy, 1)],
                "wh": [round(ww, 1), round(hh, 1)],
                "split": ch.get("split"),
                "source_text": ch.get("source_text"),
                "ray_or_cone": sc,
                "lateral": lat,
            }
        )

    reranked = rank_characters(chars, origin, direction, max_angle_deg=max_angle, max_distance=max_dist)
    verdict = decide(reranked, min_score=float(replay.get("min_score") or 0.28), min_margin=float(replay.get("min_margin") or 0.06))

    ocr_stage = {
        "live_status": result.get("status"),
        "live_character": result.get("character"),
        "live_score": result.get("score"),
        "live_bbox": result.get("bbox"),
        "live_top3": result.get("top3"),
        "live_candidates": result.get("candidates"),
        "ocr_blocks": result.get("ocr_blocks"),
        "char_boxes": result.get("char_boxes"),
        "block_texts": [b.get("text") for b in blocks],
        "blocks": blocks,
        "n_chars": len(chars),
        "focus_chars": focus_rows,
        "ranked_top12": [
            {
                "text": r.get("text"),
                "bbox": r.get("bbox"),
                "score": r.get("score"),
                "mode": r.get("mode"),
                "split": r.get("split"),
            }
            for r in (ranked or reranked)[:12]
        ],
        "rerank_verdict_status": verdict.get("status"),
        "rerank_top": None
        if not verdict.get("top")
        else {"text": verdict["top"].get("text"), "score": verdict["top"].get("score"), "mode": verdict["top"].get("mode")},
        "confirm_in_ranked": [r for r in ranked if r.get("mode") == "confirm"],
    }
    (OUT / "04_ocr_and_rank.json").write_text(
        json.dumps(ocr_stage, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if ranked:
        top0 = ranked[0]
        try:
            crop = crop_bbox(image, top0["bbox"], pad_frac=0.5)
            (OUT / "05_confirm_crop.png").write_bytes(crop)
        except Exception as e:
            print("confirm crop failed", e)

    final = {
        "asset_id": ASSET_ID,
        "image_path": str(IMG),
        "original_201": {
            "status": "ok",
            "character": "力",
            "answer_text": "手指指的是「力」。",
            "total_ms": 31682,
            "note": "Mac plugin 07:58:55; Hunyuan 5 calls; return_debug was false so original blocks were not persisted.",
        },
        "later_08_03_replay": {
            "status": "ok_with_alternatives",
            "character": "崭",
            "total_ms": 36847,
            "note": "Same image, same service, VLM non-deterministic; not intent 201.",
        },
        "this_replay": {
            "status": result.get("status"),
            "character": result.get("character"),
            "answer_text": (
                f"手指指的是「{result.get('character')}」。" if result.get("character") else result.get("reason")
            ),
            "score": result.get("score"),
            "bbox": result.get("bbox"),
            "top3": result.get("top3"),
            "timing": result.get("timing"),
            "post_s": round(post_s, 3),
        },
    }
    (OUT / "07_final.json").write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
