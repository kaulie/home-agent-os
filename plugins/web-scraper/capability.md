# Service: local.web.scraper

网页抓取插件（`web-scraper`），group=`convert`。给定一个 **http(s) 网页 URL**（或引用已登记的
Brain **url 资产**，`type=url`），抓取网页并把内容转成 **PDF 文档 Asset**（或**纯文本** Asset），
产物可交给 `printer.print` 打印或其它流程继续消费。

**Brain 不执行**；只通过心跳看到 `web.scraper`，再把 plan 派到具备该能力的 Edge
（Mac Edge laptop，`mac_edge.plugins.web_scraper`）。本机有可用 PDF 渲染引擎
（weasyprint+Pango 或 Chrome/Edge headless 至少其一）才广告。

## 规划自描述

| 字段 | 值 |
|------|-----|
| role | 网页抓取器（URL / url 资产 → 核心正文/整页 → PDF/文本） |
| planner_recognize | 用户给一个 http(s) 网址、或引用已登记的 Brain url 资产（type=url），要求把网页抓下来存成 PDF 或文本时用本步。入参 url（http/https）与 asset_ref（type=url 的 Brain url 资产）二选一；mode=article 抓核心正文（默认，剔除广告/导航）/ page 抓忠实整页；format=pdf（默认）/ text；renderer=auto/weasyprint/chrome（仅 pdf，本机自动挑可用引擎）。产出登记为新 document Asset，可交给 printer.print 打印或后续流程。本步只抓网页转文档，不打印、不问答 |
| typical_triggers | `把这个网页存成 PDF`、`把网址 http… 的文章转成 PDF`、`抓取这篇文章转成 PDF`、`把我存的链接转成 PDF`、`把网页正文导出成文本`、`保存这个网页`、`网页转 PDF` |
| do_not_dispatch | 打印、OCR、翻译、整页截图、下载图片、看图理解、投屏、配网、浏览网页问答 |

## 标识

| 字段 | 值 |
|------|-----|
| plugin id | `web-scraper` |
| service_id | `local.web.scraper` |
| group | `convert` |
| wire capability | `web.scraper` |
| kind | `action` |
| 执行方 | Mac Edge laptop（`mac_edge.plugins.web_scraper`） |

## 契约

| 方向 | 内容 |
|------|------|
| **输入** | `url`（http/https）与 `asset_ref`（可选，type=url 的 Brain url 资产）二选一；`mode`（默认 `article`=核心正文 / `page`=忠实整页）；`format`（默认 `pdf` / `text`）；`renderer`（默认 `auto` / `weasyprint` / `chrome`，仅 pdf 生效）；`name`（可选展示名） |
| **输出** | `asset_ref`（新 document AssetRef）；`title`；`url`（最终 URL）；`mode`；`format`；`renderer`（pdf 时）；`page_count`（pdf 时）；`char_count`；`status_text`（中文一句话） |

缺 `url` / 非 http(s) / 抓取失败 / 解码失败 / 抽不到正文（article） / pdf 但没有
可用渲染引擎 / 上传失败 → **明确中文失败**，不产生脏 Asset。

## 两种 mode

- **`article`（默认，核心正文）**：stdlib `html.parser` 建轻量 DOM，对
  `article/main/div/section` 等候选容器按“可读文本 − 链接文本 + 标签/class 提示分”
  打分选正文主体；剔除 `script/style/nav/aside/footer/header/form` 与广告/推荐类
  容器，保留 h1–h6/p/li/blockquote/pre/table/img/a 等语义标签并清掉无谓属性，
  相对 `href/src` 补全为绝对 URL；再套一层 A4 打印 CSS 排版。
- **`page`（忠实整页）**：保留原 HTML 全貌（含 JS/样式/广告导航），仅注入
  `<base href=最终URL>` 与 `@page` 打印 CSS，交给渲染引擎按网页原样分页。

> **局限**：`article` 只适合服务端渲染的文章/博客页；SPA（内容全靠 JS 动态渲染）
> 或非文章页会抽不到正文而明确失败，建议这类用 `mode=page` + `renderer=chrome`
> （Chrome 会执行页面 JS 后再打印整页）。

## PDF 渲染引擎（都实现，可比较）

| 引擎 | 依赖 | 特点 | auto 策略 |
|------|------|------|-----------|
| `weasyprint` | pip 装 weasyprint + 系统 **Pango ≥ 1.44**（macOS：`brew install pango`） | 纯 Python 排版、页内可控、不跑页面 JS | 仅显式 `renderer=weasyprint` 选择 |
| `chrome` | 本机 Chrome/Edge/Chromium（`WEB_SCRAPER_BROWSER_PATH` 可指定） | 真浏览器排版、执行 JS、整页还原度高 | **`auto` 默认优先（所有 mode）** |

- `renderer=auto`（默认）：**Chrome 优先**（缺浏览器才回退 weasyprint）。两者都不可用 → 中文失败。
- 可显式 `renderer=weasyprint|chrome` 强制指定以便**对比效果**。
- 探测（weasyprint=import+极小渲染 / chrome=找可执行文件）结果在进程内缓存，
  `services.py` 广告 `local.web.scraper` 前先 `any_renderer_available()`。

> **已知问题 #671**：weasyprint 70 + Pango 在本机把苹方等 TTC 子集化时会出现
> “字形偏移乱码”（PDF 文字层/ToUnicode 正常，但渲染出来每个字符错位、肉眼不可读）。
> 因此 `auto` 一律走 **Chrome**；weasyprint 仍保留给后续修复/对比。
>
> > **效果对比建议**：复杂页面（重 CSS/JS、图文混排）Chrome 还原更接近网页原貌；
> > 纯文本/规整文章两者差异不大，weasyprint 输出体积更小且不依赖 GUI 应用。

## 技术实现

- **抓取**：httpx GET（桌面 UA、跟随重定向、25s 超时、8 MiB 上限）→ 解码
  （BOM → HTTP charset → `<meta charset>` → UTF-8 兜底）。
- **url 资产消费**：入参给 `asset_ref(type=url)` 时，经 CapAsset 取 Brain `/content`
  （带本 intent grant，302 到目标链接），httpx 跟随重定向直达原网页再走同一抓取管线。
- **正文抽取**：自研 DOM-lite（无 lxml/无网络解析器依赖）；打分 + 噪音剔除。
- **PDF**：weasyprint（`HTML(string=…).write_pdf`）或 Chrome headless
  （`--headless=new --print-to-pdf`，临时 user-data-dir + 轮询产物 + 超时强杀回收）。
- **text**：无需渲染引擎，直接产出 `.txt`（UTF-8，`text/plain`）。
- **上传**：经 `asset.upload_file(producer="web.scraper", …)` 登记 document Asset
  （PDF `application/pdf` / 文本 `text/plain`）；页数用 pypdf 读。

## 输入 schema

| 字段 | 必填 | 说明 |
|---|---|---|
| `url` | 否* | http/https 网页地址；与 asset_ref 二选一（*至少给一个） |
| `asset_ref` | 否* | 已登记的 Brain url 资产（`type=url`）AssetRef；与 url 二选一，填了就抓该链接 |
| `mode` | 否 | `article`=核心正文（默认）/ `page`=忠实整页；接受 正文/整页 等中文 |
| `format` | 否 | `pdf`（默认）/ `text`；接受 文本 |
| `renderer` | 否 | `auto`（默认）/ `weasyprint` / `chrome`（仅 pdf 生效） |
| `name` | 否 | 产物展示名；不传则 `web-scraper-<时间戳>-<mode>.*` |

## 输出 schema

| 字段 | 说明 |
|---|---|
| `asset_ref` | 新 document AssetRef（PDF/文本） |
| `title` | 网页标题 |
| `url` | 跟随重定向后的最终 URL |
| `mode` | `article` / `page` |
| `format` | `pdf` / `text` |
| `renderer` | pdf 时的实际引擎：`weasyprint` / `chrome` |
| `page_count` | pdf 页数 |
| `char_count` | 导出文本字符数 |
| `status_text` | 中文一句话结果 |

## 入口

- Mac：`mac/src/mac_edge/plugins/web_scraper.py`；`services.py` 广告
  `local.web.scraper`（laptop 角色且本机有渲染引擎时广告）
- 执行器：`mac/src/mac_edge/executor.py` 的 `web.scraper` 分支
- 协议登记：`server/edge_services.py` 的 `KNOWN_CAPABILITIES["web.scraper"]`；
  `server/capability_ads.py` 与 `mac/src/mac_edge/capability_ads.py` 同步广告
