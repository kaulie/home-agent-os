# Service: PDF 投屏（display.pdf / display.pdf.page）

PDF 投屏插件（`pdf-display`），group=`display`。
把 PDF 每页渲染成图片，经现有显示后端投到电视，并支持**翻页**。

小米电视（澎湃 OS）没有 Google Cast，且 DLNA AVTransport 只能投图片、不能直接渲染
PDF。本插件是 `display.photo` / `display.slideshow` 的同族扩展：wire 新增
`display.pdf`（打开）与 `display.pdf.page`（翻页），显示后端仍按
`MAC_EDGE_DISPLAY_BACKEND` 选择（xiaomi DLNA / Cast HTTP），与 `display.photo` 一致。

**Brain 不执行**；只通过心跳看到这两个 capability，再把 plan 派到具备该能力的
Edge（Mac Edge laptop，`mac_edge.plugins.pdf_display`）。本机可 import pymupdf
时显示服务才附加广告这两个 capability。

## 规划自描述

| 字段 | 值 |
|------|-----|
| role | PDF 投屏打开器 / PDF 投屏翻页器 |
| planner_recognize（display.pdf） | 把本步已有的 PDF/document Asset 投到电视上显示（每页渲染成图片逐页投）。入参 asset_ref（必填，type=document，常为 $asset_ref），可选 page（默认第 1 页）。用户没指定哪份 PDF 时，先排 asset.inventory 取最新 document 再接本步 |
| planner_recognize（display.pdf.page） | 电视正在投屏 PDF 时翻页：下一页（默认）/上一页/翻到第 N 页。入参 action=next/prev/goto（goto 必填 page）。不需要 asset_ref——翻的是当前投屏会话里那份 PDF。没有正在投屏的 PDF 时本步会失败，应先经 display.pdf 打开会话 |
| typical_triggers | 把这份 PDF 投到电视 / PDF 上电视；下一页 / 上一页 / 翻到第 5 页 |
| do_not_dispatch | 打印、OCR、看图理解、单图投屏、幻灯片 |

## 标识

| 字段 | 值 |
|------|-----|
| plugin id | `pdf-display` |
| service_id | `xiaomi.tv.display` / `chromecast.display`（按显示后端共用广告） |
| group | `display` |
| wire capability | `display.pdf` / `display.pdf.page` |
| kind | `output` |
| 执行方 | Mac Edge laptop（`mac_edge.plugins.pdf_display`） |

## 契约

### `display.pdf`（打开并投屏）

| 方向 | 内容 |
|------|------|
| **输入** | `asset_ref`（必填，AssetRef，`type=document` PDF）；`page`（可选，默认 1，1-based；超出范围钳到边界页并在 status_text 说明） |
| **输出** | `page`（number，当前页）、`page_count`（number）、`asset_id`、`status_text`（中文一句话） |

### `display.pdf.page`（翻页）

| 方向 | 内容 |
|------|------|
| **输入** | `action`（可选，`next` 默认 / `prev` / `goto`，接受 下一页/上一页/翻到 等中文别名）；`page`（`goto` 必填，1-based） |
| **输出** | `page`、`page_count`、`status_text` |

本能力 **只看本步入参 + 本进程会话**。缺 `asset_ref` / 非 `document` / 读不了文件 /
加密 / 空 PDF / 无活动会话翻页 / `goto` 页码越界 → **明确中文失败**，不产生脏 Asset。
`next`/`prev` 越界不算失败：停在边界页，`status_text` 提示「已经是第一页 / 最后一页」。

## 会话与页图语义

- **会话**：Mac Edge 进程内单会话（一台电视一个画面）：当前 PDF 的 asset_id、
  本地路径、页数、当前页、已渲染页缓存。新 `display.pdf` 覆盖旧会话并清理旧渲染目录；
  **Edge 重启会话即失效**，翻页时明确中文提示先重新打开。
- **渲染**：PyMuPDF 逐页懒渲染成 PNG，默认 200 DPI（`MAC_EDGE_PDF_DISPLAY_DPI`，
  钳制 72–400）；渲染产物缓存于 `MAC_EDGE_DATA_DIR/pdf-display/<asset_id>/`（或 tempdir）。
- **页图通道**：渲染页经 `CapAsset.upload_file` 上传 Brain 图床登记为 image Asset
  （`producer=display.pdf`），`asset.http_url(ref)` 取 LAN URL 供电视拉取——与
  `display.photo` 同一套授权/取链通道。页图 Asset 授权按 intent 授予；跨 intent 翻回
  已显示过的页时旧 AssetRef 授权可能不在当前 intent，此时用本地已渲染 PNG 在当前
  intent 下重传（同 intent 内同页不重复上传）。

## 技术实现

- **渲染**：复用共享模块 `mac_edge.plugins.pdf_render`（PyMuPDF，wheel 自足无系统依赖；
  缺依赖时不广告、执行明确中文失败），与独立渲染能力 `pdf.to_images`
  （`plugins/pdf-to-images`）同源——本插件按页懒渲染，`pdf.to_images` 整份/范围渲染。
- **投屏**：`display_backend() == "xiaomi"` → DLNA `SetAVTransportURI` + `Play`
  （`xiaomi_tv_display.play_photo`）；否则 Cast HTTP `cast_photo`（:9095）。
- **取 PDF**：`CapAsset.materialize_file(ref)` 物化本步 document Asset。

## 入口

- Mac：`mac/src/mac_edge/plugins/pdf_display.py`；`services.py` 在两个显示服务上
  按 `pymupdf_available()` 附加广告
- 执行器：`mac/src/mac_edge/executor.py` 的 `display.pdf` / `display.pdf.page` 分支
- 协议登记：`server/edge_services.py` 的 `KNOWN_CAPABILITIES["display.pdf"]` /
  `["display.pdf.page"]`；`server/capability_ads.py` 与
  `mac/src/mac_edge/capability_ads.py` 同步广告
