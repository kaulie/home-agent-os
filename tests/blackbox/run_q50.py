#!/usr/bin/env python3
"""Q1–Q50 black-box runner: POST /api/v1/intent, poll intent_detail.

Does not send edge_id. Writes tests/blackbox/run_results_q50.json after each case.
Resume: skip ids already present in the results file unless --force.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

BRAIN = "http://127.0.0.1:9527"
OUT = Path(__file__).resolve().parent / "run_results_q50.json"
TERMINAL = {"succeeded", "failed"}

# (id, text, timeout_sec, notes, expect)
# expect keys:
#   required: subsequence of capabilities that must appear
#   forbidden: must not appear
#   last: optional last-step capability
#   timing: optional execution_timing.mode
#   outcome: succeeded | failed | http_reject | not_stuck | either
CASES: list[tuple[str, str, int, str, dict]] = [
    # --- low disturbance ---
    ("Q34", " ", 30, "empty/whitespace", {"outcome": "http_reject"}),
    ("Q1", "现在几点了", 90, "clock+feedback", {
        "required": ["clock.now"], "forbidden": ["query.content"], "outcome": "succeeded",
    }),
    ("Q2", "用语音告诉我现在几点了", 90, "clock+voice", {
        "required": ["clock.now"], "forbidden": ["query.content"], "outcome": "succeeded",
    }),
    ("Q3", "用语音说：你好，这是TTS测试", 90, "speak only", {
        "required": ["notify.speak"], "forbidden": ["query.content", "camera.capture"],
        "outcome": "succeeded",
    }),
    ("Q4", "一加一等于几", 120, "math+feedback", {
        "required": ["math.calculate"],
        "forbidden": ["query.content", "camera.capture", "display.photo", "clock.now"],
        "outcome": "succeeded",
    }),
    ("Q5", "晋字一共几画", 120, "professional hanzi", {
        "required": ["query.content"],
        "forbidden": ["display.photo", "camera.capture"],
        "outcome": "succeeded",
    }),
    ("Q6", "我家里那只猫叫什么名字", 120, "must not invent name", {
        "required": ["query.content"], "forbidden": ["camera.capture"], "outcome": "succeeded",
    }),
    ("Q7", "我头痛该吃多少阿司匹林", 120, "health refuse", {
        "required": ["query.content"],
        "forbidden": ["display.photo", "camera.capture"],
        "outcome": "succeeded",
    }),
    ("Q8", "今天天气适合散步吗", 120, "query no camera", {
        "required": ["query.content"], "forbidden": ["camera.capture"], "outcome": "succeeded",
    }),
    ("Q27", "地球到月球大约多远", 120, "query only", {
        "required": ["query.content"],
        "forbidden": ["camera.capture", "display.photo", "notify.speak"],
        "outcome": "succeeded",
    }),
    ("Q28", "用语音告诉我一加一等于几", 120, "math+voice no camera", {
        "required": ["math.calculate"], "forbidden": ["query.content", "camera.capture"],
        "outcome": "succeeded",
    }),
    ("Q40", "查询一下现在是几点钟", 90, "clock not query", {
        "required": ["clock.now"], "forbidden": ["query.content"], "outcome": "succeeded",
    }),
    ("Q47", "告诉我现在几点，不要上网搜", 90, "clock no web", {
        "required": ["clock.now"], "forbidden": ["query.content"], "outcome": "succeeded",
    }),
    ("Q45", "现在几点了，投到电视上", 90, "clock no empty display", {
        "required": ["clock.now"], "forbidden": ["query.content"], "outcome": "either",
    }),
    ("Q48", "客厅现在适合看书吗，用语音告诉我", 120, "query not camera", {
        "required": ["query.content"], "forbidden": ["camera.capture"], "outcome": "succeeded",
    }),
    ("Q23", "十秒后用语音说：该喝水了", 60, "delay ~10s", {
        "required": ["notify.speak"], "forbidden": ["endpoint.feedback"],
        "timing": "delay", "outcome": "succeeded",
    }),
    ("Q25", "从现在起每两分钟用语音说一次：测试周期提醒，先说两次就行", 50, "interval plan only", {
        "required": ["notify.speak"], "timing": "interval", "outcome": "either",
    }),
    ("Q29", "把客厅窗帘打开", 90, "no capability curtains", {
        "forbidden": ["camera.capture", "music.play"], "outcome": "not_stuck",
    }),
    ("Q30", "打开空调", 90, "no capability ac", {"outcome": "not_stuck"}),
    ("Q31", "把灯关掉", 90, "no capability light", {"outcome": "not_stuck"}),
    ("Q32", "投到电视上", 90, "display without photo", {
        "forbidden": ["camera.capture"], "outcome": "not_stuck",
    }),
    ("Q33", "把刚才拍的那些照片做成轮播投到电视", 90, "slideshow without urls", {
        "outcome": "not_stuck",
    }),
    ("Q35", ("测" * 200) + "🔥💀✨", 60, "long junk", {"outcome": "not_stuck"}),
    ("Q37", "拍张照，但是不要拍照", 90, "contradiction", {"outcome": "either"}),
    ("Q38", "看这张图里有什么人", 90, "vision without image", {
        "outcome": "not_stuck",
    }),
    ("Q39", "这个字读啥", 90, "ask without image", {"outcome": "not_stuck"}),
    ("Q41", "开始录像", 90, "take_video not advertised", {"outcome": "not_stuck"}),
    ("Q42", "用 foo.bar 煮咖啡", 90, "unknown capability", {"outcome": "not_stuck"}),
    ("Q43", "连上蓝牙音箱", 90, "bluetooth maybe missing", {"outcome": "not_stuck"}),
    ("Q46", "请把照片做成幻灯片投到电视，我就不给你图了", 90, "slideshow no urls", {
        "forbidden": ["camera.capture"], "outcome": "not_stuck",
    }),
    ("Q49", "给我看一张图，但不要拍照也不要画图", 90, "no photo source", {
        "outcome": "not_stuck",
    }),
    ("Q50", "asdfghjklqwerty", 60, "short junk", {"outcome": "not_stuck"}),
    ("Q9", "画一张客厅台灯的示意图，不要投屏", 180, "query image no display", {
        "required": ["query.content"], "forbidden": ["display.photo", "display.slideshow"],
        "outcome": "succeeded",
    }),
    ("Q24", "一分钟后用语音说：该喝水了", 150, "delay ~60s", {
        "required": ["notify.speak"], "timing": "delay", "outcome": "succeeded",
    }),
    # --- music / TV ---
    ("Q18", "播放陈奕迅的十年", 90, "music.play", {
        "required": ["music.play"], "outcome": "not_stuck",
    }),
    ("Q19", "暂停播放", 90, "music.pause", {"required": ["music.pause"], "outcome": "not_stuck"}),
    ("Q20", "停止播放", 90, "music.stop", {"required": ["music.stop"], "outcome": "not_stuck"}),
    ("Q21", "下一首", 90, "music.next", {"required": ["music.next"], "outcome": "not_stuck"}),
    ("Q22", "上一首", 90, "music.previous", {"required": ["music.previous"], "outcome": "not_stuck"}),
    ("Q15", "把装甲车的图片投到电视上", 180, "query+display", {
        "required": ["query.content", "display.photo"], "outcome": "succeeded",
    }),
    ("Q16", "晋字笔画怎么写，投到电视上", 180, "hanzi image+display", {
        "required": ["query.content", "display.photo"], "outcome": "either",
    }),
    ("Q17", "画一张客厅台灯的示意图，投到电视上", 180, "lamp image+display", {
        "required": ["query.content", "display.photo"], "outcome": "succeeded",
    }),
    # --- camera (highest disturbance, one at a time) ---
    ("Q10", "拍张照", 210, "camera+feedback no display", {
        "required": ["camera.capture"], "forbidden": ["display.photo"], "outcome": "either",
    }),
    ("Q26", "拍张照发到我这边看，不要投电视", 210, "camera+feedback", {
        "required": ["camera.capture"], "forbidden": ["display.photo"], "outcome": "either",
    }),
    ("Q11", "拍张照投到电视上", 210, "camera+display", {
        "required": ["camera.capture", "display.photo"], "outcome": "either",
    }),
    ("Q12", "拍张照看看客厅里有没有人", 240, "camera+perceive", {
        "required": ["camera.capture", "vision.perceive"], "outcome": "either",
    }),
    ("Q13", "拍张照，这个字读啥", 240, "camera+ask", {
        "required": ["camera.capture", "vision.ask"], "forbidden": ["query.content"],
        "outcome": "either",
    }),
    ("Q14", "拍张照看看客厅里有没有人，然后用语音告诉我", 240, "camera+perceive+voice", {
        "required": ["camera.capture", "vision.perceive"], "outcome": "either",
    }),
    ("Q36", "用 take_photo 拍一张", 210, "legacy id", {
        "forbidden": ["take_photo", "music.playback"], "outcome": "either",
    }),
    ("Q44", "拍张照并播放陈奕迅的十年", 210, "camera+music maybe two edges", {
        "outcome": "not_stuck",
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
    payload = json.dumps({"text": text, "source": "text"}, ensure_ascii=False).encode("utf-8")
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


def wait_detail(intent_id: object, timeout: int, interval: float = 3.0) -> dict:
    deadline = time.time() + timeout
    snapshots: list[dict] = []
    last: dict | str | None = None
    t0 = time.time()
    while time.time() < deadline:
        code, body = get_detail(intent_id)
        elapsed = round(time.time() - t0, 1)
        last = body
        status = None
        if isinstance(body, dict):
            status = body.get("status") or body.get("intent_status")
            plan = body.get("execution_plan") or []
            rec = {
                "t": elapsed,
                "http": code,
                "status": status,
                "caps": [
                    {
                        "step": s.get("step"),
                        "capability": s.get("capability"),
                        "status": s.get("status"),
                        "msg": (s.get("msg") or "")[:200],
                        "timing": (s.get("execution_timing") or {}).get("mode"),
                        "edge": s.get("assigned_edge_id"),
                    }
                    for s in plan
                    if isinstance(s, dict)
                ],
            }
            snapshots.append(rec)
            if status in TERMINAL:
                break
        else:
            snapshots.append({"t": elapsed, "http": code, "raw": str(body)[:500]})
        time.sleep(interval)
    return {
        "final": last,
        "snapshots": snapshots,
        "elapsed_sec": round(time.time() - t0, 1),
    }


def summarize_final(final: dict | str | None) -> dict:
    if not isinstance(final, dict):
        return {"status": None, "caps": [], "edges": [], "has_text": False,
                "has_status_log": False, "has_outputs": False, "step_msgs": []}
    plan = final.get("execution_plan") or []
    caps = []
    edges = []
    step_msgs = []
    has_outputs = False
    for s in plan:
        if not isinstance(s, dict):
            continue
        caps.append(s.get("capability"))
        edges.append(s.get("assigned_edge_id"))
        msg = s.get("msg") or ""
        step_msgs.append({"cap": s.get("capability"), "status": s.get("status"), "msg": msg[:200]})
        out = s.get("outputs") or s.get("step_outputs") or {}
        if out:
            has_outputs = True
    so = final.get("step_outputs") or final.get("outputs")
    if so:
        has_outputs = True
    return {
        "status": final.get("status") or final.get("intent_status"),
        "caps": caps,
        "edges": sorted({e for e in edges if e}),
        "has_text": bool(final.get("text")),
        "has_status_log": bool(final.get("status_log")),
        "has_outputs": has_outputs,
        "has_answer_text": bool(final.get("answer_text")),
        "step_msgs": step_msgs,
        "timing_modes": [
            (s.get("execution_timing") or {}).get("mode")
            for s in plan if isinstance(s, dict)
        ],
    }


def judge(expect: dict, submit_http: int, intent_id: object, summary: dict) -> str:
    outcome = expect.get("outcome") or "either"
    status = summary.get("status")
    caps = summary.get("caps") or []
    required = expect.get("required") or []
    forbidden = expect.get("forbidden") or []

    if outcome == "http_reject":
        return "pass" if submit_http >= 400 or intent_id is None else "fail"

    # required subsequence
    idx = 0
    for cap in caps:
        if idx < len(required) and cap == required[idx]:
            idx += 1
    if required and idx < len(required):
        return "fail"

    if any(c in caps for c in forbidden):
        return "fail"

    timing = expect.get("timing")
    if timing:
        modes = summary.get("timing_modes") or []
        if timing not in modes:
            return "fail"

    if outcome == "succeeded":
        if status != "succeeded":
            return "partial" if status == "failed" and required and idx >= len(required) else "fail"
        return "pass"
    if outcome == "failed":
        return "pass" if status == "failed" else "fail"
    if outcome == "not_stuck":
        if status in TERMINAL:
            return "pass"
        if status in {"intent_parsed", "received", "intent_received"} and not caps:
            return "fail"
        if status in {"intent_parsed", "received", "intent_received"}:
            return "fail"
        return "partial"
    # either: plan constraints already applied
    if status in TERMINAL:
        return "pass"
    return "partial"


def load_results() -> list[dict]:
    if not OUT.exists():
        return []
    try:
        data = json.loads(OUT.read_text())
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--only", default="", help="comma-separated ids e.g. Q1,Q2")
    args = parser.parse_args()
    only = {x.strip() for x in args.only.split(",") if x.strip()}

    results = load_results()
    done = {r["id"] for r in results} if not args.force else set()

    for cid, text, timeout, notes, expect in CASES:
        if only and cid not in only:
            continue
        if cid in done:
            print(f"skip {cid} already in {OUT.name}", flush=True)
            continue
        print(f"\n=== {cid} timeout={timeout}s ===", flush=True)
        print(f"text: {text[:80]!r}", flush=True)
        t_submit = time.time()
        http, submit = post_intent(text)
        rec: dict = {
            "id": cid,
            "text": text if len(text) < 80 else text[:40] + f"...({len(text)} chars)",
            "notes": notes,
            "expect": expect,
            "submit_http": http,
            "submit": submit,
            "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        intent_id = None
        if isinstance(submit, dict):
            intent_id = submit.get("intent_id") or submit.get("id")
        rec["intent_id"] = intent_id
        print(f"submit http={http} intent_id={intent_id}", flush=True)
        if intent_id is not None:
            rec["poll"] = wait_detail(intent_id, timeout=timeout)
            final = rec["poll"].get("final")
            rec["summary"] = summarize_final(final)
            try:
                phttp, pbody = get_intent_path(intent_id)
                rec["intent_path_http"] = phttp
                rec["intent_path_preview"] = pbody[:120]
            except Exception as e:
                rec["intent_path_http"] = None
                rec["intent_path_preview"] = str(e)
            rec["verdict"] = judge(expect, http, intent_id, rec["summary"])
            print(
                f"final status={rec['summary'].get('status')} "
                f"caps={rec['summary'].get('caps')} "
                f"verdict={rec['verdict']} elapsed={rec['poll'].get('elapsed_sec')}",
                flush=True,
            )
        else:
            rec["poll"] = None
            rec["summary"] = summarize_final(None)
            rec["verdict"] = judge(expect, http, None, rec["summary"])
            print(f"no intent_id; verdict={rec['verdict']}", flush=True)
        rec["wall_sec"] = round(time.time() - t_submit, 1)
        results.append(rec)
        OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2))
        time.sleep(2)

    print(f"\nWrote {OUT} n={len(results)}", flush=True)


if __name__ == "__main__":
    main()
