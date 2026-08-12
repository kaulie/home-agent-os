# Service: gopro.camera

GoPro 相机服务插件（`gopro-camera`），group=`camera`。

## 标识

| 字段 | 值 |
|------|-----|
| plugin id | `gopro-camera` |
| service_id | `gopro.camera` |
| group | `camera` |
| wire capabilities | `camera.capture`, `take_video` |

## 做什么

在客厅 Edge（iPhone）上通过 GoPro gpControl HTTP API 完成：

- 状态查询（本地 debug，不上报为 capability）
- **完整拍照流水线**（wire: `camera.capture`）：快门 → 下载最新图 → 上传服务器 → 返回 `photo_url`
- 开始录像（wire: `take_video`）；停止录像仍可本地 invoke
- 单独的拉取 / 上传 / 从服务器下载（本地 debug）

## Wire capabilities

| capability_id | 说明 | output_schema |
|---------------|------|---------------|
| `camera.capture` | 拍照并上传；返回服务器下载地址 | `photo_url`（必填）、`photo_local_path`、`saved_as` |
| `take_video` | 开始录像 | — |

成功时 Skill / intent status 带结构化 `outputs`，例如：

```json
{
  "photo_local_path": "/…/GoProMedia/….jpg",
  "photo_url": "http://115.190.153.53:8080/<saved_as>",
  "saved_as": "a1b2c3d4_GOPR1234.JPG"
}
```

公开访问规则：上传返回的 `saved_as` → `http://115.190.153.53:8080/{saved_as}`（静态文件服务，供 Cast 拉取）。
## 本地 debug actions（不上报）

Skill 仍可 `execute`：`status` / `stop_recording` / `latest_photo` / `upload_photo` / `download_latest_from_server`。

相机端点由 [`ios/GoProDriver.swift`](ios/GoProDriver.swift) 内常量决定。业务上传/下载由共用 [`plugins/runtime-agent-sdk`](../runtime-agent-sdk/) 的 `AssetManager` 完成。

## 与 Edge / Brain 的关系

- **Capability 插件 → Edge**：本目录由 Edge 本地注册（iOS：经 `GoProPluginEntry.makeCapabilityPlugin()` → `CameraCaptureCapabilityPlugin`）。
- **Edge UI → 插件**：调试区固定 GoPro 面板，动作一律 `GoProPluginEntry.invoke` / `AppModel.performGoPro`。
- **Edge → Brain**：心跳 `/api/v1/edge-heartbeat` 上报 `services[]` 中的 `gopro.camera`（含 `camera.capture` / `take_video`）；**不是**用本插件去注册 Edge 节点。

## 入口

见同目录 [`manifest.yaml`](manifest.yaml)：

- Python 参考驱动：`driver.py`
- iOS Entry：`ios/GoProPluginEntry.swift`
- HTTP 计时：插件内 `GoProHTTP`
