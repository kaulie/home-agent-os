#!/usr/bin/env python3
"""P0 dual-Brain / Capability Availability / Exposure Policy black-box tests.

Exercises the new P0 contract against a running Brain (default 127.0.0.1:9527):
  D  dual_registration      — client-supplied runtime_id is authoritative; no hint rebind.
  A  capability_availability — heartbeat snapshot with per-cap `available` filters the
                               schedulable map (DECLARED but unavailable = not schedulable).
  X  exposure_policy         — per-domain exposure filters schedulable capabilities;
                               admin GET/PUT exposure-policy works.

These are contract-level tests (register / heartbeat / capabilities / admin). They do
NOT exercise the LLM planning pipeline (see run_suite.py for that). capability_timeline
is deferred to the analysis engine (no history table in P0).

Run:
  python3 tests/blackbox/run_p0_dual_brain.py
  BRAIN=http://127.0.0.1:9527 python3 tests/blackbox/run_p0_dual_brain.py
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

BRAIN = os.environ.get("BRAIN", "http://127.0.0.1:9527").rstrip("/")
OUT = Path(__file__).resolve().parent / "p0_dual_brain_results.json"

TWO_CAPS = [
    {"capability_id": "gopro.capture", "kind": "input"},
    {"capability_id": "camera.capture", "kind": "input"},
    {"capability_id": "terminal.execute", "kind": "action"},
]
SERVICES = [{"service_id": "s1", "display_name": "Test Svc", "version": "0.1", "group": "test", "capabilities": TWO_CAPS}]


def _req(url: str, data: bytes | None = None, method: str | None = None, timeout: int = 15) -> tuple[int, object]:
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method=method or ("POST" if data is not None else "GET"),
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, body


def post_json(path: str, payload: dict) -> tuple[int, object]:
    return _req(f"{BRAIN}{path}", json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def get_json(path: str) -> tuple[int, object]:
    return _req(f"{BRAIN}{path}", None)


def now_ms() -> int:
    return int(time.time() * 1000)


def case_dual_registration() -> dict:
    """D: client-supplied runtime_id is authoritative; no client_hint rebind."""
    rid = "runtime-blackbox-dual-001"
    # Register with a client_hint that belongs to another (non-existent) participant,
    # plus our authoritative runtime_id. Brain must use runtime_id, not hint-rebind.
    code, body = post_json("/api/v1/edge-register", {
        "runtime_id": rid,
        "participant_id": rid,
        "client_hint": "someone-else-hint",
        "display_name": "Dual Brain Test",
        "device_type": "mac",
        "services": SERVICES,
        "roles": ["runtime"],
        "exposure_policy": {"lan": ["camera.capture", "terminal.execute"], "cloud": ["camera.capture"]},
    })
    ok = code == 200 and isinstance(body, dict) and body.get("edge_id") == rid
    # Register again with the SAME runtime_id but different hint → must reuse rid, not rebind.
    code2, body2 = post_json("/api/v1/edge-register", {
        "runtime_id": rid,
        "client_hint": "another-unrelated-hint",
        "display_name": "Dual Brain Test 2",
        "device_type": "mac",
        "services": SERVICES,
        "roles": ["runtime"],
    })
    ok2 = code2 == 200 and isinstance(body2, dict) and body2.get("edge_id") == rid
    return {"id": "D", "name": "dual_registration", "ok": ok and ok2, "edge_id": rid,
            "register1": body, "register2": body2}


def case_capability_availability(rid: str) -> dict:
    """A: per-cap `available` in heartbeat snapshot filters the schedulable map."""
    code, body = post_json("/api/v1/edge-heartbeat", {
        "edge_id": rid,
        "client_time_ms": now_ms(),
        "online_status": "online",
        "services": [{
            "service_id": "s1",
            "capabilities": [
                {"capability_id": "gopro.capture", "available": False, "observed_at": time.time()},
                {"capability_id": "camera.capture", "available": True, "observed_at": time.time()},
                {"capability_id": "terminal.execute", "available": True, "observed_at": time.time()},
            ],
        }],
    })
    hb_ok = code == 200 and isinstance(body, dict) and body.get("ok") is True
    # Query schedulable capabilities. gopro.capture (unavailable) must NOT appear.
    code2, caps = get_json("/api/v1/capabilities?capability_id=gopro.capture")
    gopro_schedulable = isinstance(caps, dict) and bool(caps.get("capabilities"))
    code3, caps2 = get_json("/api/v1/capabilities?capability_id=camera.capture")
    camera_schedulable = isinstance(caps2, dict) and bool(caps2.get("capabilities"))
    ok = hb_ok and (not gopro_schedulable) and camera_schedulable
    return {"id": "A", "name": "capability_availability", "ok": ok,
            "heartbeat_ok": hb_ok, "gopro_schedulable": gopro_schedulable,
            "camera_schedulable": camera_schedulable, "heartbeat": body}


def case_exposure_policy(rid: str) -> dict:
    """X: per-domain exposure filters schedulable caps; admin GET/PUT exposure-policy."""
    # Initial exposure: lan=[camera.capture, terminal.execute]; cloud=[camera.capture].
    # gopro.capture is DECLARED+available but NOT exposed on lan → must not be schedulable.
    # First make gopro available via a fresh heartbeat.
    post_json("/api/v1/edge-heartbeat", {
        "edge_id": rid,
        "client_time_ms": now_ms(),
        "online_status": "online",
        "services": [{
            "service_id": "s1",
            "capabilities": [
                {"capability_id": "gopro.capture", "available": True, "observed_at": time.time()},
                {"capability_id": "camera.capture", "available": True, "observed_at": time.time()},
                {"capability_id": "terminal.execute", "available": True, "observed_at": time.time()},
            ],
        }],
    })
    # gopro.capture is available but NOT in lan exposure list → not schedulable on lan.
    _, caps_gopro = get_json("/api/v1/capabilities?capability_id=gopro.capture")
    gopro_excluded = not (isinstance(caps_gopro, dict) and caps_gopro.get("capabilities"))
    # Admin GET exposure-policy.
    code_get, get_body = get_json(f"/api/v1/admin/nodes/{rid}/exposure-policy")
    get_ok = code_get == 200 and isinstance(get_body, dict) and get_body.get("ok") is True
    # Admin PUT: restrict lan to only camera.capture.
    code_put, put_body = _req(
        f"{BRAIN}/api/v1/admin/nodes/{rid}/exposure-policy",
        json.dumps({"exposure_policy": {"lan": ["camera.capture"], "cloud": []}}).encode("utf-8"),
        method="PUT",
    )
    put_ok = code_put == 200 and isinstance(put_body, dict) and put_body.get("ok") is True
    # After restriction: terminal.execute is available+declared but NOT exposed on lan.
    _, caps_term = get_json("/api/v1/capabilities?capability_id=terminal.execute")
    terminal_excluded = not (isinstance(caps_term, dict) and caps_term.get("capabilities"))
    _, caps_cam = get_json("/api/v1/capabilities?capability_id=camera.capture")
    camera_still = isinstance(caps_cam, dict) and bool(caps_cam.get("capabilities"))
    ok = gopro_excluded and get_ok and put_ok and terminal_excluded and camera_still
    return {"id": "X", "name": "exposure_policy", "ok": ok,
            "gopro_excluded_by_policy": gopro_excluded,
            "admin_get_ok": get_ok, "admin_put_ok": put_ok,
            "terminal_excluded_after_restrict": terminal_excluded,
            "camera_still_schedulable": camera_still,
            "get_body": get_body, "put_body": put_body}


def case_dual_registration_rows(rid: str) -> dict:
    """D2: registering the same runtime_id is idempotent (no duplicate participants)."""
    # Re-register the same id several times; registration_count must stay 1.
    for _ in range(3):
        post_json("/api/v1/edge-register", {
            "runtime_id": rid, "display_name": "Dual Brain Test", "device_type": "mac",
            "services": SERVICES, "roles": ["runtime"],
        })
    code, body = get_json("/api/v1/admin/nodes")
    count = 0
    if isinstance(body, dict):
        for n in body.get("nodes", []) or []:
            if isinstance(n, dict) and n.get("participant_id") == rid:
                count += 1
    ok = code == 200 and count == 1
    return {"id": "D2", "name": "dual_registration_idempotent", "ok": ok, "occurrences": count}


def main() -> None:
    results: list[dict] = []
    print(f"BRAIN={BRAIN}", flush=True)

    d = case_dual_registration()
    print(f"[{d['id']}] {d['name']}: ok={d['ok']} edge_id={d.get('edge_id')}", flush=True)
    results.append(d)
    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    if not d["ok"]:
        print("ABORT: dual_registration failed; cannot continue without a runtime_id.", flush=True)
        return

    rid = d["edge_id"]
    a = case_capability_availability(rid)
    print(f"[{a['id']}] {a['name']}: ok={a['ok']} gopro_sched={a['gopro_schedulable']} camera_sched={a['camera_schedulable']}", flush=True)
    results.append(a)

    x = case_exposure_policy(rid)
    print(f"[{x['id']}] {x['name']}: ok={x['ok']} gopro_excl={x['gopro_excluded_by_policy']} term_excl={x['terminal_excluded_after_restrict']}", flush=True)
    results.append(x)

    d2 = case_dual_registration_rows(rid)
    print(f"[{d2['id']}] {d2['name']}: ok={d2['ok']} occurrences={d2['occurrences']}", flush=True)
    results.append(d2)

    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    passed = sum(1 for r in results if r.get("ok"))
    print(f"\n{passed}/{len(results)} passed → {OUT}", flush=True)


if __name__ == "__main__":
    main()
