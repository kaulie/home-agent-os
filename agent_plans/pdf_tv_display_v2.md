# Plan v2：PDF 投屏小米电视 + 独立 PDF 渲染能力（`pdf.to_images` 复用拆分）

> 落盘：task-d1a3cf0d · 开发分支 `feature/task-d1a3cf0d` · 交付方式：PR 到 main
>
> **v2 变更**（相对 `pdf_tv_display_v1.md`）：应用户要求把「PDF 每页渲染成高清图片」
> 拆成**独立可复用能力 `pdf.to_images`**；渲染底层抽成共享模块 `pdf_render.py`，
> `display.pdf`（电视翻页场景）保持逐页懒渲染但复用同一渲染模块。

## 1. 目标与定位

两件事：

1. **PDF 投屏电视 + 翻页**（v1 原有）：`display.pdf` 打开 PDF 投到电视，
   `display.pdf.page` 翻页（下一页/上一页/第 N 页）。
2. **独立渲染能力 `pdf.to_images`**（v2 新增）：把 PDF/document Asset 的每页
   （或指定页范围）渲染成高清 PNG，逐页登记为 image Asset，产出 `asset_refs`
   供任意下游复用——`display.slideshow` 轮播、逐页 OCR、`vision.ask` 看某页、
   重新 `file.convert` 合成等。

复用关系：`pdf_render.py`（PyMuPDF 渲染 / DPI / 页数）为共享底层；
`pdf.to_images` 与 `display.pdf` 都是它的调用方。

## 2. 已确认决策汇总

| 维度 | 决策 |
|---|---|
| 渲染拆分 | 独立 wire 能力 `pdf.to_images`（kind=action，group=convert） |
| 共享底层 | `mac_edge/plugins/pdf_render.py`：`pymupdf_available` / `pdf_page_count` / `render_page_png` / `render_dpi` |
| `display.pdf` 渲染策略 | **保持懒渲染**（逐页按需）：整份预渲染+上传对大 PDF 太慢且污染 Asset 目录；翻页会话仍需进程内状态 |
| 渲染依赖 | PyMuPDF（pip `pymupdf`）；缺依赖则不广告、明确中文失败 |
| 页图格式 | PNG，默认 200 DPI（`MAC_EDGE_PDF_DISPLAY_DPI`，钳制 72–400） |
| 页范围 | `page_start` / `page_end`（可选，1-based，缺省整份；钳到边界）；安全上限 200 页/次 |
| 页图通道 | 上传 Brain 图床登记 image Asset（`producer=pdf.to_images` / `display.pdf`） |
| 页码语义 | 1-based；display.pdf 越界翻页停在边界页并中文提示 |

## 3. 能力标识与契约

### `pdf.to_images`（新，独立渲染能力）

- plugin id：`pdf-to-images` · service_id：`local.pdf.images` · group：`convert`
- kind：`action` · 执行方：Mac Edge laptop（`mac_edge.plugins.pdf_to_images`）

| 方向 | 内容 |
|------|------|
| 输入 | `asset_ref`（必填，type=document PDF）；`page_start` / `page_end`（可选，1-based，缺省整份）；`dpi`（可选，默认 200） |
| 输出 | `asset_refs`（image AssetRef 数组，顺序=页码）、`page_count`、`rendered_pages`、`status_text` |

### `display.pdf` / `display.pdf.page`（投屏 + 翻页，同 v1）

- 执行方：`mac_edge.plugins.pdf_display`；广告在显示服务
  （`xiaomi.tv.display` / `chromecast.display`）上，按 `pymupdf_available()` 门控。
- `display.pdf`：入 `asset_ref`(document) + 可选 `page`；出 `page`/`page_count`/`status_text`。
- `display.pdf.page`：入 `action`=next/prev/goto（goto 带 `page`）；出 `page`/`page_count`/`status_text`。
  无会话明确中文失败；next/prev 越界停在边界页中文提示；goto 越界明确失败。

## 4. 技术方案

- `mac/src/mac_edge/plugins/pdf_render.py`（共享，新）：PyMuPDF 导入兼容
  （pymupdf/fitz）、`pdf_page_count`、`render_page_png(path, idx0, dpi, out)`、
  `render_dpi()`（env 可调）、`pymupdf_available()`。
- `mac/src/mac_edge/plugins/pdf_to_images.py`（新）：物化 PDF → 解析页范围 →
  逐页渲染 → `CapAsset.upload_file`（image/png, type=image, producer=pdf.to_images）
  → 汇总 `asset_refs`。
- `mac/src/mac_edge/plugins/pdf_display.py`（v1 已有，改为复用 pdf_render）：
  进程内单会话；懒渲染当前页 → 上传 → DLNA/Cast 投屏；跨 intent 翻回旧页时
  授权失效则用本地 PNG 重传。

## 5. 代码改动清单（逐文件）

1. `mac/src/mac_edge/plugins/pdf_render.py` 新建（共享渲染底层）
2. `mac/src/mac_edge/plugins/pdf_to_images.py` 新建（`pdf.to_images`）
3. `mac/src/mac_edge/plugins/pdf_display.py` 改为复用 pdf_render（v1 已建）
4. `plugins/pdf-to-images/capability.md` + `manifest.yaml` 新建
5. `plugins/pdf-display/capability.md` + `manifest.yaml`（v1 已建，补共享模块说明）
6. `mac/src/mac_edge/services.py`：`LOCAL_PDF_IMAGES_SERVICE`（pymupdf 门控）+
   显示服务附加 `display.pdf`/`display.pdf.page`（v1 已改）
7. `mac/src/mac_edge/executor.py`：`pdf.to_images` 分发（display 两个 v1 已加）
8. `mac/src/mac_edge/capability_ads.py` + `server/capability_ads.py`：`pdf.to_images`
   广告（display 两条 v1 已加）
9. `server/edge_services.py`：`KNOWN_CAPABILITIES["pdf.to_images"]`（display 两条 v1 已登记）
10. `mac/requirements.txt` + `mac/pyproject.toml`：`pymupdf`（v1 已加）
11. `mac/tests/test_pdf_render.py` / `test_pdf_to_images.py` 新建；
    `test_pdf_display.py`（v1 已建）随共享模块调整 import
12. `agent_plans/pdf_tv_display_v2.md` 本计划落盘

## 6. 测试

- `test_pdf_render.py`：DPI 解析/钳制；页数读取（加密/空 PDF 中文失败）；
  真实渲染（有 pymupdf 时，pypdf 造 fixture，否则 skip）。
- `test_pdf_to_images.py`：页范围解析/钳制；缺 asset_ref / 非 document 中文失败；
  mock CapAsset + 假渲染 → `asset_refs` 顺序=页码、上传次数=页数；超上限失败。
- `test_pdf_display.py`：v1 用例保持（页码推进、页缓存、授权失效重传、广告门控、
  executor 分发）。
- 回归：`mac/` 与 `server/` 相关测试（services / ads / executor / 显示 / 转换插件）。

## 7. 明确不做（另开任务）

- 电视端直接渲染 PDF（DLNA 不支持，只能投图片）；
- `display.slideshow` 与 PDF 页码语义对齐（轮播就是轮播，不带「第 N 页」）；
- 缩放/批注等查看器功能；iOS/Android UI；跨 Edge 会话共享；
- 本任务只交付分支与 PR，不自行 merge、不触发 release/deploy。

## 8. 交付流程

任务工作区 `task-d1a3cf0d`，分支 `feature/task-d1a3cf0d`，实现并单测 →
`git commit` → `git push -u origin HEAD` → `gh pr create`，PR URL 交给用户等待合入。
