"""共享 PDF 底层：页面渲染成图片 + 文字提取（PyMuPDF）。

被 `pdf.to_images`（整份/范围渲染成 image Assets）、`display.pdf`（电视投屏逐页
懒渲染）与 `pdf.reader`（抽文字合成朗读音频）复用；本身不是 wire 能力，不单独广告。

依赖 **PyMuPDF**（pip `pymupdf`，wheel 自足无系统依赖）；缺依赖时
`pymupdf_available()` 为 False（广告门控），各入口抛明确中文失败。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger("mac_edge.pdf_render")

DEFAULT_RENDER_DPI = 200
_MIN_DPI = 72
_MAX_DPI = 400


class PdfRenderError(Exception):
    """PDF 渲染层明确中文失败（缺依赖 / 打不开 / 加密 / 无页 / 渲染失败）。"""


def _fitz() -> Any:
    """Import PyMuPDF（1.24+ 顶名 pymupdf，旧名 fitz 兼容）；缺依赖中文失败。"""
    try:
        import pymupdf

        return pymupdf
    except ImportError:
        pass
    try:
        import fitz  # type: ignore

        return fitz
    except ImportError as e:
        raise PdfRenderError(
            f"本机未安装 PyMuPDF，无法渲染 PDF：pip install pymupdf（{e}）"
        ) from e


def pymupdf_available() -> bool:
    """True when PyMuPDF is importable（广告 pdf.to_images / display.pdf 前探测用）。"""
    try:
        _fitz()
        return True
    except Exception:  # pragma: no cover - 缺依赖分支
        return False


def render_dpi() -> int:
    """渲染 DPI：MAC_EDGE_PDF_DISPLAY_DPI，默认 200，钳制 72–400。"""
    raw = (os.environ.get("MAC_EDGE_PDF_DISPLAY_DPI") or "").strip()
    if raw:
        try:
            dpi = int(float(raw))
            return max(_MIN_DPI, min(dpi, _MAX_DPI))
        except ValueError:
            log.warning("invalid MAC_EDGE_PDF_DISPLAY_DPI=%r — use default", raw)
    return DEFAULT_RENDER_DPI


def clamp_dpi(raw: Any) -> int:
    """入参 DPI 归一化（能力入参 dpi 用）；非法值中文失败。"""
    text = str(raw if raw is not None else "").strip()
    if not text:
        return render_dpi()
    try:
        dpi = int(float(text))
    except (TypeError, ValueError) as e:
        raise PdfRenderError(f"dpi 必须是数字：{raw!r}") from e
    return max(_MIN_DPI, min(dpi, _MAX_DPI))


def pdf_page_count(path: Path) -> int:
    """读 PDF 页数；打不开 / 加密 / 无页 → 明确中文失败。"""
    fitz = _fitz()
    try:
        doc = fitz.open(str(path))
    except Exception as e:
        raise PdfRenderError(f"无法读取 PDF：{e}") from e
    try:
        if getattr(doc, "needs_pass", False) or getattr(doc, "is_encrypted", False):
            raise PdfRenderError("该 PDF 已加密，无法渲染")
        count = int(doc.page_count)
    finally:
        doc.close()
    if count <= 0:
        raise PdfRenderError("该 PDF 没有任何页面，无法渲染")
    return count


def normalize_page_range(
    raw_start: Any,
    raw_end: Any,
    *,
    page_count: int,
    max_pages: int,
    what: str = "处理",
) -> tuple[int, int]:
    """页范围归一化为 1-based 闭区间 [start, end]；缺省整份，越界钳到边界。

    非数字 / <1 / start > end / 超过 max_pages → 明确中文失败（`what` 只进文案，
    如「渲染」「朗读」）。`pdf.to_images` / `pdf.reader` 共用同一套页码语义。
    """

    def _num(raw: Any, label: str) -> int | None:
        text = str(raw if raw is not None else "").strip()
        if not text:
            return None
        try:
            value = int(float(text))
        except (TypeError, ValueError) as e:
            raise PdfRenderError(f"{label} 必须是数字：{raw!r}") from e
        if value < 1:
            raise PdfRenderError(f"{label} 必须 ≥ 1：{raw!r}")
        return value

    start = _num(raw_start, "page_start") or 1
    end = _num(raw_end, "page_end") or page_count
    start = max(1, min(start, page_count))
    end = max(1, min(end, page_count))
    if start > end:
        raise PdfRenderError(
            f"页范围无效：page_start={start} > page_end={end}（共 {page_count} 页）"
        )
    span = end - start + 1
    if span > int(max_pages):
        raise PdfRenderError(
            f"一次最多{what} {int(max_pages)} 页，当前请求 {span} 页"
            f"（第 {start}–{end} 页）；请缩小页范围"
        )
    return start, end


def extract_page_texts(pdf_path: Path, *, start: int = 1, end: int | None = None) -> list[str]:
    """按 1-based 闭区间 [start, end] 逐页提取文字，返回顺序 = 页码顺序。

    打不开 / 加密 / 无页 / 某页取字失败 → 明确中文失败。扫描件（无文字层）不报错，
    返回空串页面，由调用方判定「整份无文字」。
    """
    fitz = _fitz()
    try:
        doc = fitz.open(str(pdf_path))
    except Exception as e:
        raise PdfRenderError(f"无法读取 PDF：{e}") from e
    try:
        if getattr(doc, "needs_pass", False) or getattr(doc, "is_encrypted", False):
            raise PdfRenderError("该 PDF 已加密，无法提取文字")
        count = int(doc.page_count)
        if count <= 0:
            raise PdfRenderError("该 PDF 没有任何页面")
        first = max(1, int(start))
        last = count if end is None else max(1, min(int(end), count))
        texts: list[str] = []
        for index in range(first, last + 1):
            page = doc.load_page(index - 1)
            try:
                texts.append(str(page.get_text("text") or ""))
            except Exception as e:
                raise PdfRenderError(f"提取第 {index} 页文字失败：{e}") from e
        return texts
    finally:
        doc.close()


def render_page_png(pdf_path: Path, page_index: int, *, dpi: int, out_path: Path) -> Path:
    """把 0-based 的 page_index 渲染成 PNG 写到 out_path。"""
    fitz = _fitz()
    try:
        doc = fitz.open(str(pdf_path))
    except Exception as e:
        raise PdfRenderError(f"无法读取 PDF：{e}") from e
    try:
        if page_index < 0 or page_index >= int(doc.page_count):
            raise PdfRenderError(
                f"页下标越界：{page_index + 1}（共 {doc.page_count} 页）"
            )
        page = doc.load_page(page_index)
        pix = page.get_pixmap(dpi=int(dpi))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        pix.save(str(out_path))
    except PdfRenderError:
        raise
    except Exception as e:
        raise PdfRenderError(f"渲染第 {page_index + 1} 页失败：{e}") from e
    finally:
        doc.close()
    if not out_path.is_file() or out_path.stat().st_size <= 0:
        raise PdfRenderError(f"渲染第 {page_index + 1} 页失败：未产出图片")
    return out_path


def center_clip_for_zoom(page_rect: Any, zoom: float) -> tuple[float, float, float, float]:
    """页面中心放大裁剪区（PDF 坐标）：zoom=2 → 中心 1/2 宽高的矩形。"""
    z = max(1.0, float(zoom))
    w = float(page_rect.width) / z
    h = float(page_rect.height) / z
    cx = (float(page_rect.x0) + float(page_rect.x1)) / 2.0
    cy = (float(page_rect.y0) + float(page_rect.y1)) / 2.0
    return (cx - w / 2.0, cy - h / 2.0, cx + w / 2.0, cy + h / 2.0)


def render_page_region_png(
    pdf_path: Path,
    page_index: int,
    *,
    zoom: float,
    dpi: int,
    out_path: Path,
) -> Path:
    """把页面中心 1/zoom 区域渲染成 PNG——电视放大用。

    dpi 随 zoom 同比提高时，输出像素尺寸与整页渲染一致：电视全屏显示
    即内容放大 zoom 倍且保持清晰（矢量重渲染，非位图拉伸）。
    """
    fitz = _fitz()
    try:
        doc = fitz.open(str(pdf_path))
    except Exception as e:
        raise PdfRenderError(f"无法读取 PDF：{e}") from e
    try:
        if page_index < 0 or page_index >= int(doc.page_count):
            raise PdfRenderError(
                f"页下标越界：{page_index + 1}（共 {doc.page_count} 页）"
            )
        page = doc.load_page(page_index)
        clip = center_clip_for_zoom(page.rect, zoom)
        rect = fitz.Rect(clip) & page.rect
        if rect.is_empty or rect.width <= 0 or rect.height <= 0:
            raise PdfRenderError(f"放大裁剪区无效：zoom={zoom!r}")
        pix = page.get_pixmap(dpi=int(dpi), clip=rect)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        pix.save(str(out_path))
    except PdfRenderError:
        raise
    except Exception as e:
        raise PdfRenderError(f"渲染第 {page_index + 1} 页局部失败：{e}") from e
    finally:
        doc.close()
    if not out_path.is_file() or out_path.stat().st_size <= 0:
        raise PdfRenderError(f"渲染第 {page_index + 1} 页局部失败：未产出图片")
    return out_path
