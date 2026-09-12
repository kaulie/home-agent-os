"""Shared PDF → 高清图片渲染底层（PyMuPDF）。

被 `pdf.to_images`（整份/范围渲染成 image Assets）与 `display.pdf`
（电视投屏逐页懒渲染）两个能力复用；本身不是 wire 能力，不单独广告。

依赖 **PyMuPDF**（pip `pymupdf`，wheel 自足无系统依赖）；缺依赖时
`pymupdf_available()` 为 False（广告门控），渲染入口抛明确中文失败。
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
