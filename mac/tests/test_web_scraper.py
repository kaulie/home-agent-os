"""web.scraper — URL 抓取 / 正文抽取 / HTML→PDF(text) / 渲染引擎解析 / 上传契约。

风格对齐 test_pdf_rotate.py：抽取、URL 校验、渲染引擎选择与上传全部 mock/本地构造，
不抓真实外网、不起真实浏览器（chrome 渲染用假 PDF fixture 验证链路）。
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

from pypdf import PdfWriter

from mac_edge.asset.types import AssetRef
from mac_edge.plugins import web_scraper as w
from mac_edge.services import default_services

TS = datetime(2026, 9, 9, 12, 0, 0)

SAMPLE_HTML = """<!doctype html><html><head><meta charset="utf-8"><title>测试文章标题</title></head>
<body><nav><a href="/">首页</a><a href="/x">栏目</a></nav>
<header><h1>站点头条</h1></header>
<div class="ad banner">广告广告广告广告广告广告</div>
<article>
<h1>正文标题：关于 AI 的思考</h1>
<p>这是第一段核心内容，介绍人工智能的发展。</p>
<p>第二段继续阐述。这里有一个<a href="/other">链接</a>和相对图片<img src="/img/a.png" alt="图" />。</p>
<ul><li>要点一</li><li>要点二</li></ul>
</article>
<aside>相关推荐一堆链接文字文字文字文字</aside>
<footer>版权声明</footer>
</body></html>"""


def _article_bytes() -> bytes:
    return SAMPLE_HTML.encode("utf-8")


def _make_pdf_bytes(pages: int = 1) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _asset() -> MagicMock:
    asset = MagicMock()
    asset.upload_file.return_value = AssetRef(
        asset_id="asset_ws_9", type="document", mime_type="application/pdf"
    )
    return asset


class _FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        content: bytes = b"",
        content_type: str = "text/html; charset=utf-8",
        url: str = "https://example.com/a",
        charset_encoding: str | None = "utf-8",
    ) -> None:
        self.status_code = status_code
        self.content = content
        self.url = url
        self.charset_encoding = charset_encoding
        self.headers = {"content-type": content_type}


class _FakeClient:
    def __init__(self, response: _FakeResponse) -> None:
        self.response = response

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *args: Any) -> None:
        pass

    def get(self, url: str) -> _FakeResponse:
        return self.response


class WebScraperTestCase(unittest.TestCase):
    def setUp(self) -> None:
        w._weasyprint_state["usable"] = None
        w._chrome_state["path"] = None


class ValidateUrlTests(WebScraperTestCase):
    def test_missing_fails(self) -> None:
        with self.assertRaises(w.WebScraperError):
            w.validate_url(None)
        with self.assertRaises(w.WebScraperError):
            w.validate_url("   ")

    def test_non_http_fails(self) -> None:
        for raw in ("file:///etc/passwd", "ftp://x/y", "javascript:alert(1)", "localhost"):
            with self.assertRaises(w.WebScraperError):
                w.validate_url(raw)

    def test_http_https_ok(self) -> None:
        self.assertEqual(w.validate_url("https://a.com/x#frag"), "https://a.com/x")
        self.assertEqual(w.validate_url(" http://a.com:8080/p "), "http://a.com:8080/p")


class NormalizeChoiceTests(WebScraperTestCase):
    def test_mode_aliases(self) -> None:
        for raw, want in [("article", "article"), ("正文", "article"), ("page", "page"), ("整页", "page"), ("", "article")]:
            self.assertEqual(
                w._normalize_choice(raw, w._MODE_ALIASES, "mode", "article", w.SUPPORTED_MODES),
                want,
                raw,
            )

    def test_format_aliases(self) -> None:
        for raw, want in [("pdf", "pdf"), ("文本", "text"), ("txt", "text"), ("", "pdf")]:
            self.assertEqual(
                w._normalize_choice(raw, w._FORMAT_ALIASES, "format", "pdf", w.SUPPORTED_FORMATS),
                want,
                raw,
            )

    def test_unknown_fails(self) -> None:
        with self.assertRaises(w.WebScraperError):
            w._normalize_choice("foo", w._MODE_ALIASES, "mode", "article", w.SUPPORTED_MODES)


class DecodeTests(WebScraperTestCase):
    def test_utf8(self) -> None:
        self.assertEqual(w.decode_html("你好".encode("utf-8"), "utf-8"), "你好")

    def test_utf8_bom(self) -> None:
        data = b"\xef\xbb\xbf" + "你好".encode("utf-8")
        self.assertEqual(w.decode_html(data), "你好")

    def test_gbk_by_meta(self) -> None:
        data = '<html><head><meta charset="gbk"></head><body>中文</body></html>'.encode("gbk")
        self.assertEqual(w.decode_html(data, None), '<html><head><meta charset="gbk"></head><body>中文</body></html>')

    def test_gbk_by_header(self) -> None:
        data = "中文内容".encode("gbk")
        self.assertEqual(w.decode_html(data, "gb2312"), "中文内容")


class FetchTests(WebScraperTestCase):
    def test_fetch_ok(self) -> None:
        resp = _FakeResponse(content=_article_bytes(), url="https://e.com/final")
        with patch("httpx.Client", return_value=_FakeClient(resp)):
            data, final, ctype, declared = w.fetch_html("https://e.com/a")
        self.assertEqual(final, "https://e.com/final")
        self.assertEqual(ctype, "text/html; charset=utf-8")
        self.assertIn(b"article", data)

    def test_http_error(self) -> None:
        resp = _FakeResponse(status_code=503, content=b"x")
        with patch("httpx.Client", return_value=_FakeClient(resp)):
            with self.assertRaises(w.WebScraperError) as ctx:
                w.fetch_html("https://e.com/a")
        self.assertIn("503", str(ctx.exception))

    def test_oversize(self) -> None:
        resp = _FakeResponse(content=b"a" * 10)
        with patch("httpx.Client", return_value=_FakeClient(resp)):
            with self.assertRaises(w.WebScraperError):
                w.fetch_html("https://e.com/a", max_bytes=5)


class ExtractTests(WebScraperTestCase):
    def test_article_extract(self) -> None:
        title, fragment, text = w.extract_article(SAMPLE_HTML, "https://example.com/news/1")
        self.assertEqual(title, "测试文章标题")
        self.assertIn("关于 AI 的思考", text)
        self.assertNotIn("站点头条", text)   # site header 不带入
        self.assertNotIn("广告", text)        # ad 容器剔除
        self.assertNotIn("相关推荐", text)    # aside 剔除
        self.assertNotIn("版权声明", text)    # footer 剔除
        self.assertIn("核心内容", text)

    def test_relative_links_resolved(self) -> None:
        _, fragment, _ = w.extract_article(SAMPLE_HTML, "https://example.com/news/1")
        self.assertIn('href="https://example.com/other"', fragment)
        self.assertIn('src="https://example.com/img/a.png"', fragment)

    def test_div_content_without_article(self) -> None:
        html = (
            "<html><head><title>t</title></head><body>"
            "<div class='nav'>aa bb cc</div>"
            "<div id='content'>" + "这是正文段落。" * 20 + "</div>"
            "</body></html>"
        )
        _, fragment, text = w.extract_article(html, "https://e.com/")
        self.assertIn("这是正文段落", text)
        self.assertNotIn("aa bb cc", text)

    def test_script_style_removed(self) -> None:
        html = (
            "<html><head><title>t</title></head><body><article>"
            "<p>" + "正文ok，这是第一段内容。" * 6 + "</p>"
            "<script>var fake='x'</script><style>.a{}</style>"
            "</article></body></html>"
        )
        _, _, text = w.extract_article(html, "https://e.com/")
        self.assertNotIn("var fake", text)
        self.assertNotIn(".a{}", text)
        self.assertIn("正文ok", text)

    def test_no_content_fails(self) -> None:
        html = "<html><head><title>t</title></head><body><p>hi</p></body></html>"
        with self.assertRaises(w.WebScraperError):
            w.extract_article(html, "https://e.com/")

    def test_js_only_page_fails(self) -> None:
        html = "<html><head></head><body><div id='app'></div><script>...spa...</script></body></html>"
        with self.assertRaises(w.WebScraperError):
            w.extract_article(html, "https://e.com/")


class DocumentBuildTests(WebScraperTestCase):
    def test_make_article_html(self) -> None:
        _, fragment, _ = w.extract_article(SAMPLE_HTML, "https://e.com/a")
        doc = w.make_article_html("测试文章标题", fragment, "https://e.com/a")
        self.assertTrue(doc.lstrip().lower().startswith("<!doctype html>"))
        self.assertIn("https://e.com/a", doc)  # 来源行
        self.assertIn("正文标题", doc)

    def test_inject_page_preserves_and_adds_base(self) -> None:
        page = w.inject_page_html(SAMPLE_HTML, "https://e.com/a")
        self.assertIn('<base href="https://e.com/a">', page)
        self.assertIn("广告广告广告", page)  # 整页保真：不剔除
        self.assertIn("</body></html>", page)

    def test_inject_page_without_head(self) -> None:
        body = "<p>fragment</p>"
        page = w.inject_page_html(body, "https://e.com/")
        self.assertIn("<base", page)
        self.assertIn(body, page)


class FakeWeasyModule:
    """可注入的假 weasyprint：HTML(...).write_pdf(target) 支持路径或 file-like。"""

    class HTML:
        def __init__(self, string: str = "", base_url: str | None = None) -> None:
            self.string = string
            self.base_url = base_url

        def write_pdf(self, target: Any) -> None:
            payload = b"%PDF-1.4-fake-web-scraper"
            if hasattr(target, "write"):
                target.write(payload)
            else:
                Path(str(target)).write_bytes(payload)


class RendererAvailabilityTests(WebScraperTestCase):
    def test_weasyprint_unavailable_when_import_missing(self) -> None:
        def _boom(name: str) -> None:
            raise ImportError("no weasyprint")

        with patch("mac_edge.plugins.web_scraper.importlib") as il:
            il.import_module.side_effect = _boom
            self.assertFalse(w.weasyprint_available())

    def test_weasyprint_available_when_render_ok(self) -> None:
        with patch("mac_edge.plugins.web_scraper.importlib") as il:
            il.import_module.return_value = FakeWeasyModule
            self.assertTrue(w.weasyprint_available())

    def test_chrome_path_env(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fake = Path(td) / "fake-chrome"
            fake.write_bytes(b"#!")
            with patch.dict(os.environ, {"WEB_SCRAPER_BROWSER_PATH": str(fake)}, clear=False):
                self.assertEqual(w.chrome_path(), str(fake))
            self.assertTrue(w.chrome_available())

    def test_chrome_missing_defaults(self) -> None:
        # 本机默认装了 Chrome；这里强制探测失败（env 指向不存在 + 候选全不存在）
        with patch.dict(os.environ, {"WEB_SCRAPER_BROWSER_PATH": "/nonexistent/chrome"}, clear=False):
            with patch("mac_edge.plugins.web_scraper.Path.is_file", return_value=False):
                self.assertIsNone(w.chrome_path())

    def test_any_renderer_none_available(self) -> None:
        w._weasyprint_state["usable"] = False
        with patch("mac_edge.plugins.web_scraper.importlib") as il:
            il.import_module.side_effect = ImportError("no weasyprint")
            w._chrome_state["path"] = None
            with patch.dict(os.environ, {"WEB_SCRAPER_BROWSER_PATH": "/nonexistent/chrome"}, clear=False):
                with patch("mac_edge.plugins.web_scraper.Path.is_file", return_value=False):
                    self.assertFalse(w.any_renderer_available())

    def test_resolve_auto_page_prefers_chrome(self) -> None:
        w._weasyprint_state["usable"] = True
        w._chrome_state["path"] = "/fake/chrome"
        with patch("mac_edge.plugins.web_scraper.Path.is_file", return_value=True):
            self.assertEqual(w.resolve_renderer("auto", "page"), "chrome")

    def test_resolve_auto_article_prefers_chrome(self) -> None:
        # #671：weasyprint 70 字形偏移乱码 → auto 一律 Chrome 优先
        w._weasyprint_state["usable"] = True
        w._chrome_state["path"] = "/fake/chrome"
        self.assertEqual(w.resolve_renderer("auto", "article"), "chrome")

    def test_resolve_auto_falls_back_to_weasyprint(self) -> None:
        w._weasyprint_state["usable"] = True
        w._chrome_state["path"] = None
        with patch.dict(os.environ, {"WEB_SCRAPER_BROWSER_PATH": "/nonexistent/chrome"}, clear=False):
            with patch("mac_edge.plugins.web_scraper.Path.is_file", return_value=False):
                self.assertEqual(w.resolve_renderer("auto", "article"), "weasyprint")

    def test_resolve_explicit_unavailable(self) -> None:
        w._weasyprint_state["usable"] = False
        with self.assertRaises(w.WebScraperError):
            w.resolve_renderer("weasyprint", "article")


class RenderPdfTests(WebScraperTestCase):
    def test_weasyprint_render_writes_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            dst = Path(td) / "o.pdf"
            with patch("mac_edge.plugins.web_scraper.importlib") as il:
                il.import_module.return_value = FakeWeasyModule
                w._render_weasyprint("<p>hi</p>", "https://e.com/", dst)
            self.assertGreater(dst.stat().st_size, 0)
            self.assertEqual(dst.read_bytes(), b"%PDF-1.4-fake-web-scraper")

    def test_render_chrome_mock(self) -> None:
        # chrome 分支：子进程被 mock 成直接写一个真实 PDF
        with tempfile.TemporaryDirectory() as td:
            dst = Path(td) / "o.pdf"

            def _fake_popen(cmd, **kwargs):  # noqa: ANN001
                proc = MagicMock()
                proc.poll.return_value = None
                proc.pid = os.getpid()
                proc.stderr = io.BytesIO(b"")
                dst.write_bytes(_make_pdf_bytes())  # 模拟 Chrome 打印产物
                return proc

            with patch("mac_edge.plugins.web_scraper.chrome_path", return_value="/fake/chrome"):
                with patch("mac_edge.plugins.web_scraper.subprocess.Popen", side_effect=_fake_popen):
                    with patch("mac_edge.plugins.web_scraper._rmtree_quiet"):
                        with patch("mac_edge.plugins.web_scraper.os.killpg"):
                            w._render_chrome(Path(td) / "in.html", dst)
            self.assertGreater(dst.stat().st_size, 0)

    def test_pdf_page_count(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "x.pdf"
            p.write_bytes(_make_pdf_bytes(pages=3))
            self.assertEqual(w.pdf_page_count(p), 3)


class ScrapeFromParamsTests(WebScraperTestCase):
    def test_missing_asset_fails(self) -> None:
        with self.assertRaises(w.WebScraperError):
            w.scrape_from_params({"url": "https://e.com/a"}, asset=None)

    def test_invalid_url_fails(self) -> None:
        asset = _asset()
        with self.assertRaises(w.WebScraperError):
            w.scrape_from_params({"url": "ftp://x/y"}, asset=asset, now=TS)

    @patch("mac_edge.plugins.web_scraper.fetch_html")
    def test_text_article_output(self, fetch: MagicMock) -> None:
        fetch.return_value = (_article_bytes(), "https://example.com/news/1", "text/html; charset=utf-8", "utf-8")
        asset = _asset()
        msg, outputs = w.scrape_from_params(
            {"url": "https://example.com/news/1", "format": "text"},
            asset=asset,
            now=TS,
        )
        self.assertIn("text_asset=asset_ws_9", msg)
        self.assertEqual(outputs["format"], "text")
        self.assertEqual(outputs["mode"], "article")
        self.assertIn("char_count", outputs)
        call_kwargs = asset.upload_file.call_args.kwargs
        self.assertEqual(call_kwargs["mime_type"], "text/plain")
        self.assertEqual(call_kwargs["asset_type"], "document")
        self.assertTrue(str(call_kwargs["filename"]).endswith(".txt"))
        self.assertEqual(call_kwargs["producer"], "web.scraper")
        self.assertNotIn("page_count", outputs)

    @patch("mac_edge.plugins.web_scraper.fetch_html")
    def test_pdf_article_output(self, fetch: MagicMock) -> None:
        fetch.return_value = (_article_bytes(), "https://example.com/news/1", "text/html; charset=utf-8", "utf-8")
        asset = _asset()

        def _fake_render(html_text: str, base_url: str, dst: Path, renderer: str) -> None:  # noqa: ANN001
            Path(dst).write_bytes(_make_pdf_bytes(pages=2))

        with patch("mac_edge.plugins.web_scraper.resolve_renderer", return_value="weasyprint"):
            with patch("mac_edge.plugins.web_scraper.render_pdf_to_file", side_effect=_fake_render):
                msg, outputs = w.scrape_from_params(
                    {"url": "https://example.com/news/1"},
                    asset=asset,
                    now=TS,
                )
        self.assertIn("pdf_asset=asset_ws_9", msg)
        self.assertEqual(outputs["format"], "pdf")
        self.assertEqual(outputs["renderer"], "weasyprint")
        self.assertEqual(outputs["page_count"], 2)
        self.assertEqual(outputs["mode"], "article")
        call_kwargs = asset.upload_file.call_args.kwargs
        self.assertEqual(call_kwargs["mime_type"], "application/pdf")
        self.assertEqual(call_kwargs["asset_type"], "document")
        self.assertTrue(str(call_kwargs["filename"]).endswith(".pdf"))

    @patch("mac_edge.plugins.web_scraper.fetch_html")
    def test_page_pdf_text_without_renderer_engine_needed(self, fetch: MagicMock) -> None:
        # format=text + mode=page：无需任何渲染引擎
        fetch.return_value = (_article_bytes(), "https://example.com/news/1", "text/html; charset=utf-8", "utf-8")
        asset = _asset()
        w._weasyprint_state["usable"] = False
        w._chrome_state["path"] = None
        msg, outputs = w.scrape_from_params(
            {"url": "https://example.com/news/1", "mode": "page", "format": "text"},
            asset=asset,
            now=TS,
        )
        self.assertIn("text_asset", msg)
        self.assertEqual(outputs["mode"], "page")

    @patch("mac_edge.plugins.web_scraper.fetch_html")
    def test_pdf_article_via_url_asset_ref(self, fetch: MagicMock) -> None:
        # 消费 Brain url 资产：url 缺省、asset_ref(type=url) → http_url(content) → 抓目标页
        fetch.return_value = (
            _article_bytes(),
            "https://target.example/article",
            "text/html; charset=utf-8",
            "utf-8",
        )
        asset = MagicMock()
        asset.require_ref.return_value = AssetRef(
            asset_id="asset_url1", type="url", mime_type="text/uri-list"
        )

        content_url = (
            "http://127.0.0.1:9527/api/v1/assets/asset_url1"
            "/content?intent_id=9&representation=original"
        )
        # Real CapAsset.http_url returns a URL string (not an object with .url).
        asset.http_url.return_value = content_url
        asset.upload_file.return_value = AssetRef(
            asset_id="asset_ws_10", type="document", mime_type="application/pdf"
        )

        def _fake_render(html_text: str, base_url: str, dst: Path, renderer: str) -> None:  # noqa: ANN001
            Path(dst).write_bytes(_make_pdf_bytes(pages=1))

        with patch("mac_edge.plugins.web_scraper.resolve_renderer", return_value="weasyprint"):
            with patch("mac_edge.plugins.web_scraper.render_pdf_to_file", side_effect=_fake_render):
                msg, outputs = w.scrape_from_params(
                    {"asset_ref": {"asset_id": "asset_url1", "type": "url"}},
                    asset=asset,
                    now=TS,
                )
        asset.require_ref.assert_called_once()
        asset.http_url.assert_called_once()
        self.assertEqual(fetch.call_args.args[0], content_url)
        self.assertEqual(outputs["url"], "https://target.example/article")
        self.assertEqual(outputs["format"], "pdf")
        self.assertIn("pdf_asset=asset_ws_10", msg)

    def test_url_asset_ref_wrong_type_fails(self) -> None:
        asset = MagicMock()
        asset.require_ref.return_value = AssetRef(
            asset_id="asset_doc1", type="document", mime_type="application/pdf"
        )
        with self.assertRaises(w.WebScraperError) as ctx:
            w.scrape_from_params(
                {"asset_ref": {"asset_id": "asset_doc1", "type": "document"}},
                asset=asset,
                now=TS,
            )
        self.assertIn("type=url", str(ctx.exception))
        asset.http_url.assert_not_called()


class CapabilityRegistrationTests(WebScraperTestCase):
    def _caps(self, services: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for svc in services:
            out.extend(svc.get("capabilities") or [])
        return out

    def test_web_scraper_advertised_and_structured(self) -> None:
        services = default_services()
        svc = next(
            (s for s in services if s.get("service_id") == "local.web.scraper"),
            None,
        )
        if svc is None:
            self.skipTest("本机无可用渲染引擎（weasyprint/chrome），web.scraper 未广告")
        caps = {c.get("capability_id"): c for c in svc.get("capabilities") or []}
        self.assertIn("web.scraper", caps)
        cap = caps["web.scraper"]
        self.assertIn("input_schema", cap)
        self.assertIn("output_schema", cap)
        self.assertIn("url", cap["input_schema"])
        self.assertTrue(cap["input_schema"]["url"]["required"])

    def test_ads_contain_web_scraper_row(self) -> None:
        from mac_edge.capability_ads import ADS

        self.assertIn("web.scraper", ADS)
        self.assertEqual(ADS["web.scraper"]["kind"], "action")


if __name__ == "__main__":
    unittest.main()



