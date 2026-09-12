"""display.pdf / display.pdf.page — PDF 投屏电视（逐页渲染）+ 翻页会话。

风格对齐 test_pdf_rotate.py / test_xiaomi_tv_display.py：mock CapAsset +
注入假 render/display，断言页码推进、页缓存复用、越界中文提示与广告门控；
本机装有 pymupdf 时追加真实渲染用例（无则 skip）。
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from mac_edge.asset.types import AssetError, AssetRef
from mac_edge.plugins import pdf_display
from mac_edge.plugins.pdf_display import (
    ACTION_GOTO,
    ACTION_NEXT,
    ACTION_PREV,
    ZOOM_IN,
    ZOOM_OUT,
    ZOOM_RESET,
    PdfDisplayError,
    open_from_params,
    page_from_params,
    parse_page_action,
    parse_page_number,
    parse_zoom_action,
    reset_session,
    zoom_from_params,
)
from mac_edge.plugins.pdf_render import pymupdf_available, render_dpi
from mac_edge.services import default_services

DOC_REF = AssetRef(asset_id="doc_1", type="document", mime_type="application/pdf")
PAGE_REF = AssetRef(asset_id="asset_p1", type="image", mime_type="image/png")
LAN_URL = "http://192.168.3.65:8080/pdf-page-doc_1-p1.png"


def _fake_render(pdf_path: Path, page_index: int, dpi: int, out_path: Path) -> Path:
    """假渲染：写最小 PNG 头字节，记录调用页。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes([page_index]))
    return out_path


def _asset_for(pdf_path: Path, *, upload_side_effect=None) -> MagicMock:
    asset = MagicMock()
    asset.require_ref.return_value = DOC_REF
    asset.materialize_file.return_value = pdf_path
    if upload_side_effect is not None:
        asset.upload_file.side_effect = upload_side_effect
    else:
        asset.upload_file.return_value = PAGE_REF
    asset.http_url.return_value = LAN_URL
    return asset


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        reset_session()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(reset_session)
        env = {"MAC_EDGE_DATA_DIR": self._tmp.name, "MAC_EDGE_PDF_DISPLAY_DPI": ""}
        self._env = patch.dict(os.environ, env, clear=False)
        self._env.start()
        self.addCleanup(self._env.stop)
        self.pdf_path = Path(self._tmp.name) / "in.pdf"
        self.pdf_path.write_bytes(b"%PDF-1.4 fake")
        # 不接真 pymupdf：页数固定 3，渲染用假实现。
        self._pages = patch.object(pdf_display, "pdf_page_count", return_value=3)
        self._pages.start()
        self.addCleanup(self._pages.stop)

    def _open(self, asset: MagicMock, displayed: list[str], **params):
        return open_from_params(
            params,
            asset=asset,
            display_fn=lambda url: displayed.append(url) or "display ok",
            render_fn=_fake_render,
        )


class ParseTests(unittest.TestCase):
    def test_action_aliases(self) -> None:
        for raw in ("next", "下一页", "下页", "往后翻", "翻页", None, ""):
            self.assertEqual(parse_page_action(raw), ACTION_NEXT, raw)
        for raw in ("prev", "previous", "上一页", "上页", "往前翻"):
            self.assertEqual(parse_page_action(raw), ACTION_PREV, raw)
        for raw in ("goto", "翻到", "跳到"):
            self.assertEqual(parse_page_action(raw), ACTION_GOTO, raw)

    def test_action_invalid_fails(self) -> None:
        with self.assertRaises(PdfDisplayError):
            parse_page_action("乱翻")

    def test_page_number(self) -> None:
        self.assertIsNone(parse_page_number(None))
        self.assertIsNone(parse_page_number(""))
        self.assertEqual(parse_page_number("5"), 5)
        self.assertEqual(parse_page_number(2), 2)
        with self.assertRaises(PdfDisplayError):
            parse_page_number(None, required=True)
        with self.assertRaises(PdfDisplayError):
            parse_page_number("abc")
        with self.assertRaises(PdfDisplayError):
            parse_page_number("0")

    def test_render_dpi_default_and_clamp(self) -> None:
        with patch.dict(os.environ, {"MAC_EDGE_PDF_DISPLAY_DPI": ""}, clear=False):
            self.assertEqual(render_dpi(), 200)
        with patch.dict(os.environ, {"MAC_EDGE_PDF_DISPLAY_DPI": "300"}, clear=False):
            self.assertEqual(render_dpi(), 300)
        with patch.dict(os.environ, {"MAC_EDGE_PDF_DISPLAY_DPI": "9999"}, clear=False):
            self.assertEqual(render_dpi(), 400)


class OpenTests(_Base):
    def test_open_displays_first_page(self) -> None:
        asset = _asset_for(self.pdf_path)
        displayed: list[str] = []
        msg, outputs = self._open(asset, displayed, asset_ref=DOC_REF.to_dict())
        self.assertEqual(displayed, [LAN_URL])
        self.assertEqual(outputs["page"], 1)
        self.assertEqual(outputs["page_count"], 3)
        self.assertEqual(outputs["asset_id"], "doc_1")
        self.assertIn("第 1 页", outputs["status_text"])
        self.assertIn("display.pdf", msg)
        asset.upload_file.assert_called_once()
        session = pdf_display.current_session()
        self.assertIsNotNone(session)
        self.assertEqual(session.current_page, 1)

    def test_open_with_page_and_clamp(self) -> None:
        asset = _asset_for(self.pdf_path)
        _msg, outputs = self._open(asset, [], asset_ref=DOC_REF.to_dict(), page=99)
        self.assertEqual(outputs["page"], 3)
        self.assertIn("超出范围", outputs["status_text"])

    def test_open_rejects_non_document(self) -> None:
        asset = _asset_for(self.pdf_path)
        asset.require_ref.return_value = AssetRef(asset_id="img_1", type="image")
        with self.assertRaises(PdfDisplayError) as ctx:
            self._open(asset, [], asset_ref={"asset_id": "img_1", "type": "image"})
        self.assertIn("document", str(ctx.exception))

    def test_open_missing_asset_ref_fails(self) -> None:
        asset = _asset_for(self.pdf_path)
        asset.require_ref.side_effect = AssetError("missing or invalid asset_ref")
        with self.assertRaises(PdfDisplayError):
            self._open(asset, [])

    def test_open_replaces_session_and_cleans_old_dir(self) -> None:
        asset = _asset_for(self.pdf_path)
        self._open(asset, [], asset_ref=DOC_REF.to_dict())
        old = pdf_display.current_session()
        self.assertIsNotNone(old)
        old_dir = old.work_dir
        self.assertTrue(old_dir.is_dir())
        # 打开另一份 PDF（不同 asset_id → 不同渲染目录）→ 旧目录被清理。
        other_ref = AssetRef(asset_id="doc_2", type="document", mime_type="application/pdf")
        asset.require_ref.return_value = other_ref
        self._open(asset, [], asset_ref=other_ref.to_dict())
        self.assertFalse(old_dir.exists())
        session = pdf_display.current_session()
        self.assertIsNotNone(session)
        self.assertEqual(session.asset_id, "doc_2")


class PageTurnTests(_Base):
    def test_next_prev_goto(self) -> None:
        asset = _asset_for(self.pdf_path)
        displayed: list[str] = []
        self._open(asset, displayed, asset_ref=DOC_REF.to_dict())

        msg, outputs = page_from_params(
            {}, asset=asset,
            display_fn=lambda url: displayed.append(url) or "display ok",
            render_fn=_fake_render,
        )
        self.assertEqual(outputs["page"], 2)
        self.assertIn("第 2 页", outputs["status_text"])

        _msg, outputs = page_from_params(
            {"action": "上一页"}, asset=asset,
            display_fn=lambda url: displayed.append(url) or "ok",
            render_fn=_fake_render,
        )
        self.assertEqual(outputs["page"], 1)

        _msg, outputs = page_from_params(
            {"action": "goto", "page": 3}, asset=asset,
            display_fn=lambda url: displayed.append(url) or "ok",
            render_fn=_fake_render,
        )
        self.assertEqual(outputs["page"], 3)
        self.assertEqual(len(displayed), 4)

    def test_next_at_last_page_stays(self) -> None:
        asset = _asset_for(self.pdf_path)
        displayed: list[str] = []
        self._open(asset, displayed, asset_ref=DOC_REF.to_dict(), page=3)
        before = len(displayed)
        _msg, outputs = page_from_params(
            {"action": "next"}, asset=asset,
            display_fn=lambda url: displayed.append(url) or "ok",
            render_fn=_fake_render,
        )
        self.assertEqual(outputs["page"], 3)
        self.assertIn("已经是最后一页", outputs["status_text"])
        self.assertEqual(len(displayed), before)  # 不重复投屏

    def test_prev_at_first_page_stays(self) -> None:
        asset = _asset_for(self.pdf_path)
        displayed: list[str] = []
        self._open(asset, displayed, asset_ref=DOC_REF.to_dict())
        _msg, outputs = page_from_params(
            {"action": "prev"}, asset=asset,
            display_fn=lambda url: displayed.append(url) or "ok",
            render_fn=_fake_render,
        )
        self.assertEqual(outputs["page"], 1)
        self.assertIn("已经是第一页", outputs["status_text"])

    def test_goto_out_of_range_fails(self) -> None:
        asset = _asset_for(self.pdf_path)
        self._open(asset, [], asset_ref=DOC_REF.to_dict())
        with self.assertRaises(PdfDisplayError) as ctx:
            page_from_params(
                {"action": "goto", "page": 9}, asset=asset,
                display_fn=lambda url: "ok", render_fn=_fake_render,
            )
        self.assertIn("超出范围", str(ctx.exception))

    def test_goto_missing_page_fails(self) -> None:
        asset = _asset_for(self.pdf_path)
        self._open(asset, [], asset_ref=DOC_REF.to_dict())
        with self.assertRaises(PdfDisplayError):
            page_from_params(
                {"action": "goto"}, asset=asset,
                display_fn=lambda url: "ok", render_fn=_fake_render,
            )

    def test_page_without_session_fails(self) -> None:
        asset = _asset_for(self.pdf_path)
        with self.assertRaises(PdfDisplayError) as ctx:
            page_from_params(
                {}, asset=asset,
                display_fn=lambda url: "ok", render_fn=_fake_render,
            )
        self.assertIn("没有正在投屏的 PDF", str(ctx.exception))

    def test_same_page_uploaded_once_per_grant(self) -> None:
        """同 intent 内翻回已显示的页：复用缓存 AssetRef，不重复上传。"""
        asset = _asset_for(self.pdf_path)
        self._open(asset, [], asset_ref=DOC_REF.to_dict())
        page_from_params(
            {"action": "prev"}, asset=asset,  # 第 1 页已在 open 时传过
            display_fn=lambda url: "ok", render_fn=_fake_render,
        )
        asset.upload_file.assert_called_once()

    def test_stale_grant_reuploads_page(self) -> None:
        """跨 intent 翻回旧页：缓存 ref 授权失效 → 用本地 PNG 在当前 intent 重传。"""
        asset = _asset_for(self.pdf_path)
        self._open(asset, [], asset_ref=DOC_REF.to_dict())
        # 先翻到第 2 页，再翻回第 1 页（第 1 页的缓存 ref 在新 intent 下无授权）。
        page_from_params(
            {"action": "next"}, asset=asset,
            display_fn=lambda url: "ok", render_fn=_fake_render,
        )
        self.assertEqual(asset.upload_file.call_count, 2)  # open p1 + next p2
        asset.http_url.side_effect = [
            AssetError("denied"),  # 缓存 ref 在新 intent 下无授权
            LAN_URL,               # 重传后取链
        ]
        new_ref = AssetRef(asset_id="asset_p1b", type="image", mime_type="image/png")
        asset.upload_file.side_effect = [new_ref]
        _msg, outputs = page_from_params(
            {"action": "prev"}, asset=asset,
            display_fn=lambda url: "ok", render_fn=_fake_render,
        )
        self.assertEqual(outputs["page"], 1)
        self.assertEqual(asset.upload_file.call_count, 3)  # + 重传 p1


class RealRenderTests(_Base):
    """本机有 pymupdf 时真实渲染一遍（pypdf 造 fixture）。"""

    def setUp(self) -> None:
        super().setUp()
        if not pymupdf_available():
            self.skipTest("pymupdf not installed")

    def test_render_real_pdf_pages(self) -> None:
        from pypdf import PdfWriter

        real_pdf = Path(self._tmp.name) / "real.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        writer.add_blank_page(width=595, height=842)
        with open(real_pdf, "wb") as fh:
            writer.write(fh)

        self._pages.stop()  # 用真实 pdf_page_count
        try:
            asset = _asset_for(real_pdf)
            displayed: list[str] = []
            msg, outputs = open_from_params(
                {"asset_ref": DOC_REF.to_dict()},
                asset=asset,
                display_fn=lambda url: displayed.append(url) or "display ok",
            )
            self.assertEqual(outputs["page_count"], 2)
            self.assertIn("display.pdf", msg)
            session = pdf_display.current_session()
            self.assertIsNotNone(session)
            png = session.work_dir / "page-1.png"
            self.assertTrue(png.is_file())
            self.assertTrue(png.read_bytes().startswith(b"\x89PNG"))
        finally:
            self._pages.start()


class AdvertiseTests(unittest.TestCase):
    _ENV = {
        "MAC_EDGE_ROLE": "laptop",
        "MAC_EDGE_SERVICE_WHITELIST": "",
        "MAC_EDGE_GOPRO_SSID": "",
        "MAC_EDGE_ADVERTISE_CAST": "1",
        "MAC_EDGE_HISENSE_USERNAME": "",
        "MAC_EDGE_HISENSE_PASSWORD": "",
        "MAC_EDGE_XIAOMI_USERNAME": "",
        "MAC_EDGE_XIAOMI_PASSWORD": "",
        "MAC_EDGE_DISPLAY_BACKEND": "xiaomi",
        "MAC_EDGE_XIAOMI_TV": "1",
        "MAC_EDGE_XIAOMI_TV_HOST": "",
    }

    def _cap_ids(self) -> set[str]:
        with patch.dict(os.environ, self._ENV, clear=False):
            services = default_services()
        return {
            str(c["capability_id"])
            for s in services
            for c in (s.get("capabilities") or [])
        }

    def test_pdf_caps_advertised_when_pymupdf_available(self) -> None:
        with patch("mac_edge.plugins.pdf_render.pymupdf_available", return_value=True):
            ids = self._cap_ids()
        self.assertIn("display.pdf", ids)
        self.assertIn("display.pdf.page", ids)

    def test_pdf_caps_skipped_without_pymupdf(self) -> None:
        with patch("mac_edge.plugins.pdf_render.pymupdf_available", return_value=False):
            ids = self._cap_ids()
        self.assertNotIn("display.pdf", ids)
        self.assertNotIn("display.pdf.page", ids)
        self.assertIn("display.photo", ids)


class ExecutorDispatchTests(_Base):
    def test_executor_dispatches_display_pdf(self) -> None:
        from mac_edge.executor import _execute_capability

        asset = _asset_for(self.pdf_path)
        config = MagicMock()
        config.cast_display_url = "http://127.0.0.1:9095/endpoint/display"
        config.display_http_timeout_sec = 5.0
        with patch(
            "mac_edge.executor.pdf_display_open_from_params",
            return_value=("ok", {"page": 1, "page_count": 3}),
        ) as fn:
            ok, msg, outputs = _execute_capability(
                "display.pdf", asset, params={"asset_ref": DOC_REF.to_dict()}, config=config
            )
        self.assertTrue(ok)
        self.assertEqual(outputs["page"], 1)
        fn.assert_called_once()

    def test_executor_dispatches_display_pdf_page(self) -> None:
        from mac_edge.executor import _execute_capability

        asset = _asset_for(self.pdf_path)
        config = MagicMock()
        config.cast_display_url = "http://127.0.0.1:9095/endpoint/display"
        config.display_http_timeout_sec = 5.0
        with patch(
            "mac_edge.executor.pdf_display_page_from_params",
            return_value=("ok", {"page": 2, "page_count": 3}),
        ) as fn:
            ok, msg, outputs = _execute_capability(
                "display.pdf.page", asset, params={"action": "next"}, config=config
            )
        self.assertTrue(ok)
        self.assertEqual(outputs["page"], 2)
        fn.assert_called_once()

    def test_executor_surfaces_plugin_failure(self) -> None:
        from mac_edge.executor import _execute_capability

        asset = _asset_for(self.pdf_path)
        config = MagicMock()
        config.cast_display_url = "http://127.0.0.1:9095/endpoint/display"
        config.display_http_timeout_sec = 5.0
        with patch(
            "mac_edge.executor.pdf_display_page_from_params",
            side_effect=PdfDisplayError("当前没有正在投屏的 PDF"),
        ):
            ok, msg, _outputs = _execute_capability(
                "display.pdf.page", asset, params={}, config=config
            )
        self.assertFalse(ok)
        self.assertIn("没有正在投屏的 PDF", msg)


def _fake_region_render(pdf_path: Path, page_index: int, zoom: float, dpi: int, out_path: Path) -> Path:
    """假局部渲染：写最小 PNG 头字节，记录 zoom/dpi。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes([page_index]))
    return out_path


class ZoomParseTests(unittest.TestCase):
    def test_zoom_action_aliases(self) -> None:
        for raw in ("in", "zoom_in", "放大", "再放大", None, ""):
            self.assertEqual(parse_zoom_action(raw), ZOOM_IN, raw)
        for raw in ("out", "zoom_out", "缩小"):
            self.assertEqual(parse_zoom_action(raw), ZOOM_OUT, raw)
        for raw in ("reset", "还原", "恢复原图", "原图"):
            self.assertEqual(parse_zoom_action(raw), ZOOM_RESET, raw)

    def test_zoom_action_invalid_fails(self) -> None:
        with self.assertRaises(PdfDisplayError):
            parse_zoom_action("随便")


class ZoomTests(_Base):
    def _zoom(self, asset: MagicMock, displayed: list[str], **params):
        return zoom_from_params(
            params,
            asset=asset,
            display_fn=lambda url: displayed.append(url) or "display ok",
            render_fn=_fake_render,
            region_render_fn=_fake_region_render,
        )

    def test_zoom_in_ladder_and_clamp(self) -> None:
        asset = _asset_for(self.pdf_path)
        displayed: list[str] = []
        self._open(asset, displayed, asset_ref=DOC_REF.to_dict())

        _msg, outputs = self._zoom(asset, displayed, action="in")
        self.assertEqual(outputs["zoom"], 1.5)
        self.assertIn("已放大到 1.5 倍", outputs["status_text"])

        _msg, outputs = self._zoom(asset, displayed, action="放大")
        self.assertEqual(outputs["zoom"], 2.0)

        for want in (3.0, 4.0):
            _msg, outputs = self._zoom(asset, displayed, action="in")
            self.assertEqual(outputs["zoom"], want)

        # 到顶后不再重投屏，中文提示
        before = len(displayed)
        _msg, outputs = self._zoom(asset, displayed, action="in")
        self.assertEqual(outputs["zoom"], 4.0)
        self.assertIn("已是最大放大倍数", outputs["status_text"])
        self.assertEqual(len(displayed), before)

    def test_zoom_out_and_reset(self) -> None:
        asset = _asset_for(self.pdf_path)
        displayed: list[str] = []
        self._open(asset, displayed, asset_ref=DOC_REF.to_dict())
        self._zoom(asset, displayed, action="in")
        self._zoom(asset, displayed, action="in")

        _msg, outputs = self._zoom(asset, displayed, action="out")
        self.assertEqual(outputs["zoom"], 1.5)
        self.assertIn("已缩小到 1.5 倍", outputs["status_text"])

        _msg, outputs = self._zoom(asset, displayed, action="还原")
        self.assertEqual(outputs["zoom"], 1.0)
        self.assertIn("已恢复原图大小", outputs["status_text"])

        # 原图再缩小：不重投屏
        before = len(displayed)
        _msg, outputs = self._zoom(asset, displayed, action="out")
        self.assertEqual(outputs["zoom"], 1.0)
        self.assertIn("已是原图大小", outputs["status_text"])
        self.assertEqual(len(displayed), before)

    def test_zoom_uses_region_render_with_raised_dpi(self) -> None:
        asset = _asset_for(self.pdf_path)
        self._open(asset, [], asset_ref=DOC_REF.to_dict())
        calls: list[tuple] = []

        def spy_region(pdf_path, page_index, zoom, dpi, out_path):
            calls.append((page_index, zoom, dpi))
            return _fake_region_render(pdf_path, page_index, zoom, dpi, out_path)

        _msg, outputs = zoom_from_params(
            {"action": "in"},
            asset=asset,
            display_fn=lambda url: "ok",
            render_fn=_fake_render,
            region_render_fn=spy_region,
        )
        self.assertEqual(outputs["zoom"], 1.5)
        # 页 1（0-based 0），zoom 1.5，dpi = 200×1.5 = 300
        self.assertEqual(calls, [(0, 1.5, 300)])

    def test_zoom_renders_distinct_cache_and_reuses(self) -> None:
        asset = _asset_for(self.pdf_path)
        displayed: list[str] = []
        self._open(asset, displayed, asset_ref=DOC_REF.to_dict())
        self._zoom(asset, displayed, action="in")   # z1.5 渲染+上传
        self._zoom(asset, displayed, action="out")  # 回 1.0 用整页缓存
        uploads_before = asset.upload_file.call_count
        self._zoom(asset, displayed, action="in")   # 再放大：z1.5 PNG 已渲染，但跨 intent 授权可能重传
        session = pdf_display.current_session()
        self.assertIsNotNone(session)
        self.assertTrue((session.work_dir / "page-1-z1p5.png").is_file())
        self.assertTrue((session.work_dir / "page-1.png").is_file())
        # 同 intent 内 ref 缓存命中 → 不重复上传
        self.assertEqual(asset.upload_file.call_count, uploads_before)

    def test_zoom_upload_filename_uses_legal_charset(self) -> None:
        # 黑盒回归：Brain 上传校验只允许字母/数字/中文/-/_，1.5 倍档文件名不得含多余小数点
        asset = _asset_for(self.pdf_path)
        displayed: list[str] = []
        self._open(asset, displayed, asset_ref=DOC_REF)
        asset.upload_file.reset_mock()
        self._zoom(asset, displayed, action="in")
        filename = asset.upload_file.call_args.kwargs["filename"]
        stem = filename.rsplit(".", 1)[0]
        self.assertIn("z1p5", stem)
        self.assertRegex(stem, r"^[A-Za-z0-9\-_一-鿿]+$")

    def test_page_turn_resets_zoom(self) -> None:
        asset = _asset_for(self.pdf_path)
        displayed: list[str] = []
        self._open(asset, displayed, asset_ref=DOC_REF.to_dict())
        self._zoom(asset, displayed, action="in")
        session = pdf_display.current_session()
        self.assertEqual(session.zoom, 1.5)

        _msg, outputs = page_from_params(
            {"action": "next"}, asset=asset,
            display_fn=lambda url: displayed.append(url) or "ok",
            render_fn=_fake_render,
        )
        self.assertEqual(outputs["page"], 2)
        self.assertEqual(session.zoom, 1.0)

    def test_zoom_without_session_fails(self) -> None:
        asset = _asset_for(self.pdf_path)
        with self.assertRaises(PdfDisplayError) as ctx:
            self._zoom(asset, [], action="in")
        self.assertIn("没有正在投屏的 PDF", str(ctx.exception))

    def test_executor_dispatches_display_pdf_zoom(self) -> None:
        from mac_edge.executor import _execute_capability

        asset = _asset_for(self.pdf_path)
        config = MagicMock()
        config.cast_display_url = "http://127.0.0.1:9095/endpoint/display"
        config.display_http_timeout_sec = 5.0
        with patch(
            "mac_edge.executor.pdf_display_zoom_from_params",
            return_value=("ok", {"page": 1, "page_count": 3, "zoom": 1.5}),
        ) as fn:
            ok, msg, outputs = _execute_capability(
                "display.pdf.zoom", asset, params={"action": "in"}, config=config
            )
        self.assertTrue(ok)
        self.assertEqual(outputs["zoom"], 1.5)
        fn.assert_called_once()


if __name__ == "__main__":
    unittest.main()
