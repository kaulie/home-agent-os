"""Mac Edge capability: display.pdf / display.pdf.page — PDF 投屏电视并翻页。

小米电视（澎湃 OS）等显示端经 DLNA/Cast 只能投**图片**，不能直接渲染 PDF。
本插件把 PDF 当页渲染成 PNG（渲染底层复用 `mac_edge.plugins.pdf_render`，
与 `pdf.to_images` 同源），经 ``CapAsset.upload_file`` 上传 Brain 图床登记为
image Asset（现成授权 + LAN 取链通道），再按 ``display_backend()`` 选择小米
DLNA（``xiaomi_tv_display.play_photo``）或 Cast HTTP
（``chromecast_display.cast_photo``）把当页投上电视。

翻页（``display.pdf.page``）在**本进程内会话**上推进：会话记录当前 PDF 的
asset_id / 本地路径 / 页数 / 当前页 / 已渲染页缓存。Edge 重启会话即失效，
此时翻页明确中文失败，提示先重新「把 PDF 投到电视」。

页图 Asset 授权按 intent 授予：跨 intent 翻回已显示过的页时，旧 AssetRef 在
当前 intent 下可能无读取授权，此时用已渲染的本地 PNG 在当前 intent 下重传
（同 intent 内同页不重复上传）。

对外入口：``open_from_params`` / ``page_from_params`` —— 与 display.photo /
pdf.rotate 对齐，``asset`` 是 Runtime SDK 的 ``CapAsset`` 会话。
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from mac_edge.plugins.chromecast_display import (
    DEFAULT_CAST_DISPLAY_URL,
    cast_photo,
)
from mac_edge.plugins.pdf_render import (
    PdfRenderError,
    pdf_page_count,
    render_dpi,
    render_page_png,
    render_page_region_png,
)
from mac_edge.plugins.xiaomi_tv_display import display_backend
from mac_edge.plugins.xiaomi_tv_display import play_photo as xiaomi_play_photo

log = logging.getLogger("mac_edge.pdf_display")

ACTION_NEXT = "next"
ACTION_PREV = "prev"
ACTION_GOTO = "goto"
SUPPORTED_ACTIONS = frozenset({ACTION_NEXT, ACTION_PREV, ACTION_GOTO})

_ACTION_ALIASES = {
    "next": ACTION_NEXT,
    "下一页": ACTION_NEXT,
    "下页": ACTION_NEXT,
    "往后翻": ACTION_NEXT,
    "向后翻": ACTION_NEXT,
    "翻页": ACTION_NEXT,
    "prev": ACTION_PREV,
    "previous": ACTION_PREV,
    "上一页": ACTION_PREV,
    "上页": ACTION_PREV,
    "往前翻": ACTION_PREV,
    "向前翻": ACTION_PREV,
    "goto": ACTION_GOTO,
    "翻到": ACTION_GOTO,
    "跳到": ACTION_GOTO,
    "跳转到": ACTION_GOTO,
}


ZOOM_IN = "in"
ZOOM_OUT = "out"
ZOOM_RESET = "reset"
SUPPORTED_ZOOM_ACTIONS = frozenset({ZOOM_IN, ZOOM_OUT, ZOOM_RESET})

_ZOOM_ACTION_ALIASES = {
    "in": ZOOM_IN,
    "zoom_in": ZOOM_IN,
    "放大": ZOOM_IN,
    "再放大": ZOOM_IN,
    "out": ZOOM_OUT,
    "zoom_out": ZOOM_OUT,
    "缩小": ZOOM_OUT,
    "reset": ZOOM_RESET,
    "还原": ZOOM_RESET,
    "恢复原图": ZOOM_RESET,
    "原图": ZOOM_RESET,
    "重置": ZOOM_RESET,
}

# 放大档位：中心区域 1/zoom 重渲染；dpi 随档位同比提高，输出像素恒定清晰。
ZOOM_LEVELS = (1.0, 1.5, 2.0, 3.0, 4.0)
_ZOOM_MAX_RENDER_DPI = 1200


class PdfDisplayError(Exception):
    """display.pdf / display.pdf.page / display.pdf.zoom 明确中文失败。"""


# ---------------------------------------------------------------------------
# 会话（本进程内，单会话：一台电视一个画面）
# ---------------------------------------------------------------------------


@dataclass
class _PdfSession:
    asset_id: str
    pdf_path: Path
    page_count: int
    current_page: int
    dpi: int
    work_dir: Path
    zoom: float = 1.0
    page_refs: dict[tuple[int, float], Any] = field(default_factory=dict)


_SESSION: _PdfSession | None = None
_SESSION_LOCK = threading.Lock()


def current_session() -> _PdfSession | None:
    """当前 PDF 投屏会话（观测 / 测试用）。"""
    return _SESSION


def reset_session() -> None:
    """清掉当前会话与渲染目录（测试 / 显式重置用）。"""
    global _SESSION
    with _SESSION_LOCK:
        old = _SESSION
        _SESSION = None
    if old is not None:
        shutil.rmtree(old.work_dir, ignore_errors=True)


def _safe_dir_name(asset_id: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "-", str(asset_id or "").strip())
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    return cleaned or "pdf"


def _session_work_dir(asset_id: str) -> Path:
    root = (os.environ.get("MAC_EDGE_DATA_DIR") or "").strip()
    if root:
        base = Path(root) / "pdf-display"
    else:
        base = Path(tempfile.gettempdir()) / "mac-edge-pdf-display"
    return base / _safe_dir_name(asset_id)


# ---------------------------------------------------------------------------
# 参数解析
# ---------------------------------------------------------------------------


def parse_page_number(raw: Any, *, required: bool = False) -> int | None:
    """1-based 页码；非法输入中文失败。required=False 且缺省时返回 None。"""
    text = str(raw if raw is not None else "").strip()
    if not text:
        if required:
            raise PdfDisplayError("缺少必填 page（1-based 页码，如 page=5）")
        return None
    try:
        page = int(float(text))
    except (TypeError, ValueError) as e:
        raise PdfDisplayError(f"page 必须是数字：{raw!r}") from e
    if page < 1:
        raise PdfDisplayError(f"page 必须 ≥ 1：{raw!r}")
    return page


def parse_page_action(raw: Any) -> str:
    """翻页动作归一化：next / prev / goto；接受 下一页/上一页/翻到 等中文别名。"""
    text = str(raw if raw is not None else "").strip().lower()
    if not text:
        return ACTION_NEXT
    hit = _ACTION_ALIASES.get(text)
    if hit is not None:
        return hit
    compact = text.replace(" ", "").replace("_", "")
    for alias, canonical in _ACTION_ALIASES.items():
        if alias and compact == alias.replace(" ", "").replace("_", ""):
            return canonical
    raise PdfDisplayError(
        f"action 无法识别：{raw!r}（可用 next=下一页 / prev=上一页 / goto=翻到第 N 页，"
        "也接受 下一页/上一页/翻到 等）"
    )


def parse_zoom_action(raw: Any) -> str:
    """缩放动作归一化：in / out / reset；接受 放大/缩小/还原 等中文别名。"""
    text = str(raw if raw is not None else "").strip().lower()
    if not text:
        return ZOOM_IN
    hit = _ZOOM_ACTION_ALIASES.get(text)
    if hit is not None:
        return hit
    compact = text.replace(" ", "").replace("_", "")
    for alias, canonical in _ZOOM_ACTION_ALIASES.items():
        if alias and compact == alias.replace(" ", "").replace("_", ""):
            return canonical
    raise PdfDisplayError(
        f"action 无法识别：{raw!r}（可用 in=放大 / out=缩小 / reset=还原，"
        "也接受 放大/缩小/还原 等）"
    )


def _zoom_step_up(zoom: float) -> float:
    for level in ZOOM_LEVELS:
        if level > zoom + 1e-9:
            return level
    return ZOOM_LEVELS[-1]


def _zoom_step_down(zoom: float) -> float:
    for level in reversed(ZOOM_LEVELS):
        if level < zoom - 1e-9:
            return level
    return ZOOM_LEVELS[0]


def _zoom_render_dpi(session: "_PdfSession", zoom: float) -> int:
    """放大时 dpi 同比提高，输出像素尺寸与整页一致（清晰不糊）。"""
    return min(int(round(session.dpi * max(1.0, zoom))), _ZOOM_MAX_RENDER_DPI)


# ---------------------------------------------------------------------------
# 投屏后端（与 executor 的 display.photo 分支同一套选择逻辑）
# ---------------------------------------------------------------------------


def _display_photo(
    url: str,
    *,
    display_base_url: str,
    timeout_sec: float,
) -> str:
    if display_backend() == "xiaomi":
        return xiaomi_play_photo(url, timeout_sec=timeout_sec)
    return cast_photo(
        url,
        display_base_url=display_base_url,
        timeout_sec=timeout_sec,
    )


# ---------------------------------------------------------------------------
# 页图：渲染 → 上传 → LAN URL（会话内缓存；跨 intent 授权失效时重传）
# ---------------------------------------------------------------------------


def _zoom_token(zoom: float) -> str:
    """zoom 文件名标记：Brain 上传校验只允许字母/数字/中文/-/_，小数点换成 p（1.5 → 1p5）。"""
    return f"{zoom:g}".replace(".", "p")


def _page_cache_stem(page: int, zoom: float) -> str:
    if zoom > 1.0:
        return f"page-{page}-z{_zoom_token(zoom)}"
    return f"page-{page}"


def _ensure_rendered(
    session: _PdfSession,
    page: int,
    *,
    zoom: float = 1.0,
    render_fn: Callable[[Path, int, int, Path], Path] | None = None,
    region_render_fn: Callable[[Path, int, float, int, Path], Path] | None = None,
) -> Path:
    """本页（或本页放大区域）PNG 本地路径；未渲染则渲染（render fns 可注入，便于无 pymupdf 单测）。"""
    out_path = session.work_dir / f"{_page_cache_stem(page, zoom)}.png"
    if out_path.is_file() and out_path.stat().st_size > 0:
        return out_path
    if zoom > 1.0:
        dpi = _zoom_render_dpi(session, zoom)
        if region_render_fn is not None:
            produced = region_render_fn(session.pdf_path, page - 1, zoom, dpi, out_path)
            produced_path = Path(produced) if produced else out_path
            if not produced_path.is_file() or produced_path.stat().st_size <= 0:
                raise PdfDisplayError(f"渲染第 {page} 页放大区域失败：未产出图片")
            return produced_path
        try:
            return render_page_region_png(
                session.pdf_path, page - 1, zoom=zoom, dpi=dpi, out_path=out_path
            )
        except PdfRenderError as e:
            raise PdfDisplayError(str(e)) from e
    if render_fn is not None:
        produced = render_fn(session.pdf_path, page - 1, session.dpi, out_path)
        produced_path = Path(produced) if produced else out_path
        if not produced_path.is_file() or produced_path.stat().st_size <= 0:
            raise PdfDisplayError(f"渲染第 {page} 页失败：未产出图片")
        return produced_path
    try:
        return render_page_png(
            session.pdf_path, page - 1, dpi=session.dpi, out_path=out_path
        )
    except PdfRenderError as e:
        raise PdfDisplayError(str(e)) from e


def _upload_page(
    session: _PdfSession,
    page: int,
    png_path: Path,
    *,
    asset: Any,
    zoom: float = 1.0,
) -> Any:
    from mac_edge.asset.types import AssetError

    zoom_suffix = f"-z{_zoom_token(zoom)}" if zoom > 1.0 else ""
    filename = f"pdf-page-{_safe_dir_name(session.asset_id)[:24]}-p{page}{zoom_suffix}.png"
    try:
        return asset.upload_file(
            png_path,
            producer="display.pdf",
            mime_type="image/png",
            asset_type="image",
            filename=filename,
        )
    except AssetError as e:
        raise PdfDisplayError(f"第 {page} 页图片上传登记失败：{e}") from e


def _page_url(
    session: _PdfSession,
    page: int,
    *,
    asset: Any,
    zoom: float = 1.0,
    render_fn: Callable[[Path, int, int, Path], Path] | None = None,
    region_render_fn: Callable[[Path, int, float, int, Path], Path] | None = None,
) -> str:
    """当页（或放大区域）LAN URL：会话缓存命中直接取链；授权失效 / 未传过则（重）上传。"""
    from mac_edge.asset.types import AssetError

    cache_key = (page, zoom)
    ref = session.page_refs.get(cache_key)
    if ref is not None:
        try:
            return asset.http_url(ref)
        except AssetError:
            # 页图 Asset 授权按 intent 授予；跨 intent 翻回旧页时重传。
            session.page_refs.pop(cache_key, None)
            log.info(
                "pdf display: page %s zoom=%s ref grant stale under intent %s — re-upload",
                page,
                zoom,
                getattr(asset, "intent_id", ""),
            )
    png = _ensure_rendered(
        session, page, zoom=zoom, render_fn=render_fn, region_render_fn=region_render_fn
    )
    ref = _upload_page(session, page, png, asset=asset, zoom=zoom)
    session.page_refs[cache_key] = ref
    try:
        return asset.http_url(ref)
    except AssetError as e:
        raise PdfDisplayError(f"第 {page} 页图片取链失败：{e}") from e


def _show_page(
    session: _PdfSession,
    page: int,
    *,
    asset: Any,
    display_base_url: str,
    timeout_sec: float,
    zoom: float = 1.0,
    display_fn: Callable[[str], str] | None = None,
    render_fn: Callable[[Path, int, int, Path], Path] | None = None,
    region_render_fn: Callable[[Path, int, float, int, Path], Path] | None = None,
) -> str:
    url = _page_url(
        session, page, asset=asset, zoom=zoom, render_fn=render_fn, region_render_fn=region_render_fn
    )
    if display_fn is not None:
        return display_fn(url)
    return _display_photo(
        url,
        display_base_url=display_base_url,
        timeout_sec=timeout_sec,
    )


def _require_cap_asset(asset: Any) -> None:
    if asset is None or not (
        hasattr(asset, "require_ref")
        and hasattr(asset, "materialize_file")
        and hasattr(asset, "upload_file")
        and hasattr(asset, "http_url")
    ):
        raise PdfDisplayError("display.pdf 需要 CapAsset（Runtime SDK）")


# ---------------------------------------------------------------------------
# 能力入口
# ---------------------------------------------------------------------------


def open_from_params(
    params: dict[str, Any],
    *,
    asset: Any,
    display_base_url: str = DEFAULT_CAST_DISPLAY_URL,
    timeout_sec: float = 60.0,
    display_fn: Callable[[str], str] | None = None,
    render_fn: Callable[[Path, int, int, Path], Path] | None = None,
) -> tuple[str, dict[str, Any]]:
    """display.pdf：物化 PDF → 建新会话 → 渲染并投屏目标页（默认第 1 页）。"""
    from mac_edge.asset.types import AssetError

    _require_cap_asset(asset)
    raw_params = params if isinstance(params, dict) else {}
    try:
        ref = asset.require_ref(raw_params, "asset_ref")
    except AssetError as e:
        raise PdfDisplayError(f"display.pdf 缺少或无效的 asset_ref：{e}") from e
    if str(ref.type or "").strip() != "document":
        raise PdfDisplayError(
            f"display.pdf 只接受 type=document 的 Asset（PDF），收到 type={ref.type!r}"
        )
    try:
        local_path = Path(asset.materialize_file(ref))
    except AssetError as e:
        raise PdfDisplayError(f"无法物化待投屏 PDF：{e}") from e
    if not local_path.is_file():
        raise PdfDisplayError(f"待投屏 PDF 文件不存在：{local_path}")

    try:
        page_count = pdf_page_count(local_path)
    except PdfRenderError as e:
        raise PdfDisplayError(str(e)) from e
    page = parse_page_number(raw_params.get("page")) or 1
    clamped = max(1, min(page, page_count))

    global _SESSION
    with _SESSION_LOCK:
        old = _SESSION
        work_dir = _session_work_dir(ref.asset_id)
        session = _PdfSession(
            asset_id=ref.asset_id,
            pdf_path=local_path,
            page_count=page_count,
            current_page=clamped,
            dpi=render_dpi(),
            work_dir=work_dir,
        )
        _SESSION = session
    if old is not None and old.work_dir != work_dir:
        shutil.rmtree(old.work_dir, ignore_errors=True)

    msg = _show_page(
        session,
        clamped,
        asset=asset,
        display_base_url=display_base_url,
        timeout_sec=timeout_sec,
        display_fn=display_fn,
        render_fn=render_fn,
    )
    status_text = f"已把 PDF 投到电视，第 {clamped} 页 / 共 {page_count} 页"
    if clamped != page:
        status_text = (
            f"第 {page} 页超出范围（共 {page_count} 页），"
            f"已投屏第 {clamped} 页"
        )
    outputs: dict[str, Any] = {
        "page": clamped,
        "page_count": page_count,
        "asset_id": ref.asset_id,
        "status_text": status_text,
    }
    log.info(
        "display.pdf ok asset=%s page=%s/%s dpi=%s",
        ref.asset_id,
        clamped,
        page_count,
        session.dpi,
    )
    return f"{msg} · display.pdf page={clamped}/{page_count}", outputs


def page_from_params(
    params: dict[str, Any],
    *,
    asset: Any,
    display_base_url: str = DEFAULT_CAST_DISPLAY_URL,
    timeout_sec: float = 60.0,
    display_fn: Callable[[str], str] | None = None,
    render_fn: Callable[[Path, int, int, Path], Path] | None = None,
) -> tuple[str, dict[str, Any]]:
    """display.pdf.page：在当前会话上翻页（next/prev/goto）。"""
    _require_cap_asset(asset)
    raw_params = params if isinstance(params, dict) else {}
    session = current_session()
    if session is None or not session.pdf_path.is_file():
        raise PdfDisplayError(
            "当前没有正在投屏的 PDF（可能已重启），请先说「把这份 PDF 投到电视」"
        )
    action = parse_page_action(raw_params.get("action"))
    if action == ACTION_GOTO:
        target = parse_page_number(raw_params.get("page"), required=True)
        assert target is not None
        if target > session.page_count:
            raise PdfDisplayError(
                f"第 {target} 页超出范围（共 {session.page_count} 页）"
            )
    elif action == ACTION_PREV:
        target = session.current_page - 1
    else:
        target = session.current_page + 1

    if target < 1:
        status_text = f"已经是第一页（共 {session.page_count} 页）"
        return status_text, {
            "page": session.current_page,
            "page_count": session.page_count,
            "asset_id": session.asset_id,
            "status_text": status_text,
        }
    if target > session.page_count:
        status_text = f"已经是最后一页（第 {session.current_page} 页 / 共 {session.page_count} 页）"
        return status_text, {
            "page": session.current_page,
            "page_count": session.page_count,
            "asset_id": session.asset_id,
            "status_text": status_text,
        }

    # 翻页回到整页视图（缩放状态不跨页保留）
    session.zoom = 1.0
    msg = _show_page(
        session,
        target,
        asset=asset,
        display_base_url=display_base_url,
        timeout_sec=timeout_sec,
        zoom=1.0,
        display_fn=display_fn,
        render_fn=render_fn,
    )
    session.current_page = target
    status_text = f"已翻到第 {target} 页 / 共 {session.page_count} 页"
    outputs: dict[str, Any] = {
        "page": target,
        "page_count": session.page_count,
        "asset_id": session.asset_id,
        "status_text": status_text,
    }
    log.info(
        "display.pdf.page ok asset=%s action=%s page=%s/%s",
        session.asset_id,
        action,
        target,
        session.page_count,
    )
    return f"{msg} · display.pdf.page page={target}/{session.page_count}", outputs


def zoom_from_params(
    params: dict[str, Any],
    *,
    asset: Any,
    display_base_url: str = DEFAULT_CAST_DISPLAY_URL,
    timeout_sec: float = 60.0,
    display_fn: Callable[[str], str] | None = None,
    render_fn: Callable[[Path, int, int, Path], Path] | None = None,
    region_render_fn: Callable[[Path, int, float, int, Path], Path] | None = None,
) -> tuple[str, dict[str, Any]]:
    """display.pdf.zoom：在当前会话上放大/缩小/还原当前页（中心区域无损重渲染）。"""
    _require_cap_asset(asset)
    raw_params = params if isinstance(params, dict) else {}
    session = current_session()
    if session is None or not session.pdf_path.is_file():
        raise PdfDisplayError(
            "当前没有正在投屏的 PDF（可能已重启），请先说「把这份 PDF 投到电视」"
        )
    action = parse_zoom_action(raw_params.get("action"))
    old_zoom = float(session.zoom)
    if action == ZOOM_RESET:
        new_zoom = 1.0
    elif action == ZOOM_OUT:
        new_zoom = _zoom_step_down(old_zoom)
    else:
        new_zoom = _zoom_step_up(old_zoom)

    base_outputs = {
        "page": session.current_page,
        "page_count": session.page_count,
        "asset_id": session.asset_id,
    }
    if abs(new_zoom - old_zoom) < 1e-9:
        if action == ZOOM_IN:
            status_text = f"已是最大放大倍数（{old_zoom:g} 倍）"
        else:
            status_text = "已是原图大小"
        return status_text, {**base_outputs, "zoom": old_zoom, "status_text": status_text}

    session.zoom = new_zoom
    msg = _show_page(
        session,
        session.current_page,
        asset=asset,
        display_base_url=display_base_url,
        timeout_sec=timeout_sec,
        zoom=new_zoom,
        display_fn=display_fn,
        render_fn=render_fn,
        region_render_fn=region_render_fn,
    )
    where = f"第 {session.current_page} 页 / 共 {session.page_count} 页"
    if new_zoom <= 1.0:
        status_text = f"已恢复原图大小（{where}）"
    elif action == ZOOM_OUT:
        status_text = f"已缩小到 {new_zoom:g} 倍（{where}）"
    else:
        status_text = f"已放大到 {new_zoom:g} 倍（{where}）"
    outputs: dict[str, Any] = {
        **base_outputs,
        "zoom": new_zoom,
        "status_text": status_text,
    }
    log.info(
        "display.pdf.zoom ok asset=%s action=%s zoom=%s page=%s/%s",
        session.asset_id,
        action,
        new_zoom,
        session.current_page,
        session.page_count,
    )
    return f"{msg} · display.pdf.zoom zoom={new_zoom:g} page={session.current_page}/{session.page_count}", outputs
