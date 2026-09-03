"""Mac Edge capability: file.convert — image(s) → PDF（纯标准库，零新增依赖）。

一期只实现 ``image → pdf``：N 张 ``type=image`` 的 Brain Asset（JPEG
baseline/sequential Huffman，或 8bit 非隔行 PNG）按 ``asset_refs`` 顺序合并成
**单文件 A4 纵向多页 PDF**（1 张 = 1 页，等比适配居中留白边），然后把产物经
Brain ``/api/v1/assets/upload`` 登记为 ``type=document`` / ``mime_type=application/pdf``
的 document Asset，返回新的 ``asset_ref``。

技术：
- JPEG 只解析 marker 取宽高，原字节作为 ``/DCTDecode`` 图像流直嵌（不解码）。
- PNG 用 stdlib ``zlib`` 还原 IDAT + 逐行 filter（0–4），alpha 在白色背景上拍平，
  以 RGB 原始像素 + ``/FlateDecode`` 入 PDF。
- 其它组合 / 变体（HEIC、WebP、隔行 PNG、16bit、渐进/算术 JPEG 等）**明确中文失败**，
  不产生脏 Asset。

对外入口：``convert_from_params(params, *, asset)`` —— 与 printer.print 对齐，
``asset`` 是 Runtime SDK 的 ``CapAsset`` 会话。
"""

from __future__ import annotations

import logging
import os
import re
import struct
import tempfile
import zlib
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger("mac_edge.file_convert")

# A4 纵向（pt）。
A4_WIDTH_PT = 595.276
A4_HEIGHT_PT = 841.89
# 默认页边距：上下/左右约 36pt（可调常量）。
PAGE_MARGIN_PT = 36.0
# 一期源格式标记。
JPEG_MAGIC = b"\xff\xd8\xff"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
SUPPORTED_FROM_FORMAT = "image"
SUPPORTED_TO_FORMAT = "pdf"


class FileConvertError(Exception):
    """file.convert 明确中文失败（校验 / 解码 / 合成 / 上传）。"""


# ---------------------------------------------------------------------------
# 通用小工具
# ---------------------------------------------------------------------------

def _fmt(v: float) -> str:
    """PT 数值：足够精度，去掉多余尾零。"""
    s = "%.4f" % float(v)
    s = s.rstrip("0").rstrip(".")
    return s or "0"


def _safe_pdf_filename(raw: Any, ts: datetime) -> str:
    """Brain 文件名白名单 [A-Za-z0-9\\u4e00-\\u9fff_-] + .pdf。"""
    text = str(raw or "").strip()
    if text:
        text = Path(text.replace("\\", "/")).name.strip()
        text = re.sub(r"\.[Pp][Dd][Ff]$", "", text)
    if not text:
        text = f"convert-{ts.strftime('%Y%m%d-%H%M%S')}"
    cleaned = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff_-]", "-", text)
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    if not cleaned:
        cleaned = f"convert-{ts.strftime('%Y%m%d-%H%M%S')}"
    if len(cleaned) > 80:
        cleaned = cleaned[:80].rstrip("-")
    return f"{cleaned}.pdf"

# ---------------------------------------------------------------------------
# 最小 PDF 书写器
# ---------------------------------------------------------------------------

def build_pdf(pages: list[dict[str, Any]]) -> bytes:
    """把若干页图像规格序列化为单文件 A4 纵向多页 PDF。

    每页元素：
      {"kind": "jpeg", "width": int, "height": int, "components": 1|3,
       "data": <原始 JPEG 字节>}
    或
      {"kind": "rgb",  "width": int, "height": int,
       "data": <width*height*3 的 RGB 字节>}

    JPEG 以 /DCTDecode 直嵌；RGB 以 /FlateDecode（zlib 压缩）入 PDF。
    """
    if not pages:
        raise FileConvertError("没有可转换的图片（asset_refs 为空）")

    ordered: dict[int, bytes] = {1: b"<< /Type /Catalog /Pages 2 0 R >>"}
    kids = " ".join(f"{3 + 3 * i} 0 R" for i in range(len(pages)))
    ordered[2] = (
        f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode("ascii")
    )

    # 对象编号分配：1 Catalog / 2 Pages / 页 i：page=3+3i, content=4+3i, image=5+3i
    for i, spec in enumerate(pages):
        width = int(spec.get("width") or 0)
        height = int(spec.get("height") or 0)
        if width <= 0 or height <= 0:
            raise FileConvertError(f"第 {i + 1} 张图片尺寸无效（{width}×{height}）")
        kind = str(spec.get("kind") or "").strip()

        # --- 图像 XObject ---
        if kind == "jpeg":
            img_data = bytes(spec.get("data") or b"")
            if not img_data:
                raise FileConvertError(f"第 {i + 1} 张 JPEG 内容为空")
            components = int(spec.get("components") or 3)
            if components not in (1, 3):
                raise FileConvertError(
                    f"第 {i + 1} 张 JPEG 颜色分量数不支持（components={components}）"
                )
            cs = "/DeviceGray" if components == 1 else "/DeviceRGB"
            img_stream = img_data
            img_dict = (
                f"<< /Type /XObject /Subtype /Image /Width {width} "
                f"/Height {height} /ColorSpace {cs} /BitsPerComponent 8 "
                f"/Filter /DCTDecode /Length {len(img_stream)} >>"
            ).encode("ascii")
        elif kind == "rgb":
            raw_rgb = bytes(spec.get("data") or b"")
            expected = width * height * 3
            if len(raw_rgb) != expected:
                raise FileConvertError(
                    f"第 {i + 1} 张图片像素数据不完整"
                    f"（期望 {expected} 字节，实际 {len(raw_rgb)}）"
                )
            img_stream = zlib.compress(raw_rgb)
            img_dict = (
                f"<< /Type /XObject /Subtype /Image /Width {width} "
                f"/Height {height} /ColorSpace /DeviceRGB /BitsPerComponent 8 "
                f"/Filter /FlateDecode /Length {len(img_stream)} >>"
            ).encode("ascii")
        else:
            raise FileConvertError(f"第 {i + 1} 张图片类型不支持：{kind!r}")

        # --- 页面几何：等比适配、居中留白 ---
        avail_w = A4_WIDTH_PT - 2 * PAGE_MARGIN_PT
        avail_h = A4_HEIGHT_PT - 2 * PAGE_MARGIN_PT
        scale = min(avail_w / width, avail_h / height)
        draw_w = width * scale
        draw_h = height * scale
        x0 = (A4_WIDTH_PT - draw_w) / 2.0
        y0 = (A4_HEIGHT_PT - draw_h) / 2.0
        op = (
            f"q {_fmt(draw_w)} 0 0 {_fmt(draw_h)} "
            f"{_fmt(x0)} {_fmt(y0)} cm /Im{i} Do Q"
        ).encode("ascii")

        page_obj = 3 + 3 * i
        content_obj = 4 + 3 * i
        image_obj = 5 + 3 * i

        content_body = b"<< /Length " + str(len(op)).encode("ascii") + (
            b" >>\nstream\n" + op + b"\nendstream"
        )
        image_body = img_dict + b"\nstream\n" + img_stream + b"\nendstream"
        page_body = (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 "
            + _fmt(A4_WIDTH_PT).encode("ascii")
            + b" "
            + _fmt(A4_HEIGHT_PT).encode("ascii")
            + (
                f"] /Resources << /XObject << /Im{i} {image_obj} 0 R >> >> "
                f"/Contents {content_obj} 0 R >>"
            ).encode("ascii")
        )
        ordered[page_obj] = page_body
        ordered[content_obj] = content_body
        ordered[image_obj] = image_body

    max_obj = 5 + 3 * (len(pages) - 1)
    out = bytearray()
    out += b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    offsets: list[int] = []
    for num in range(1, max_obj + 1):
        offsets.append(len(out))
        out += f"{num} 0 obj\n".encode("ascii")
        out += ordered[num]
        out += b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {max_obj + 1}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode("ascii")
    out += (
        f"trailer\n<< /Size {max_obj + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    ).encode("ascii")
    return bytes(out)


# ---------------------------------------------------------------------------
# JPEG：解析 marker 取宽高，仅支持 baseline/sequential Huffman
# ---------------------------------------------------------------------------

def _jpeg_info(data: bytes) -> tuple[int, int, int]:
    """返回 (width, height, components)；不支持的变体明确中文失败。"""
    if not data.startswith(b"\xff\xd8"):
        raise FileConvertError("不是有效的 JPEG 文件（缺少 SOI 标记）")
    n = len(data)
    i = 2
    while i < n - 1:
        if data[i] != 0xFF:
            i += 1
            continue
        code = data[i + 1]
        if code == 0xFF:  # 填充字节
            i += 1
            continue
        if code == 0x01 or 0xD0 <= code <= 0xD7:  # TEM / RSTn：无长度
            i += 2
            continue
        if code == 0xD8:  # 重复 SOI（异常）——继续扫
            i += 2
            continue
        if code == 0xD9:  # EOI 还没见 SOF → 缺尺寸
            break
        if i + 4 > n:
            break
        seg_len = struct.unpack_from(">H", data, i + 2)[0]
        if seg_len < 2:
            raise FileConvertError("JPEG 段长度异常，无法解析")
        if code == 0xC0 or code == 0xC1:  # SOF0 baseline / SOF1 extended sequential
            if i + 10 > n or seg_len < 8:
                raise FileConvertError("JPEG SOF 段不完整，无法解析尺寸")
            precision = data[i + 4]
            height = struct.unpack_from(">H", data, i + 5)[0]
            width = struct.unpack_from(">H", data, i + 7)[0]
            components = data[i + 9]
            if precision != 8:
                raise FileConvertError(
                    f"该 JPEG 位深 {precision} 不支持（一期仅支持 8bit baseline/顺序 JPEG）"
                )
            if width <= 0 or height <= 0:
                raise FileConvertError(f"JPEG 尺寸无效：{width}×{height}")
            if components not in (1, 3):
                raise FileConvertError(
                    f"该 JPEG 颜色分量数不支持（components={components}），"
                    "一期仅支持灰度/RGB"
                )
            return width, height, components
        if code == 0xC2:
            raise FileConvertError(
                "渐进式（progressive）JPEG 暂不支持，请使用 baseline/顺序 JPEG"
            )
        if code == 0xC9 or code == 0xCA:
            raise FileConvertError(
                "算术编码 JPEG 暂不支持，请使用 Huffman baseline/顺序 JPEG"
            )
        if code in (0xC3, 0xC5, 0xC6, 0xC7, 0xC8, 0xCB, 0xCD, 0xCE, 0xCF):
            raise FileConvertError("该 JPEG 变体（无损/分层/差分）暂不支持")
        # 其它带长度的段（APPn/DQT/DHT/DRI/SOS/COM…）：跳过
        i += 2 + seg_len
    raise FileConvertError(
        "无法解析 JPEG 尺寸（可能不是 baseline/顺序 JPEG，或文件不完整）"
    )


# ---------------------------------------------------------------------------
# PNG：chunk 解析 + filter 还原 + alpha 白色拍平 → RGB
# ---------------------------------------------------------------------------

_PNG_CT_BITDEPTH_OK = {0: {8}, 2: {8}, 3: {8}, 4: {8}, 6: {8}}
_PNG_CT_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


def _png_iter_chunks(data: bytes):
    """Yields (chunk_type: str, payload: bytes) up to IEND（含）。"""
    if not data.startswith(PNG_MAGIC):
        raise FileConvertError("不是有效的 PNG 文件（缺少 PNG 签名）")
    pos = len(PNG_MAGIC)
    n = len(data)
    while pos + 8 <= n:
        length = struct.unpack_from(">I", data, pos)[0]
        ctype = data[pos + 4:pos + 8].decode("latin1")
        if pos + 12 + length > n:
            raise FileConvertError("PNG 文件被截断，无法解析")
        payload = data[pos + 8:pos + 8 + length]
        yield ctype, payload
        if ctype == "IEND":
            return
        pos += 12 + length
    raise FileConvertError("PNG 缺少 IEND 结束块，无法解析")


def _png_to_rgb(data: bytes) -> tuple[int, int, bytes]:
    """PNG（8bit 非隔行，color type 0/2/3/4/6）→ (width, height, RGB 字节)。

    alpha 在白色背景上拍平。隔行、16bit 等变体明确中文失败。
    """
    width = height = bit_depth = color_type = 0
    interlace = 1
    palette = b""
    trns: bytes | None = None
    idat_parts: list[bytes] = []

    for ctype, payload in _png_iter_chunks(data):
        if ctype == "IHDR":
            if len(payload) < 13:
                raise FileConvertError("PNG IHDR 块不完整")
            width, height, bit_depth, color_type = struct.unpack(">IIBB", payload[:10])
            compression = payload[10]
            filter_method = payload[11]
            interlace = payload[12]
            if compression != 0 or filter_method != 0:
                raise FileConvertError("PNG 压缩/滤波方法不支持（仅标准 deflate + 方法0）")
            if bit_depth not in _PNG_CT_BITDEPTH_OK.get(color_type, set()):
                raise FileConvertError(
                    "该 PNG 的位深/颜色类型组合暂不支持"
                    "（一期仅支持 8bit、color type 0/2/3/4/6）"
                )
        elif ctype == "PLTE":
            palette = payload
        elif ctype == "tRNS":
            trns = payload
        elif ctype == "IDAT":
            idat_parts.append(payload)
        elif ctype == "IEND":
            break

    if width <= 0 or height <= 0:
        raise FileConvertError("PNG 尺寸无效")
    if interlace != 0:
        raise FileConvertError(
            "隔行（interlace）PNG 暂不支持，请使用非隔行 PNG"
        )
    channels = _PNG_CT_CHANNELS.get(color_type)
    if channels is None:
        raise FileConvertError(
            f"该 PNG 颜色类型（{color_type}）暂不支持，一期仅支持 0/2/3/4/6"
        )
    if color_type == 3 and len(palette) == 0:
        raise FileConvertError("调色板（color type 3）PNG 缺少 PLTE 块")

    try:
        raw = zlib.decompress(b"".join(idat_parts))
    except zlib.error as e:
        raise FileConvertError(f"PNG IDAT 解压失败：{e}") from e

    stride = width * channels
    expected = height * (1 + stride)
    if len(raw) < expected:
        raise FileConvertError("PNG 像素数据不完整")

    # 逐行还原 filter 0–4（8bit/像素时 bpp = channels）
    bpp = channels
    unfiltered = bytearray()
    prev = bytearray(stride)
    pos = 0
    for _ in range(height):
        fbyte = raw[pos]
        pos += 1
        line = bytearray(raw[pos:pos + stride])
        pos += stride
        if fbyte == 0:
            pass
        elif fbyte == 1:  # Sub
            for x in range(bpp, stride):
                line[x] = (line[x] + line[x - bpp]) & 0xFF
        elif fbyte == 2:  # Up
            for x in range(stride):
                line[x] = (line[x] + prev[x]) & 0xFF
        elif fbyte == 3:  # Average
            for x in range(stride):
                left = line[x - bpp] if x >= bpp else 0
                line[x] = (line[x] + ((left + prev[x]) >> 1)) & 0xFF
        elif fbyte == 4:  # Paeth
            for x in range(stride):
                a = line[x - bpp] if x >= bpp else 0
                b = prev[x]
                c = prev[x - bpp] if x >= bpp else 0
                p = a + b - c
                pa = abs(p - a)
                pb = abs(p - b)
                pc = abs(p - c)
                if pa <= pb and pa <= pc:
                    pred = a
                elif pb <= pc:
                    pred = b
                else:
                    pred = c
                line[x] = (line[x] + pred) & 0xFF
        else:
            raise FileConvertError(f"PNG 行滤波类型不支持（filter={fbyte}）")
        unfiltered += line
        prev = line

    return _png_channels_to_rgb(
        bytes(unfiltered),
        width=width,
        height=height,
        channels=channels,
        color_type=color_type,
        palette=palette,
        trns=trns,
    )


def _png_channels_to_rgb(
    pixels: bytes,
    *,
    width: int,
    height: int,
    channels: int,
    color_type: int,
    palette: bytes,
    trns: bytes | None,
) -> tuple[int, int, bytes]:
    """把还原后的原始扫描线像素展开为 RGB（alpha 在白底拍平）。"""
    out = bytearray(width * height * 3)
    gray_key: int | None = None
    rgb_key: tuple[int, int, int] | None = None
    if trns is not None:
        if color_type == 0 and len(trns) >= 2:
            gray_key = struct.unpack(">H", trns[:2])[0]
        elif color_type == 2 and len(trns) >= 6:
            rgb_key = struct.unpack(">HHH", trns[:6])
    pal_alpha: list[int] | None = None
    if color_type == 3 and trns is not None:
        pal_alpha = list(trns)

    o = 0
    for y in range(height):
        row = y * width * channels
        for x in range(width):
            base = row + x * channels
            if color_type == 0:
                g = pixels[base]
                a = 0 if gray_key == g else 255
                r = gr = b = g
            elif color_type == 2:
                r = pixels[base]
                gr = pixels[base + 1]
                b = pixels[base + 2]
                a = 0 if (r, gr, b) == rgb_key else 255
            elif color_type == 3:
                idx = pixels[base]
                p3 = 3 * idx
                if p3 + 3 > len(palette):
                    raise FileConvertError("PNG 调色板索引越界，无法解析")
                r = palette[p3]
                gr = palette[p3 + 1]
                b = palette[p3 + 2]
                a = pal_alpha[idx] if pal_alpha is not None and idx < len(pal_alpha) else 255
            elif color_type == 4:
                g = pixels[base]
                a = pixels[base + 1]
                r = gr = b = g
            else:  # color_type == 6
                r = pixels[base]
                gr = pixels[base + 1]
                b = pixels[base + 2]
                a = pixels[base + 3]
            # alpha 在白色背景上拍平
            if a <= 0:
                out[o] = out[o + 1] = out[o + 2] = 255
            elif a >= 255:
                out[o] = r
                out[o + 1] = gr
                out[o + 2] = b
            else:
                inv = 255 - a
                out[o] = (r * a + 255 * inv) // 255
                out[o + 1] = (gr * a + 255 * inv) // 255
                out[o + 2] = (b * a + 255 * inv) // 255
            o += 3
    return width, height, bytes(out)


# ---------------------------------------------------------------------------
# 解码一个图片文件 → 可入 PDF 的页规格
# ---------------------------------------------------------------------------

def _decode_image_bytes(data: bytes, *, index: int) -> dict[str, Any]:
    """按 magic 分派 JPEG/PNG 解码；不支持格式/变体明确中文失败。"""
    if not data:
        raise FileConvertError(f"第 {index + 1} 张图片内容为空")
    if data.startswith(JPEG_MAGIC):
        width, height, components = _jpeg_info(data)
        return {
            "kind": "jpeg",
            "width": width,
            "height": height,
            "components": components,
            "data": data,
        }
    if data.startswith(PNG_MAGIC):
        width, height, rgb = _png_to_rgb(data)
        return {"kind": "rgb", "width": width, "height": height, "data": rgb}
    raise FileConvertError(
        f"第 {index + 1} 张图片格式不支持（仅支持 JPEG/PNG，"
        "HEIC/WebP 等一期未接入）"
    )


def _decode_image_file(path: Path, *, index: int) -> dict[str, Any]:
    try:
        data = Path(path).read_bytes()
    except OSError as e:
        raise FileConvertError(f"读取第 {index + 1} 张图片失败：{e}") from e
    return _decode_image_bytes(data, index=index)


# ---------------------------------------------------------------------------
# 能力入口
# ---------------------------------------------------------------------------

def convert_from_params(
    params: dict[str, Any],
    *,
    asset: Any,
    now: datetime | None = None,
) -> tuple[str, dict[str, Any]]:
    """Capability entry：校验 → 取图 → 合成 PDF → 上传登记 → 输出。"""
    from mac_edge.asset.types import AssetError

    if asset is None or not (
        hasattr(asset, "require_refs")
        and hasattr(asset, "materialize_file")
        and hasattr(asset, "upload_file")
    ):
        raise FileConvertError("file.convert 需要 CapAsset（Runtime SDK）")

    raw_params = params if isinstance(params, dict) else {}

    to_format = str(raw_params.get("to_format") or "").strip().lower()
    if not to_format:
        raise FileConvertError("file.convert 缺少必填 to_format（一期仅支持 pdf）")
    if to_format != SUPPORTED_TO_FORMAT:
        raise FileConvertError(
            "file.convert 一期仅支持转换为 pdf，"
            f"收到 to_format={raw_params.get('to_format')!r}"
        )

    from_raw = raw_params.get("from_format")
    if from_raw is not None and str(from_raw).strip():
        from_format = str(from_raw).strip().lower()
        if from_format != SUPPORTED_FROM_FORMAT:
            raise FileConvertError(
                "file.convert 一期仅支持从 image 转换"
                f"（JPEG/PNG），收到 from_format={from_raw!r}"
            )

    try:
        refs = asset.require_refs(raw_params, "asset_refs")
    except AssetError as e:
        raise FileConvertError(
            f"file.convert 需要非空的 image asset_refs 数组：{e}"
        ) from e

    for i, ref in enumerate(refs):
        if str(getattr(ref, "type", "") or "").strip() != "image":
            raise FileConvertError(
                f"asset_refs[{i}] 必须是 type=image 的 Asset（JPEG/PNG），"
                f"收到 type={getattr(ref, 'type', '')!r}"
            )

    pages: list[dict[str, Any]] = []
    for i, ref in enumerate(refs):
        try:
            local_path = asset.materialize_file(ref)
        except AssetError as e:
            raise FileConvertError(
                f"无法物化第 {i + 1} 张图片（asset {ref.asset_id}）：{e}"
            ) from e
        p = Path(local_path)
        if not p.is_file():
            raise FileConvertError(f"第 {i + 1} 张图片文件不存在：{p}")
        pages.append(_decode_image_file(p, index=i))

    pdf_bytes = build_pdf(pages)

    ts = now or datetime.now()
    pdf_name = _safe_pdf_filename(raw_params.get("name"), ts=ts)
    fd, tmp_name = tempfile.mkstemp(prefix="file-convert-", suffix=".pdf")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(pdf_bytes)
        try:
            out_ref = asset.upload_file(
                tmp_path,
                producer="file.convert",
                mime_type="application/pdf",
                asset_type="document",
                filename=pdf_name,
            )
        except AssetError as e:
            raise FileConvertError(f"PDF 上传登记失败：{e}") from e
    finally:
        tmp_path.unlink(missing_ok=True)

    page_count = len(pages)
    status_text = (
        f"已把 {page_count} 张图片合成 PDF（{page_count} 页，A4），"
        f"已登记为 document Asset {out_ref.asset_id}"
    )
    outputs: dict[str, Any] = {
        "asset_ref": out_ref.to_dict(),
        "page_count": page_count,
        "status_text": status_text,
    }
    log.info(
        "file.convert ok images=%s pdf_asset=%s name=%s",
        page_count,
        out_ref.asset_id,
        pdf_name,
    )
    return f"file.convert ok pdf_asset={out_ref.asset_id} pages={page_count}", outputs

