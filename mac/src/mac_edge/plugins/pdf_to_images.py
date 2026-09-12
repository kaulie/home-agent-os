"""Mac Edge capability: pdf.to_images — PDF 每页渲染成高清图片（独立可复用）。

把已有 ``type=document``（PDF）Asset 的每页（或指定页范围）经 PyMuPDF 渲染成
PNG（渲染底层复用 ``mac_edge.plugins.pdf_render``，与 display.pdf 同源），逐页
上传 Brain 图床登记为 image Asset，产出 ``asset_refs``（顺序=页码）供下游复用：
``display.slideshow`` 轮播、逐页 OCR、``vision.ask`` 看某页、``file.convert``
重新合成等。

本能力 **只渲染登记，不投屏、不 OCR、不打印**。电视翻页场景请用
``display.pdf``（逐页懒渲染 + 会话翻页），不要经本能力整份预渲染。

对外入口：``images_from_params(params, *, asset, ...)`` —— 与 file.convert /
pdf.rotate 对齐，``asset`` 是 Runtime SDK 的 ``CapAsset`` 会话。
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
    clamp_dpi,
    pdf_page_count,
    render_page_png,
)

log = logging.getLogger("mac_edge.pdf_to_images")

# 单次渲染页数安全上限（防整份超大 PDF 打爆图床 / 超时）。
MAX_RENDER_PAGES = 200


class PdfToImagesError(Exception):
    """pdf.to_images 明确中文失败（缺参 / 非 document / 读不了 / 渲染失败）。"""


def parse_page_range(
    raw_start: Any,
    raw_end: Any,
    *,
    page_count: int,
) -> tuple[int, int]:
    """页范围归一化为 1-based 闭区间 [start, end]；缺省整份，越界钳到边界。"""
    def _num(raw: Any, label: str) -> int | None:
        text = str(raw if raw is not None else "").strip()
        if not text:
            return None
        try:
            value = int(float(text))
        except (TypeError, ValueError) as e:
            raise PdfToImagesError(f"{label} 必须是数字：{raw!r}") from e
        if value < 1:
            raise PdfToImagesError(f"{label} 必须 ≥ 1：{raw!r}")
        return value

    start = _num(raw_start, "page_start") or 1
    end = _num(raw_end, "page_end") or page_count
    start = max(1, min(start, page_count))
    end = max(1, min(end, page_count))
    if start > end:
        raise PdfToImagesError(
            f"页范围无效：page_start={start} > page_end={end}（共 {page_count} 页）"
        )
    if end - start + 1 > MAX_RENDER_PAGES:
        raise PdfToImagesError(
            f"一次最多渲染 {MAX_RENDER_PAGES} 页，当前请求 {end - start + 1} 页"
            f"（第 {start}–{end} 页）；请缩小页范围"
        )
    return start, end


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
        base = Path(root) / "pdf-to-images"
    else:
        base = Path(tempfile.gettempdir()) / "mac-edge-pdf-to-images"
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "-", str(asset_id or "").strip()) or "pdf"
    return base / cleaned


def images_from_params(
    params: dict[str, Any],
    *,
    asset: Any,
    render_fn: Callable[[Path, int, int, Path], Path] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Capability entry：校验 → 物化 PDF → 逐页渲染 → 逐页登记 image Asset。"""
    from mac_edge.asset.types import AssetError

    if asset is None or not (
        hasattr(asset, "require_ref")
        and hasattr(asset, "materialize_file")
        and hasattr(asset, "upload_file")
    ):
        raise PdfToImagesError("pdf.to_images 需要 CapAsset（Runtime SDK）")

    raw_params = params if isinstance(params, dict) else {}
    try:
        ref = asset.require_ref(raw_params, "asset_ref")
    except AssetError as e:
        raise PdfToImagesError(f"pdf.to_images 缺少或无效的 asset_ref：{e}") from e
    if str(ref.type or "").strip() != "document":
        raise PdfToImagesError(
            f"pdf.to_images 只接受 type=document 的 Asset（PDF），收到 type={ref.type!r}"
        )
    try:
        local_path = Path(asset.materialize_file(ref))
    except AssetError as e:
        raise PdfToImagesError(f"无法物化待渲染 PDF：{e}") from e
    if not local_path.is_file():
        raise PdfToImagesError(f"待渲染 PDF 文件不存在：{local_path}")

    try:
        page_count = pdf_page_count(local_path)
        dpi = clamp_dpi(raw_params.get("dpi"))
    except PdfRenderError as e:
        raise PdfToImagesError(str(e)) from e
    start, end = parse_page_range(
        raw_params.get("page_start"),
        raw_params.get("page_end"),
        page_count=page_count,
    )

    stem = _safe_stem(raw_params.get("name"), fallback=f"pdf-{ref.asset_id[:12]}")
    work = _work_dir(ref.asset_id)
    refs: list[Any] = []
    for page in range(start, end + 1):
        out_path = work / f"page-{page}.png"
        if render_fn is not None:
            produced = render_fn(local_path, page - 1, dpi, out_path)
            png = Path(produced) if produced else out_path
            if not png.is_file() or png.stat().st_size <= 0:
                raise PdfToImagesError(f"渲染第 {page} 页失败：未产出图片")
        else:
            try:
                png = render_page_png(local_path, page - 1, dpi=dpi, out_path=out_path)
            except PdfRenderError as e:
                raise PdfToImagesError(str(e)) from e
        try:
            page_ref = asset.upload_file(
                png,
                producer="pdf.to_images",
                mime_type="image/png",
                asset_type="image",
                filename=f"{stem}-p{page}.png",
            )
        except AssetError as e:
            raise PdfToImagesError(f"第 {page} 页图片上传登记失败：{e}") from e
        refs.append(page_ref)

    asset_refs = [r.to_dict() if hasattr(r, "to_dict") else r for r in refs]
    rendered = len(refs)
    status_text = (
        f"已把 PDF 第 {start}–{end} 页渲染成 {rendered} 张高清图片"
        f"（共 {page_count} 页，{dpi} DPI）"
    )
    outputs: dict[str, Any] = {
        "asset_refs": asset_refs,
        "page_count": page_count,
        "rendered_pages": rendered,
        "status_text": status_text,
    }
    log.info(
        "pdf.to_images ok asset=%s pages=%s-%s/%s dpi=%s",
        ref.asset_id,
        start,
        end,
        page_count,
        dpi,
    )
    return (
        f"pdf.to_images ok pdf_asset={ref.asset_id} pages={start}-{end} rendered={rendered}",
        outputs,
    )
