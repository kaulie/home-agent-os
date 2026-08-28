# Service: gopro.camera

GoPro 相机服务插件（`gopro-camera`），group=`camera`。

## 标识

| 字段 | 值 |
|------|-----|
| plugin id | `gopro-camera` |
| service_id | `gopro.camera` |
| group | `camera` |
| wire capabilities | `camera.capture`（atomic）、`camera.capture_and_upload`（composite）；iOS 另有 `take_video` |

## 做什么

通过 GoPro gpControl HTTP API 完成拍照流水线。对外产出本机 inbox `capture_ref`（还不是 Asset，没有 `asset_id`）；**不**在本步上传、不 `POST /assets`。禁止对外 `photo_url` / path。

## is_available（Runtime 执行前必调）

所有 capability 默认 `is_available()` → true。`camera.capture` **必须**快探：

| 端 | 探测 |
|----|------|
| Mac | 配置 SSID/密码；已在热点上则短 HTTP status；否则 CoreWLAN 扫描热点是否可见（**不** join、不等 45s） |
| iPhone | 短 GET `http://10.5.5.9/.../status`（需已连相机热点） |

不可用时 Runtime 立即失败并带可读 `msg`，避免长时间切网/快门超时。

## 规划自描述

心跳结构化字段：拍一张现场照片并写入本机 inbox，产出 `capture_ref`，**不上传、不登记 Asset**。  
典型触发：`拍一张`、`看看现在`、`看看客厅电视画面`、`拍一下电视屏幕`、`拍照`。  
不能：上传 / 传到图床 / 传到云上、看图理解、投屏、无拍照直接回答画面内容。要把图给用户看或上图床时，**优先**排 `camera.capture_and_upload`（同一 Runtime 内拆成 capture→upload）。独立 `asset.upload` 只用于已有 `capture_ref` / `asset_ref`。禁止把 path 写进 plan。

### iPhone / Android Console

家庭拍照也可以在手机 Console 上跑：预装 `gopro.camera` / `camera.capture`。

**iPhone 与 Mac 实现必须分开：**

| | iPhone / Android Console | Mac home-server |
|--|--|--|
| 源码 | iOS `ios/LivingRoomEdge/LivingRoomEdge/GoPro/`；Android `android/living-room-android/.../gopro/` | `mac/.../gopro_camera.py` + `wifi_switch.py` |
| Wi‑Fi | **不切网**。停在 GoPro AP 上控相机；上传若需达 Brain 可走蜂窝 | 必须切网：家 → GoPro → **切回家** 再写 inbox |
| 上传 | atomic `camera.capture` 不上传。给人看图用 composite `camera.capture_and_upload`（本机拆成 capture→upload，蜂窝）。独立 `asset.upload` 仍可单独调度 | 给人看图用 composite（切网后本机 upload 走家里 LAN）。独立 `asset.upload` 仍可单独调度 |

不要把 Mac 的 `wifi_switch` / restore home 搬进 iPhone 或 Android Console。

### Mac Edge（无感切网）

Mac 无蜂窝 Multipath，流水线必须切网：

1. 记录家里 SSID  
2. CoreWLAN 加入 GoPro AP（`MAC_EDGE_GOPRO_SSID` / `PASSWORD`；不用 `networksetup`，避免 LaunchAgent 弹管理员框）  
3. 快门 → `gpMediaList` → `:8080` 下载到 Runtime inbox `mac/data/captures/inbox/{capture_id}.jpg`  
4. 切回家里 Wi‑Fi（连上即跳过 settle；短 hold 防首选网络回跳 GoPro）→ 产出 `capture_ref`。**不**登记 Brain Asset，**不**在本步上传图床。

实现：[`mac/src/mac_edge/plugins/gopro_camera.py`](../../mac/src/mac_edge/plugins/gopro_camera.py) + [`wifi_switch.py`](../../mac/src/mac_edge/plugins/wifi_switch.py)。

## Wire capabilities

| capability_id | 说明 | output_schema |
|---------------|------|---------------|
| `camera.capture` | atomic。拍照并写入本机 inbox；**不上传、不登记 Asset** | `capture_ref`（必填 CaptureRef） |
| `camera.capture_and_upload` | composite。`composition=composite`，`decomposes_to=["camera.capture","asset.upload"]`。Brain 调度一步；Runtime 同机执行两个 atomic，产出 Asset | `asset_ref`（必填） |
| `take_video` | 开始录像（仅 iOS 本地，不上报 Brain） | — |

`camera.capture_and_upload` 声明 `prefer_when`：拍照后还有后续动作要消费这张照片（给人看、变成 Asset、vision、投屏）时优先本能力，不要再拆成跨边的 capture+upload。心跳 **同时** 上报这三条（以及 `asset.upload` 在 `local.asset` 上）。`available` = 两个 atomic 的 AND。Plugin 不实现第三套快门/上传。

成功时 Skill / intent status 带结构化 `outputs`，例如：

```json
{
  "capture_ref": {
    "capture_id": "cap_01ab...",
    "type": "image",
    "mime_type": "image/jpeg"
  }
}
```

Plugin 只写本机 inbox；步间只见 `capture_ref`。上传由 `asset.upload` 用本步 `$capture_ref` 完成，成功后才 `POST /assets` 得到 `asset_id`。禁止 plugin 自己去捡 `step_outputs` 或扫描 inbox。

失败时步骤 `msg` 必须是可读中文（扫描不到热点 / 切回家失败 / 相机无响应 / 上传失败等），括号内保留技术原文。空 `msg` 不算完成。

## 本地 debug actions（不上报，iOS）

Skill 仍可 `execute`：`status` / `stop_recording` / `latest_photo` / `upload_photo` / `download_latest_from_server`。

相机端点由 [`ios/GoProDriver.swift`](ios/GoProDriver.swift) 内常量决定。业务上传/下载由共用 [`plugins/runtime-agent-sdk`](../runtime-agent-sdk/) 的 `AssetManager` 完成。

## 与 Edge / Brain 的关系

- **Capability 插件 → Edge**：iOS 经 `GoProPluginEntry`；Mac 经 `services.py` 广告 + `executor` 派发 `camera.capture`。
- **Edge → Brain**：谁心跳广告了 `gopro.camera` / `camera.capture`，调度就派给谁。iPhone 预装并默认打开 runtime，会广告该能力。

## 入口

见同目录 [`manifest.yaml`](manifest.yaml)：

- Python 参考驱动：`driver.py`
- Mac 流水线：`mac/src/mac_edge/plugins/gopro_camera.py`
- iOS Entry：`ios/GoProPluginEntry.swift`
- HTTP 计时：插件内 `GoProHTTP`
