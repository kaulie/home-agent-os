# Service: system.ocr

图片 OCR（`image-ocr`），group=`ocr`，`kind=system`。  
把一张 **Image Asset** 上的视觉文字转成结构化 OCR 结果（全文 + bbox + 置信度）。

**Brain 就地执行**，不绑任何 Runtime、不进 Mac Edge、不放 LAN。  
云上独立 HTTP 服务：`/root/chat-gateway/ocr-service/`（本仓库 `ocr-service/`）。

**不是** 看图理解、问答、总结、识字教学。那些仍走 `vision.ask` / `query.content`。  
Planner 只看见 `image.ocr`，看不见 PaddleOCR。

## 两层

1. **OCR 服务**（独立）：只收图片字节，返回 `{text, blocks, engine, model, model_version, language}`。不知道 `asset_id` / Brain / Runtime。默认引擎 PP-OCRv5_server。
2. **Brain 薄包装**（`server/sdk/image_ocr.py`）：入参 `asset_ref` → 从 Asset 目录取图字节 → `POST {OCR_SERVICE_URL}/v1/ocr` → 产出 OCRResult。

## 规划自描述

| 字段 | 值 |
|------|-----|
| kind | system |
| role | 图片文字识别器 |
| planner_recognize | 把图片上的文字转成带坐标的结构化 OCR 结果（原样读字，不做语义理解） |
| typical_triggers | `图上写了什么`、`识别照片里的字`、`OCR`、`把小票上的字读出来` |
| do_not_dispatch | 看图理解、看图问答、文档总结、识字教学、拍照本身、搜图、文生图 |

## 标识

| 字段 | 值 |
|------|-----|
| plugin id | `image-ocr` |
| service_id | `system.ocr` |
| group | `ocr` |
| wire capability | `image.ocr` |
| kind | `system` |
| 执行方 | Brain（`system_capabilities.ocr_from_params` → `sdk.image_ocr`） |

## 契约

| 方向 | 内容 |
|------|------|
| **输入** | `asset_ref`（必填 AssetRef / asset_id）。禁止 `image_url` / path / base64。可选 `language`、`return_bbox`、`return_confidence` |
| **输出** | `text`（必填）；`blocks`（JSON 数组字符串）；`language`；`engine`；`model`；`model_version`；`asset_id` |

缺 `asset_ref` 则失败。禁止从前序 step 自己去捡图。  
Presentation：`type=text`，`from=text`。

## 入口

- 服务：`ocr-service/` → 云 `docker compose up -d`（`127.0.0.1:9188`）
- Brain：`OCR_SERVICE_URL=http://127.0.0.1:9188`（只写云 `.env`）
- 协议：`KNOWN_CAPABILITIES["image.ocr"]`
