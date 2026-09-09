"""Mac Edge capability: web.scraper — given a URL, fetch a web page and export
its core content (or the faithful whole page) to a PDF document Asset — or to a
plain-text document Asset.

Pipeline:

1. **抓取** ``fetch_html``：httpx GET（桌面 UA、跟随重定向、超时/大小上限）。
2. **解码** ``decode_html``：BOM → HTTP 头 charset → ``<meta charset>`` → UTF-8。
3. **mode=article**：stdlib ``html.parser`` 建轻量 DOM，按“可读文本 − 链接文本 +
   标签/class 提示分”为 article/main/div/section 等候选容器打分选正文；剔除
   script/style/nav/aside/footer/form 噪音，保留 h1–h6/p/li/blockquote/table/img/a，
   相对链接补全绝对 URL，产出干净 HTML 与纯文本。
4. **mode=page**：保留整页 HTML，注入 ``<base href=final_url>`` 与 ``@page`` 打印 CSS。
5. **format=pdf**：交给渲染引擎转 PDF —— ``weasyprint``（进程内，需 Pango）或本机
   Chrome/Edge headless。``renderer=auto`` 时 article 优先 weasyprint、page 优先
   chrome，缺一自动回退另一；都不可用则明确中文失败。产物经 pypdf 读页数。
6. **format=text**：无需渲染引擎，直接产出 ``.txt``。
7. 产物统一经 ``asset.upload_file(producer="web.scraper", ...)`` 登记为 document
   Asset（PDF ``application/pdf`` / 文本 ``text/plain``），返回新 ``asset_ref``。

对外入口：``scrape_from_params(params, *, asset, now=None)`` —— 与 file.convert /
printer.print 对齐，``asset`` 是 Runtime SDK 的 ``CapAsset`` 会话。
"""

from __future__ import annotations

import importlib
import logging
import os
import re
import subprocess
import tempfile
import time
from datetime import datetime
from html import escape as _html_escape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

log = logging.getLogger("mac_edge.web_scraper")

MODE_ARTICLE = "article"
MODE_PAGE = "page"
SUPPORTED_MODES = frozenset({MODE_ARTICLE, MODE_PAGE})

FORMAT_PDF = "pdf"
FORMAT_TEXT = "text"
SUPPORTED_FORMATS = frozenset({FORMAT_PDF, FORMAT_TEXT})

RENDERER_AUTO = "auto"
RENDERER_WEASYPRINT = "weasyprint"
RENDERER_CHROME = "chrome"
SUPPORTED_RENDERERS = frozenset({RENDERER_AUTO, RENDERER_WEASYPRINT, RENDERER_CHROME})

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
FETCH_TIMEOUT_SEC = 25.0
MAX_HTML_BYTES = 8 * 1024 * 1024  # 8 MiB 抓取上限
RENDER_TIMEOUT_SEC = 90.0         # 渲染（weasyprint/chrome）超时

_MODE_ALIASES = {
    "article": MODE_ARTICLE,
    "正文": MODE_ARTICLE,
    "核心": MODE_ARTICLE,
    "内容": MODE_ARTICLE,
    "extract": MODE_ARTICLE,
    "page": MODE_PAGE,
    "整页": MODE_PAGE,
    "完整": MODE_PAGE,
    "full": MODE_PAGE,
    "原样": MODE_PAGE,
}
_FORMAT_ALIASES = {
    "pdf": FORMAT_PDF,
    "pdf文档": FORMAT_PDF,
    "pdf文件": FORMAT_PDF,
    "text": FORMAT_TEXT,
    "txt": FORMAT_TEXT,
    "文本": FORMAT_TEXT,
}
_RENDERER_ALIASES = {
    "auto": RENDERER_AUTO,
    "weasyprint": RENDERER_WEASYPRINT,
    "weasy": RENDERER_WEASYPRINT,
    "chrome": RENDERER_CHROME,
    "chromium": RENDERER_CHROME,
    "edge": RENDERER_CHROME,
    "浏览器": RENDERER_CHROME,
}

_HINT_RE = re.compile(
    r"(?:^|[\s_-])(article|content|main|body|post|entry|story|text|blog|page|"
    r"news|detail|article-body|rich_media|js_content)(?:[\s_-]|$)",
    re.IGNORECASE,
)
_MIN_CANDIDATE_TEXT = 40  # 候选主体至少要有这么多非链接字符，否则退回 body
_CANDIDATE_CONTAINERS = frozenset({"article", "main", "div", "section", "td"})

# 整棵子树丢弃的噪音标签
_DROP_SUBTREE_TAGS = frozenset(
    {
        "script", "style", "noscript", "template", "iframe", "frameset", "frame",
        "svg", "canvas", "object", "embed", "applet", "form", "button", "select",
        "textarea", "input", "label", "nav", "aside", "footer", "head", "link",
        "meta", "base", "title", "video", "audio", "source", "track", "map",
        "area", "dialog", "math", "picture", "portal",
    }
)
# 序列化时保留的语义标签（去掉属性，只留必要的 href/src）
_KEEP_TAGS = frozenset(
    {
        "h1", "h2", "h3", "h4", "h5", "h6", "p", "br", "hr", "ul", "ol", "li",
        "dl", "dt", "dd", "blockquote", "pre", "code", "figure", "figcaption",
        "img", "a", "div", "section", "span", "strong", "em", "b", "i", "u",
        "s", "small", "sub", "sup", "mark", "del", "ins", "table", "thead",
        "tbody", "tfoot", "tr", "th", "td", "caption", "q", "abbr", "time",
        "address",
    }
)
# 只展开子节点、自身不输出的“透明容器”（避免把页面级包裹结构带进 PDF）
_TRANSPARENT_TAGS = frozenset(
    {"html", "body", "header", "article", "main", "center", "font"}
)
_VOID_TAGS = frozenset(
    {"br", "hr", "img", "source", "track", "input", "area", "base", "meta",
     "link", "col", "embed", "param"}
)
_BLOCK_TEXT_TAGS = frozenset(
    {
        "h1", "h2", "h3", "h4", "h5", "h6", "p", "div", "section", "ul", "ol",
        "li", "dl", "dt", "dd", "blockquote", "pre", "table", "tr", "caption",
        "figure", "figcaption", "hr", "address",
    }
)
_HEADING_START_RE = re.compile(r"^\s*<h[1-3](?:\s|>)", re.IGNORECASE)


class WebScraperError(Exception):
    """web.scraper 明确中文失败（URL 非法 / 抓取失败 / 抽不到正文 / 渲染器不可用…）。"""


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------

def _clean_text(raw: str) -> str:
    """把连续空白（含换行）折叠成单个空格，去掉首尾空白。"""
    return re.sub(r"\s+", " ", raw or "").strip()


def _safe_display_filename(raw: Any, suffix: str, ts: datetime) -> str:
    """Brain 文件名白名单 [A-Za-z0-9\\u4e00-\\u9fff_-] + 后缀。"""
    text = str(raw or "").strip()
    if text:
        text = Path(text.replace("\\", "/")).name.strip()
        ext = Path(text).suffix.lower()
        text = Path(text).stem if ext else text
    if not text:
        text = f"web-scraper-{ts.strftime('%Y%m%d-%H%M%S')}"
    cleaned = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff_-]", "-", text)
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    if not cleaned:
        cleaned = f"web-scraper-{ts.strftime('%Y%m%d-%H%M%S')}"
    if len(cleaned) > 80:
        cleaned = cleaned[:80].rstrip("-")
    return f"{cleaned}.{suffix.lstrip('.')}"


def validate_url(raw: Any) -> str:
    """url 校验：必填、http/https、有主机名；返回去掉片段后的规范串。"""
    text = str(raw or "").strip()
    if not text:
        raise WebScraperError("web.scraper 缺少必填 url（http/https 网页地址）")
    parsed = urlparse(text)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise WebScraperError(
            f"url 仅支持 http/https 网页，收到 {text!r}（禁止 file:// 等本地协议）"
        )
    return parsed._replace(fragment="").geturl()


def _normalize_choice(raw: Any, aliases: dict[str, str], label: str, default: str, supported: frozenset[str]) -> str:
    text = str(raw or "").strip().lower().replace("_", "").replace(" ", "")
    if not text:
        return default
    hit = aliases.get(text) or aliases.get(str(raw or "").strip().lower())
    if hit is not None:
        return hit
    for alias, canonical in aliases.items():
        if text == alias.replace("_", "").replace(" ", ""):
            return canonical
    raise WebScraperError(
        f"{label} 无法识别：{raw!r}（可用 {' / '.join(sorted(supported))}）"
    )


def _mode_label(mode: str) -> str:
    return "核心正文" if mode == MODE_ARTICLE else "忠实整页"


# ---------------------------------------------------------------------------
# 抓取 + 解码
# ---------------------------------------------------------------------------

def fetch_html(url: str, *, timeout: float = FETCH_TIMEOUT_SEC, max_bytes: int = MAX_HTML_BYTES) -> tuple[bytes, str, str, str | None]:
    """httpx GET：跟随重定向；返回 (bytes, final_url, content_type, declared_charset)。

    非 2xx / 超时 / 超出容量上限 → 明确中文失败。
    """
    try:
        import httpx
    except Exception as e:  # pragma: no cover - 缺依赖
        raise WebScraperError(f"web.scraper 依赖 httpx 缺失：{e}") from e
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
    }
    try:
        with httpx.Client(
            follow_redirects=True, timeout=timeout, headers=headers
        ) as client:
            resp = client.get(url)
    except Exception as e:
        raise WebScraperError(f"抓取网页失败（{url}）：{type(e).__name__}: {e}") from e
    if resp.status_code >= 400:
        raise WebScraperError(
            f"抓取网页失败（{url}）：HTTP {resp.status_code}"
        )
    content = resp.content or b""
    if not content:
        raise WebScraperError(f"网页为空（{url}）")
    if len(content) > max_bytes:
        raise WebScraperError(
            f"网页超过抓取上限（{len(content)} > {max_bytes} 字节）：{url}"
        )
    final_url = str(resp.url)
    content_type = str(resp.headers.get("content-type") or "").strip()
    declared = str(getattr(resp, "charset_encoding", None) or "").strip() or None
    return content, final_url, content_type, declared


def decode_html(content: bytes, declared: str | None = None) -> str:
    """按 BOM → 声明 charset → <meta charset> → UTF-8 兜底解码 HTML。"""
    if not content:
        raise WebScraperError("网页内容为空，无法解码")
    candidates: list[str] = []
    if content.startswith(b"\xef\xbb\xbf"):
        candidates.append("utf-8-sig")
    if declared and str(declared).strip():
        candidates.append(str(declared).strip().lower())
    meta = re.search(
        rb"""<meta[^>]+charset\s*=\s*["']?\s*([A-Za-z0-9_\-:.]+)""",
        content[:4096],
        re.IGNORECASE,
    )
    if meta:
        candidates.append(meta.group(1).decode("ascii", errors="ignore").lower())
    candidates.append("utf-8")
    seen: set[str] = set()
    for enc in candidates:
        enc = (enc or "").strip()
        if not enc or enc in seen:
            continue
        seen.add(enc)
        try:
            return content.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return content.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# 轻量 DOM
# ---------------------------------------------------------------------------

class _Node:
    """极简 DOM 节点：children 里字符串为文本节点、_Node 为元素，保序。"""

    __slots__ = ("tag", "attrs", "children")

    def __init__(self, tag: str, attrs: list[tuple[str, str | None]] | None = None) -> None:
        self.tag = tag
        self.attrs = attrs or []
        self.children: list[Any] = []


class _DomBuilder(HTMLParser):
    """用 html.parser 把整页建成轻量 DOM（容忍错误闭合）。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("__root__", [])
        self.stack: list[_Node] = [self.root]

    def _push(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Node(tag, attrs)
        self.stack[-1].children.append(node)
        self.stack.append(node)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() not in _VOID_TAGS:
            self._push(tag.lower(), attrs)
        else:
            self.stack[-1].children.append(_Node(tag.lower(), attrs))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.stack[-1].children.append(_Node(tag.lower(), attrs))

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data: str) -> None:
        if data:
            self.stack[-1].children.append(data)


def build_dom(html: str) -> _Node:
    """把 HTML 字符串解析成轻量 DOM，返回根节点。"""
    parser = _DomBuilder()
    try:
        parser.feed(html or "")
        parser.close()
    except Exception as e:  # pragma: no cover - 解析器容错
        log.warning("web.scraper DOM 解析异常（忽略，继续）：%s", e)
    return parser.root


# ---------------------------------------------------------------------------
# 正文抽取：打分 + 序列化
# ---------------------------------------------------------------------------

def _iter_nodes(node: _Node):
    for child in node.children:
        if isinstance(child, _Node):
            yield child
            yield from _iter_nodes(child)


_AD_ATTR_RE = re.compile(
    r"(?:^|[\s_-])(ad|ads|advert|advertise|advertisement|banner|promo|sponsor|"
    r"related|recommend|social|share|subscribe|newsletter|comment|commercial|"
    r"portlet|interlanguage|langlinks)"
    r"(?:[\s_-]|$)",
    re.IGNORECASE,
)
_ATTR_NOISE_TAGS = frozenset({"div", "section", "span", "ul", "figure", "table", "aside", "nav"})


def _node_hint(node: _Node) -> str:
    parts: list[str] = []
    for name, value in node.attrs:
        if name in ("id", "class") and value:
            parts.append(str(value))
    return " ".join(parts)


def _should_drop(node: _Node) -> bool:
    """标签级或 class/id/role 级噪音（广告/推荐/导航/社交/评论等容器整棵丢弃）。"""
    if node.tag in _DROP_SUBTREE_TAGS:
        return True
    for name, value in node.attrs:
        if name == "role" and str(value or "").strip().lower() == "navigation":
            return True
    if node.tag in _ATTR_NOISE_TAGS and _AD_ATTR_RE.search(_node_hint(node)):
        return True
    return False


def measure_text(node: _Node) -> tuple[int, int]:
    """返回 (total_chars, link_chars)：子树文本总长与 <a> 内文本长。

    丢弃噪音子树（_DROP_SUBTREE_TAGS + 广告/推荐类容器），不计入。
    """
    total = 0
    link = 0

    def walk(n: _Node, in_link: bool) -> None:
        nonlocal total, link
        if _should_drop(n):
            return
        child_link = in_link or n.tag == "a"
        for child in n.children:
            if isinstance(child, str):
                size = len(child)
                total += size
                if child_link:
                    link += size
            else:
                walk(child, child_link)

    walk(node, False)
    return total, link


def score_candidate(node: _Node, total: int, link: int) -> float:
    usable = max(0, total - link)
    score = float(usable) - float(link)
    tag = node.tag
    if tag in ("article", "main"):
        score += 600.0
    if _HINT_RE.search(_node_hint(node)):
        score += 250.0
    return score


def find_article_node(root: _Node) -> _Node | None:
    """打分选正文容器；都没有合格候选才退回 <body>；仍不够则 None。"""
    best: _Node | None = None
    best_score = float("-inf")
    for node in _iter_nodes(root):
        if _should_drop(node):
            continue
        tag = node.tag
        if tag in ("article", "main") or (
            tag in _CANDIDATE_CONTAINERS and _HINT_RE.search(_node_hint(node))
        ):
            total, link = measure_text(node)
            usable = max(0, total - link)
            if usable < _MIN_CANDIDATE_TEXT:
                continue
            score = score_candidate(node, total, link)
            if score > best_score:
                best_score, best = score, node
    body: _Node | None = None
    for node in _iter_nodes(root):
        if node.tag == "body":
            body = node
            break
    if best is None and body is not None:
        b_total, b_link = measure_text(body)
        if max(0, b_total - b_link) >= _MIN_CANDIDATE_TEXT:
            best = body
    return best


def _find_title(root: _Node) -> str:
    for node in _iter_nodes(root):
        if node.tag == "title":
            text = "".join(c for c in node.children if isinstance(c, str))
            text = _clean_text(text)
            if text:
                return text
    return ""


def _resolve_attr(value: str | None, base_url: str) -> str | None:
    """把相对 URL 补全为绝对 http(s) URL；非 http(s)/空 → None。"""
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.startswith(("data:", "javascript:", "mailto:", "tel:", "#")):
        return None
    joined = urljoin(base_url, raw)
    parsed = urlparse(joined)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return joined


def serialize_node(node: _Node, base_url: str) -> str:
    """把选中容器子树转成干净 HTML 片段（保语义标签、丢弃噪音与无谓属性）。"""
    parts: list[str] = []

    def esc_text(text: str) -> str:
        return _html_escape(text, quote=False)

    def esc_attr(value: str) -> str:
        return _html_escape(value, quote=True)

    def emit(n: _Node) -> None:
        tag = n.tag
        if _should_drop(n):
            return
        if tag in _TRANSPARENT_TAGS or tag not in _KEEP_TAGS:
            for child in n.children:
                if isinstance(child, str):
                    parts.append(esc_text(child))
                else:
                    emit(child)
            return
        attrs: list[str] = []
        if tag == "a":
            href = _resolve_attr(dict(n.attrs).get("href"), base_url)
            if href:
                attrs.append(f'href="{esc_attr(href)}"')
        elif tag == "img":
            src = _resolve_attr(dict(n.attrs).get("src"), base_url)
            if not src:
                return  # 无法补全的图直接丢弃
            out_attrs = [f'src="{esc_attr(src)}"']
            alt = _clean_text(str(dict(n.attrs).get("alt") or ""))
            if alt:
                out_attrs.append(f'alt="{esc_attr(alt)}"')
            parts.append(f"<img {' '.join(out_attrs)} />")
            return
        if tag in _VOID_TAGS:  # br / hr 等空元素，不输出闭合标签
            parts.append(f"<{tag}>" if not attrs else f"<{tag} {' '.join(attrs)}>")
            return
        if attrs:
            parts.append(f"<{tag} {' '.join(attrs)}>")
        else:
            parts.append(f"<{tag}>")
        for child in n.children:
            if isinstance(child, str):
                parts.append(esc_text(child))
            else:
                emit(child)
        parts.append(f"</{tag}>")

    emit(node)
    out = "".join(parts)
    out = re.sub(r"[ \t]+\n", "\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def node_to_text(node: _Node) -> str:
    """把节点子树转成可读纯文本（块级标签间空行分段）。"""

    def walk_inline(n: _Node, target: list[str]) -> None:
        for child in n.children:
            if isinstance(child, str):
                target.append(child)
            elif not _should_drop(child):
                walk_inline(child, target)

    lines: list[str] = []
    inline: list[str] = []

    def flush() -> None:
        text = "".join(inline).strip()
        if text:
            lines.append(text)
        inline.clear()

    def walk(n: _Node) -> None:
        for child in n.children:
            if isinstance(child, str):
                inline.append(child)
                continue
            child_tag = child.tag
            if _should_drop(child):
                continue
            if child_tag in (
                "a", "strong", "em", "b", "i", "u", "s", "small", "sub", "sup",
                "mark", "code", "span", "q", "abbr", "time", "del", "ins",
            ):
                walk_inline(child, inline)
                continue
            if child_tag in _BLOCK_TEXT_TAGS or child_tag in _TRANSPARENT_TAGS:
                flush()
                walk(child)
                flush()
            else:
                walk(child)
        flush()

    if _should_drop(node):
        return ""
    walk(node)
    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# 文档组装（article 干净文档 / page 整页注入）
# ---------------------------------------------------------------------------

_ARTICLE_CSS = """\
@page { size: A4; margin: 1.5cm 1.4cm; }
body { font-family: -apple-system, 'PingFang SC', 'Hiragino Sans GB', 'Noto Sans CJK SC', 'Microsoft YaHei', sans-serif; font-size: 11.5pt; line-height: 1.75; color: #1a1a1a; margin: 0; }
h1 { font-size: 20pt; line-height: 1.35; margin: 0 0 0.4em; }
h2 { font-size: 16pt; margin: 1em 0 0.4em; }
h3 { font-size: 14pt; margin: 0.8em 0 0.3em; }
h4, h5, h6 { font-size: 12.5pt; margin: 0.6em 0 0.2em; }
p { margin: 0.55em 0; text-align: justify; }
img { max-width: 100%; height: auto; }
pre { white-space: pre-wrap; background: #f6f6f6; padding: 8px; font-size: 9.5pt; border-radius: 4px; }
code { font-family: Menlo, Consolas, monospace; font-size: 9.5pt; }
blockquote { margin: 0.6em 0; padding-left: 1em; border-left: 3px solid #ccc; color: #444; }
ul, ol { margin: 0.5em 0; padding-left: 1.6em; }
table { border-collapse: collapse; width: 100%; }
th, td { border: 1px solid #ccc; padding: 4px 8px; font-size: 10.5pt; }
a { color: #0b57d0; text-decoration: none; word-break: break-all; }
.article-source { color: #666; font-size: 9.5pt; margin-bottom: 1.2em; word-break: break-all; }
"""

_PAGE_EXTRA_CSS = """\
@page { size: A4; margin: 1.2cm; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
"""


def make_article_html(title: str, fragment: str, source_url: str) -> str:
    """把标题 + 干净正文片段 + 抓取来源组装成一份可打印 HTML。"""
    esc_title = _html_escape(_clean_text(title), quote=False)
    head = f"<h1>{esc_title}</h1>" if not _HEADING_START_RE.match(fragment) else ""
    source = (
        f'<div class="article-source">来源：'
        f'<a href="{_html_escape(source_url, quote=True)}">{_html_escape(source_url, quote=True)}</a>'
        f"</div>"
    )
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        f"<title>{esc_title}</title><style>{_ARTICLE_CSS}</style></head>"
        f"<body>{head}{source}{fragment}</body></html>"
    )


def inject_page_html(html_text: str, base_url: str) -> str:
    """整页模式：保留原 HTML，注入 <base href> 与 @page 打印 CSS。"""
    base_tag = f'<base href="{_html_escape(base_url, quote=True)}">'
    style = f"<style>{_PAGE_EXTRA_CSS}</style>"
    setup = f"{base_tag}{style}"
    m = re.search(r"<head[^>]*>", html_text, re.IGNORECASE)
    if m:
        return html_text[: m.end()] + setup + html_text[m.end():]
    m_html = re.search(r"<html[^>]*>", html_text, re.IGNORECASE)
    if m_html:
        return html_text[: m_html.end()] + f"<head>{setup}</head>" + html_text[m_html.end():]
    return f"<!doctype html><html><head>{setup}</head><body>{html_text}</body></html>"


def extract_article(html_text: str, base_url: str) -> tuple[str, str, str]:
    """返回 (title, fragment, plain_text)；抽不到正文则明确中文失败。"""
    root = build_dom(html_text)
    node = find_article_node(root)
    title = _find_title(root)
    if not title:
        try:
            title = urlparse(base_url).netloc or base_url
        except Exception:
            title = base_url
    if node is None:
        raise WebScraperError(
            f"从该网页抽不到正文（可能是 JS 渲染页或非文章页）：{base_url}"
        )
    fragment = serialize_node(node, base_url)
    text = node_to_text(node)
    if not text.strip():
        raise WebScraperError(
            f"从该网页抽不到正文（可能是 JS 渲染页或非文章页）：{base_url}"
        )
    return title, fragment, text


# ---------------------------------------------------------------------------
# PDF 渲染引擎（weasyprint / Chrome-Edge headless）
# ---------------------------------------------------------------------------

_weasyprint_state: dict[str, bool | None] = {"usable": None}
_chrome_state: dict[str, str | None] = {"path": None}


def weasyprint_available() -> bool:
    """weasyprint 是否可用：import + 极小渲染探测（缺 Pango 时渲染会抛错）。"""
    if _weasyprint_state["usable"] is not None:
        return bool(_weasyprint_state["usable"])
    usable = False
    try:
        import io

        weasyprint = importlib.import_module("weasyprint")
        out = io.BytesIO()
        weasyprint.HTML(string="<p>probe</p>", base_url=None).write_pdf(out)
        usable = len(out.getvalue()) > 0
    except Exception as e:  # pragma: no cover - 环境探测
        log.info("weasyprint 不可用：%s", e)
    _weasyprint_state["usable"] = usable
    if usable:
        log.info("weasyprint usable (renderer available)")
    return usable


def chrome_path() -> str | None:
    """定位本机 Chrome/Edge/Chromium 可执行文件；env 优先，结果进程内缓存。"""
    if _chrome_state["path"] is not None:
        return _chrome_state["path"]
    found = None
    env = (os.environ.get("WEB_SCRAPER_BROWSER_PATH") or "").strip()
    if env:
        p = Path(env).expanduser()
        if p.is_file():
            found = str(p)
    if not found:
        home = Path.home()
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            str(home / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            str(home / "Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium",
            "/usr/bin/microsoft-edge",
            "/usr/bin/chromium-browser",
        ]
        for cand in candidates:
            if Path(cand).is_file():
                found = cand
                break
    _chrome_state["path"] = found
    return found


def chrome_available() -> bool:
    return chrome_path() is not None


def any_renderer_available() -> bool:
    """services.py 广告门控用：pdf 至少有一条渲染路径可用即可广告。"""
    return weasyprint_available() or chrome_available()


def resolve_renderer(requested: str, mode: str) -> str:
    """把 renderer 参数解析为实际可用引擎；都不可用 → 明确中文失败。"""
    if requested == RENDERER_WEASYPRINT:
        if weasyprint_available():
            return RENDERER_WEASYPRINT
        raise WebScraperError(
            "renderer=weasyprint 不可用：未安装 weasyprint 或系统缺 Pango；"
            "可改 renderer=chrome（本机 Chrome/Edge headless）"
        )
    if requested == RENDERER_CHROME:
        if chrome_available():
            return RENDERER_CHROME
        raise WebScraperError(
            "renderer=chrome 不可用：本机没找到 Chrome/Edge；"
            "可用 WEB_SCRAPER_BROWSER_PATH 指定，或改 renderer=weasyprint"
        )
    # auto：article 优先 weasyprint（纯 Python），page 优先 chrome（整页保真）
    if mode == MODE_PAGE:
        if chrome_available():
            return RENDERER_CHROME
        if weasyprint_available():
            return RENDERER_WEASYPRINT
    else:
        if weasyprint_available():
            return RENDERER_WEASYPRINT
        if chrome_available():
            return RENDERER_CHROME
    raise WebScraperError(
        "没有可用的 PDF 渲染引擎：weasyprint（需 Pango）与 Chrome/Edge 都不可用；"
        "text 格式不需要渲染引擎"
    )


def _render_weasyprint(html_text: str, base_url: str, dst: Path) -> None:
    weasyprint = importlib.import_module("weasyprint")

    out = weasyprint.HTML(string=html_text, base_url=base_url or None)
    out.write_pdf(str(dst))
    if not (dst.exists() and dst.stat().st_size > 0):
        raise WebScraperError("weasyprint 渲染产出为空 PDF")


def _render_chrome(html_file: Path, dst: Path) -> None:
    """用本机 Chrome/Edge headless 把本地 HTML 打印成 PDF。

    实测 Chrome headless 出完 PDF 后进程可能不退出，因此这里 Popen + 轮询产物 +
    超时强杀，并清理临时 user-data-dir。
    """
    browser = chrome_path()
    if not browser:
        raise WebScraperError("chrome/edge headless 不可用")
    profile = tempfile.mkdtemp(prefix="web-scraper-chrome-")
    html_uri = html_file.expanduser().resolve().as_uri()
    cmd = [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--disable-background-networking",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        f"--user-data-dir={profile}",
        "--no-pdf-header-footer",
        f"--print-to-pdf={dst}",
        html_uri,
    ]
    proc: subprocess.Popen[bytes] | None = None
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        deadline = time.monotonic() + RENDER_TIMEOUT_SEC
        stable_since: float | None = None
        done = False
        while time.monotonic() < deadline:
            if dst.exists() and dst.stat().st_size > 0:
                if stable_since is None:
                    stable_since = time.monotonic()
                elif time.monotonic() - stable_since >= 1.0:
                    done = True
                    break
            else:
                stable_since = None
            if proc.poll() is not None and not (dst.exists() and dst.stat().st_size > 0):
                break
            time.sleep(0.5)
        if not done and not (dst.exists() and dst.stat().st_size > 0):
            _kill_chrome(proc)
            err = _chrome_stderr(proc)
            raise WebScraperError(f"Chrome headless 渲染超时或失败：{err}")
    finally:
        _kill_chrome(proc)
        _rmtree_quiet(profile)
    if not (dst.exists() and dst.stat().st_size > 0):
        raise WebScraperError("Chrome headless 渲染产出为空 PDF")


def _kill_chrome(proc: subprocess.Popen[bytes] | None) -> None:
    if proc is None:
        return
    if proc.poll() is None:
        try:
            os.killpg(os.getpgid(proc.pid), 9)
        except Exception:
            try:
                proc.terminate()
            except Exception:
                pass
    try:
        proc.wait(timeout=3)
    except Exception:
        pass


def _chrome_stderr(proc: subprocess.Popen[bytes] | None) -> str:
    if proc is None:
        return ""
    try:
        err = (proc.stderr.read() or b"")[-400:]
        return err.decode("utf-8", errors="replace").strip()
    except Exception:
        return ""


def _rmtree_quiet(path: str) -> None:
    try:
        import shutil

        shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass


def render_pdf_to_file(
    html_text: str,
    base_url: str,
    dst: Path,
    renderer: str,
) -> None:
    """按已解析的 renderer 渲染 HTML → PDF 文件。"""
    if renderer == RENDERER_WEASYPRINT:
        _render_weasyprint(html_text, base_url, dst)
        return
    if renderer == RENDERER_CHROME:
        fd, tmp_name = tempfile.mkstemp(prefix="web-scraper-page-", suffix=".html")
        tmp_html = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(html_text)
            _render_chrome(tmp_html, dst)
        finally:
            tmp_html.unlink(missing_ok=True)
        return
    raise WebScraperError(f"未知渲染引擎：{renderer!r}")


def pdf_page_count(path: Path) -> int:
    """用 pypdf 读 PDF 页数；读不了则明确失败（不应发生在渲染成功后）。"""
    try:
        from pypdf import PdfReader
    except Exception as e:  # pragma: no cover - 缺依赖
        raise WebScraperError(f"web.scraper 依赖 pypdf 缺失：{e}") from e
    try:
        return len(PdfReader(str(path)).pages)
    except Exception as e:
        raise WebScraperError(f"读取生成的 PDF 失败：{e}") from e


def _find_body(root: _Node) -> _Node:
    for node in _iter_nodes(root):
        if node.tag == "body":
            return node
    return root


def _page_plain_text(html_text: str) -> tuple[str, str]:
    """整页 → (title, 可读全文)：跳过 head/script/style，保留正文排版文本。"""
    root = build_dom(html_text)
    title = _find_title(root)
    body = _find_body(root)
    return title, node_to_text(body)


def _make_text_output(title: str, source_url: str, text: str) -> str:
    parts: list[str] = []
    if _clean_text(title):
        parts.append(_clean_text(title))
    parts.append(f"来源：{source_url}")
    if _clean_text(text):
        parts.append(text)
    return "\n\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# 能力入口
# ---------------------------------------------------------------------------

def scrape_from_params(
    params: dict[str, Any],
    *,
    asset: Any,
    now: datetime | None = None,
) -> tuple[str, dict[str, Any]]:
    """Capability entry：校验 → 抓取 → 抽取/组装 → 渲染/导出 → 上传登记 → 输出。"""
    if asset is None or not (
        hasattr(asset, "require_refs") or hasattr(asset, "upload_file")
    ):
        raise WebScraperError("web.scraper 需要 CapAsset（Runtime SDK）")

    raw = params if isinstance(params, dict) else {}

    url = validate_url(raw.get("url"))
    mode = _normalize_choice(raw.get("mode"), _MODE_ALIASES, "mode", MODE_ARTICLE, SUPPORTED_MODES)
    fmt = _normalize_choice(raw.get("format"), _FORMAT_ALIASES, "format", FORMAT_PDF, SUPPORTED_FORMATS)
    if fmt == FORMAT_PDF:
        renderer = _normalize_choice(raw.get("renderer"), _RENDERER_ALIASES, "renderer", RENDERER_AUTO, SUPPORTED_RENDERERS)
    else:
        renderer = RENDERER_AUTO
    ts = now or datetime.now()

    # 1. 抓取 + 解码
    content, final_url, _content_type, declared = fetch_html(url)
    html_text = decode_html(content, declared)
    if not html_text.strip():
        raise WebScraperError(f"网页解码后为空（{final_url}）")

    title = ""
    plain_text = ""
    if mode == MODE_ARTICLE:
        title, fragment, plain_text = extract_article(html_text, final_url)
    elif fmt == FORMAT_TEXT:
        title, plain_text = _page_plain_text(html_text)
    else:
        title = _find_title(build_dom(html_text))

    char_count = len(plain_text or "")
    mode_cn = _mode_label(mode)

    if fmt == FORMAT_TEXT:
        doc_text = _make_text_output(title, final_url, plain_text)
        if not _clean_text(plain_text):
            raise WebScraperError(f"该网页没有可导出的文本内容：{final_url}")
        txt_name = _safe_display_filename(raw.get("name"), "txt", ts)
        fd, tmp_name = tempfile.mkstemp(prefix="web-scraper-text-", suffix=".txt")
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(doc_text.encode("utf-8"))
            try:
                out_ref = asset.upload_file(
                    tmp,
                    producer="web.scraper",
                    mime_type="text/plain",
                    asset_type="document",
                    filename=txt_name,
                )
            except Exception as e:
                raise WebScraperError(f"文本上传登记失败：{e}") from e
        finally:
            tmp.unlink(missing_ok=True)
        status_text = (
            f"已从 {url} 抓取{mode_cn}并导出为文本"
            f"（{char_count} 字），已登记为 document Asset {out_ref.asset_id}"
        )
        outputs: dict[str, Any] = {
            "asset_ref": out_ref.to_dict(),
            "title": title,
            "url": final_url,
            "mode": mode,
            "format": FORMAT_TEXT,
            "char_count": char_count,
            "status_text": status_text,
        }
        log.info(
            "web.scraper ok text mode=%s chars=%s asset=%s url=%s",
            mode, char_count, out_ref.asset_id, final_url,
        )
        return (
            f"web.scraper ok text_asset={out_ref.asset_id} mode={mode} chars={char_count}",
            outputs,
        )

    # format == pdf
    actual_renderer = resolve_renderer(renderer, mode)
    if mode == MODE_ARTICLE:
        doc_html = make_article_html(title, fragment, final_url)
    else:
        doc_html = inject_page_html(html_text, final_url)
    pdf_name = _safe_display_filename(raw.get("name"), "pdf", ts)
    fd, tmp_name = tempfile.mkstemp(prefix="web-scraper-pdf-", suffix=".pdf")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as _fh:  # 占位空文件，渲染会覆盖
            pass
        try:
            render_pdf_to_file(doc_html, final_url, tmp, actual_renderer)
        except WebScraperError:
            raise
        except Exception as e:
            raise WebScraperError(f"HTML 转 PDF 失败（{actual_renderer}）：{type(e).__name__}: {e}") from e
        page_count = pdf_page_count(tmp)
        try:
            out_ref = asset.upload_file(
                tmp,
                producer="web.scraper",
                mime_type="application/pdf",
                asset_type="document",
                filename=pdf_name,
            )
        except Exception as e:
            raise WebScraperError(f"PDF 上传登记失败：{e}") from e
    finally:
        tmp.unlink(missing_ok=True)

    status_text = (
        f"已从 {url} 抓取{mode_cn}并转成 PDF"
        f"（{page_count} 页，{actual_renderer} 渲染），"
        f"已登记为 document Asset {out_ref.asset_id}"
    )
    outputs = {
        "asset_ref": out_ref.to_dict(),
        "title": title,
        "url": final_url,
        "mode": mode,
        "format": FORMAT_PDF,
        "renderer": actual_renderer,
        "page_count": page_count,
        "char_count": char_count,
        "status_text": status_text,
    }
    log.info(
        "web.scraper ok mode=%s renderer=%s pages=%s asset=%s url=%s",
        mode, actual_renderer, page_count, out_ref.asset_id, final_url,
    )
    return (
        f"web.scraper ok pdf_asset={out_ref.asset_id} mode={mode} "
        f"renderer={actual_renderer} pages={page_count}",
        outputs,
    )








