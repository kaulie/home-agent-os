# Service: chromecast.display

Chromecast 投屏插件（`chromecast-display`），group=`display`。

**当前主路径：iPhone Cast Sender**（Google Cast SDK → Default Media Receiver）。  
Android 目录下仍保留本机全屏 ImageView 实现，但 **app-v2 默认不安装**。

## 标识

| 字段 | 值 |
|------|-----|
| plugin id | `chromecast-display` |
| service_id | `chromecast.display` |
| group | `display` |
| wire capabilities | `display.photo`、`display.slideshow` |
| 广告 Edge | **Mac Edge**（本机 Cast HTTP `:9095`）；iPhone 暂不广告 Cast |

## 做什么

给定本步 **image_ref**（AssetRef）。Runtime 在 execute 前 resolve 成本步临时 LAN URL，电视端拉取该 URL；插件不收 `photo_url` / path / 永久 URL。公网 `115.190.153.53:8080` 的大图又慢又容易「图片加载失败」。

## 规划自描述

心跳 `description`：`display.photo` 能投本步已有的 `image_ref` 到电视（仅用户明确要投屏）；不能拍照、不能自己捡图、不能收 `photo_url`。`display.slideshow` 能轮播必填 `image_refs`；不能从前序自己拼列表。

Mac 主路径：`GET http://127.0.0.1:9095/endpoint/display?url=…`。轮播在 Mac plugin 内按 `interval_sec` 循环该接口，不把重复投屏拆成多个 plan step。

## Wire capabilities

| capability_id | 说明 | input_schema |
|---------------|------|--------------|
| `display.photo` | 投一张 | `image_ref`（AssetRef JSON, required） |
| `display.slideshow` | 轮播一轮 | `image_refs`（AssetRef JSON 数组，**必填**）；`interval_sec`（默认 5）；`order`：`array_asc`（默认）/ `array_desc` / `alphabet_asc` / `alphabet_desc` / `random` |

`display.slideshow` 不读前序 capture。不传 `image_refs` 则失败。

## 网络前提

- iPhone 与 Chromecast 须在 **同一局域网**（勿停在 GoPro 相机热点）
- Chromecast 须能访问 Runtime 为本步 resolve 出的临时 LAN URL（家里 `192.168.3.65:8080`，不要用公网 8080）

## 入口

- iOS：[`ios/ChromecastPluginEntry.swift`](ios/ChromecastPluginEntry.swift)、[`CastSessionController.swift`](ios/CastSessionController.swift)
- Android（未默认安装）：[`android/ChromecastDisplaySkill.kt`](android/ChromecastDisplaySkill.kt)
