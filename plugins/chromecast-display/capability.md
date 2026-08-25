# Service: chromecast.display

Chromecast 投屏插件（`chromecast-display`），group=`display`。

**主路径：iPhone Cast Sender** → 自定义 CAF Receiver **`F7649303`**，namespace **`urn:x-cast:local.image`**。  
**不是** Default Media Receiver；DMR 收不到该 namespace。

协议：[`docs/chromecast-cast-protocol.md`](../../docs/chromecast-cast-protocol.md)。  
Endpoint 契约：[`docs/endpoint-contract.md`](../../docs/endpoint-contract.md)。  
**Receiver HTML 本地管理**：[`receiver/index.html`](receiver/index.html)（你部署到公网；本仓库不替你改 Cast Console）。

Android 目录下仍保留本机全屏 ImageView，**app-v2 默认不安装**。

## 标识

| 字段 | 值 |
|------|-----|
| plugin id | `chromecast-display` |
| service_id | `chromecast.display` |
| group | `display` |
| wire capabilities | `display.photo`、`display.slideshow` |
| Cast App ID | `F7649303` |
| Cast namespace | `urn:x-cast:local.image` |
| 广告 Edge | Mac Edge 可广告 `:9095` 路径；**Presentation Protocol 以 iPhone Cast Sender 为准** |

## 做什么

给定本步 **asset_ref**（AssetRef）。Runtime / Sender resolve 成本步临时 LAN URL，经 Cast 发 **Presentation Command**（V1）；兼容期消息仍带顶层 `url` 供旧 HTML。插件不收永久 URL。公网 `115.190.153.53:8080` 大图不可靠。

`send` 成功 = **accepted**；真正出图以 Receiver 回传 `presentation.started` 为准（见协议）。

## 规划自描述

心跳 `description`：`display.photo` 能投本步已有的 `asset_ref` 到电视（仅用户明确要投屏）；不能拍照、不能自己捡图、不能收 `photo_url`。`display.slideshow` 能轮播必填 `asset_refs`；不能从前序自己拼列表。

## Wire capabilities

| capability_id | 说明 | input_schema |
|---------------|------|--------------|
| `display.photo` | 投一张 | `asset_ref`（AssetRef JSON, required） |
| `display.slideshow` | 轮播一轮 | `asset_refs`（必填）；`interval_sec`（默认 5）；`order`：`array_asc` / `array_desc` / `alphabet_asc` / `alphabet_desc` / `random` |

`display.slideshow` 在 Cast V1 上映射为多次 `present`（同 namespace），不是第二个 Cast 通道。

## Cast 消息（摘要）

Sender → Receiver：`type=command`，`action=present|clear|stop|…`，含 `command_id` / `presentation_id` / `content`。  
Receiver → Sender：`type=event`，`presentation.started|error|cleared`、`receiver.ready` 等。

## 网络前提

- iPhone 与 Chromecast 同一局域网（勿停在 GoPro 热点）
- Chromecast 能访问临时 LAN Asset URL

## 入口

- iOS：[`ios/ChromecastPluginEntry.swift`](ios/ChromecastPluginEntry.swift)、[`CastSessionController.swift`](ios/CastSessionController.swift)
- Android（未默认安装）：[`android/ChromecastDisplaySkill.kt`](android/ChromecastDisplaySkill.kt)
- Mac legacy：`mac_edge` → `GET http://127.0.0.1:9095/endpoint/display?url=…`（URL-only，无 Presentation Protocol）
