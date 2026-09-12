# Plan：PDF 投屏到小米电视（`display.pdf` / `display.pdf.page`，支持翻页）

> 落盘：task-d1a3cf0d · 开发分支 `feature/task-d1a3cf0d` · 交付方式：PR 到 main

## 1. 目标与定位

用户问：「可以把 Pdf 文件直接投屏到小米电视上显示吗？支持翻页」。

小米电视（澎湃 OS）没有 Google Cast，现有 `xiaomi-tv-display` 插件经 **DLNA AVTransport**
只能投**图片**（`display.photo` / `display.slideshow`），电视端无法直接渲染 PDF。
因此本任务在 Mac Edge 新增 **PDF 投屏能力**：把 PDF 每页渲染成图片，经现有显示后端
（小米 DLNA / Cast HTTP）投上电视，并提供**翻页**能力（下一页 / 上一页 / 跳到第 N 页）。

典型闭环：

1. 「把最新的 PDF 投到电视上」→ planner：`asset.inventory`（最新 document）→
   `display.pdf`（$asset_ref）→ Mac 渲染第 1 页 → 上传图床 → DLNA 投屏。
2. 「下一页」→ planner：`display.pdf.page`（action=next）→ Mac 渲染第 N+1 页 → 投屏。
3. 「翻到第 5 页」→ `display.pdf.page`（action=goto, page=5）。

## 2. 已确认决策汇总

| 维度 | 决策 |
|---|---|
| 执行层 | Mac Edge 插件（`kind=output`），Brain 只路由，不新增 server 依赖 |
| 渲染 | **PyMuPDF**（pip `pymupdf`，wheel 自足无系统依赖）；缺依赖则不广告、明确中文失败 |
| 页图格式 | PNG（文字清晰），默认 200 DPI（`MAC_EDGE_PDF_DISPLAY_DPI` 可调） |
| 页图通道 | 逐页懒渲染 + 上传 Brain 图床登记为 image Asset（现成授权/取链通道），会话内缓存 asset_ref，同页不重复上传 |
| 投屏后端 | 复用 `display_backend()`：xiaomi → DLNA `play_photo`；cast → Cast HTTP `cast_photo` |
| 翻页状态 | Mac Edge 进程内单会话（当前 PDF asset_id、本地路径、页数、当前页、页缓存）；重启即失效，翻页时明确中文提示重新打开 |
| 页码语义 | 1-based；越界翻页不报错，停在边界页并中文提示（「已经是最后一页」） |
| wire 契约 | `display.pdf`（asset_ref 必填 / page 可选）+ `display.pdf.page`（action=next/prev/goto，goto 带 page） |

## 3. 能力标识与契约

- plugin id：`pdf-display` · group：`display`
- wire capability：`display.pdf` / `display.pdf.page` · kind：`output`
- 执行方：Mac Edge laptop（`mac_edge.plugins.pdf_display`）
- 广告方：现有显示服务（`xiaomi.tv.display` 或 `chromecast.display`，按 `display_backend()`），
  且仅当本机可 import pymupdf 时附加这两个 capability

### `display.pdf`（打开并投屏）

| 方向 | 内容 |
|------|------|
| 输入 | `asset_ref`（必填，type=document PDF）；`page`（可选，默认 1，1-based） |
| 输出 | `page`（当前页）、`page_count`、`asset_id`、`status_text`（中文一句话） |

### `display.pdf.page`（翻页）

| 方向 | 内容 |
|------|------|
| 输入 | `action`（可选，next/prev/goto，接受 下一页/上一页/翻到 等中文别名，缺省 next）；`page`（goto 必填，1-based） |
| 输出 | `page`、`page_count`、`status_text` |

无活动会话（未打开过 PDF / Edge 重启）→ 明确中文失败，提示先「把 PDF 投到电视」。

## 4. 技术方案

Mac 侧 `mac/src/mac_edge/plugins/pdf_display.py`：

- **渲染**：`pymupdf.open(path)` → `page.get_pixmap(dpi=...)` → PNG 字节写会话目录
  （`MAC_EDGE_DATA_DIR/pdf-display/<asset_id>/` 或 tempdir）；页缓存 `{page: AssetRef}`。
- **上传**：`CapAsset.upload_file(path, producer="display.pdf", mime_type="image/png",
  asset_type="image")` → `asset.http_url(ref)` 得 LAN URL（电视可拉）。
- **投屏**：按 `display_backend()` 调 `xiaomi_tv_display.play_photo(url)` 或
  `chromecast_display.cast_photo(url, display_base_url=...)`（与 executor 的
  `display.photo` 分支同一套选择逻辑）。
- **会话**：模块级 `_SESSION`（asset_id / path / page_count / current_page / page_refs /
  渲染目录）；新 `display.pdf` 覆盖旧会话并清理旧渲染目录。
- 加密 / 无页 / 渲染失败 / 缺参 → 明确中文失败，不产生脏 Asset。

## 5. 代码改动清单（逐文件）

1. `plugins/pdf-display/capability.md` + `manifest.yaml` 新建
2. `mac/src/mac_edge/plugins/pdf_display.py` 新建（渲染 + 会话 + 两个 `*_from_params` 入口）
3. `mac/src/mac_edge/services.py` 显示服务按 pymupdf 可用性附加 `display.pdf` /
   `display.pdf.page` 广告（xiaomi / cast 两个服务共用）
4. `mac/src/mac_edge/executor.py` import + `display.pdf` / `display.pdf.page` 分发
5. `mac/src/mac_edge/capability_ads.py` 新增两条广告
6. `server/capability_ads.py` 镜像两条广告
7. `server/edge_services.py` `KNOWN_CAPABILITIES` 登记两条
8. `mac/requirements.txt` 增加 `pymupdf`
9. `mac/tests/test_pdf_display.py` 新建单测
10. `agent_plans/pdf_tv_display_v1.md` 本计划落盘

## 6. 测试

`mac/tests/test_pdf_display.py`：

- 页码解析 / action 别名（next/prev/goto/中文）与缺参中文失败；
- 无会话翻页 → 明确中文失败；
- 打开 + 翻页全流程：mock CapAsset（物化本地 PDF、上传返回 AssetRef）+ 注入
  render/display 假实现 → 断言当前页推进、页缓存复用（同页不重复上传）、
  越界停在边界页；
- 若本机装有 pymupdf：真实渲染一个 2 页 PDF 断言 PNG 产出（无则 skip）。

回归：跑 `mac/` 与 `server/` 相关测试（services / ads / executor / 显示插件）。

## 7. 明确不做（另开任务）

- 电视端直接渲染 PDF（DLNA 协议本身不支持，只能投图片）；
- 双指缩放 / 批注 / 演讲者模式等查看器功能；
- iOS / Android 端 UI；
- 跨 Edge 会话共享（会话只在执行显示的 Mac 进程内）；
- 本任务只交付分支与 PR，不自行 merge、不触发 release/deploy。

## 8. 交付流程

在任务工作区 `task-d1a3cf0d` 开发，分支 `feature/task-d1a3cf0d`，按清单实现并单测 →
`git commit` → `git push -u origin HEAD` → `gh pr create` 并把 PR URL 交给用户等待合入。
