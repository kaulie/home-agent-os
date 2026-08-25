"""PaddleOCR engine adapter. Independent of HomeAgent / Asset / Brain.

Normalizes PP-OCRv5 (and older PaddleOCR) output to {text, blocks}.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable

log = logging.getLogger("ocr_service.engine")

ENGINE_NAME = "paddleocr"
MODEL_NAME = "PP-OCRv5_server"
DEFAULT_VERSION = "PP-OCRv5"


class OcrEngineError(Exception):
    pass


def model_version() -> str:
    return (os.environ.get("OCR_MODEL_VERSION") or DEFAULT_VERSION).strip() or DEFAULT_VERSION


def _to_nested(points: Any) -> Any:
    if points is None:
        return None
    if hasattr(points, "tolist") and not isinstance(points, (list, tuple)):
        try:
            return points.tolist()
        except Exception:
            return points
    return points


def _is_number(n: Any) -> bool:
    return isinstance(n, (int, float)) and not isinstance(n, bool)


def _as_xyxy(points: Any) -> list[int]:
    points = _to_nested(points)
    xs: list[float] = []
    ys: list[float] = []
    if points is None:
        return [0, 0, 0, 0]
    if isinstance(points, (list, tuple)) and len(points) == 4 and all(_is_number(n) for n in points):
        x1, y1, x2, y2 = (float(n) for n in points)
        return [int(min(x1, x2)), int(min(y1, y2)), int(max(x1, x2)), int(max(y1, y2))]
    if isinstance(points, (list, tuple)) and len(points) == 8 and all(_is_number(n) for n in points):
        xs = [float(points[i]) for i in range(0, 8, 2)]
        ys = [float(points[i]) for i in range(1, 8, 2)]
        return [int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))]
    try:
        rows = list(points)
    except TypeError:
        return [0, 0, 0, 0]
    for item in rows:
        item = _to_nested(item)
        if (
            isinstance(item, (list, tuple))
            and len(item) >= 2
            and _is_number(item[0])
            and _is_number(item[1])
        ):
            xs.append(float(item[0]))
            ys.append(float(item[1]))
    if not xs or not ys:
        return [0, 0, 0, 0]
    return [int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))]


def normalize_raw(raw: Any) -> list[dict[str, Any]]:
    """Turn PaddleOCR 2.x / 3.x raw output into blocks[{text, bbox, confidence}]."""
    if raw is None:
        return []
    if isinstance(raw, dict):
        return _blocks_from_mapping(raw)
    if hasattr(raw, "keys") and not isinstance(raw, (list, tuple, str, bytes)):
        try:
            return _blocks_from_mapping(dict(raw))
        except Exception:
            pass
    if isinstance(raw, (list, tuple)) and raw:
        first = raw[0]
        if isinstance(first, dict) or hasattr(first, "keys"):
            out: list[dict[str, Any]] = []
            for item in raw:
                out.extend(normalize_raw(item))
            return out
        return _blocks_from_legacy_lines(raw)
    return []


def _first_present(data: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key not in data:
            continue
        value = data[key]
        if value is not None:
            return value
    return None


def _blocks_from_mapping(data: dict[str, Any]) -> list[dict[str, Any]]:
    # Do not use `a or b` — rec_boxes is often a numpy array (truth value is ambiguous).
    texts = _to_nested(_first_present(data, ("rec_texts", "rec_text", "texts")))
    scores = _to_nested(_first_present(data, ("rec_scores", "rec_score", "scores")))
    boxes = _to_nested(_first_present(data, ("rec_boxes", "rec_polys", "dt_polys", "boxes")))
    if texts is None:
        return []
    if isinstance(texts, str):
        texts = [texts]
    texts = list(texts)
    scores_list = list(scores) if scores is not None else [None] * len(texts)
    boxes_list = list(boxes) if boxes is not None else [None] * len(texts)
    blocks: list[dict[str, Any]] = []
    for i, text in enumerate(texts):
        line = str(text or "").strip()
        if not line:
            continue
        conf = scores_list[i] if i < len(scores_list) else None
        box = boxes_list[i] if i < len(boxes_list) else None
        item: dict[str, Any] = {"text": line, "bbox": _as_xyxy(box)}
        if conf is not None:
            try:
                item["confidence"] = round(float(conf), 4)
            except (TypeError, ValueError):
                pass
        blocks.append(item)
    return blocks


def _blocks_from_legacy_lines(lines: Any) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for line in lines or []:
        if not isinstance(line, (list, tuple)) or len(line) < 2:
            continue
        box, payload = line[0], line[1]
        text = ""
        conf = None
        if isinstance(payload, (list, tuple)) and payload:
            text = str(payload[0] or "")
            if len(payload) > 1:
                conf = payload[1]
        else:
            text = str(payload or "")
        text = text.strip()
        if not text:
            continue
        item: dict[str, Any] = {"text": text, "bbox": _as_xyxy(box)}
        if conf is not None:
            try:
                item["confidence"] = round(float(conf), 4)
            except (TypeError, ValueError):
                pass
        blocks.append(item)
    return blocks


def build_result(
    blocks: list[dict[str, Any]],
    *,
    language: str,
    return_bbox: bool,
    return_confidence: bool,
) -> dict[str, Any]:
    cleaned: list[dict[str, Any]] = []
    for block in blocks:
        item = {"text": str(block.get("text") or "")}
        if return_bbox:
            item["bbox"] = list(block.get("bbox") or [0, 0, 0, 0])
        if return_confidence and block.get("confidence") is not None:
            item["confidence"] = block["confidence"]
        if item["text"]:
            cleaned.append(item)
    return {
        "engine": ENGINE_NAME,
        "model": MODEL_NAME,
        "model_version": model_version(),
        "language": language,
        "text": "".join(b["text"] for b in cleaned),
        "blocks": cleaned,
    }


class PaddleOcrEngine:
    """Lazy PP-OCRv5_server wrapper. `predict` is injectable for tests."""

    def __init__(self, predict: Callable[[bytes], Any] | None = None) -> None:
        self._predict = predict
        self._ocr: Any = None

    def _load(self) -> Any:
        if self._ocr is not None:
            return self._ocr
        try:
            from paddleocr import PaddleOCR
        except ImportError as e:
            raise OcrEngineError(
                "PaddleOCR 未安装。请在 ocr-service 容器内安装 paddleocr / paddlepaddle"
            ) from e
        kwargs: dict[str, Any] = {
            "lang": "ch",
            "ocr_version": "PP-OCRv5",
        }
        try:
            self._ocr = PaddleOCR(
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                **kwargs,
            )
        except TypeError:
            self._ocr = PaddleOCR(use_angle_cls=False, **kwargs)
        log.info("paddleocr loaded model=%s version=%s", MODEL_NAME, model_version())
        return self._ocr

    def recognize(self, image_bytes: bytes) -> list[dict[str, Any]]:
        if not image_bytes:
            raise OcrEngineError("empty image")
        if self._predict is not None:
            return normalize_raw(self._predict(image_bytes))
        ocr = self._load()
        import tempfile

        suffix = ".jpg" if image_bytes[:3] == b"\xff\xd8\xff" else ".png"
        fd, tmp_path = tempfile.mkstemp(suffix=suffix)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(image_bytes)
            raw = ocr.predict(tmp_path)
        except Exception:
            log.exception("paddle predict failed")
            raise OcrEngineError("PaddleOCR predict 失败")
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        return normalize_raw(raw)
