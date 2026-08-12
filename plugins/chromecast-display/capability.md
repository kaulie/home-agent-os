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
| wire capabilities | `display.photo` |
| 广告 Edge | **iPhone** LivingRoomEdge |

## 做什么

给定可通过 HTTP(S) 访问的 `photo_url`，由 **iPhone 作为 Cast Sender** 投到局域网 Chromecast；电视端用系统 Default Media Receiver 拉取并展示图片。

`camera.capture` 流水线在上传成功拿到 `photo_url` 后会 **自动 Cast**。

## Wire capabilities

| capability_id | 说明 | input_schema |
|---------------|------|--------------|
| `display.photo` | Cast 投屏 | `photo_url`（string, required） |

## 网络前提

- iPhone 与 Chromecast 须在 **同一局域网**（勿停在 GoPro 相机热点）
- Chromecast 须能访问 `photo_url`（公网/同网服务器）

## 入口

- iOS：[`ios/ChromecastPluginEntry.swift`](ios/ChromecastPluginEntry.swift)、[`CastSessionController.swift`](ios/CastSessionController.swift)
- Android（未默认安装）：[`android/ChromecastDisplaySkill.kt`](android/ChromecastDisplaySkill.kt)
