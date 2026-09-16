"""Mac Edge capability: pdf.reader — PDF 文字朗读成可播放 TTS 音频。

把已有 ``type=document``（PDF）Asset 指定页范围（缺省整份）的文字经 PyMuPDF 抽出来
（复用共享底层 ``mac_edge.plugins.pdf_render``），再用共享合成底层
``mac_edge.plugins.tts_file`` 合成为**一段音频**（edge-tts 神经音色 mp3；失败自动
回退 macOS ``say`` AAC），上传 Brain 登记为 **audio Asset**，产出 ``asset_ref``：

- 语音入口的默认交付：规划把 presentation 设为 ``{type: audio, from: asset_ref}``，
  Brain 组装后发出端（iPhone 等）直接播放这段音频；
- 也可交下游继续复用（转存、投设备、再合成等）。

本能力 **只抽文字 + 合成 + 登记音频**：不投屏、不打印、不 OCR、不播放到音箱、
不改原 PDF。扫描件（无文字层）→ 明确中文失败，提示先 ``pdf.to_images`` + ``image.ocr``。

对外入口：``read_from_params(params, *, asset, ...)`` —— 与 ``pdf.to_images`` /
``file.convert`` 对齐，``asset`` 是 Runtime SDK 的 ``CapAsset`` 会话。
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Callable

from mac_edge.plugins.pdf_render import (
    PdfRenderError,
    extract_page_texts,
    normalize_page_range,
    pdf_page_count,
    pymupdf_available,
)
from mac_edge.plugins.tts_file import (
    TtsFileError,
    TtsResult,
    synthesize_speech,
    tts_available,
    truncate_text,
)

log = logging.getLogger("mac_edge.pdf_reader")

# 单次朗读页数安全上限（防整份超大 PDF 合成超时；文案提示缩小页范围）。
MAX_READ_PAGES = 200
# 单次合成字数上限（默认约 40 分钟语音）：入参 max_chars=0 表示不截断。
DEFAULT_MAX_CHARS = 12000
_PREVIEW_CHARS = 80

_MIME_EXT = {"audio/mpeg": ".mp3", "audio/mp4": ".m4a"}


class PdfReaderError(Exception):
    """pdf.reader 明确中文失败（缺参 / 非 document / 读不了 / 无文字 / 合成失败）。"""


def pdf_reader_available() -> bool:
    """本机能不能朗读：PyMuPDF 可导入（抽文字）+ 有可用 TTS 引擎。"""
    return pymupdf_available() and tts_available()


def _max_chars(raw: Any) -> int:
    """入参 max_chars 归一化（0 = 不截断）；缺省取 env 或 DEFAULT_MAX_CHARS。"""
    text = str(raw if raw is not None else "").strip()
    if text:
        try:
            value = int(float(text))
        except (TypeError, ValueError) as e:
            raise PdfReaderError(f"max_chars 必须是数字：{raw!r}") from e
        if value < 0:
            raise PdfReaderError(f"max_chars 不能为负数：{raw!r}")
        return value
    env = (os.environ.get("MAC_EDGE_PDF_READER_MAX_CHARS") or "").strip()
    if env:
        try:
            value = int(float(env))
            if value >= 0:
                return value
        except ValueError:
            log.warning("invalid MAC_EDGE_PDF_READER_MAX_CHARS=%r — use default", env)
    return DEFAULT_MAX_CHARS


def _clean_page_text(raw: str) -> str:
    """页文字规整：统一换行、压空格、去空行（换行保留为句子边界，供 TTS 断句）。"""
    text = str(raw or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t\u3000]+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def _safe_stem(raw: Any, *, fallback: str) -> str:
    text = str(raw or "").strip()
    if text:
        text = Path(text.replace("\\", "/")).name.strip()
        text = re.sub(r"\.[Pp][Dd][Ff]$", "", text)
    cleaned = re.sub(r"[^A-Za-z0-9一-鿿_-]", "-", text)
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    if not cleaned:
        cleaned = fallback
    return cleaned[:60].rstrip("-") or fallback


def _work_dir(asset_id: str) -> Path:
    root = (os.environ.get("MAC_EDGE_DATA_DIR") or "").strip()
    if root:
        base = Path(root) / "pdf-reader"
    else:
        base = Path(tempfile.gettempdir()) / "mac-edge-pdf-reader"
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "-", str(asset_id or "").strip()) or "pdf"
    return base / cleaned


def _fmt_duration(seconds: float | None) -> str:
    if not seconds or seconds <= 0:
        return "时长未知"
    total = int(round(seconds))
    if total < 60:
        return f"约 {total} 秒"
    return f"约 {total // 60} 分 {total % 60} 秒"


def _preview(text: str) -> str:
    body = re.sub(r"\s+", " ", (text or "")).strip()
    if len(body) <= _PREVIEW_CHARS:
        return body
    return body[:_PREVIEW_CHARS] + "…"


def _default_extract(pdf_path: Path, *, start: int, end: int) -> list[str]:
    return extract_page_texts(pdf_path, start=start, end=end)


def read_from_params(
    params: dict[str, Any],
    *,
    asset: Any,
    extract_fn: Callable[..., list[str]] | None = None,
    synthesize_fn: Callable[..., TtsResult] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Capability entry：校验 → 物化 PDF → 抽文字 → 合成音频 → 登记 audio Asset。"""
    from mac_edge.asset.types import AssetError

    if asset is None or not (
        hasattr(asset, "require_ref")
        and hasattr(asset, "materialize_file")
        and hasattr(asset, "upload_file")
    ):
        raise PdfReaderError("pdf.reader 需要 CapAsset（Runtime SDK）")

    raw_params = params if isinstance(params, dict) else {}
    try:
        ref = asset.require_ref(raw_params, "asset_ref")
    except AssetError as e:
        raise PdfReaderError(f"pdf.reader 缺少或无效的 asset_ref：{e}") from e
    if str(ref.type or "").strip() != "document":
        raise PdfReaderError(
            f"pdf.reader 只接受 type=document 的 Asset（PDF），收到 type={ref.type!r}"
        )
    try:
        local_path = Path(asset.materialize_file(ref))
    except AssetError as e:
        raise PdfReaderError(f"无法物化待朗读 PDF：{e}") from e
    if not local_path.is_file():
        raise PdfReaderError(f"待朗读 PDF 文件不存在：{local_path}")

    try:
        page_count = pdf_page_count(local_path)
        start, end = normalize_page_range(
            raw_params.get("page_start"),
            raw_params.get("page_end"),
            page_count=page_count,
            max_pages=MAX_READ_PAGES,
            what="朗读",
        )
    except PdfRenderError as e:
        raise PdfReaderError(str(e)) from e

    extract = extract_fn or _default_extract
    try:
        raw_pages = extract(local_path, start=start, end=end)
    except PdfRenderError as e:
        raise PdfReaderError(str(e)) from e
    body = "\n".join(text for text in (_clean_page_text(p) for p in raw_pages) if text)
    if not body:
        raise PdfReaderError(
            f"PDF 第 {start}–{end} 页没有可提取的文字（可能是扫描件）：本能力不做 OCR，"
            "请先 pdf.to_images 渲染成图片，再用 image.ocr 识别"
        )

    limit = _max_chars(raw_params.get("max_chars"))
    text, truncated = truncate_text(body, limit)
    if not text:
        raise PdfReaderError("朗读失败：抽取到的文字为空")

    stem = _safe_stem(raw_params.get("name"), fallback=f"pdf-{ref.asset_id[:12]}")
    # lang 不传（None）＝按正文语言自动判定音色；显式传入仍以调用方为准
    lang = str(raw_params.get("lang") or "").strip() or None
    voice = str(raw_params.get("voice") or "").strip() or None
    backend = str(raw_params.get("backend") or "").strip().lower() or None
    synthesize = synthesize_fn or synthesize_speech
    try:
        result = synthesize(
            text,
            _work_dir(ref.asset_id),
            stem=stem,
            backend=backend,
            voice=voice,
            speed=raw_params.get("speed"),
            lang=lang,
        )
    except TtsFileError as e:
        raise PdfReaderError(str(e)) from e

    ext = _MIME_EXT.get(str(result.mime_type or ""), ".mp3")
    try:
        audio_ref = asset.upload_file(
            result.path,
            producer="pdf.reader",
            mime_type=result.mime_type,
            asset_type="audio",
            filename=f"{stem}{ext}",
        )
    except AssetError as e:
        raise PdfReaderError(f"朗读音频上传登记失败：{e}") from e

    engine_label = (
        f"{result.engine}-tts 音色 {result.voice}"
        if result.engine == "edge"
        else f"macOS {result.engine} 音色 {result.voice}"
    )
    status_text = (
        f"已朗读 PDF 第 {start}–{end} 页（共 {page_count} 页）共 {len(text)} 字，"
        f"{_fmt_duration(result.duration_sec)}（{engine_label}）"
    )
    if truncated:
        status_text += f"；已按上限 {limit} 字截断（可指定 page_start/page_end 分段朗读）"
    if result.fallback_reason:
        status_text += "；神经音色不可用，已回退本机语音"
    status_text += "。音频已登记为 audio Asset。"

    outputs: dict[str, Any] = {
        "asset_ref": audio_ref.to_dict() if hasattr(audio_ref, "to_dict") else audio_ref,
        "page_count": page_count,
        "page_start": start,
        "page_end": end,
        "chars": len(text),
        "chars_total": len(body),
        "truncated": bool(truncated),
        "duration_sec": result.duration_sec,
        "engine": result.engine,
        "voice": result.voice,
        "text_preview": _preview(text),
        "status_text": status_text,
    }
    log.info(
        "pdf.reader ok pdf_asset=%s pages=%s-%s/%s chars=%s truncated=%s engine=%s voice=%s audio=%s",
        ref.asset_id,
        start,
        end,
        page_count,
        len(text),
        truncated,
        result.engine,
        result.voice,
        getattr(audio_ref, "asset_id", "?"),
    )
    return (
        f"pdf.reader ok pdf_asset={ref.asset_id} pages={start}-{end} chars={len(text)} "
        f"audio_asset={getattr(audio_ref, 'asset_id', '?')} engine={result.engine}",
        outputs,
    )