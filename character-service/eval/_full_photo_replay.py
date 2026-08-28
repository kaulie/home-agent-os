#!/usr/bin/env python3
"""Offline geometry replay of all saved point_to_character dumps. No Brain, no VLM."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from geometry import rank_characters  # noqa: E402

EVAL = ROOT / "eval"

# Any of these counts as the pointed character (documented GT / aliases).
EXPECTED: dict[str, set[str]] = {
    "IMG_7832": {"渊"},
    "IMG_8022": {"因"},
    "IMG_8023": {"娘", "姑"},
    "IMG_8024": {"霸"},
    "IMG_8025": {"剧", "本"},
    "IMG_8026": {"碾"},
    "IMG_8049": {"零", "七"},
    "IMG_8050": {"患", "之"},
    "IMG_8051": {"辎", "重"},
    "IMG_8052": {"柔"},
    "IMG_8053": {"统", "到", "一"},
    "IMG_8054": {"迭", "代"},
    "intent201": {"崭"},
}

# q4/q8/gen45 historical top1-pass at dump time (from scored/README).
# Used only to flag regression vs new-pass; not a second GT.
BASELINE_TOP1_FAIL: set[tuple[str, str]] = {
    # gen45: 8050 r1-r4 top1=的 (GT 患/之); r5 passed
    ("gen45", "IMG_8050_r1.json"),
    ("gen45", "IMG_8050_r2.json"),
    ("gen45", "IMG_8050_r3.json"),
    ("gen45", "IMG_8050_r4.json"),
    # q8: 8022 all 5 rounds top1=《
    ("q8", "IMG_8022_r1.json"),
    ("q8", "IMG_8022_r2.json"),
    ("q8", "IMG_8022_r3.json"),
    ("q8", "IMG_8022_r4.json"),
    ("q8", "IMG_8022_r5.json"),
}


def stem_to_img(name: str) -> str:
    stem = Path(name).stem
    if stem.startswith("IMG_"):
        return stem.split("_r")[0] if "_r" in stem else stem
    return stem


def expected_for(corpus: str, name: str) -> set[str] | None:
    if corpus == "intent201":
        return EXPECTED["intent201"]
    img = stem_to_img(name)
    if img.startswith("IMG_8022"):
        return EXPECTED["IMG_8022"]
    return EXPECTED.get(img)


def rank_dump(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    replay = data.get("replay") or {}
    chars = replay.get("chars")
    if not chars:
        return {"error": "no replay.chars"}
    origin = tuple(replay["origin"])
    direction = tuple(replay["direction"])
    ranked = rank_characters(
        chars,
        origin,
        direction,
        max_angle_deg=float(replay.get("max_angle_deg") or 30),
        max_distance=float(replay["max_distance"]),
    )
    old = replay.get("ranked") or data.get("candidates") or []
    old_top1 = (old[0].get("text") if old else "") or ""
    old_mode = (old[0].get("mode") if old else "") or ""
    new_top1 = (ranked[0].get("text") if ranked else "") or ""
    new_mode = (ranked[0].get("mode") if ranked else "") or ""
    top3 = [r.get("text") or "" for r in ranked[:3]]
    return {
        "new_top1": new_top1,
        "new_mode": new_mode,
        "top3": top3,
        "n_ranked": len(ranked),
        "old_top1": old_top1,
        "old_mode": old_mode,
        "score": round(float(ranked[0]["score"]), 4) if ranked else None,
    }


def main() -> None:
    jobs: list[tuple[str, Path]] = []
    for corpus, rel in (
        ("q4", "q4/replay"),
        ("q8", "q8/replay"),
        ("gen45", "gen45/replay"),
        ("local-8022", "local-8022"),
        ("intent201", "intent201_capability_stages"),
    ):
        folder = EVAL / rel
        if corpus == "local-8022":
            files = sorted(folder.glob("*.json"))
        elif corpus == "intent201":
            files = [folder / "00_live_replay.json"]
        else:
            files = sorted(folder.glob("*.json"))
        for f in files:
            if f.is_file():
                jobs.append((corpus, f))

    rows = []
    for corpus, path in jobs:
        name = path.name
        exp = expected_for(corpus, name)
        if exp is None:
            continue
        rec = rank_dump(path)
        if rec.get("error"):
            rows.append(
                {
                    "corpus": corpus,
                    "image": name,
                    "expected": "/".join(sorted(exp)),
                    "got": rec["error"],
                    "mode": "",
                    "pass_top1": False,
                    "pass_top3": False,
                    "flag": "ERROR",
                    "old_top1": "",
                    "top3": "",
                }
            )
            continue
        got = rec["new_top1"]
        pass1 = got in exp
        pass3 = any(t in exp for t in rec["top3"])
        key = (corpus, name)
        was_fail = key in BASELINE_TOP1_FAIL
        # Dump-time old_top1 for extra regression signal (same OCR boxes).
        old_ok = rec["old_top1"] in exp if rec["old_top1"] else None
        flag = ""
        if was_fail and pass1:
            flag = "NEW_PASS"
        elif (not was_fail) and (old_ok is True) and (not pass1):
            flag = "REGRESSION"
        elif was_fail and not pass1:
            flag = "still_fail"
        elif pass1 and rec["old_top1"] and rec["old_top1"] not in exp:
            flag = "NEW_PASS_vs_dump"
        rows.append(
            {
                "corpus": corpus,
                "image": name,
                "expected": "/".join(sorted(exp)),
                "got": got,
                "mode": rec["new_mode"],
                "pass_top1": pass1,
                "pass_top3": pass3,
                "flag": flag,
                "old_top1": rec["old_top1"],
                "old_mode": rec["old_mode"],
                "top3": " ".join(rec["top3"]),
                "score": rec["score"],
            }
        )

    # Print TSV table
    print("corpus\timage\texpected\tgot\tpass_top1\tpass_top3\tmode\told_top1\tflag\ttop3")
    for r in rows:
        print(
            f"{r['corpus']}\t{r['image']}\t{r['expected']}\t{r['got']}\t"
            f"{'PASS' if r['pass_top1'] else 'FAIL'}\t"
            f"{'PASS' if r['pass_top3'] else 'FAIL'}\t"
            f"{r['mode']}\t{r['old_top1']}\t{r['flag']}\t{r['top3']}"
        )

    print("\n=== TOTALS ===")
    from collections import defaultdict

    by = defaultdict(lambda: {"n": 0, "t1": 0, "t3": 0, "reg": 0, "new": 0})
    for r in rows:
        b = by[r["corpus"]]
        b["n"] += 1
        b["t1"] += int(r["pass_top1"])
        b["t3"] += int(r["pass_top3"])
        if r["flag"] == "REGRESSION":
            b["reg"] += 1
        if r["flag"] in ("NEW_PASS", "NEW_PASS_vs_dump"):
            b["new"] += 1
    print("corpus\tn\ttop1\ttop3\tregressions\tnew_passes")
    tot = {"n": 0, "t1": 0, "t3": 0, "reg": 0, "new": 0}
    for c in ("q4", "q8", "gen45", "local-8022", "intent201"):
        b = by[c]
        if not b["n"]:
            continue
        print(f"{c}\t{b['n']}\t{b['t1']}/{b['n']}\t{b['t3']}/{b['n']}\t{b['reg']}\t{b['new']}")
        for k in tot:
            tot[k] += b[k]
    print(
        f"ALL\t{tot['n']}\t{tot['t1']}/{tot['n']}\t{tot['t3']}/{tot['n']}\t{tot['reg']}\t{tot['new']}"
    )

    print("\n=== REGRESSIONS ===")
    regs = [r for r in rows if r["flag"] == "REGRESSION"]
    if not regs:
        print("(none)")
    else:
        for r in regs:
            print(f"  {r['corpus']} {r['image']}: expected {r['expected']} dump={r['old_top1']} now={r['got']} mode={r['mode']}")

    print("\n=== NEW PASSES ===")
    news = [r for r in rows if r["flag"] in ("NEW_PASS", "NEW_PASS_vs_dump")]
    if not news:
        print("(none)")
    else:
        for r in news:
            print(f"  {r['corpus']} {r['image']}: dump={r['old_top1']} now={r['got']} mode={r['mode']}")

    print("\n=== FAILS (top1) ===")
    fails = [r for r in rows if not r["pass_top1"]]
    if not fails:
        print("(none)")
    else:
        for r in fails:
            print(
                f"  {r['corpus']} {r['image']}: expected {r['expected']} got={r['got']} "
                f"mode={r['mode']} top3=[{r['top3']}] dump={r['old_top1']} {r['flag']}"
            )


if __name__ == "__main__":
    main()
