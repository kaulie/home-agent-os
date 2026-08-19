# Service: gopro.camera

GoPro 相机服务插件（`gopro-camera`），group=`camera`。

## 标识

| 字段 | 值 |
|------|-----|
| plugin id | `gopro-camera` |
| service_id | `gopro.camera` |
| group | `camera` |
| wire capabilities | `camera.capture`（Mac / iOS）；iOS 另有 `take_video` |

## 做什么

通过 GoPro gpControl HTTP API 完成拍照流水线。对外产出 `capture_ref`（AssetRef）；blob 上传后由 Runtime register，禁止对外 `photo_url`。

## 规划自描述

心跳 `description`：能拍一张并产出 `capture_ref`；不能分析照片、投电视、TTS、无图硬答已经看了；不能产出 `photo_url`。

### iPhone

家庭拍照不在 iPhone 上跑。iOS App 只做意图入口（`POST /api/v1/intent`）；`gopro.camera` 由 Mac home-server 执行。

插件包里仍保留 `plugins/gopro-camera/ios/` 源码，但 **不再编入** LivingRoomEdge。

### Mac Edge（无感切网）

Mac 无蜂窝 Multipath，流水线必须切网：

1. 记录家里 SSID  
2. CoreWLAN 加入 GoPro AP（`MAC_EDGE_GOPRO_SSID` / `PASSWORD`；不用 `networksetup`，避免 LaunchAgent 弹管理员框）  
3. 快门 → `gpMediaList` → `:8080` 下载到 `mac/data/gopro/`  
4. 切回家里 Wi‑Fi（连上即跳过 settle；短 hold 防首选网络回跳 GoPro）→ `POST /api/v1/photos/upload` → Runtime register → `capture_ref`

`camera.capture` 可选入参 `upload_dest`（开关）：

- **默认 `lan`**：传到家里 `192.168.3.65:8080`。**投屏/电视/display.photo 必须 lan，禁止 cloud**
- `cloud`：传到 `http://115.190.153.53:9527/api/v1/photos/upload`，下载 `http://115.190.153.53:8080/{saved_as}`。仅用户明确要求公网时才填
- 未传时读环境变量 `MAC_EDGE_PHOTO_UPLOAD_DEST`（默认 `lan`）。别名：`local` / `home` → `lan`。

实现：[`mac/src/mac_edge/plugins/gopro_camera.py`](../../mac/src/mac_edge/plugins/gopro_camera.py) + [`wifi_switch.py`](../../mac/src/mac_edge/plugins/wifi_switch.py)。

## Wire capabilities

| capability_id | 说明 | output_schema |
|---------------|------|---------------|
| `camera.capture` | 拍照并上传；默认 lan（`192.168.3.65:8080`）；仅明确要求公网时 `cloud` | `capture_ref`（必填 AssetRef） |
| `take_video` | 开始录像（仅 iOS 本地，不上报 Brain） | — |

成功时 Skill / intent status 带结构化 `outputs`，例如：

```json
{
  "capture_ref": {
    "asset_id": "asset_01J...",
    "type": "image",
    "mime_type": "image/jpeg"
  }
}
```

Plugin 内部仍把上传结果交给 Runtime register；步间与 Brain 只见 `capture_ref`，禁止 `photo_url`。

失败时步骤 `msg` 必须是可读中文（扫描不到热点 / 切回家失败 / 相机无响应 / 上传失败等），括号内保留技术原文。空 `msg` 不算完成。

## 本地 debug actions（不上报，iOS）

Skill 仍可 `execute`：`status` / `stop_recording` / `latest_photo` / `upload_photo` / `download_latest_from_server`。

相机端点由 [`ios/GoProDriver.swift`](ios/GoProDriver.swift) 内常量决定。业务上传/下载由共用 [`plugins/runtime-agent-sdk`](../runtime-agent-sdk/) 的 `AssetManager` 完成。

## 与 Edge / Brain 的关系

- **Capability 插件 → Edge**：iOS 经 `GoProPluginEntry`；Mac 经 `services.py` 广告 + `executor` 派发 `camera.capture`。
- **Edge → Brain**：谁心跳广告了 `gopro.camera` / `camera.capture`，调度就派给谁。iPhone 默认 `advertiseGoProCameraToBrain = false`（插件与本地「拍照」仍可用）；家里拍照由已广告该能力的 Mac home-server 承接。

## 入口

见同目录 [`manifest.yaml`](manifest.yaml)：

- Python 参考驱动：`driver.py`
- Mac 流水线：`mac/src/mac_edge/plugins/gopro_camera.py`
- iOS Entry：`ios/GoProPluginEntry.swift`
- HTTP 计时：插件内 `GoProHTTP`
