"""Mac Edge pronunciation assessment plugin.

Atomic capability:
  pronunciation.assess   reference_audio + student_audio (audio AssetRef) → scores JSON

Bridges the Asset contract to pronunciation-service HTTP
(http://127.0.0.1:9190/v1/assess). The service knows nothing about HomeAgent
Asset / Brain / Planner.

This plugin does NOT record or upload audio. Both audio AssetRefs must already be
resolved into this step's params by the planner (from upstream upload steps).
Missing either required ref → fail. Sidecar down → fail with readable msg.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import time
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

log = logging.getLogger("mac_edge.pronunciation_assess")

DEFAULT_PRONUNCIATION_BASE = "http://127.0.0.1:9190"
DEFAULT_HEALTH_URL = "http://127.0.0.1:9190/health"
ASSESS_PATH = "/v1/assess"
DEFAULT_TIMEOUT_SEC = 180.0


class PronunciationAssessError(Exception):
    pass


def _base_url() -> str:
    raw = (os.environ.get("MAC_EDGE_PRONUNCIATION_URL") or DEFAULT_PRONUNCIATION_BASE).strip()
    # Tolerate someone pasting the full assess/health URL.
    for suffix in (ASSESS_PATH, "/assess", "/health", "/healthz", "/v1/health"):
        if raw.endswith(suffix):
            raw = raw[: -len(suffix)]
            break
    return (raw or DEFAULT_PRONUNCIATION_BASE).rstrip("/")


def _health_url() -> str:
    raw = (os.environ.get("MAC_EDGE_PRONUNCIATION_HEALTH_URL") or DEFAULT_HEALTH_URL).strip()
    return raw or DEFAULT_HEALTH_URL


def is_available(_config: Any = None) -> Any:
    """Cheap liveness probe so the executor fails fast instead of timing out."""
    from mac_edge.capability_availability import Availability

    url = _health_url()
    try:
        req = Request(url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=1.0) as resp:
            if 200 <= resp.status < 300:
                return Availability.available()
            return Availability.unavailable(f"pronunciation-service health {resp.status}")
    except Exception as e:  # noqa: BLE001 — availability must never hang
        return Availability.unavailable(f"pronunciation-service 不可达：{e}")


def _guess_mime(path: str) -> tuple[str, str]:
    mime, _ = mimetypes.guess_type(path)
    if not mime:
        ext = os.path.splitext(path)[1].lower()
        mime = {
            ".wav": "audio/wav",
            ".mp3": "audio/mpeg",
            ".m4a": "audio/mp4",
            ".aac": "audio/aac",
            ".ogg": "audio/ogg",
            ".flac": "audio/flac",
        }.get(ext, "application/octet-stream")
    filename = os.path.basename(path) or "audio.bin"
    return mime, filename


def _build_multipart(fields: dict[str, tuple[str, bytes, str]]) -> tuple[bytes, str]:
    """fields: name -> (filename, bytes, mime). Returns (body, content_type)."""
    boundary = "----mac_edge_pronunciation_boundary"
    crlf = "\r\n"
    parts: list[bytes] = []
    for name, (filename, data, mime) in fields.items():
        parts.append(f"--{boundary}{crlf}".encode("utf-8"))
        parts.append(
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"{crlf}'
            f"Content-Type: {mime}{crlf}{crlf}".encode("utf-8")
        )
        parts.append(data)
        parts.append(crlf.encode("utf-8"))
    parts.append(f"--{boundary}--{crlf}".encode("utf-8"))
    body = b"".join(parts)
    return body, f"multipart/form-data; boundary={boundary}"


def _post_assess(
    reference_path: str,
    student_path: str,
    *,
    timeout_sec: float,
) -> dict[str, Any]:
    base = _base_url()
    url = base + ASSESS_PATH
    ref_bytes = _read_audio(reference_path)
    stu_bytes = _read_audio(student_path)
    ref_mime, ref_name = _guess_mime(reference_path)
    stu_mime, stu_name = _guess_mime(student_path)
    body, content_type = _build_multipart({
        "reference": (ref_name, ref_bytes, ref_mime),
        "student": (stu_name, stu_bytes, stu_mime),
    })
    req = Request(
        url,
        data=body,
        headers={"Content-Type": content_type, "Accept": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read()
    except Exception as e:  # noqa: BLE001
        raise PronunciationAssessError(f"pronunciation-service 调用失败：{e}") from e
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise PronunciationAssessError("pronunciation-service 返回非 JSON") from e
    if not isinstance(payload, dict):
        raise PronunciationAssessError("pronunciation-service 返回不是对象")
    if "error" in payload:
        raise PronunciationAssessError(str(payload["error"]) or "pronunciation-service error")
    return payload


def _read_audio(path: str) -> bytes:
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as e:
        raise PronunciationAssessError(f"读取音频文件失败：{e}") from e
    if not data:
        raise PronunciationAssessError(f"音频文件为空：{path}")
    return data


_OUTPUT_KEYS = (
    "overall_score",
    "accuracy_score",
    "fluency_score",
    "completeness_score",
    "prosody_score",
    "duration",
    "problem_words",
    "problem_phonemes",
    "fluency",
    "raw_alignment",
)


def assess_from_params(
    params: dict[str, Any],
    *,
    asset: "CapAsset",
    timeout_sec: float = DEFAULT_TIMEOUT_SEC,
) -> tuple[str, dict[str, Any]]:
    # Duck-typed CapAsset check (Runtime SDK surface): require_ref + manager +
    # intent_id. Avoids importing the full asset/brain_client chain at import time
    # and keeps the plugin unit-testable without the heavy runtime deps. Asset
    # resolution failures (AssetError) are caught generically here and surfaced as
    # PronunciationAssessError with a readable msg.
    if not (
        hasattr(asset, "require_ref")
        and hasattr(asset, "manager")
        and hasattr(asset, "intent_id")
    ):
        raise PronunciationAssessError("pronunciation.assess requires CapAsset (Runtime SDK)")
    try:
        ref_ref = asset.require_ref(params, "reference_audio")
        stu_ref = asset.require_ref(params, "student_audio")
        ref_path = asset.manager.materialize_file(ref_ref, intent_id=asset.intent_id)
        stu_path = asset.manager.materialize_file(stu_ref, intent_id=asset.intent_id)
    except PronunciationAssessError:
        raise
    except Exception as e:  # noqa: BLE001 — asset resolution failures → readable msg
        raise PronunciationAssessError(str(e)) from e

    t0 = time.perf_counter()
    result = _post_assess(str(ref_path), str(stu_path), timeout_sec=timeout_sec)
    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    # Map sidecar response → wire outputs (1:1). feedback_text is extra (for Brain).
    outputs: dict[str, Any] = {}
    for key in _OUTPUT_KEYS:
        if key in result:
            outputs[key] = result[key]
    if "feedback_text" in result:
        outputs["feedback_text"] = result["feedback_text"]
    # Guarantee required keys exist so downstream consumers don't KeyError.
    for key in _OUTPUT_KEYS:
        outputs.setdefault(key, [] if key in ("problem_words", "problem_phonemes", "raw_alignment") else
                           {} if key in ("duration", "fluency") else 0)

    overall = outputs.get("overall_score")
    preview = str(outputs.get("feedback_text") or "")[:100]
    log.info("pronunciation.assess ok overall=%s ms=%s", overall, elapsed_ms)
    msg = f"pronunciation.assess: {preview or 'ok'}"
    return msg, outputs
