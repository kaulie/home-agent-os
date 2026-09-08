"""pdf.rotate — document(PDF) 横版/竖版整份切换：方向判定 / 旋转 / 契约校验 / 插件分发。

风格对齐 test_xiaomi_aio_printer.py / test_file_convert.py：用 pypdf 构造最小
多页 PDF fixture，断言判定、旋转后 /Rotate/有效方向与中文失败文案，不接真打印机。
"""

from __future__ import annotations

import io
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from pypdf import PdfReader, PdfWriter

from mac_edge.asset.types import AssetError, AssetRef
from mac_edge.plugins.pdf_rotate import (
    ORIENTATION_LANDSCAPE,
    ORIENTATION_PORTRAIT,
    PdfRotateError,
    classify_pages,
    page_effective_size,
    page_orientation,
    parse_orientation,
    plan_rotation,
    read_pdf_orientations,
    rotate_from_params,
)
from mac_edge.services import default_services


# ---------------------------------------------------------------------------
# fixture helpers（用 pypdf 构造页面尺寸可选的 PDF）
# ---------------------------------------------------------------------------

A4_PORTRAIT = (595, 842)   # 高>宽 竖版
A4_LANDSCAPE = (842, 595)  # 宽>高 横版
SQUARE = (600, 600)        # 方形页


def _build_pdf(
    pages: list[tuple[int, int]],
    *,
    prerotate: list[int] | None = None,
    dst: Path | None = None,
) -> Path:
    """构造多页 PDF；prerotate[i]=90 表示该页预先带 /Rotate 90（模拟第三方旋转页）。"""
    writer = PdfWriter()
    for i, (w, h) in enumerate(pages):
        page = writer.add_blank_page(width=w, height=h)
        if prerotate and i < len(prerotate) and prerotate[i]:
            page.rotate(int(prerotate[i]))
    out = dst or Path(tempfile.mktemp(suffix=".pdf"))
    with open(out, "wb") as fh:
        writer.write(fh)
    return out


def _rotated_copy(data: bytes) -> PdfReader:
    return PdfReader(io.BytesIO(data))


def _asset_for(
    path: Path,
    *,
    asset_id: str = "doc_in_1",
    ref_type: str = "document",
) -> MagicMock:
    asset = MagicMock()
    asset.require_ref.return_value = AssetRef(
        asset_id=asset_id, type=ref_type, mime_type="application/pdf"
    )
    asset.materialize_file.return_value = path
    asset.upload_file.return_value = AssetRef(
        asset_id="asset_rot_9", type="document", mime_type="application/pdf"
    )
    return asset


# ---------------------------------------------------------------------------
# orientation 解析 / 别名
# ---------------------------------------------------------------------------

class ParseOrientationTests(unittest.TestCase):
    def test_missing_fails(self) -> None:
        with self.assertRaises(PdfRotateError) as ctx:
            parse_orientation(None)
        self.assertIn("orientation", str(ctx.exception))

    def test_portrait_aliases(self) -> None:
        for raw in ("portrait", "竖版", "竖", "竖排", "竖向", "纵向", " 竖版 "):
            self.assertEqual(parse_orientation(raw), ORIENTATION_PORTRAIT, raw)

    def test_landscape_aliases(self) -> None:
        for raw in ("landscape", "横版", "横", "横排", "横向", " 横版 "):
            self.assertEqual(parse_orientation(raw), ORIENTATION_LANDSCAPE, raw)

    def test_unknown_fails(self) -> None:
        with self.assertRaises(PdfRotateError) as ctx:
            parse_orientation("diagonal")
        self.assertIn("diagonal", str(ctx.exception))


# ---------------------------------------------------------------------------
# 页面方向判定（MediaBox + /Rotate）
# ---------------------------------------------------------------------------

class PageOrientationTests(unittest.TestCase):
    def test_portrait_landscape_square(self) -> None:
        path = _build_pdf([A4_PORTRAIT, A4_LANDSCAPE, SQUARE])
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        reader = PdfReader(str(path))
        self.assertEqual(page_orientation(reader.pages[0]), ORIENTATION_PORTRAIT)
        self.assertEqual(page_orientation(reader.pages[1]), ORIENTATION_LANDSCAPE)
        self.assertEqual(page_orientation(reader.pages[2]), "square")
        # 有效宽高：/Rotate=0 时 A4 竖版有效尺寸仍是高>宽
        w, h = page_effective_size(reader.pages[0])
        self.assertEqual((round(w), round(h)), A4_PORTRAIT)

    def test_rotate90_swaps_effective_orientation(self) -> None:
        # 声明框竖版 + /Rotate 90 → 实际出纸为横版
        path = _build_pdf([A4_PORTRAIT], prerotate=[90])
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        reader = PdfReader(str(path))
        w, h = page_effective_size(reader.pages[0])
        self.assertEqual((round(w), round(h)), A4_LANDSCAPE)
        self.assertEqual(page_orientation(reader.pages[0]), ORIENTATION_LANDSCAPE)


class ClassifyAndPlanTests(unittest.TestCase):
    def test_classify(self) -> None:
        self.assertEqual(classify_pages(["portrait"]), "portrait")
        self.assertEqual(classify_pages(["portrait", "portrait"]), "portrait")
        self.assertEqual(classify_pages(["landscape"]), "landscape")
        self.assertEqual(classify_pages(["portrait", "landscape"]), "mixed")
        self.assertEqual(classify_pages(["square", "square"]), "square")
        # 方形页不参与整份方向
        self.assertEqual(classify_pages(["portrait", "square"]), "portrait")

    def test_plan_rotation(self) -> None:
        self.assertEqual(
            plan_rotation(["portrait", "landscape"], ORIENTATION_LANDSCAPE), [0]
        )
        self.assertEqual(
            plan_rotation(["portrait", "landscape"], ORIENTATION_PORTRAIT), [1]
        )
        self.assertEqual(
            plan_rotation(["landscape", "landscape"], ORIENTATION_LANDSCAPE), []
        )
        # 方形页不转
        self.assertEqual(
            plan_rotation(["square", "portrait"], ORIENTATION_PORTRAIT), []
        )
        self.assertEqual(
            plan_rotation(["square", "portrait"], ORIENTATION_LANDSCAPE), [1]
        )


# ---------------------------------------------------------------------------
# 契约校验
# ---------------------------------------------------------------------------

class ContractTests(unittest.TestCase):
    def test_missing_capasset(self) -> None:
        with self.assertRaises(PdfRotateError) as ctx:
            rotate_from_params({"orientation": "landscape"}, asset=None)
        self.assertIn("CapAsset", str(ctx.exception))

    def test_missing_orientation(self) -> None:
        asset = _asset_for(Path("/tmp/nonexistent.pdf"))
        with self.assertRaises(PdfRotateError) as ctx:
            rotate_from_params(
                {"asset_ref": {"asset_id": "a", "type": "document"}}, asset=asset
            )
        self.assertIn("orientation", str(ctx.exception))

    def test_non_document_asset_fails(self) -> None:
        asset = _asset_for(Path("/tmp/nonexistent.pdf"), ref_type="image")
        with self.assertRaises(PdfRotateError) as ctx:
            rotate_from_params(
                {"orientation": "landscape", "asset_ref": {"asset_id": "a", "type": "image"}},
                asset=asset,
            )
        self.assertIn("type=document", str(ctx.exception))

    def test_missing_asset_ref_fails(self) -> None:
        asset = _asset_for(Path("/tmp/nonexistent.pdf"))
        asset.require_ref.side_effect = AssetError("missing asset_ref")
        with self.assertRaises(PdfRotateError) as ctx:
            rotate_from_params({"orientation": "landscape"}, asset=asset)
        self.assertIn("asset_ref", str(ctx.exception))

    def test_nonexistent_file_fails(self) -> None:
        asset = _asset_for(Path("/tmp/definitely-not-here.pdf"))
        with self.assertRaises(PdfRotateError) as ctx:
            rotate_from_params(
                {
                    "orientation": "landscape",
                    "asset_ref": {"asset_id": "a", "type": "document"},
                },
                asset=asset,
            )
        self.assertIn("不存在", str(ctx.exception))

    def test_not_a_pdf_fails(self) -> None:
        fd, name = tempfile.mkstemp(suffix=".pdf")
        with os.fdopen(fd, "wb") as fh:
            fh.write(b"this is not a pdf")
        path = Path(name)
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        asset = _asset_for(path)
        with self.assertRaises(PdfRotateError) as ctx:
            rotate_from_params(
                {
                    "orientation": "landscape",
                    "asset_ref": {"asset_id": "a", "type": "document"},
                },
                asset=asset,
            )
        self.assertIn("无法读取", str(ctx.exception))


# ---------------------------------------------------------------------------
# 插件分发（mock CapAsset）
# ---------------------------------------------------------------------------

class RotateFromParamsTests(unittest.TestCase):
    def test_portrait_to_landscape_uploads_rotated_pdf(self) -> None:
        src = _build_pdf([A4_PORTRAIT, A4_PORTRAIT])
        self.addCleanup(lambda: src.unlink(missing_ok=True))
        captured: dict[str, bytes] = {}
        asset = _asset_for(src)

        def _fake_upload(path: Any, **kw: Any) -> AssetRef:
            captured["data"] = Path(path).read_bytes()
            return AssetRef(
                asset_id="asset_rot_9", type="document", mime_type="application/pdf"
            )

        asset.upload_file.side_effect = _fake_upload

        msg, outputs = rotate_from_params(
            {"orientation": "landscape"},
            asset=asset,
            now=datetime(2026, 9, 8, 9, 0, 0),
        )
        self.assertIn("pdf.rotate ok", msg)
        self.assertEqual(outputs["page_count"], 2)
        self.assertEqual(outputs["source_orientation"], "portrait")
        self.assertEqual(outputs["target_orientation"], "landscape")
        self.assertEqual(outputs["rotated_pages"], 2)
        self.assertEqual(outputs["asset_ref"]["asset_id"], "asset_rot_9")
        self.assertIn("asset_rot_9", outputs["status_text"])
        self.assertIn("横版", outputs["status_text"])

        upload_kwargs = asset.upload_file.call_args.kwargs
        self.assertEqual(upload_kwargs["producer"], "pdf.rotate")
        self.assertEqual(upload_kwargs["mime_type"], "application/pdf")
        self.assertEqual(upload_kwargs["asset_type"], "document")
        self.assertEqual(upload_kwargs["filename"], "pdf-rotate-20260908-090000-横版.pdf")

        # 上传物确实是旋转后的横版 PDF
        data = captured["data"]
        self.assertTrue(data.startswith(b"%PDF-"))
        reader = _rotated_copy(data)
        self.assertEqual(len(reader.pages), 2)
        orientations = [page_orientation(p) for p in reader.pages]
        self.assertEqual(orientations, ["landscape", "landscape"])

    def test_landscape_to_portrait_rotates_back(self) -> None:
        src = _build_pdf([A4_LANDSCAPE])
        self.addCleanup(lambda: src.unlink(missing_ok=True))
        captured: dict[str, bytes] = {}
        asset = _asset_for(src, asset_id="doc_wide")

        def _fake_upload(path: Any, **kw: Any) -> AssetRef:
            captured["data"] = Path(path).read_bytes()
            return AssetRef(
                asset_id="asset_portrait_1", type="document", mime_type="application/pdf"
            )

        asset.upload_file.side_effect = _fake_upload
        _, outputs = rotate_from_params(
            {"orientation": "竖版"},
            asset=asset,
            now=datetime(2026, 9, 8, 9, 0, 0),
        )
        self.assertEqual(outputs["source_orientation"], "landscape")
        self.assertEqual(outputs["target_orientation"], "portrait")
        self.assertEqual(outputs["rotated_pages"], 1)
        reader = _rotated_copy(captured["data"])
        self.assertEqual(page_orientation(reader.pages[0]), "portrait")

    def test_preexisting_rotate90_page_is_landscape(self) -> None:
        # 声明框竖版 + /Rotate 90 → 判为横版；目标竖版时旋转该页
        src = _build_pdf([A4_PORTRAIT], prerotate=[90])
        self.addCleanup(lambda: src.unlink(missing_ok=True))
        captured: dict[str, bytes] = {}
        asset = _asset_for(src)
        asset.upload_file.side_effect = (
            lambda _p, **kw: captured.__setitem__("data", Path(_p).read_bytes())
            or AssetRef(
                asset_id="asset_rot_x", type="document", mime_type="application/pdf"
            )
        )
        _, outputs = rotate_from_params({"orientation": "portrait"}, asset=asset)
        self.assertEqual(outputs["source_orientation"], "landscape")
        self.assertEqual(outputs["rotated_pages"], 1)
        reader = _rotated_copy(captured["data"])
        self.assertEqual(page_orientation(reader.pages[0]), "portrait")

    def test_mixed_pages_only_mismatch_rotated(self) -> None:
        src = _build_pdf([A4_PORTRAIT, A4_LANDSCAPE])
        self.addCleanup(lambda: src.unlink(missing_ok=True))
        asset = _asset_for(src)
        asset.upload_file.side_effect = lambda _p, **kw: AssetRef(
            asset_id="asset_mixed_1", type="document", mime_type="application/pdf"
        )
        _, outputs = rotate_from_params({"orientation": "portrait"}, asset=asset)
        self.assertEqual(outputs["source_orientation"], "mixed")
        self.assertEqual(outputs["rotated_pages"], 1)

    def test_noop_reuses_original_asset_without_upload(self) -> None:
        src = _build_pdf([A4_PORTRAIT, A4_PORTRAIT])
        self.addCleanup(lambda: src.unlink(missing_ok=True))
        asset = _asset_for(src)
        _, outputs = rotate_from_params({"orientation": "portrait"}, asset=asset)
        asset.upload_file.assert_not_called()
        self.assertEqual(outputs["rotated_pages"], 0)
        self.assertEqual(outputs["source_orientation"], "portrait")
        self.assertEqual(outputs["asset_ref"]["asset_id"], "doc_in_1")
        self.assertIn("已是竖版", outputs["status_text"])
        self.assertIn("doc_in_1", outputs["status_text"])

    def test_all_square_reuses_original_asset(self) -> None:
        src = _build_pdf([SQUARE, SQUARE])
        self.addCleanup(lambda: src.unlink(missing_ok=True))
        asset = _asset_for(src)
        _, outputs = rotate_from_params({"orientation": "landscape"}, asset=asset)
        asset.upload_file.assert_not_called()
        self.assertEqual(outputs["rotated_pages"], 0)
        self.assertEqual(outputs["source_orientation"], "square")
        self.assertIn("正方形", outputs["status_text"])

    def test_custom_name_appended_pdf(self) -> None:
        src = _build_pdf([A4_PORTRAIT])
        self.addCleanup(lambda: src.unlink(missing_ok=True))
        asset = _asset_for(src)
        asset.upload_file.side_effect = lambda _p, **kw: AssetRef(
            asset_id="asset_n", type="document", mime_type="application/pdf"
        )
        rotate_from_params({"orientation": "landscape", "name": "合同竖改横"}, asset=asset)
        self.assertEqual(asset.upload_file.call_args.kwargs["filename"], "合同竖改横.pdf")

    def test_read_pdf_orientations(self) -> None:
        src = _build_pdf([A4_PORTRAIT, A4_LANDSCAPE, SQUARE])
        self.addCleanup(lambda: src.unlink(missing_ok=True))
        count, per_page = read_pdf_orientations(src)
        self.assertEqual(count, 3)
        self.assertEqual(per_page, ["portrait", "landscape", "square"])


# ---------------------------------------------------------------------------
# 广告：laptop 且装有 pypdf 时广告 local.pdf.rotate
# ---------------------------------------------------------------------------

class AdvertisePdfRotateTests(unittest.TestCase):
    def _env(self) -> dict[str, str]:
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

    def test_laptop_advertises_when_pypdf_available(self) -> None:
        with patch.dict(os.environ, self._env(), clear=False), patch(
            "mac_edge.plugins.pdf_rotate.pypdf_available", return_value=True
        ):
            services = default_services()
        ids = [s["service_id"] for s in services]
        self.assertIn("local.pdf.rotate", ids)
        svc = next(s for s in services if s["service_id"] == "local.pdf.rotate")
        caps = [c["capability_id"] for c in svc["capabilities"]]
        self.assertIn("pdf.rotate", caps)

    def test_skips_when_pypdf_missing(self) -> None:
        with patch.dict(os.environ, self._env(), clear=False), patch(
            "mac_edge.plugins.pdf_rotate.pypdf_available", return_value=False
        ):
            services = default_services()
        ids = [s["service_id"] for s in services]
        self.assertNotIn("local.pdf.rotate", ids)


if __name__ == "__main__":
    unittest.main()





