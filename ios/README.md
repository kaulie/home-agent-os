# iOS Living Room Edge（iPhone）

独立的 **iPhone Edge Agent Demo**（SwiftUI），与 Android `app-v2`（Chromecast Edge）共用同一套 Brain / Plan / Skill 契约字段，本期两边各自进程内 **MockBrain**，便于以后换成同一云端大脑。

## 双 Edge 对照

| | Chromecast Edge | iPhone Edge |
|---|---|---|
| 工程 | `android/app-v2` | `ios/LivingRoomEdge` |
| edgeId | `living-room-chromecast` | `living-room-iphone` |
| 首期 Skill | NetEase、Marshall | GoPro + Chromecast Cast Sender |
| capability | `music.play` 等 | `camera.capture` / `take_video` / `display.photo`（Cast Sender） |
| service | `netease.music` (group=music) | `gopro.camera` + `chromecast.display` |
| Brain | `MockBrainClient`（进程内） | 同左 |

两 Edge **各自注册、各自拉 Plan / Commands**；互不依赖。本期不在 Chromecast 上跑 GoPro，也不在 iPhone 上接网易云。

心跳 / 注册只上报 `services[]`（Service → Capability + schemas）。

## Intent 管线（Edge 拉取）

```text
GET /api/v1/devices/living-room/intents?intent_status=intent_parsed
        │
        ▼
 CommandHandler
   ├─ decompose execution_plan → Task[]
   ├─ Scheduler：Instant（立刻）/ Cron骨架 / Event骨架
   ├─ Dispatcher → LocalEdgeRuntime
   └─ Skill / Plugin（如 gopro.camera ← camera.capture）
```

- 默认拉取：`http://115.190.153.53:9527/api/v1/devices/living-room/intents?intent_status=intent_parsed`
- 响应示例：

```json
{
  "intents": [
    {
      "id": 1,
      "status": "intent_parsed",
      "execution_plan": [{ "capability": "camera.capture", "step": 1 }]
    }
  ]
}
```

- `?intent_status=` 按状态过滤；`?peek=1` 只看不消费
- `EdgeAgent.tick`：heartbeat → 拉 intents → Handler；本地 Mock Plan 也走同一管线
- UI「执行指令」经 `CommandController` → `CommandHandler`
- 服务端 stub：`server/device_commands_flask.py`

源码目录：`LivingRoomEdge/Command/`（`generate_xcodeproj.py` 会扫入）。

## GoPro 分层

```text
Skill / 调试 UI  →  GoProPluginEntry.invoke  →  GoProSkill / GoProController  →  GoProDriver
                                              ↘  RuntimeAgentSDK.assets（业务服务器）
```

- **GoProPluginEntry**：插件对外唯一入口（manifest `entry.ios`）；Edge UI / Command 分发只依赖 Entry
- **CapabilityDriver**：通用 `identity` / `connect` / `disconnect` / `status` / `capabilities`
- **GoProDriver**：相机 gpControl；HTTP 计时用插件内 `GoProHTTP`（不引用 App `TimedHTTP`）
- **Controller**：编排 Driver；上传/下载走 RuntimeAgentSDK（`RuntimeHTTP`）
- 调试 UI 对 URL **只读展示**；动作经 Entry，不直调 Controller/Driver

## 插件目录约定（`plugins/`）

仓库根目录 `plugins/` 与 `ios/`、`server/` 平级。共用 SDK + 各能力插件：

```text
plugins/runtime-agent-sdk/   # RuntimeAgentSDK（AssetManager 等）
plugins/gopro-camera/
  capability.md
  manifest.yaml
  driver.py
  ios/                # 编入 LivingRoomEdge 的 Swift 源码
    …
```

- **规范与文档**以插件包为准；**iPhone Edge 运行时仍是 Swift**（`driver.py` 不替代 App）。
- App 侧仍 `installCapabilities([CameraCaptureCapabilityPlugin(...)])`，类型名不变。
- `generate_xcodeproj.py` 会扫描 `plugins/gopro-camera/ios/*.swift` 与 `plugins/runtime-agent-sdk/ios/**/*.swift`。

上传示例：

```swift
await model.goproPlugin.invoke(action: "upload_photo", params: ["local_path": path])
// 或
await model.performGoPro(action: "status")
```

单独验证 Python 驱动（需已连相机网；无相机时 CLI 报错退出即可）：

```bash
python3 plugins/gopro-camera/driver.py status
```

## 打开工程

```bash
open ios/LivingRoomEdge/LivingRoomEdge.xcodeproj
```

- Bundle ID：`com.gaolei.livingroom.edge.iphone`（Personal Team 需唯一）
- 最低系统：iOS 16

若改了 Swift 文件列表，重新生成工程：

```bash
python3 ios/LivingRoomEdge/generate_xcodeproj.py
```

真机需在 Signing & Capabilities 登录 Apple ID 并选 Team。

**相机 Wi‑Fi**：免费 Personal Team 的 `+ Capability` 里**搜不到 Hotspot Configuration**（需付费 Apple Developer Program）。请用「设置 → Wi‑Fi」手动加入 GoPro 热点后再操作 App。自动加网按钮在无该能力时会失败，属预期。

## 调试闭环

1. 启动 App → **启动 Agent**
2. GoPro「拍照」→ `camera.capture`：快门 → 下最新图 → 上传 → **Cast `photo_url` 到 Chromecast**（需与电视同 Wi‑Fi）
3. Skill 另含 `display.photo`（单独投屏）、`start_recording` / `stop_recording` / `latest_photo` / `upload_photo` / `download_latest_from_server`

## 发出指令（文本 / 语音）

调试页「用户意图」区域：

1. **文本**：输入后点「发出指令」
2. **语音**：点「开始录音」→ 本机 `Speech` 转写为中文 → 点「发出指令」

均 `POST` JSON 到：

`http://115.190.153.53:9527/api/v1/intent`

```json
{ "text": "帮我拍张照", "source": "text|voice", "edge_id": "living-room-iphone" }
```

成功时服务端返回（生产契约）：

```json
{
  "ok": true,
  "intent_id": 1,
  "intent_status": "intent_received",
  "text": "拍张照照片",
  "source": "voice",
  "edge_id": "edge-node-…",
  "reply": "已收到指令（voice）：…"
}
```

App 以**物流式时间线**展示进度；约每 **1.5s** 轮询 `GET /api/v1/intent_detail?intent_id=`（终态或约 **60s** 超时停止）。空文本本地拦截，不建 job。

**时间线只信后端**：UI 仅通过 `intent_detail`（及发出指令 POST 的首包）更新；Edge 推进阶段时必须 `POST .../status`，成功后再拉 detail 刷新，**不做本地假推进**。上报失败只打日志，不假装进入下一阶段。

| intent_status | 时间线步骤 |
|---------------|------------|
| `intent_received` | 1 已上传待解析 |
| `intent_parsed` | 2 解析完成待下发中控 |
| `hub_received` | 3 中控已收到待调度 |
| `scheduled` | 4 已调度 |
| `assigned` | 5 已分配 edge node |
| `running` | 6 执行中 |
| `succeeded` / `failed` | 7 终态 |

详情响应示例：

```json
{
  "id": 1,
  "status": "intent_parsed",
  "execution_plan": [{ "capability": "camera.capture", "step": 1 }]
}
```

服务端 stub：`server/intent_dispatch_flask.py`（创建后停在 `intent_parsed`；后续靠 Edge 上报）

| 方法 | 路径 |
|------|------|
| `POST` | `/api/v1/intent` |
| `GET` | `/api/v1/intent_detail?intent_id=<id>` |
| `GET` | `/api/v1/intent/<intent_id>`（兼容） |
| `POST` | `/api/v1/intent/<intent_id>/status` |

Edge 在 CommandHandler / LocalEdgeRuntime 看到 `params.intent_id` 时依次上报：  
`hub_received` → `scheduled` → `assigned` → `running` → `succeeded`/`failed`（每次成功后拉 `intent_detail`；失败只打日志，不阻断执行）。

需麦克风 + 语音识别权限（`Info.plist` 已声明）；语音请用**真机**。
## 上传 / 从服务器下载（业务服务器）

| 能力 | 方法 | 路径 | 说明 |
|---|---|---|---|
| 上传 | `POST` multipart 字段 **`file`** | `/api/v1/photos/upload` | 保存到服务器目录 |
| 下载最新 | `GET` 返回图片二进制 | `/api/v1/photos/download_latest` | 按目录 mtime 取最新一张 |

```bash
# Flask 示例（含 upload + download_latest）
python3 server/photo_upload_flask.py
```

App 调试 UI **展示用**常量（与 SDK 实际请求地址独立）：

- 上传：`http://115.190.153.53:9527/api/v1/photos/upload`
- 下载：`http://115.190.153.53:9527/api/v1/photos/download_latest`

插件实际请求经 `RuntimeAgentSDK` → `AssetHTTPTransport`（见 `plugins/runtime-agent-sdk/`）。

iOS ATS：明文 `http://` 需在 `Info.plist` 的 `NSAppTransportSecurity` 放行（已为上传 IP / GoPro `10.5.5.9` 配置）。改完后请 **删掉手机上旧 App → Clean Build → 重装**。

注意：手机连 GoPro Wi‑Fi 时通常上不了公网；上传/从服务器下载前需切回可访问上传服务器的网络。

1. GoPro 开启相机 AP；**iPhone 手动加入该 Wi‑Fi**（或调用 Controller/`joinCameraWiFi`）
2. 默认 URL：
   - 状态：`http://10.5.5.9/gp/gpControl/status`
   - 拍照：`http://10.5.5.9/gp/gpControl/command/shutter?p=1`
   - 媒体列表：`http://10.5.5.9/gp/gpMediaList`
   - 文件下载：`http://10.5.5.9:8080/videos/DCIM/...`（控制口 :80，媒体口 **:8080**；超时 120s）
3. 单次「接口返回」与各自「事件」区分开；轮询只写事件区

## 目录

```text
plugins/gopro-camera/   # GoPro 能力插件（见上文）
ios/LivingRoomEdge/
  LivingRoomEdge/
    App/              SwiftUI 入口与调试面板
    Edge/             EdgeAgent, SkillRegistry, PlanExecutor
    Brain/            BrainClient, MockBrainClient, DTOs
    Controller/       DeviceController + Intent/Command
    Driver/           CapabilityDriver（GoPro 已迁入插件包）
    Skill/            Intent / Command（GoPro 已迁入插件包）
    Capability/       非相机 Capability 插件
    Info.plist
```

## 明确不做（本期）

- 真云端大脑 / 语音意图
- 完整 BLE Open GoPro 配对
- Kotlin Multiplatform 公共库
