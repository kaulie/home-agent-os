# Service: local.pdf.images

PDF 页面渲染插件（`pdf-to-images`），group=`convert`。
把已有 `type=document`（PDF）Asset 的每页（或指定页范围）经 **PyMuPDF** 渲染成
高清 PNG，逐页上传 Brain 图床登记为 image Asset，产出 `asset_refs`（顺序=页码）
供下游复用：`display.slideshow` 轮播、逐页 OCR、`vision.ask` 看某页、
`file.convert` 重新合成等。

**Brain 不执行**；只通过心跳看到 `pdf.to_images`，再把 plan 派到具备该能力的
Edge（Mac Edge laptop，`mac_edge.plugins.pdf_to_images`）。本机可 import
pymupdf 时才广告。渲染底层复用 `mac_edge.plugins.pdf_render`，与电视投屏
`display.pdf` 同源。

## 规划自描述

| 字段 | 值 |
|------|-----|
| role | PDF 页面渲染器 |
| planner_recognize | 把本步已有的 PDF/document Asset 的每页（或 page_start–page_end 页范围）渲染成高清 PNG 图片并逐页登记为 image Asset，产出 asset_refs（顺序=页码），可交给 display.slideshow 轮播、逐页 OCR、vision.ask 看某页等下游。入参 asset_ref（必填，type=document），可选 page_start/page_end/dpi（默认 200）。本能力只渲染登记图片，不投屏、不 OCR、不打印；电视翻页场景用 display.pdf，不要经本能力整份预渲染 |
| typical_triggers | `把这个 PDF 每页转成图片`、`PDF 转图片`、`把这份 PDF 拆成一页一页的图`、`把 PDF 第 3 到 5 页转成图` |
| do_not_dispatch | 打印、OCR、看图理解、投屏翻页、PDF 旋转、图片合成 PDF、拍照 |

## 标识

| 字段 | 值 |
|------|-----|
| plugin id | `pdf-to-images` |
| service_id | `local.pdf.images` |
| group | `convert` |
| wire capability | `pdf.to_images` |
| kind | `action` |
| 执行方 | Mac Edge laptop（`mac_edge.plugins.pdf_to_images`） |

## 契约

| 方向 | 内容 |
|------|------|
| **输入** | `asset_ref`（必填，AssetRef，`type=document` PDF）；`page_start` / `page_end`（可选，1-based 闭区间，缺省整份，越界钳到边界）；`dpi`（可选，默认 200，钳制 72–400）；`name`（可选，页图文件名前缀） |
| **输出** | `asset_refs`（image AssetRef JSON 数组，顺序=页码）；`page_count`（number，PDF 总页数）；`rendered_pages`（number，本次渲染页数）；`status_text`（中文一句话） |

本能力 **只看本步入参**。缺 `asset_ref` / 非 `document` / 读不了文件 / 加密 /
空 PDF / 页范围无效（start > end）/ 单次超 200 页 → **明确中文失败**，不产生脏 Asset。

## 技术实现

- **渲染**：共享模块 `mac_edge.plugins.pdf_render`（PyMuPDF，wheel 自足无系统依赖）：
  `pdf_page_count` / `render_page_png(path, idx0, dpi, out)` / `render_dpi`。
- **取 PDF**：`CapAsset.materialize_file(ref)` 物化本步 document Asset。
- **回传产物**：每页 PNG 写 `MAC_EDGE_DATA_DIR/pdf-to-images/<asset_id>/`（或 tempdir）
  → Brain `/api/v1/assets/upload`（`manager.upload_file`）以 `mime=image/png`、
  `type=image`、`producer/pdf.to_images` 上传登记（现成通道，无需改 Brain）。

## 入口

- Mac：`mac/src/mac_edge/plugins/pdf_to_images.py`；`services.py` 广告
  `local.pdf.images`（laptop 角色且本机可 import pymupdf 时广告）
- 执行器：`mac/src/mac_edge/executor.py` 的 `pdf.to_images` 分支
- 协议登记：`server/edge_services.py` 的 `KNOWN_CAPABILITIES["pdf.to_images"]`；
  `server/capability_ads.py` 与 `mac/src/mac_edge/capability_ads.py` 同步广告
