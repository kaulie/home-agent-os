"""file.convert — image(s) → PDF：PDF 书写器 / PNG-JPEG 解码 / 契约校验 / 插件分发。

风格对齐 test_xiaomi_aio_printer.py：只用 stdlib 构造最小合法 PNG/JPEG fixture，
不断言真实渲染，只断言 PDF 结构、解码结果与中文失败文案。
"""

from __future__ import annotations

import os
import struct
import tempfile
import unittest
import zlib
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from mac_edge.asset.types import AssetError, AssetRef
from mac_edge.plugins.file_convert import (
    A4_HEIGHT_PT,
    A4_WIDTH_PT,
    FileConvertError,
    _decode_image_bytes,
    _jpeg_info,
    _png_to_rgb,
    build_pdf,
    convert_from_params,
)
from mac_edge.services import default_services


# ---------------------------------------------------------------------------
# fixture helpers (stdlib only)
# ---------------------------------------------------------------------------

def _chunk(ctype: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + ctype
        + payload
        + struct.pack(">I", zlib.crc32(ctype + payload) & 0xFFFFFFFF)
    )


def _png_bytes(
    width: int,
    height: int,
    color_type: int,
    channels: int,
    rows: list[bytes],
    *,
    bit_depth: int = 8,
    interlace: int = 0,
    palette: bytes = b"",
    trns: bytes = b"",
) -> bytes:
    """Build a minimal legal PNG (each row filter 0) from raw pixel rows."""
    scan = b"".join(b"\x00" + row for row in rows)
    out = (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, bit_depth, color_type, 0, 0, interlace))
    )
    if palette:
        out += _chunk(b"PLTE", palette)
    if trns:
        out += _chunk(b"tRNS", trns)
    out += _chunk(b"IDAT", zlib.compress(scan))
    out += _chunk(b"IEND", b"")
    return out


def _solid_png(width: int, height: int, color_type: int, channels: int, pixel: bytes, **kw) -> bytes:
    row = pixel * width
    return _png_bytes(width, height, color_type, channels, [row] * height, **kw)


def _baseline_jpeg_bytes(width: int = 4, height: int = 3, components: int = 3) -> bytes:
    """SOI + APP0 + SOF0(baseline) + EOI — 结构上可被本模块解析/直嵌。"""
    jpeg = bytearray(b"\xff\xd8")
    app0 = b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    jpeg += b"\xff\xe0" + struct.pack(">H", len(app0) + 2) + app0
    payload = struct.pack(">BHHB", 8, height, width, components)
    desc = b"".join(struct.pack(">BBB", i + 1, 0x11, 0) for i in range(components))
    jpeg += b"\xff\xc0" + struct.pack(">H", len(payload) + len(desc) + 2) + payload + desc
    jpeg += b"\xff\xd9"
    return bytes(jpeg)


def _progressive_jpeg_bytes(width: int = 4, height: int = 3) -> bytes:
    jpeg = bytearray(b"\xff\xd8")
    payload = struct.pack(">BHHB", 8, height, width, 3)
    desc = b"".join(struct.pack(">BBB", i + 1, 0x11, 0) for i in range(3))
    jpeg += b"\xff\xc2" + struct.pack(">H", len(payload) + len(desc) + 2) + payload + desc
    jpeg += b"\xff\xd9"
    return bytes(jpeg)


# ---------------------------------------------------------------------------
# 纯 PDF 书写器
# ---------------------------------------------------------------------------

class BuildPdfTests(unittest.TestCase):
    def test_jpeg_page_headers(self) -> None:
        jpeg = _baseline_jpeg_bytes()
        pdf = build_pdf(
            [{"kind": "jpeg", "width": 4, "height": 3, "components": 3, "data": jpeg}]
        )
        self.assertTrue(pdf.startswith(b"%PDF-"))
        text = pdf.decode("latin1")
        self.assertIn("/Type /Catalog", text)
        self.assertIn("/Type /Pages", text)
        self.assertEqual(text.count("/Type /Page "), 1)
        self.assertIn("/Filter /DCTDecode", text)
        self.assertIn("/ColorSpace /DeviceRGB", text)
        self.assertIn(f"[0 0 {A4_WIDTH_PT} {A4_HEIGHT_PT}]", text)
        self.assertTrue(text.rstrip().endswith("%%EOF"))

    def test_two_pages_page_count(self) -> None:
        jpeg = _baseline_jpeg_bytes(width=2, height=2, components=1)
        pdf = build_pdf(
            [
                {"kind": "jpeg", "width": 2, "height": 2, "components": 1, "data": jpeg},
                {"kind": "jpeg", "width": 2, "height": 2, "components": 1, "data": jpeg},
            ]
        )
        text = pdf.decode("latin1")
        self.assertEqual(text.count("/Type /Page "), 2)
        self.assertEqual(text.count("/Type /Pages"), 1)
        self.assertIn("/ColorSpace /DeviceGray", text)
        self.assertIn("/Count 2", text)

    def test_rgb_page_flate(self) -> None:
        rgb = bytes([255, 0, 0, 0, 255, 0])  # 2 像素
        pdf = build_pdf([{"kind": "rgb", "width": 2, "height": 1, "data": rgb}])
        text = pdf.decode("latin1")
        self.assertIn("/Filter /FlateDecode", text)
        self.assertIn("/ColorSpace /DeviceRGB", text)
        self.assertIn(f"[0 0 {A4_WIDTH_PT} {A4_HEIGHT_PT}]", text)
        self.assertIn("/Type /Page", text)

    def test_rgb_mismatch_fails(self) -> None:
        with self.assertRaises(FileConvertError):
            build_pdf([{"kind": "rgb", "width": 2, "height": 1, "data": b"\x00\x01"}])


# ---------------------------------------------------------------------------
# 解码（JPEG/PNG）
# ---------------------------------------------------------------------------

class DecodeTests(unittest.TestCase):
    def test_baseline_jpeg_info(self) -> None:
        width, height, components = _jpeg_info(_baseline_jpeg_bytes(30, 20, 3))
        self.assertEqual((width, height, components), (30, 20, 3))

    def test_progressive_jpeg_fails_chinese(self) -> None:
        with self.assertRaises(FileConvertError) as ctx:
            _decode_image_bytes(_progressive_jpeg_bytes(), index=0)
        self.assertIn("progressive", str(ctx.exception))
        self.assertIn("不支持", str(ctx.exception))

    def test_png_rgb_decode(self) -> None:
        png = _solid_png(2, 2, 2, 3, bytes([255, 0, 0]))
        width, height, rgb = _png_to_rgb(png)
        self.assertEqual((width, height), (2, 2))
        self.assertEqual(rgb, bytes([255, 0, 0]) * 4)

    def test_png_gray_decode(self) -> None:
        png = _solid_png(1, 1, 0, 1, bytes([77]))
        _, _, rgb = _png_to_rgb(png)
        self.assertEqual(rgb, bytes([77, 77, 77]))

    def test_png_palette_decode(self) -> None:
        palette = bytes([255, 0, 0, 0, 255, 0, 0, 0, 255])  # 红/绿/蓝
        png = _png_bytes(1, 1, 3, 1, [bytes([2])], palette=palette)
        _, _, rgb = _png_to_rgb(png)
        self.assertEqual(rgb, bytes([0, 0, 255]))

    def test_png_rgba_flatten_on_white(self) -> None:
        # 半透明红 (200,10,40,128) 拍平到白底 → (227,132,147)
        png = _solid_png(1, 1, 6, 4, bytes([200, 10, 40, 128]))
        _, _, rgb = _png_to_rgb(png)
        self.assertEqual(rgb, bytes([227, 132, 147]))

    def test_png_rgba_alpha_0_white(self) -> None:
        png = _solid_png(1, 1, 6, 4, bytes([0, 0, 0, 0]))
        _, _, rgb = _png_to_rgb(png)
        self.assertEqual(rgb, bytes([255, 255, 255]))

    def test_interlaced_png_fails_chinese(self) -> None:
        png = _solid_png(2, 2, 2, 3, bytes([1, 2, 3]), interlace=1)
        with self.assertRaises(FileConvertError) as ctx:
            _png_to_rgb(png)
        self.assertIn("隔行", str(ctx.exception))

    def test_16bit_png_fails_chinese(self) -> None:
        png = _solid_png(1, 1, 2, 3, bytes([0, 1, 0, 2, 0, 3]), bit_depth=16)
        with self.assertRaises(FileConvertError) as ctx:
            _png_to_rgb(png)
        self.assertIn("位深", str(ctx.exception))

    def test_heic_fails_chinese(self) -> None:
        with self.assertRaises(FileConvertError) as ctx:
            _decode_image_bytes(b"\x00\x00\x00\x18ftypheic", index=0)
        self.assertIn("HEIC", str(ctx.exception))


# ---------------------------------------------------------------------------
# 契约校验
# ---------------------------------------------------------------------------

class ContractTests(unittest.TestCase):
    def _asset(self) -> MagicMock:
        asset = MagicMock()
        asset.require_refs.return_value = [
            AssetRef(asset_id="img_1", type="image", mime_type="image/jpeg")
        ]
        asset.materialize_file.return_value = Path("/tmp/nonexistent.jpg")
        asset.upload_file.return_value = AssetRef(
            asset_id="asset_pdf_1", type="document", mime_type="application/pdf"
        )
        return asset

    def test_missing_to_format(self) -> None:
        with self.assertRaises(FileConvertError) as ctx:
            convert_from_params({"asset_refs": []}, asset=self._asset())
        self.assertIn("to_format", str(ctx.exception))

    def test_non_pdf_to_format(self) -> None:
        with self.assertRaises(FileConvertError) as ctx:
            convert_from_params(
                {"to_format": "docx", "asset_refs": []}, asset=self._asset()
            )
        self.assertIn("docx", str(ctx.exception))

    def test_non_image_from_format(self) -> None:
        with self.assertRaises(FileConvertError) as ctx:
            convert_from_params(
                {"to_format": "pdf", "from_format": "video", "asset_refs": []},
                asset=self._asset(),
            )
        self.assertIn("video", str(ctx.exception))

    def test_empty_asset_refs(self) -> None:
        asset = self._asset()
        asset.require_refs.side_effect = AssetError(
            "asset_refs must be a non-empty AssetRef JSON array"
        )
        with self.assertRaises(FileConvertError) as ctx:
            convert_from_params({"to_format": "pdf"}, asset=asset)
        self.assertIn("asset_refs", str(ctx.exception))

    def test_non_image_asset_ref(self) -> None:
        asset = self._asset()
        asset.require_refs.return_value = [
            AssetRef(asset_id="doc_1", type="document", mime_type="application/pdf")
        ]
        with self.assertRaises(FileConvertError) as ctx:
            convert_from_params({"to_format": "pdf"}, asset=asset)
        self.assertIn("type=image", str(ctx.exception))

    def test_missing_capasset(self) -> None:
        with self.assertRaises(FileConvertError):
            convert_from_params({"to_format": "pdf"}, asset=None)


# ---------------------------------------------------------------------------
# 插件分发（mock CapAsset）
# ---------------------------------------------------------------------------

class ConvertFromParamsTests(unittest.TestCase):
    def _temp_image(self, data: bytes, suffix: str) -> Path:
        fh = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        with fh:
            fh.write(data)
        path = Path(fh.name)
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        return path

    def test_rgb_and_jpeg_merge_to_pdf(self) -> None:
        png = _solid_png(3, 2, 2, 3, bytes([0, 0, 255]))
        jpeg = _baseline_jpeg_bytes(width=5, height=4)
        img1 = self._temp_image(png, ".png")
        img2 = self._temp_image(jpeg, ".jpg")

        asset = MagicMock()
        asset.require_refs.return_value = [
            AssetRef(asset_id="img_a", type="image", mime_type="image/png"),
            AssetRef(asset_id="img_b", type="image", mime_type="image/jpeg"),
        ]
        asset.materialize_file.side_effect = [img1, img2]
        captured: dict[str, bytes] = {}

        def _fake_upload(path: Any, **kw: Any) -> AssetRef:
            captured["data"] = Path(path).read_bytes()
            return AssetRef(
                asset_id="asset_pdf_9", type="document", mime_type="application/pdf"
            )

        asset.upload_file.side_effect = _fake_upload

        msg, outputs = convert_from_params(
            {"to_format": "pdf", "name": "发票扫描件"},
            asset=asset,
            now=datetime(2026, 9, 3, 8, 0, 0),
        )
        self.assertIn("file.convert ok", msg)
        self.assertEqual(outputs["page_count"], 2)
        self.assertEqual(outputs["asset_ref"]["asset_id"], "asset_pdf_9")
        self.assertEqual(outputs["asset_ref"]["type"], "document")
        self.assertIn("asset_pdf_9", outputs["status_text"])
        self.assertIn("2 张", outputs["status_text"])

        upload_kwargs = asset.upload_file.call_args.kwargs
        self.assertEqual(upload_kwargs["producer"], "file.convert")
        self.assertEqual(upload_kwargs["mime_type"], "application/pdf")
        self.assertEqual(upload_kwargs["asset_type"], "document")
        self.assertEqual(upload_kwargs["filename"], "发票扫描件.pdf")

        data = captured["data"]
        self.assertTrue(data.startswith(b"%PDF-"))
        self.assertEqual(data.decode("latin1").count("/Type /Page "), 2)

    def test_default_name_when_no_name(self) -> None:
        png = _solid_png(1, 1, 2, 3, bytes([1, 2, 3]))
        img = self._temp_image(png, ".png")
        asset = MagicMock()
        asset.require_refs.return_value = [
            AssetRef(asset_id="img_a", type="image", mime_type="image/png")
        ]
        asset.materialize_file.return_value = img
        asset.upload_file.return_value = AssetRef(
            asset_id="asset_pdf_1", type="document", mime_type="application/pdf"
        )
        convert_from_params(
            {"to_format": "pdf"},
            asset=asset,
            now=datetime(2026, 9, 3, 8, 0, 0),
        )
        filename = asset.upload_file.call_args.kwargs["filename"]
        self.assertTrue(filename.startswith("convert-20260903-080000"))
        self.assertTrue(filename.endswith(".pdf"))

    def test_materialize_failure_chinese(self) -> None:
        asset = MagicMock()
        asset.require_refs.return_value = [
            AssetRef(asset_id="img_bad", type="image", mime_type="image/png")
        ]
        asset.materialize_file.side_effect = AssetError("asset not accessible")
        with self.assertRaises(FileConvertError) as ctx:
            convert_from_params({"to_format": "pdf"}, asset=asset)
        self.assertIn("img_bad", str(ctx.exception))
        asset.upload_file.assert_not_called()


# ---------------------------------------------------------------------------
# 服务广告
# ---------------------------------------------------------------------------

def _laptop_env() -> dict:
    return {
        "MAC_EDGE_ROLE": "laptop",
        "MAC_EDGE_SERVICE_WHITELIST": "",
        "MAC_EDGE_GOPRO_SSID": "",
        "MAC_EDGE_ADVERTISE_CAST": "0",
        "MAC_EDGE_HISENSE_USERNAME": "",
        "MAC_EDGE_HISENSE_PASSWORD": "",
        "MAC_EDGE_XIAOMI_USERNAME": "",
        "MAC_EDGE_XIAOMI_PASSWORD": "",
        "MAC_EDGE_XIAOMI_TV": "",
        "MAC_EDGE_DISPLAY_BACKEND": "",
        "MAC_EDGE_XIAOMI_TV_HOST": "",
    }


class AdvertiseFileConvertTests(unittest.TestCase):
    def test_laptop_advertises_local_file_convert(self) -> None:
        with patch.dict(os.environ, _laptop_env(), clear=False):
            services = default_services()
        ids = [s["service_id"] for s in services]
        self.assertIn("local.file.convert", ids)
        svc = next(s for s in services if s["service_id"] == "local.file.convert")
        self.assertEqual(svc["group"], "convert")
        caps = [c["capability_id"] for c in svc["capabilities"]]
        self.assertIn("file.convert", caps)
        cap = svc["capabilities"][0]
        schema = cap.get("input_schema") or {}
        self.assertTrue((schema.get("asset_refs") or {}).get("required"))
        self.assertTrue((schema.get("to_format") or {}).get("required"))

    def test_home_server_does_not_advertise_file_convert(self) -> None:
        env = _laptop_env()
        env["MAC_EDGE_ROLE"] = "home-server"
        with patch.dict(os.environ, env, clear=False):
            ids = [s["service_id"] for s in default_services()]
        self.assertNotIn("local.file.convert", ids)


if __name__ == "__main__":
    unittest.main()






