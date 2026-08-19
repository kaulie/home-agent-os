#!/usr/bin/env python3
"""N1–N20 black-box: POST /api/v1/intent, poll intent_detail."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

BRAIN = "http://115.190.153.53:9527"
OUT = Path(__file__).resolve().parent / "run_results_n20.json"
TERMINAL = {"succeeded", "failed", "plan_failed"}

# id, text, timeout_sec, notes, expect
# expect.required / forbidden: capability ids
# expect.outcome: succeeded | failed | plan_failed | http_reject | not_stuck | either
CASES: list[tuple[str, str, int, str, dict]] = [
    ("N1", "现在几点了", 90, "clock.now; presentation with time; no query", {
        "required": ["clock.now"], "forbidden": ["query.content"], "outcome": "succeeded",
    }),
    ("N2", "用语音告诉我现在几点了", 90, "clock + voice", {
        "required": ["clock.now"], "forbidden": ["query.content"], "outcome": "succeeded",
    }),
    ("N3", "用语音说：你好，这是TTS测试", 90, "notify.speak only", {
        "required": ["notify.speak"], "forbidden": ["query.content", "camera.capture"],
        "outcome": "succeeded",
    }),
    ("N4", "一加一等于几", 120, "query.content", {
        "required": ["query.content"],
        "forbidden": ["camera.capture", "clock.now"], "outcome": "succeeded",
    }),
    ("N5", "晋字一共几画", 120, "professional query, no display", {
        "required": ["query.content"], "forbidden": ["display.photo", "camera.capture"],
        "outcome": "succeeded",
    }),
    ("N6", "我家里那只猫叫什么名字", 120, "must not invent name", {
        "required": ["query.content"], "forbidden": ["camera.capture"], "outcome": "succeeded",
    }),
    ("N7", "客厅现在适合看书吗，用语音告诉我", 120, "query not camera", {
        "required": ["query.content"], "forbidden": ["camera.capture"], "outcome": "succeeded",
    }),
    ("N8", "把客厅窗帘打开", 75, "no curtain cap; clean fail + msg", {
        "forbidden": ["camera.capture", "music.play"], "outcome": "failed",
    }),
    ("N9", "拍张照", 180, "camera only", {
        "required": ["camera.capture"], "outcome": "succeeded",
    }),
    ("N10", "拍张照投到电视上", 210, "camera + display.photo", {
        "required": ["camera.capture", "display.photo"], "outcome": "succeeded",
    }),
    ("N11", "拍张照看看客厅里有没有人，然后用语音告诉我", 240, "camera + perceive + speak", {
        "required": ["camera.capture", "vision.perceive"], "forbidden": ["vision.ask"],
        "outcome": "succeeded",
    }),
    ("N12", "画一张客厅台灯的示意图，投到电视上", 180, "query image + display", {
        "required": ["query.content", "display.photo"], "forbidden": ["camera.capture"],
        "outcome": "succeeded",
    }),
    ("N13", "播放陈奕迅的十年", 90, "music.play", {
        "required": ["music.play"], "outcome": "succeeded",
    }),
    ("N14", "投到电视上", 75, "display without photo must not succeed", {
        "outcome": "failed",
    }),
    ("N15", "把刚才拍的那些照片做成轮播投到电视", 75, "slideshow without urls must fail", {
        "outcome": "failed",
    }),
    ("N16", "一分钟后用语音说：该喝水了", 150, "delay speak ~60s", {
        "required": ["notify.speak"], "outcome": "succeeded",
    }),
    ("N17", "用 take_photo 拍一张", 180, "legacy name -> camera.capture", {
        "forbidden": ["take_photo"], "outcome": "either",
    }),
    ("N18", "拍张照，但是不要拍照", 90, "contradiction; not both succeed", {
        "outcome": "either",
    }),
    ("N19", "地球到月球大约多远", 120, "query only", {
        "required": ["query.content"],
        "forbidden": ["camera.capture", "display.photo"], "outcome": "succeeded",
    }),
    ("N20", "今天天气适合散步吗", 120, "query no camera", {
        "required": ["query.content"], "forbidden": ["camera.capture"], "outcome": "succeeded",
    }),
]


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
    except (TimeoutError, urllib.error.URLError, OSError) as e:
        return 0, f"{type(e).__name__}: {e}"


def post_intent(text: str) -> tuple[int, dict | str]:
    payload = json.dumps({"text": text, "source": "text"}, ensure_ascii=False).encode()
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


def get_intent_path(intent_id: object) -> tuple[int, str]:
    return _req(f"{BRAIN}/api/v1/intent/{intent_id}", timeout=10)


def summarize(body: dict) -> dict:
    plan = body.get("execution_plan") or []
    steps = []
    for s in plan:
        if not isinstance(s, dict):
            continue
        steps.append({
            "step": s.get("step"),
            "capability": s.get("capability"),
            "status": s.get("status"),
            "msg": (s.get("msg") or "")[:240],
            "edge": s.get("assigned_edge_id"),
            "timing": (s.get("execution_timing") or {}).get("mode"),
        })
    return {
        "status": body.get("status") or body.get("intent_status"),
        "msg": body.get("msg") or body.get("err_msg") or body.get("error"),
        "text": body.get("text"),
        "presentation": body.get("presentation"),
        "caps": [x["capability"] for x in steps],
        "edges": sorted({x["edge"] for x in steps if x.get("edge")}),
        "steps": steps,
        "has_status_log": bool(body.get("status_log")),
        "step_outputs_keys": list((body.get("step_outputs") or {}).keys())
        if isinstance(body.get("step_outputs"), dict) else body.get("step_outputs"),
    }


def wait_detail(intent_id: object, timeout: int) -> dict:
    deadline = time.time() + timeout
    snapshots: list[dict] = []
    last: dict | str | None = None
    t0 = time.time()
    last_status = object()
    while time.time() < deadline:
        code, body = get_detail(intent_id)
        elapsed = round(time.time() - t0, 1)
        last = body
        if isinstance(body, dict):
            rec = {"t": elapsed, "http": code, **summarize(body)}
            status = rec.get("status")
            if not snapshots or status != last_status or elapsed == 0:
                snapshots.append({k: rec[k] for k in rec if k != "steps"})
                last_status = status
            if status in TERMINAL:
                snapshots.append(rec)
                break
        else:
            snapshots.append({"t": elapsed, "http": code, "raw": str(body)[:400]})
        time.sleep(3.0)
    g_code, g_raw = get_intent_path(intent_id)
    final = summarize(last) if isinstance(last, dict) else last
    return {
        "elapsed_sec": round(time.time() - t0, 1),
        "final": final,
        "snapshots": snapshots[-8:],
        "get_intent": {"http": g_code, "body": g_raw[:240]},
    }


def judge(expect: dict, rec: dict) -> dict:
    post = rec.get("post")
    wait = rec.get("wait") or {}
    final = wait.get("final") if isinstance(wait.get("final"), dict) else {}
    status = final.get("status")
    caps = final.get("caps") or []
    outcome = expect.get("outcome")
    notes: list[str] = []
    ok = True
    if rec.get("post_http") not in (200, 201) and outcome != "http_reject":
        ok = False
        notes.append(f"post_http={rec.get('post_http')}")
    if outcome == "http_reject":
        ok = rec.get("post_http") not in (200, 201) or (
            isinstance(post, dict) and not post.get("ok")
        )
    elif outcome == "succeeded" and status != "succeeded":
        ok = False
        notes.append(f"status={status}")
    elif outcome == "failed" and status not in ("failed", "plan_failed"):
        ok = False
        notes.append(f"status={status} want failed")
    elif outcome == "not_stuck" and status not in TERMINAL:
        ok = False
        notes.append(f"stuck status={status}")
    for cap in expect.get("required") or []:
        if cap not in caps:
            ok = False
            notes.append(f"missing {cap}")
    for cap in expect.get("forbidden") or []:
        if cap in caps:
            ok = False
            notes.append(f"forbidden {cap}")
    if status in ("failed", "plan_failed") and not (final.get("msg") or any(
        (s.get("msg") or "").strip() for s in (final.get("steps") or [])
    )):
        notes.append("fail_without_msg")
        if outcome in ("failed", "succeeded"):
            ok = False
    return {"ok": ok, "notes": notes, "status": status, "caps": caps}


def main() -> None:
    results: dict = {"brain": BRAIN, "cases": []}
    if OUT.exists():
        results = json.loads(OUT.read_text())
    done = {c["id"] for c in results.get("cases", [])}
    for cid, text, timeout, notes, expect in CASES:
        if cid in done:
            print(f"skip {cid}")
            continue
        print(f"POST {cid} {text!r}", flush=True)
        code, body = post_intent(text)
        rec = {
            "id": cid,
            "text": text,
            "notes": notes,
            "expect": expect,
            "post_http": code,
            "post": body,
        }
        intent_id = None
        if isinstance(body, dict):
            intent_id = body.get("intent_id") or body.get("id")
        rec["intent_id"] = intent_id
        if intent_id is not None:
            rec["wait"] = wait_detail(intent_id, timeout)
        rec["judge"] = judge(expect, rec)
        results.setdefault("cases", []).append(rec)
        OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2))
        j = rec["judge"]
        print(
            f"  -> id={intent_id} status={j.get('status')} caps={j.get('caps')} "
            f"ok={j['ok']} {j['notes']}",
            flush=True,
        )
    oks = sum(1 for c in results["cases"] if c.get("judge", {}).get("ok"))
    print(f"wrote {OUT} {oks}/{len(results['cases'])} ok")


if __name__ == "__main__":
    main()
