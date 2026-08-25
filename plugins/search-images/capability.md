# Service: local.search

文搜图插件（`search-images`），group=`search`。  
按关键词检索互联网**存量实拍图**（必应 / Openverse），下载后经 Runtime Asset Manager 登记为 `asset_refs`。

**不是 AI 文生图。** 「画一张 / 生成一张 / 来张图」仍走 `query.content`。本能力与问答插件 **禁止互相 import**。

**Brain 不执行、不持有 Bing 密钥**；只通过心跳看到 `search.images`，再把 plan 派到具备该能力的 Mac Edge。

## 规划自描述

| 字段 | 值 |
|------|-----|
| role | 互联网实拍图检索器 |
| planner_recognize | 按关键词检索互联网存量实拍图片（必应/Openverse），不是 AI 生成，也不是家里已拍相册 |
| typical_triggers | `搜一张猫的照片`、`找网上的实拍图`、`搜索故宫的照片`、`给我找几张风景图` |
| do_not_dispatch | AI文生图、画一张、生成图片、知识问答、拍照、看本地相册、投屏本身 |

用户只要看图：本步产出 `asset_refs`，Brain 组装 `presentation`（image）。  
用户要投电视：下一步另排 `display.slideshow` / `display.photo`。本步不 Cast / TTS。

## 搜图源（provider）

`ImageSearchProvider`：只返回命中（content URL / 缩略图 / 来源页 / 标题 / 许可），**不**下载、不上传、不登记 Asset。

| 名称 | 说明 | 配置 |
|------|------|------|
| `openverse` | Openverse `GET /v1/images/`，CC / 开放许可；匿名可用 | 无需密钥；可选 `MAC_EDGE_OPENVERSE_ACCESS_TOKEN` |
| `bing` | Azure Bing Image Search v7 | `MAC_EDGE_BING_SEARCH_KEY`（F1 每月 1000 次） |

选择顺序：**本步 `provider` 入参** → `MAC_EDGE_IMAGE_SEARCH_PROVIDER` → 有 Bing 密钥则 `bing` → 否则 `openverse`。  
至少有一个源可用时才广告本能力（Openverse 默认可用）。

## 标识

| 字段 | 值 |
|------|-----|
| plugin id | `search-images` |
| service_id | `local.search` |
| group | `search` |
| wire capability | `search.images` |
| 执行方 | Mac Edge（`mac_edge.plugins.search_images`） |

## 契约

| 方向 | 内容 |
|------|------|
| **输入** | `query`（必填）；`count`（1–8，默认 4）；`size` / `freshness`（Bing 可选）；`provider`（可选 bing\|openverse）；`upload_dest`（默认 lan） |
| **输出** | `asset_refs`（必填 AssetRef 数组）；`query_used`；`hit_count`；`provider`；`sources`（含 Openverse license） |

缺 `query` 则失败。禁止从前序 step 补。对外禁止 `photo_url`。  
同一关键词短时缓存命中列表（省 Bing 额度）；仍会重新下载并登记新 Asset。

## 入口

- Mac：`search_images.py` + `image_search_providers/` + `services.py` 广告 `local.search`
- 协议登记：`KNOWN_CAPABILITIES["search.images"]`（仅索引）
- 密钥只放 `mac/.env`，不要入库
