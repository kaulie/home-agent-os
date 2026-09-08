"""Mac Edge capability: pdf.rotate — document(PDF) 页面方向整份切换（横版/竖版）。

把一个已有的 ``type=document``（PDF）Asset 按用户要求整份转成横版或竖版：

- **判断方向**：逐页读 MediaBox（宽高）+ 页面 ``/Rotate``（90/270 时宽高对调）得
  “有效方向”。非方形页 ``宽>高=横版``、``高>宽=竖版``；``/Rotate`` 是 90/270 时
  物理纸方向已对调，判断要把它算进去。
- **整份判**：全部非方形页同向 → ``portrait``/``landscape``；横竖都有 → ``mixed``；
  全为方形 → ``square``（方形页横竖等价）。
- **整份转**：对每页比较“有效方向”与目标方向，不同的页顺时针转 90°（改写页面
  ``/Rotate``，不动内容流），已同向的页不动。产物经 Brain ``/api/v1/assets/upload``
  登记为新 ``type=document`` / ``mime_type=application/pdf`` 的 Asset，返回新
  ``asset_ref``，可交给 printer.print / 其它流程。若没有需要旋转的页则直接复用原
  Asset（不重复上传）。

技术：依赖 **pypdf**（纯 Python，能解析第三方 PDF 的 xref/object stream / /Rotate）。
旋转只累加页面 ``/Rotate``，是 PDF 规范标准做法，CUPS/lp 与各家查看器打印时都会
遵守，因此转完的横版 PDF 打印出来就是横版。

对外入口：``rotate_from_params(params, *, asset, now=None)`` —— 与 file.convert /
printer.print 对齐，``asset`` 是 Runtime SDK 的 ``CapAsset`` 会话。
"""

from __future__ import annotations

import io
import logging
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger("mac_edge.pdf_rotate")

ORIENTATION_PORTRAIT = "portrait"
ORIENTATION_LANDSCAPE = "landscape"
SUPPORTED_ORIENTATIONS = frozenset({ORIENTATION_PORTRAIT, ORIENTATION_LANDSCAPE})

# 页面有效宽高差小于该值视为“方形页”（横竖方向等价，不参与旋转/判定）。
_SQUARE_TOLERANCE_PT = 0.5
# 目标方向中文文案（status_text / 失败信息）。
_ORIENTATION_LABELS = {
    ORIENTATION_PORTRAIT: "竖版",
    ORIENTATION_LANDSCAPE: "横版",
    "mixed": "横竖混合",
    "square": "方形",
}
_ORIENTATION_ALIASES = {
    "portrait": ORIENTATION_PORTRAIT,
    "竖版": ORIENTATION_PORTRAIT,
    "竖": ORIENTATION_PORTRAIT,
    "竖排": ORIENTATION_PORTRAIT,
    "竖向": ORIENTATION_PORTRAIT,
    "纵向": ORIENTATION_PORTRAIT,
    "landscape": ORIENTATION_LANDSCAPE,
    "横版": ORIENTATION_LANDSCAPE,
    "横": ORIENTATION_LANDSCAPE,
    "横排": ORIENTATION_LANDSCAPE,
    "横向": ORIENTATION_LANDSCAPE,
}




class PdfRotateError(Exception):
    """pdf.rotate 明确中文失败（缺参 / 非 document / 读不了 / 旋转失败）。"""


def pypdf_available() -> bool:
    """True when pypdf is importable（广告 local.pdf.rotate 前探测用）。"""
    try:
        import pypdf  # noqa: F401

        return True
    except Exception:  # pragma: no cover - 缺依赖分支
        return False


def parse_orientation(raw: Any) -> str:
    """把入参归一化为 portrait / landscape；无法识别则中文失败。

    接受英文（portrait/landscape）与中文别名（竖版/横版/竖向/横向…）。
    """
    text = str(raw or "").strip().lower()
    if not text:
        raise PdfRotateError("pdf.rotate 缺少必填 orientation（portrait=竖版 / landscape=横版）")
    hit = _ORIENTATION_ALIASES.get(text)
    if hit is not None:
        return hit
    # 兼容个别变体（去掉下划线/空格后再次匹配）。
    for alias, canonical in _ORIENTATION_ALIASES.items():
        if alias and text.replace(" ", "").replace("_", "") == alias.replace(" ", "").replace("_", ""):
            return canonical
    raise PdfRotateError(
        f"orientation 无法识别：{raw!r}（可用 landscape=横版 / portrait=竖版，"
        "也接受 横版/竖版/横向/竖向 等）"
    )


def orientation_label(orientation: str) -> str:
    """方向 → 中文（portrait→竖版 / landscape→横版 / mixed→横竖混合 / square→方形）。"""
    return _ORIENTATION_LABELS.get(str(orientation or "").strip(), str(orientation or "").strip())


# ---------------------------------------------------------------------------
# 方向判定（读 MediaBox + /Rotate）
# ---------------------------------------------------------------------------

def page_effective_size(page: Any) -> tuple[float, float]:
    """页面“有效宽高”：MediaBox 宽高再按 /Rotate(90/270) 对调。

    pypdf 的 ``page.mediabox`` 是不含旋转的声明框；查看/打印时页面按 /Rotate
    顺时针旋转显示，所以 90/270 时有效宽高要互换才是实际出纸方向。
    """
    mediabox = page.mediabox
    width = float(mediabox.width)
    height = float(mediabox.height)
    if width <= 0 or height <= 0:
        raise PdfRotateError(f"页面 MediaBox 宽高无效：{width}×{height}")
    rot = int(page.get("/Rotate", 0) or 0) % 360
    if rot in (90, 270):
        width, height = height, width
    return width, height


def page_orientation(page: Any) -> str:
    """单页有效方向：landscape / portrait / square。"""
    width, height = page_effective_size(page)
    if abs(width - height) <= _SQUARE_TOLERANCE_PT:
        return "square"
    return ORIENTATION_LANDSCAPE if width > height else ORIENTATION_PORTRAIT


def classify_pages(per_page: list[str]) -> str:
    """整份判：portrait / landscape / mixed / square。

    方形页横竖等价，不参与“整份”方向；只看非方形页集合：
    - 空（全方形）→ square
    - 只有竖版 → portrait；只有横版 → landscape
    - 横竖都有 → mixed
    """
    orient_set = {o for o in per_page if o != "square"}
    if not orient_set:
        return "square"
    if orient_set == {ORIENTATION_PORTRAIT}:
        return ORIENTATION_PORTRAIT
    if orient_set == {ORIENTATION_LANDSCAPE}:
        return ORIENTATION_LANDSCAPE
    return "mixed"


def plan_rotation(per_page: list[str], target: str) -> list[int]:
    """需要顺时针转 90° 的页下标：有效方向 ≠ 目标且非方形页。"""
    target = parse_orientation(target)
    return [i for i, o in enumerate(per_page) if o not in ("square", target)]


# ---------------------------------------------------------------------------
# PDF 读取 / 旋转 / 写出
# ---------------------------------------------------------------------------

def read_pdf_orientations(path: Path) -> tuple[int, list[str]]:
    """读 PDF 页数 + 每页有效方向；文件打不开/无页明确中文失败。"""
    try:
        from pypdf import PdfReader
    except Exception as e:  # pragma: no cover - 缺依赖分支
        raise PdfRotateError(f"本机未安装 pypdf，无法执行 pdf.rotate：{e}") from e
    try:
        reader = PdfReader(str(path))
    except Exception as e:
        raise PdfRotateError(f"无法读取 PDF：{e}") from e
    if reader.is_encrypted:
        raise PdfRotateError("该 PDF 已加密，无法读取页面信息")
    page_count = len(reader.pages)
    if page_count == 0:
        raise PdfRotateError("该 PDF 没有任何页面，无法旋转")
    per_page: list[str] = []
    for i, page in enumerate(reader.pages):
        try:
            per_page.append(page_orientation(page))
        except Exception as e:
            raise PdfRotateError(f"解析第 {i + 1} 页方向失败：{e}") from e
    return page_count, per_page


def rotate_pdf_bytes(path: Path, pages_to_rotate: list[int]) -> bytes:
    """把指定页顺时针旋转 90°，输出新 PDF 字节（不动其它页内容流）。"""
    try:
        from pypdf import PdfReader, PdfWriter
    except Exception as e:  # pragma: no cover - 缺依赖分支
        raise PdfRotateError(f"本机未安装 pypdf，无法执行 pdf.rotate：{e}") from e
    try:
        reader = PdfReader(str(path))
    except Exception as e:
        raise PdfRotateError(f"无法读取 PDF：{e}") from e
    try:
        for idx in pages_to_rotate:
            if not 0 <= idx < len(reader.pages):
                raise PdfRotateError(f"页下标越界：{idx}")
            page = reader.pages[idx]
            rotator = getattr(page, "rotate", None) or getattr(page, "rotate_clockwise", None)
            if rotator is None:  # pragma: no cover - pypdf>=4 必有 rotate()
                raise PdfRotateError("当前 pypdf 版本不支持页面旋转")
            rotator(90)
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        buf = io.BytesIO()
        writer.write(buf)
        return buf.getvalue()
    except PdfRotateError:
        raise
    except Exception as e:
        raise PdfRotateError(f"旋转 PDF 失败：{e}") from e


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------

def _safe_pdf_filename(raw: Any, *, suffix: str, ts: datetime) -> str:
    """Brain 文件名白名单 [A-Za-z0-9\\u4e00-\\u9fff_-] + .pdf。"""
    text = str(raw or "").strip()
    if text:
        text = Path(text.replace("\\", "/")).name.strip()
        text = re.sub(r"\.[Pp][Dd][Ff]$", "", text)
    if not text:
        text = f"pdf-rotate-{ts.strftime('%Y%m%d-%H%M%S')}-{suffix}"
    cleaned = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff_-]", "-", text)
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    if not cleaned:
        cleaned = f"pdf-rotate-{ts.strftime('%Y%m%d-%H%M%S')}-{suffix}"
    if len(cleaned) > 80:
        cleaned = cleaned[:80].rstrip("-")
    return f"{cleaned}.pdf"


# ---------------------------------------------------------------------------
# 能力入口
# ---------------------------------------------------------------------------

def rotate_from_params(
    params: dict[str, Any],
    *,
    asset: Any,
    now: datetime | None = None,
) -> tuple[str, dict[str, Any]]:
    """Capability entry：校验 → 物化 PDF → 整份判向 → 旋转并回传新 Asset。"""
    from mac_edge.asset.types import AssetError

    if asset is None or not (
        hasattr(asset, "require_ref")
        and hasattr(asset, "materialize_file")
        and hasattr(asset, "upload_file")
    ):
        raise PdfRotateError("pdf.rotate 需要 CapAsset（Runtime SDK）")

    raw_params = params if isinstance(params, dict) else {}
    target = parse_orientation(raw_params.get("orientation"))

    try:
        ref = asset.require_ref(raw_params, "asset_ref")
    except AssetError as e:
        raise PdfRotateError(f"pdf.rotate 缺少或无效的 asset_ref：{e}") from e
    if str(ref.type or "").strip() != "document":
        raise PdfRotateError(
            f"pdf.rotate 只接受 type=document 的 Asset（PDF），收到 type={ref.type!r}"
        )

    try:
        local_path = asset.materialize_file(ref)
    except AssetError as e:
        raise PdfRotateError(f"无法物化待旋转 PDF：{e}") from e
    path = Path(local_path)
    if not path.is_file():
        raise PdfRotateError(f"待旋转 PDF 文件不存在：{path}")

    page_count, per_page = read_pdf_orientations(path)
    source = classify_pages(per_page)
    to_rotate = plan_rotation(per_page, target)
    ts = now or datetime.now()

    # 无需旋转 → 复用原 Asset，不重复上传。
    if not to_rotate:
        status_text = _noop_status(source, target, page_count, ref.asset_id)
        outputs: dict[str, Any] = {
            "asset_ref": ref.to_dict(),
            "page_count": page_count,
            "source_orientation": source,
            "target_orientation": target,
            "rotated_pages": 0,
            "status_text": status_text,
        }
        log.info(
            "pdf.rotate noop asset=%s source=%s target=%s pages=%s",
            ref.asset_id,
            source,
            target,
            page_count,
        )
        return f"pdf.rotate noop source={source} pages={page_count}", outputs

    pdf_bytes = rotate_pdf_bytes(path, to_rotate)
    rotated_count = len(to_rotate)

    suffix = _ORIENTATION_LABELS.get(target, target)
    pdf_name = _safe_pdf_filename(raw_params.get("name"), suffix=suffix, ts=ts)
    fd, tmp_name = tempfile.mkstemp(prefix="pdf-rotate-", suffix=".pdf")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(pdf_bytes)
        try:
            out_ref = asset.upload_file(
                tmp_path,
                producer="pdf.rotate",
                mime_type="application/pdf",
                asset_type="document",
                filename=pdf_name,
            )
        except AssetError as e:
            raise PdfRotateError(f"旋转后 PDF 上传登记失败：{e}") from e
    finally:
        tmp_path.unlink(missing_ok=True)

    status_text = (
        f"已把整份 PDF 从{orientation_label(source)}转为{orientation_label(target)}"
        f"（共 {page_count} 页，旋转 {rotated_count} 页），"
        f"已登记为 document Asset {out_ref.asset_id}"
    )
    outputs = {
        "asset_ref": out_ref.to_dict(),
        "page_count": page_count,
        "source_orientation": source,
        "target_orientation": target,
        "rotated_pages": rotated_count,
        "status_text": status_text,
    }
    log.info(
        "pdf.rotate ok asset=%s source=%s target=%s pages=%s rotated=%s out=%s name=%s",
        ref.asset_id,
        source,
        target,
        page_count,
        rotated_count,
        out_ref.asset_id,
        pdf_name,
    )
    return (
        f"pdf.rotate ok pdf_asset={out_ref.asset_id} pages={page_count} rotated={rotated_count}",
        outputs,
    )


def _noop_status(source: str, target: str, page_count: int, asset_id: str) -> str:
    """无需旋转时的中文 status_text（含方形页 / 已是目标方向两种情况）。"""
    if source == "square":
        return (
            f"该 PDF 页面均为正方形（{page_count} 页），横竖方向等价，无需旋转；"
            f"沿用原 document Asset {asset_id}"
        )
    return (
        f"该 PDF 已是{orientation_label(source)}（{page_count} 页），无需旋转；"
        f"沿用原 document Asset {asset_id}"
    )


