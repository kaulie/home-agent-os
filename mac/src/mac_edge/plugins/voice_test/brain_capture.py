"""Capture a still by dispatching existing ``camera.capture`` through Brain.

Does not talk to GoPro HTTP or switch Wi-Fi. iPhone (on the GoPro AP) runs
the advertised capability; this helper only POSTs /intent and downloads bytes.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

log = logging.getLogger("mac_edge.voice_test.brain_capture")

from mac_edge.config import primary_brain_url


DEFAULT_BRAIN = "http://127.0.0.1:9527"
DEFAULT_ISSUER = "edge-node-JzvEe287"
TERMINAL = frozenset({"succeeded", "failed", "plan_failed"})


class BrainCaptureError(Exception):
    pass


def _brain_url() -> str:
    return primary_brain_url(os.environ.get("MAC_EDGE_BRAIN_URL"), default=DEFAULT_BRAIN)


def _issuer() -> str:
    return (
        os.environ.get("MAC_EDGE_VOICE_TEST_ISSUER")
        or os.environ.get("MAC_EDGE_VOICE_TEST_PARTICIPANT_ID")
        or DEFAULT_ISSUER
    ).strip()


def _request(url: str, data: dict | None = None, *, timeout: float = 30.0) -> dict[str, Any]:
    raw = json.dumps(data, ensure_ascii=False).encode() if data is not None else None
    req = urllib.request.Request(
        url,
        data=raw,
        headers={"Content-Type": "application/json"} if raw else {},
        method="POST" if raw else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", errors="replace")
        raise BrainCaptureError(f"Brain HTTP {e.code}: {text[:240]}") from e
    except (TimeoutError, urllib.error.URLError, OSError) as e:
        raise BrainCaptureError(f"Brain 请求失败（{e}）") from e
    if not isinstance(body, dict):
        raise BrainCaptureError("Brain 返回不是 JSON 对象")
    return body


def _asset_ref_from_intent(intent: dict[str, Any]) -> dict[str, Any] | None:
    blobs: list[Any] = []
    ctx = intent.get("ctx_param") or intent.get("context")
    if isinstance(ctx, dict):
        blobs.append(ctx)
    outputs = intent.get("step_outputs")
    if isinstance(outputs, dict):
        blobs.extend(v for v in outputs.values() if isinstance(v, dict))
    pres = intent.get("presentation")
    if isinstance(pres, dict):
        blobs.append(pres)
    for blob in blobs:
        ref = blob.get("asset_ref")
        if isinstance(ref, dict) and str(ref.get("asset_id") or "").strip():
            return ref
        if isinstance(ref, str) and ref.strip().startswith("{"):
            try:
                parsed = json.loads(ref)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict) and str(parsed.get("asset_id") or "").strip():
                return parsed
    return None


def _download(url: str, dest: Path, *, timeout: float = 25.0) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
    except (TimeoutError, urllib.error.URLError, OSError) as e:
        raise BrainCaptureError(f"下载验证图失败（{e}）") from e
    if len(data) < 128 or data[:2] != b"\xff\xd8":
        raise BrainCaptureError("下载验证图失败：不是 JPEG。")
    dest.write_bytes(data)
    return dest


def capture_still(
    dest: Path,
    *,
    device: str = "0",
    timeout_sec: float = 180.0,
) -> Path:
    """POST 拍张照, wait for camera.capture, save JPEG to dest. ``device`` unused."""
    _ = device
    brain = _brain_url()
    issuer = _issuer()
    if not issuer:
        raise BrainCaptureError("缺少发出端 participant_id（MAC_EDGE_VOICE_TEST_ISSUER）。")
    posted = _request(
        f"{brain}/api/v1/intent",
        {"text": "拍张照", "source": "text", "participant_id": issuer},
        timeout=20.0,
    )
    if not posted.get("ok"):
        raise BrainCaptureError(f"入队失败：{posted.get('error') or posted}")
    intent_id = posted.get("intent_id")
    if intent_id in (None, ""):
        raise BrainCaptureError("入队成功但没有 intent_id")
    log.info("brain camera.capture queued intent_id=%s issuer=%s", intent_id, issuer)

    deadline = time.time() + max(30.0, float(timeout_sec))
    last: dict[str, Any] = {}
    while time.time() < deadline:
        last = _request(f"{brain}/api/v1/intent_detail?intent_id={intent_id}", timeout=15.0)
        status = str(last.get("status") or last.get("intent_status") or "")
        if status in TERMINAL:
            break
        time.sleep(2.0)
    else:
        raise BrainCaptureError(f"camera.capture 超时（intent_id={intent_id}）")

    status = str(last.get("status") or last.get("intent_status") or "")
    if status != "succeeded":
        msg = str(last.get("msg") or last.get("err_msg") or status)
        raise BrainCaptureError(f"camera.capture 未成功（intent {intent_id}：{msg}）")
    plan = last.get("execution_plan") or []
    caps = [
        str(s.get("capability") or "")
        for s in plan
        if isinstance(s, dict)
    ]
    if "camera.capture" not in caps:
        raise BrainCaptureError(
            f"计划里没有 camera.capture（intent {intent_id}：{caps}）"
        )
    ref = _asset_ref_from_intent(last)
    if ref is None:
        raise BrainCaptureError(f"成功但没有 asset_ref（intent {intent_id}）")
    asset_id = str(ref.get("asset_id") or "").strip()
    # Preview is small and public-cloud reachable; original often hangs on LAN.
    url = (
        f"{brain}/api/v1/assets/{asset_id}/content"
        f"?intent_id={intent_id}&representation=preview"
    )
    path = _download(url, dest.with_suffix(".jpg"))
    sidecar = path.with_suffix(".asset.json")
    sidecar.write_text(
        json.dumps(
            {"asset_ref": ref, "intent_id": intent_id, "content_url": url},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    log.info("brain camera.capture saved %s asset_id=%s", path, asset_id)
    return path
