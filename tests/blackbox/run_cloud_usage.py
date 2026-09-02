#!/usr/bin/env python3
"""Black-box: Dev cloud API usage stats (brain 9c17848 + dba 026).

GET /api/v1/admin/dev_task/usage?period=day
  → usage.cloud_calls.period / all_time rows {service_id, label, count, ok, fail}

Optional: POST /api/v1/edge-heartbeat with cloud_usage_delta and assert ark.vision increases.

Run:
  python3 tests/blackbox/run_cloud_usage.py
  BRAIN=http://127.0.0.1:9527 python3 tests/blackbox/run_cloud_usage.py
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

BRAIN = os.environ.get("BRAIN", "http://127.0.0.1:9527").rstrip("/")
OUT = Path(__file__).resolve().parent / "run_results_cloud_usage.json"
SHA = "9c17848"

KNOWN_V1 = (
    "ark.planner",
    "ark.vision",
    "ark.query",
    "volc.stt",
    "bing.images",
    "xiaomi.cloud",
    "hisense.cloud",
)

EDGE_ID = "edge-node-blackbox-cloud-usage"


def _headers() -> dict[str, str]:
    token = (os.environ.get("BRAIN_ADMIN_TOKEN") or "").strip()
    h = {"Content-Type": "application/json"}
    if token:
        h["X-Admin-Token"] = token
    return h


def _req(
    path: str,
    *,
    data: dict | None = None,
    method: str | None = None,
    timeout: int = 20,
) -> tuple[int, Any]:
    body = None if data is None else json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{BRAIN}{path}",
        data=body,
        headers=_headers(),
        method=method or ("POST" if body is not None else "GET"),
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw


def _row_map(rows: list[dict]) -> dict[str, dict]:
    return {str(r.get("service_id") or ""): r for r in rows if r.get("service_id")}


def _assert_cloud_rows(rows: list, *, label: str) -> list[str]:
    errs: list[str] = []
    if not isinstance(rows, list):
        return [f"{label}: not a list"]
    for row in rows:
        if not isinstance(row, dict):
            errs.append(f"{label}: row not object")
            continue
        for key in ("service_id", "label", "count", "ok", "fail"):
            if key not in row:
                errs.append(f"{label}: missing {key} in {row.get('service_id')}")
        for num in ("count", "ok", "fail"):
            if num in row and not isinstance(row.get(num), int):
                errs.append(f"{label}: {row.get('service_id')} {num} not int")
    return errs


def usage_cloud_calls() -> tuple[int, dict[str, Any]]:
    code, body = _req("/api/v1/admin/dev_task/usage?period=day")
    if code != 200 or not isinstance(body, dict) or not body.get("ok"):
        return code, {"error": "usage GET failed", "body": body}
    usage = body.get("usage") or {}
    cloud = usage.get("cloud_calls")
    if not isinstance(cloud, dict):
        return code, {"error": "usage.cloud_calls missing", "usage_keys": list(usage.keys())}
    period = cloud.get("period")
    all_time = cloud.get("all_time")
    errs: list[str] = []
    if not isinstance(period, list) or not isinstance(all_time, list):
        errs.append("cloud_calls.period/all_time must be lists")
    else:
        errs.extend(_assert_cloud_rows(period, label="period"))
        errs.extend(_assert_cloud_rows(all_time, label="all_time"))
        period_ids = {r.get("service_id") for r in period}
        for sid in KNOWN_V1:
            if sid not in period_ids:
                errs.append(f"known v1 id missing from period: {sid}")
    return code, {
        "cloud_calls": cloud,
        "period_ark_vision": _row_map(period if isinstance(period, list) else []).get("ark.vision"),
        "errors": errs,
    }


def ensure_edge_registered() -> tuple[bool, str]:
    code, body = _req(
        "/api/v1/edge-register",
        data={
            "runtime_id": EDGE_ID,
            "participant_id": EDGE_ID,
            "display_name": "Blackbox Cloud Usage",
            "device_type": "mac",
            "services": [
                {
                    "service_id": "bb.cloud",
                    "capabilities": [{"capability_id": "notify.speak"}],
                }
            ],
        },
    )
    if code != 200 or not isinstance(body, dict) or not body.get("edge_id"):
        return False, f"edge-register failed code={code} body={body!r}"
    return True, str(body["edge_id"])


def heartbeat_delta(edge_id: str, delta: list[dict]) -> tuple[int, Any]:
    return _req(
        "/api/v1/edge-heartbeat",
        data={
            "edge_id": edge_id,
            "client_time_ms": int(time.time() * 1000),
            "online_status": "online",
            "cloud_usage_delta": delta,
            "services": [
                {
                    "service_id": "bb.cloud",
                    "capabilities": [{"capability_id": "notify.speak"}],
                }
            ],
        },
    )


def main() -> int:
    report: dict[str, Any] = {
        "brain": BRAIN,
        "sha": SHA,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "cases": [],
        "ok": True,
    }

    # C1: usage schema
    code, snap = usage_cloud_calls()
    c1_ok = code == 200 and not snap.get("errors")
    report["cases"].append(
        {
            "id": "C1",
            "name": "usage_cloud_calls_schema",
            "ok": c1_ok,
            "http": code,
            "errors": snap.get("errors"),
            "period_sample": (snap.get("cloud_calls") or {}).get("period", [])[:2],
        }
    )
    if not c1_ok:
        report["ok"] = False

    # C2: heartbeat delta increases ark.vision (optional but run when C1 passes)
    c2: dict[str, Any] = {"id": "C2", "name": "heartbeat_cloud_usage_delta", "ok": False, "skipped": False}
    if not c1_ok:
        c2["skipped"] = True
        c2["note"] = "skipped: C1 failed"
    else:
        before = int((snap.get("period_ark_vision") or {}).get("count") or 0)
        reg_ok, edge_id = ensure_edge_registered()
        if not reg_ok:
            c2["skipped"] = True
            c2["note"] = edge_id
        else:
            hb_code, hb_body = heartbeat_delta(
                edge_id,
                [{"service_id": "ark.vision", "ok": 1, "fail": 0}],
            )
            _, after_snap = usage_cloud_calls()
            after = int((after_snap.get("period_ark_vision") or {}).get("count") or 0)
            c2.update(
                {
                    "edge_id": edge_id,
                    "heartbeat_http": hb_code,
                    "heartbeat_body_ok": isinstance(hb_body, dict) and hb_body.get("ok"),
                    "ark_vision_before": before,
                    "ark_vision_after": after,
                }
            )
            c2["ok"] = hb_code == 200 and after >= before + 1
            if not c2["ok"]:
                report["ok"] = False
    report["cases"].append(c2)

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
