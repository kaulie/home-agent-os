"""End-to-end regression for the crop-passing optimization.

Compares two ways to run reading.point_to_character on the same photo:

  A. Standalone  : POST /v1/point_to_character (run_still) — detect→ocr→rank
                   all in one process on the FULL image. Baseline.
  B. Composite   : the new atom-by-atom flow the mac-edge executor now uses:
                   1. detect_finger(return_crop=True) → finger (full-image),
                      finger_crop_b64, crop_origin, full_image_shape
                   2. translate finger into crop space (finger - crop_origin)
                   3. ocr_at_finger(crop_image, crop_relative_finger) → chars
                   4. rank_pointed(crop_image, crop_relative_finger, chars,
                      full_image_shape) → character

Both must return the SAME character (the crop covers the same OCR windows).
Reports per-stage timing so we can see the fetch/transfer savings in practice.
"""

from __future__ import annotations

import base64
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:9189"
PHOTOS = [
    "character-service/samples/IMG_8022.jpg",
    "character-service/samples/IMG_8023.jpg",
    "character-service/samples/IMG_8024.jpg",
    "character-service/samples/IMG_8025.jpg",
]


def post(path: str, body: dict) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}{path}", data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read().decode("utf-8"))


def read_b64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def standalone(img_b64: str) -> tuple[str, float]:
    t0 = time.perf_counter()
    r = post("/v1/point_to_character", {"image_base64": img_b64})
    return str(r.get("character") or ""), time.perf_counter() - t0


def composite(img_b64: str) -> tuple[str, float, dict]:
    t0 = time.perf_counter()
    # 1. detect with crop
    d = post("/v1/detect_finger", {"image_base64": img_b64, "return_crop": True})
    if d.get("status") != "ok" or "finger_crop_b64" not in d:
        return f"<detect:{d.get('status')}>", time.perf_counter() - t0, {}
    finger = d["finger"]
    crop_origin = d["crop_origin"]
    full_shape = d["full_image_shape"]
    crop_b64 = d["finger_crop_b64"]
    # 2. translate finger into crop space
    rel_finger = {
        "tip": [finger["tip"][0] - crop_origin[0], finger["tip"][1] - crop_origin[1]],
        "direction": finger["direction"],
    }
    if "digit" in finger:
        rel_finger["digit"] = finger["digit"]
    # 3. ocr on the crop
    o = post(
        "/v1/ocr_at_finger",
        {"image_base64": crop_b64, "finger": rel_finger},
    )
    chars = o.get("chars") or []
    if not chars:
        return f"<ocr:{o.get('status')}>", time.perf_counter() - t0, {}
    # 4. rank on the crop
    r = post(
        "/v1/rank_pointed",
        {
            "image_base64": crop_b64,
            "finger": rel_finger,
            "chars": chars,
            "full_image_shape": full_shape,
        },
    )
    return str(r.get("character") or ""), time.perf_counter() - t0, {
        "detect": d.get("timing", {}),
        "ocr": o.get("timing", {}),
        "rank": r.get("timing", {}),
        "crop_kb": round(len(crop_b64) * 3 / 4 / 1024, 1),
        "full_kb": round(len(img_b64) * 3 / 4 / 1024, 1),
    }


def main() -> int:
    fails = 0
    for p in PHOTOS:
        try:
            img = read_b64(p)
        except FileNotFoundError:
            print(f"skip {p} (missing)")
            continue
        ca, ta = standalone(img)
        cb, tb, meta = composite(img)
        same = (ca or "") == (cb or "")
        marker = "OK " if same else "DIFF"
        if not same:
            fails += 1
        print(
            f"{marker} {p.split('/')[-1]}: standalone={ca!r} ({ta:.2f}s) | "
            f"composite={cb!r} ({tb:.2f}s) | crop={meta.get('crop_kb','?')}KB "
            f"vs full={meta.get('full_kb','?')}KB"
        )
        if meta:
            dt = meta.get("detect", {})
            ot = meta.get("ocr", {})
            print(
                f"     timing: detect_hand={dt.get('hand_detection_s','?')}s "
                f"ocr_vlm={ot.get('ocr_vlm_s','?')}s"
            )
    print(f"\n{'PASS' if fails == 0 else f'{fails} DIFF'} — crop-passing parity vs standalone")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
