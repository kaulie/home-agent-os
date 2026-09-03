# Service: local.file.convert

独立格式转换插件（`file-convert`），group=`convert`。  **纯标准库**生成 PDF，零新增依赖。
一期只实现 **image → pdf**；其它 from→to 组合与 HEIC/WebP 等源格式**明确中文失败**。

**Brain 不执行**；只通过心跳看到 `file.convert`，再把 plan 派到具备该能力的
Edge（Mac Edge laptop，`mac_edge.plugins.file_convert`）。

## 规划自描述

| 字段 | 值 |
|------|-----|
| role | 文件格式转换器 |
| planner_recognize | 把本步已有的一张或多张 Image Asset 按顺序合并转成一个 PDF 文档 Asset。入参 `asset_refs`（必填，type=image 数组，顺序即页码）、`to_format=pdf`（可选 from_format=image）。本能力只产出 PDF，不打印、不 OCR、不识别内容 |
| typical_triggers | `把这几张图转成 PDF`、`图片转 PDF`、`合成一个 PDF`、`把这几张照片合并成 PDF`、`转成 PDF 文件`、`把扫描件导成 PDF` |
| do_not_dispatch | 打印、OCR、看图理解、投屏、拍照、图片上传本身、文字识别 |

## 标识

| 字段 | 值 |
|------|-----|
| plugin id | `file-convert` |
| service_id | `local.file.convert` |
| group | `convert` |
| wire capability | `file.convert` |
| kind | `action` |
| 执行方 | Mac Edge laptop（`mac_edge.plugins.file_convert`） |

## 契约

| 方向 | 内容 |
|------|------|
| **输入** | `to_format`（必填，一期仅 `pdf`）；`from_format`（可选，缺省推断 `image`，显式非 `image` 失败）；`asset_refs`（必填，非空 type=image AssetRef 数组，顺序=页码）；`name`（可选，默认 `convert-<时间戳>.pdf`） |
| **输出** | `asset_ref`（新登记 document AssetRef，type=document）；`page_count`（number）；`status_text`（中文一句话，含页数与 asset_id） |

本能力 **只看本步入参**。非法格式组合 / 缺参 / 非 image / 不支持的图片变体
（隔行 PNG、16bit、渐进/算术 JPEG、HEIC、WebP…）→ **明确中文失败**，不产生脏 Asset。

### 页面语义

- 多张按 `asset_refs` 顺序合并为多页 PDF，**1 张 = 1 页**（覆盖单张场景）。
- 每页统一 **A4 纵向**（595.276 × 841.89 pt），留边距（默认上下/左右约 36pt，可调常量），
  图片按 `min` 缩放**等比适配居中留白边**。

### 源格式

| 格式 | 支持 | 说明 |
|------|------|------|
| JPEG | ✅ | baseline / sequential Huffman；JPEG 直嵌 `DCTDecode`。progressive / 算术编码明确失败 |
| PNG | ✅ | 8bit、非隔行，color type 0/2/3/4/6；alpha 在**白色背景**上拍平 |
| HEIC / WebP | ❌ | 一期未接入，明确中文失败 |

## 技术实现（纯标准库）

- **JPEG**：扫描 marker 到 SOF0/SOF1 取宽高，原字节作为 `/DCTDecode` 图像流直嵌 PDF
  （`/ColorSpace /DeviceRGB`，灰度 JPEG 用 `/DeviceGray`）。
- **PNG**：解析 chunk → `zlib.decompress(合并 IDAT)` → 按 PNG 规范还原每行 filter(0–4)
  → RGB 入 PDF（`/FlateDecode`）。调色板 tRNS / 灰度-RGB key 透明度一并支持。
- **取图**：复用 Runtime SDK `CapAsset.materialize_file(ref)` 把每个 Image Asset 物化为本地路径。
- **回传产物**：PDF 字节写临时文件 → Brain `/api/v1/assets/upload`
  （`manager.upload_file`）以 `mime=application/pdf`、`type=document`、
  `producer/file.convert`、携带 `intent_id`/`edge_id` 上传 → Brain 落库并授予当前
  intent 读取权（现成通道，无需改 Brain 上传逻辑）。

## 输入 schema

| 字段 | 必填 | 说明 |
|---|---|---|
| `to_format` | 是 | 一期仅接受 `pdf`，否则明确中文失败 |
| `from_format` | 否 | 缺省按 `asset_refs` 类型推断为 `image`；显式传非 `image` 则失败 |
| `asset_refs` | 是 | 非空 AssetRef JSON 数组，type 必须为 `image`（JPEG/PNG）；顺序 = PDF 页码顺序 |
| `name` | 否 | 生成 PDF 的展示名（不传则用 `convert-<时间戳>.pdf`） |

## 输出 schema

| 字段 | 说明 |
|---|---|
| `asset_ref` | 新登记 document AssetRef（type=document） |
| `page_count` | number，PDF 页数（= 图片数） |
| `status_text` | 中文一句话（含页数与 asset_id） |

## 入口

- Mac：`mac/src/mac_edge/plugins/file_convert.py`；`services.py` 广告
  `local.file.convert`（laptop 角色恒广告——纯标准库无额外可用性依赖）
- 协议登记：`server/edge_services.py` 的 `KNOWN_CAPABILITIES["file.convert"]`
