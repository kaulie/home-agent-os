#!/usr/bin/env python3
"""End-to-end regression: load photos → run full point_to_character pipeline → report.

Unlike _full_photo_replay.py (geometry-only replay on cached OCR dumps), this
script loads the actual photo files and runs the complete pipeline:
  detect_finger → ocr_at_finger (VLM) → rank_pointed (PaddleOCR confirm) → decide

Usage:
    cd character-service
    /path/to/venv/bin/python3.11 eval/full_pipeline_regression.py
    /path/to/venv/bin/python3.11 eval/full_pipeline_regression.py --quick   # skip slow cases
    /path/to/venv/bin/python3.11 eval/full_pipeline_regression.py --verbose  # full per-case detail

Exit code: 0 if no regressions, 1 if any top1 regression.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REPO = ROOT.parent
SAMPLES = ROOT / "samples"
IMG_SERVER = REPO / "img-server" / "img"
_TEST = REPO / "local-rt" / "test-imgs"

# ── Test cases ────────────────────────────────────────────────────────────
# Each case: (name, photo_path, expected_chars, notes)
# expected_chars: set of acceptable top1 answers.  Empty set = expect non-ok
# status (no_hand / ambiguous_finger / no_text).

CASES: list[tuple[str, Path, set[str], str]] = [
    # ── Q4 production baseline (6 photos) ──
    # Use full-res images from local-rt/test-imgs/ — MediaPipe detects different
    # hands at different resolutions, so the Q4 baseline (created on full-res)
    # only reproduces on full-res.  The _1600 samples are for geometry-only replay.
    ("IMG_7832", _TEST / "IMG_7832.jpg", {"渊"}, "Q4 生产基线"),
    ("IMG_8022", _TEST / "IMG_8022.jpg", {"因"}, "Q4 生产基线（Q8 still_fail）"),
    ("IMG_8023", _TEST / "IMG_8023.jpg", {"娘", "姑"}, "Q4 生产基线"),
    ("IMG_8024", _TEST / "IMG_8024.jpg", {"霸"}, "Q4 生产基线"),
    ("IMG_8025", _TEST / "IMG_8025.jpg", {"剧", "本"}, "Q4 生产基线"),
    ("IMG_8026", _TEST / "IMG_8026.jpg", {"碾"}, "Q4 生产基线"),

    # ── Intent cases (real user photos from img-server) ──
    ("intent201", IMG_SERVER / "3f089bec_upload_1787701987925.jpg", {"崭"}, "扫描件 contact 模式"),
    ("intent259", IMG_SERVER / "7c8c131f_cap_23f52099d577f3915fe2a1ec.jpg", {"弗"}, "Android 绘本 skin fallback"),
    ("intent277", IMG_SERVER / "57bb7cd2_photo_1787795714933.jpg", {"野"}, "Android 绘本 插图肤色干扰"),
    ("intent278", IMG_SERVER / "ad225ed3_photo_1787797386939.jpg", {"雕"}, "Android 绘本"),

    # ── Known bad cases (expect non-ok) ──
    ("intent253", IMG_SERVER / "4f83b365_photo_1787757124.jpg", set(), "木桌面 no_hand（已知限制）"),
    ("intent239", IMG_SERVER / "49ce8930_photo_1787751581950.jpg", set(), "五指全伸 ambiguous_finger"),
]

# Cases that are historically slow (>60s) — skipped in --quick mode.
SLOW_CASES = {"IMG_8022", "intent259", "intent277"}


def run_case(name: str, photo_path: Path, expected: set[str]) -> dict:
    """Run the full pipeline on one photo. Returns a result dict."""
    import pipeline  # noqa: E402

    if not photo_path.exists():
        return {
            "name": name,
            "status": "ERROR",
            "character": "",
            "expected": "/".join(sorted(expected)) if expected else "(non-ok)",
            "pass_top1": False,
            "pass_top3": False,
            "error": f"photo not found: {photo_path}",
            "timing": {},
        }

    image_bytes = photo_path.read_bytes()
    t0 = time.perf_counter()

    def _progress(stage: str, info: dict) -> None:
        elapsed = time.perf_counter() - t0
        if stage == "detect_finger":
            st = info.get("status", "?")
            print(f"\r  [{name}] detect_finger → {st} ({elapsed:.1f}s)", end="", flush=True)
        elif stage == "ocr_at_finger":
            n = info.get("n_chars", 0)
            print(f"\r  [{name}] ocr_at_finger → {n} chars ({elapsed:.1f}s)", end="", flush=True)
        elif stage == "rank_pointed":
            ch = info.get("character") or info.get("status", "?")
            print(f"\r  [{name}] rank_pointed → {ch} ({elapsed:.1f}s)", end="", flush=True)

    try:
        result = pipeline.run_still(image_bytes, language="zh", return_debug=False, progress=_progress)
    except Exception as e:
        elapsed = time.perf_counter() - t0
        status = getattr(e, "status", "failed")
        return {
            "name": name,
            "status": status,
            "character": "",
            "expected": "/".join(sorted(expected)) if expected else "(non-ok)",
            "pass_top1": _check_pass(status, "", expected),
            "pass_top3": False,
            "error": str(e),
            "timing": {"total_s": round(elapsed, 1)},
        }

    elapsed = time.perf_counter() - t0
    status = result.get("status", "")
    character = str(result.get("character") or "")
    top3_texts = [t.get("text", "") for t in (result.get("top3") or [])]
    timing = result.get("timing", {})

    pass_top1 = _check_pass(status, character, expected)
    pass_top3 = any(t in expected for t in top3_texts) if expected else (status != "ok")

    return {
        "name": name,
        "status": status,
        "character": character,
        "expected": "/".join(sorted(expected)) if expected else "(non-ok)",
        "pass_top1": pass_top1,
        "pass_top3": pass_top3,
        "top3": " ".join(top3_texts),
        "score": result.get("score"),
        "timing": timing,
        "wall_s": round(elapsed, 1),
        "finger": result.get("finger"),
        "error": None,
    }


def _check_pass(status: str, character: str, expected: set[str]) -> bool:
    """Check if the result matches expectations."""
    if not expected:
        # Empty expected set → pipeline should NOT return ok
        return status not in ("ok", "ok_with_alternatives")
    return status in ("ok", "ok_with_alternatives") and character in expected


def main() -> None:
    parser = argparse.ArgumentParser(description="Full pipeline regression test")
    parser.add_argument("--quick", action="store_true", help="skip slow cases")
    parser.add_argument("--verbose", action="store_true", help="full per-case detail")
    parser.add_argument("--rounds", type=int, default=1, help="number of rounds per case (default: 1)")
    args = parser.parse_args()

    cases = CASES
    if args.quick:
        cases = [c for c in cases if c[0] not in SLOW_CASES]

    rounds = max(1, args.rounds)
    print(f"=== Full Pipeline Regression ({len(cases)} cases × {rounds} round{'s' if rounds > 1 else ''}) ===")
    print()

    # results: {case_name: [round_results...]}
    all_results: dict[str, list[dict]] = {}
    for name, photo_path, expected, notes in cases:
        all_results[name] = []
        for rnd in range(rounds):
            label = f"{name} r{rnd+1}" if rounds > 1 else name
            print(f"  [{sum(len(v) for v in all_results.values())+1}/{len(cases)*rounds}] {label} ... ", end="", flush=True)
            r = run_case(name, photo_path, expected)
            all_results[name].append(r)
            ok = "PASS" if r["pass_top1"] else "FAIL"
            wall = r.get("wall_s", r.get("timing", {}).get("total_s", "?"))
            print(f"\r  [{sum(len(v) for v in all_results.values())}/{len(cases)*rounds}] {label} ... {ok}  {r['character'] or r['status']}  ({wall}s){' '*20}")

    # Flatten for single-round compatibility; aggregate for multi-round
    results = []
    for name in all_results:
        results.extend(all_results[name])

    # ── Summary table ──
    print()
    print("=== RESULTS ===")
    if rounds == 1:
        print(f"{'name':<16} {'expected':<10} {'got':<10} {'status':<24} {'top1':<6} {'top3':<6} {'time':>6}")
        print("-" * 80)
        for r in results:
            wall = r.get("wall_s", r.get("timing", {}).get("total_s", "?"))
            print(
                f"{r['name']:<16} {r['expected']:<10} {r['character'] or '-':<10} "
                f"{r['status']:<24} {'PASS' if r['pass_top1'] else 'FAIL':<6} "
                f"{'PASS' if r['pass_top3'] else 'FAIL':<6} {wall:>5}s"
            )
    else:
        print(f"{'name':<16} {'expected':<10} {'top1':>8} {'top3':>8} {'avg':>6} {'min':>6} {'max':>6} {'last_got':<10}")
        print("-" * 80)
        for name, round_results in all_results.items():
            n_pass1 = sum(r["pass_top1"] for r in round_results)
            n_pass3 = sum(r["pass_top3"] for r in round_results)
            walls = [r.get("wall_s", 0) for r in round_results]
            avg_w = sum(walls) / len(walls) if walls else 0
            min_w = min(walls) if walls else 0
            max_w = max(walls) if walls else 0
            last = round_results[-1]
            print(
                f"{name:<16} {last['expected']:<10} "
                f"{n_pass1}/{rounds:>3}  {n_pass3}/{rounds:>3}  "
                f"{avg_w:>5.1f}s {min_w:>5.1f}s {max_w:>5.1f}s "
                f"{last['character'] or last['status']:<10}"
            )

    # ── Totals ──
    n = len(results)
    n_pass1 = sum(r["pass_top1"] for r in results)
    n_pass3 = sum(r["pass_top3"] for r in results)
    n_errors = sum(1 for r in results if r["status"] == "ERROR")
    n_fail = n - n_pass1 - n_errors

    print()
    print("=== TOTALS ===")
    print(f"  rounds: {rounds}")
    print(f"  total runs: {n}")
    print(f"  top1: {n_pass1}/{n}")
    print(f"  top3: {n_pass3}/{n}")
    if n_errors:
        print(f"  errors: {n_errors}")
    print(f"  fails:  {n_fail}")

    # ── Timing breakdown ──
    print()
    print("=== TIMING ===")
    if rounds == 1:
        print(f"{'name':<16} {'hand':>6} {'ocr':>6} {'geom':>6} {'total':>6}")
        print("-" * 44)
        for r in results:
            t = r.get("timing", {})
            hand = t.get("hand_detection_s", 0)
            ocr = t.get("ocr_vlm_s", 0)
            geom = t.get("geometry_ranking_s", 0)
            total = t.get("total_s", r.get("wall_s", 0))
            print(f"{r['name']:<16} {hand:>5.1f}s {ocr:>5.1f}s {geom:>5.1f}s {total:>5.1f}s")
    else:
        print(f"{'name':<16} {'avg_total':>10} {'avg_ocr':>10} {'avg_hand':>10}")
        print("-" * 48)
        for name, round_results in all_results.items():
            walls = [r.get("wall_s", 0) for r in round_results]
            ocrs = [r.get("timing", {}).get("ocr_vlm_s", 0) for r in round_results]
            hands = [r.get("timing", {}).get("hand_detection_s", 0) for r in round_results]
            print(
                f"{name:<16} "
                f"{sum(walls)/len(walls):>9.1f}s "
                f"{sum(ocrs)/len(ocrs):>9.1f}s "
                f"{sum(hands)/len(hands):>9.1f}s"
            )

    # ── Failures detail ──
    fails = [r for r in results if not r["pass_top1"] and r["status"] != "ERROR"]
    if fails:
        print()
        print("=== FAILURES ===")
        for r in fails:
            print(f"  {r['name']}: expected={r['expected']} got={r['character'] or r['status']}")
            if r.get("top3"):
                print(f"    top3: [{r['top3']}]")
            if r.get("finger"):
                print(f"    finger: {json.dumps(r['finger'], ensure_ascii=False)}")
            if r.get("error"):
                print(f"    error: {r['error']}")

    # ── Errors ──
    errors = [r for r in results if r["status"] == "ERROR"]
    if errors:
        print()
        print("=== ERRORS ===")
        for r in errors:
            print(f"  {r['name']}: {r.get('error', 'unknown')}")

    # ── Verbose detail ──
    if args.verbose:
        print()
        print("=== VERBOSE DETAIL ===")
        for r in results:
            print(f"--- {r['name']} ---")
            print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
            print()

    # ── Exit code ──
    n_regressions = n_fail
    if n_regressions > 0:
        print(f"\n*** {n_regressions} REGRESSION(S) ***")
        sys.exit(1)
    print(f"\n*** ALL PASS ({n_pass1}/{n}) ***")


if __name__ == "__main__":
    main()
