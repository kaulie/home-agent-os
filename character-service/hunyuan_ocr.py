"""HTTP client for HunyuanOCR-1.5 via llama.cpp llama-server (OpenAI-compatible).

Returns blocks in the same shape as ocr_client: {"text", "bbox", "confidence"}.
Coordinates from HunyuanOCR are normalized to [0, 1000]; we scale them back
to pixel space using the decoded image dimensions.
"""

from __future__ import annotations

import base64
import io
import json
import os
import urllib.error
import urllib.request
from typing import Any


class HunyuanOcrError(Exception):
    pass


SPOTTING_PROMPT = (
    "检测并识别图中所有的文字行，请按从上到下、从左到右的阅读顺序进行识别。 "
    "输出格式为 JSON 数组，每个元素必须包含："
    '"box": [xmin, ymin, xmax, ymax]（坐标需归一化到 [0, 1000] 范围内）；'
    '"text": "识别出的文字内容"。 '
    "注意：请直接输出 JSON 数组，不要包含任何多余的描述性文字。"
)


def server_url() -> str:
    return (os.environ.get("HUNYUAN_OCR_URL") or "http://127.0.0.1:8082").rstrip("/")


def _image_size(image_bytes: bytes) -> tuple[int, int]:
    """Return (width, height) without heavy deps."""
    try:
        from PIL import Image

        with Image.open(io.BytesIO(image_bytes)) as img:
            return img.size
    except Exception:
        pass
    try:
        import cv2
        import numpy as np

        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is not None:
            h, w = img.shape[:2]
            return w, h
    except Exception:
        pass
    return 0, 0


def _strip_code_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        lines = t.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    return t


def recognize(
    image_bytes: bytes,
    *,
    language: str = "zh",
    timeout: float = 300.0,
    return_timings: bool = False,
) -> dict[str, Any]:
    if not image_bytes:
        raise HunyuanOcrError("empty image")

    w, h = _image_size(image_bytes)
    if not w or not h:
        raise HunyuanOcrError("cannot decode image dimensions")

    img_b64 = base64.b64encode(image_bytes).decode("ascii")
    req_body: dict[str, Any] = {
        "model": "HYVL",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                    {"type": "text", "text": SPOTTING_PROMPT},
                ],
            }
        ],
        "max_tokens": 1024,
        "temperature": 0.1,
    }
    if return_timings:
        req_body["timings"] = True
    payload = json.dumps(req_body).encode("utf-8")

    req = urllib.request.Request(
        server_url() + "/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:400]
        raise HunyuanOcrError(f"hunyuan HTTP {e.code}: {detail}") from e
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise HunyuanOcrError(f"hunyuan unreachable ({server_url()}): {e}") from e

    content = ""
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise HunyuanOcrError(f"hunyuan bad response: {str(body)[:300]}")

    raw = _strip_code_fence(content)
    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        items = []

    if not isinstance(items, list):
        items = []

    blocks: list[dict[str, Any]] = []
    texts: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        box = item.get("box")
        if not text or not isinstance(box, list) or len(box) != 4:
            continue
        try:
            x1n, y1n, x2n, y2n = (float(v) for v in box)
        except (TypeError, ValueError):
            continue
        x1 = x1n / 1000.0 * w
        y1 = y1n / 1000.0 * h
        x2 = x2n / 1000.0 * w
        y2 = y2n / 1000.0 * h
        if x2 <= x1 or y2 <= y1:
            continue
        blocks.append(
            {
                "text": text,
                "bbox": [int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2))],
                "confidence": None,
            }
        )
        texts.append(text)

    result: dict[str, Any] = {"blocks": blocks, "text": "".join(texts)}
    if return_timings and isinstance(body.get("timings"), dict):
        result["timings"] = body["timings"]
    return result
