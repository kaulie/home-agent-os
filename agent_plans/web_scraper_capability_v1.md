# Plan：新增网页抓取能力 `web.scraper`（URL → 核心正文/整页 → PDF/文本）

> 落盘：task-c7cf506e · 开发分支 `feature/task-c7cf506e-web-craper` · 交付方式：PR 到 main

## 1. 目标与定位

新增一个独立能力 `web.scraper`：给定一个 **http(s) 网页 URL**，抓取网页并把内容转成
**PDF document Asset**（或**纯文本** Asset），产物可交给 `printer.print` / 后续流程。
能力以 **Mac Edge 插件**形态实现（与 pdf.rotate/file.convert 同层），Brain 只负责规划
路由与协议登记（server 侧 capability_ads / edge_services 同步镜像）。

典型闭环：用户说「把这个网址 http… 的文章转成 PDF」→ planner 派 `web.scraper` 到
Mac Edge → 抓网页 → 抽核心正文（或整页）→ weasyprint / Chrome headless 渲染 PDF →
上传 Brain 登记为 document Asset → 对话返回文本结果与 `asset_ref`。

## 2. 已确认决策汇总

| 维度 | 决策 |
|---|---|
| 能力名 | wire `web.scraper`，服务 `local.web.scraper`，group=`convert` |
| 执行层 | Mac Edge 插件（`kind=action`），Brain 只路由 |
| mode | `article`（默认，抽核心正文） / `page`（忠实整页） |
| format | `pdf`（默认） / `text`（纯文本 .txt，`text/plain`） |
| renderer | `auto`（默认） / `weasyprint` / `chrome`；article 优先 weasyprint、page 优先 chrome，缺一自动回退 |
| 正文抽取 | stdlib `html.parser` 轻量 DOM + 文本密度打分（零新增解析依赖） |
| PDF 引擎 | weasyprint（纯 Python，需系统 Pango）与 Chrome/Edge headless 都实现、可对比 |
| 输出 | 上传 Brain 登记 document Asset（PDF `application/pdf` / 文本 `text/plain`），pypdf 读页数 |
| 依赖 | 新增 weasyprint（requirements + pyproject）；httpx/pypdf 复用已有 |
| 广告门控 | weasyprint 可用或 chrome 可用才广告 `local.web.scraper` |
| 安全 | url 仅 http/https；抓取带 UA/超时/容量上限；文件名走 Brain 白名单清洗 |

## 3. 能力标识与契约

- 入参：`url`（必填）、`mode`、`format`、`renderer`、`name`
- 出参：`asset_ref`/`title`/`url`/`mode`/`format`/`renderer`(pdf)/`page_count`(pdf)/`char_count`/`status_text`
- 失败：缺 url / 非 http(s) / 抓取失败 / 解码失败 / article 抽不到正文 / pdf 无可用渲染引擎 / 上传失败 → 明确中文失败

## 4. 改动文件

mac：`plugins/web_scraper.py`（新）、`executor.py`（分支）、`services.py`（广告）、
`capability_ads.py`（广告）、`tests/test_web_scraper.py`（新）、requirements.txt/pyproject。
server：`capability_ads.py`（广告）、`edge_services.py`（KNOWN_CAPABILITIES）。
plugins：`web-scraper/manifest.yaml` + `capability.md`（新）。

## 5. 验收

- 单测覆盖：URL 校验 / 抽取打分与噪音剔除 / 链接补全 / 双引擎渲染(mock) / text 无需引擎 / 上传与广告。
- 本机实测：weasyprint 70 + `brew install pango` 可用；Chrome headless 可用；二者对同一
  Wikipedia 文章各渲染 14 页 PDF，抽取正文干净（语言导航已剔除）。
