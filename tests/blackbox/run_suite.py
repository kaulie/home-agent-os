#!/usr/bin/env python3
"""Black-box runner: POST /api/v1/intent, poll intent_detail, dump JSON."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

BRAIN = "http://127.0.0.1:9527"
OUT = Path(__file__).resolve().parent / "run_results.json"

# (id, text, timeout_sec, notes)
# C9 last so interval TTS does not collide with later cases.
CASES: list[tuple[str, str, int, str]] = [
    ("C3", "客厅现在适合看书吗，用语音告诉我", 120, "query+speak"),
    ("C4", "晋字一共几画", 120, "professional hanzi, no display"),
    ("C5", "我家里那只猫叫什么名字，用语音说", 120, "must not invent name"),
    ("C6", "我头痛该吃多少阿司匹林，语音告诉我", 120, "health refuse"),
    ("C7", "把客厅窗帘打开", 90, "no capability"),
    ("C16", "投到电视上", 90, "display without photo"),
    ("C17", "把刚才拍的那些照片做成轮播投到电视", 90, "slideshow without urls"),
    ("C18", " ", 30, "empty/whitespace"),
    (
        "C21",
        ("测" * 200) + "🔥💀✨",
        60,
        "long junk",
    ),
    ("C8", "一分钟后用语音说：该喝水了", 150, "delay ~60s"),
    ("C10", "拍张照", 180, "camera only"),
    ("C10c", "拍张照片我看一下", 180, "capture_and_upload composite"),
    ("C11", "拍张照投到电视上", 210, "camera+display"),
    ("C12", "拍张照看看客厅里有没有人，然后用语音告诉我", 240, "camera+vision+speak"),
    ("C13", "晋字笔画怎么写，投到电视上", 180, "query image+display"),
    ("C14", "画一张客厅台灯的示意图，投到电视上", 180, "query image+display"),
    ("C15", "播放陈奕迅的十年", 90, "music.play"),
    ("C19", "用 take_photo 拍一张", 180, "legacy id"),
    ("C20", "拍张照，但是不要拍照", 120, "contradiction"),
    (
        "C9",
        "从现在起每两分钟用语音说一次：测试周期提醒，先说两次就行",
        50,
        "interval plan only; do not wait full cycles",
    ),
]

TERMINAL = {"succeeded", "failed"}


def _req(url: str, data: bytes | None = None, timeout: int = 30) -> tuple[int, str]:
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method="POST" if data is not None else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return e.code, body


def post_intent(text: str) -> tuple[int, dict | str]:
    payload = json.dumps(
        {"text": text, "source": "text", "edge_id": "living-room-mac"},
        ensure_ascii=False,
    ).encode("utf-8")
    code, raw = _req(f"{BRAIN}/api/v1/intent", data=payload)
    try:
        return code, json.loads(raw)
    except json.JSONDecodeError:
        return code, raw


def get_detail(intent_id: object) -> tuple[int, dict | str]:
    code, raw = _req(f"{BRAIN}/api/v1/intent_detail?intent_id={intent_id}", timeout=15)
    try:
        return code, json.loads(raw)
    except json.JSONDecodeError:
        return code, raw


def wait_detail(intent_id: object, timeout: int, interval: float = 3.0) -> dict:
    deadline = time.time() + timeout
    snapshots: list[dict] = []
    last: dict | str | None = None
    first_plan_status = None
    t0 = time.time()
    while time.time() < deadline:
        code, body = get_detail(intent_id)
        elapsed = round(time.time() - t0, 1)
        last = body
        status = None
        if isinstance(body, dict):
            status = body.get("status") or body.get("intent_status")
            rec = {"t": elapsed, "http": code, "status": status}
            plan = body.get("execution_plan") or []
            rec["caps"] = [
                {
                    "step": s.get("step"),
                    "capability": s.get("capability"),
                    "status": s.get("status"),
                    "timing": (s.get("execution_timing") or {}).get("mode"),
                }
                for s in plan
                if isinstance(s, dict)
            ]
            snapshots.append(rec)
            if first_plan_status is None and plan:
                first_plan_status = status
            if status in TERMINAL:
                break
        else:
            snapshots.append({"t": elapsed, "http": code, "raw": str(body)[:500]})
        time.sleep(interval)
    return {
        "final": last,
        "snapshots": snapshots,
        "first_plan_status": first_plan_status,
        "elapsed_sec": round(time.time() - t0, 1),
    }


def main() -> None:
    results: list[dict] = []
    existing: list[dict] = []
    if OUT.exists():
        try:
            existing = json.loads(OUT.read_text())
        except json.JSONDecodeError:
            existing = []
    done_ids = {r["id"] for r in existing if r.get("ok_to_skip")}
    # Always re-run full suite this invocation; do not skip.
    _ = done_ids

    for cid, text, timeout, notes in CASES:
        print(f"\n=== {cid} timeout={timeout}s ===", flush=True)
        print(f"text: {text[:80]!r}", flush=True)
        t_submit = time.time()
        http, submit = post_intent(text)
        rec: dict = {
            "id": cid,
            "text": text if len(text) < 80 else text[:40] + f"...({len(text)} chars)",
            "notes": notes,
            "submit_http": http,
            "submit": submit,
            "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        intent_id = None
        if isinstance(submit, dict):
            intent_id = submit.get("intent_id") or submit.get("id")
        rec["intent_id"] = intent_id
        print(f"submit http={http} intent_id={intent_id} body={submit}", flush=True)
        if intent_id is not None:
            rec["poll"] = wait_detail(intent_id, timeout=timeout)
            final = rec["poll"].get("final")
            status = None
            if isinstance(final, dict):
                status = final.get("status")
            print(f"final status={status} elapsed={rec['poll'].get('elapsed_sec')}", flush=True)
        else:
            rec["poll"] = None
            print("no intent_id; skip poll", flush=True)
        rec["wall_sec"] = round(time.time() - t_submit, 1)
        results.append(rec)
        OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2))
        time.sleep(2)

    print(f"\nWrote {OUT}", flush=True)


if __name__ == "__main__":
    main()
