# HomeAgent Console（Android）

与 iPhone [HomeAgent Console](../../ios/README.md) 对齐的手机发出窗口：**Intent Source + Endpoint + 本机 Runtime**。

五栏壳 + 对话发意图；**扫描 / 拍照 / 文件 / 录音**走本机 inbox 上传 Asset；**phone.call** 按本机家庭目录给特定人拨号；**camera.capture** 默认走本机 CameraX（`android.camera`），GoPro（`gopro.camera`）仍保留作 fallback。直播本期不做。不广告、不执行 `light.set`。

## 构建

```bash
cd android
./gradlew :living-room-android:assembleDebug
adb install -r living-room-android/build/outputs/apk/debug/living-room-android-debug.apk
```

- 主屏幕名称：`HomeAgent Console`
- applicationId：`com.smarthome.livingroom_android`
- 最低系统：Android 8.0（API 26）
- 扫描依赖 Google Play 服务（ML Kit Document Scanner）

## 做什么

```text
启动 / 改 Brain URL
        │
    POST /api/v1/edge-register
      roles: intent_source + runtime + endpoint
      services: document.scanner → document.scan
                android.phone → phone.call
                android.camera → camera.capture
                gopro.camera → camera.capture
      endpoints: android.display → image, text
        │
    POST /api/v1/edge-heartbeat（立刻，之后每 30s；发意图前必须先成功）
        │
用户（文本 / 语音）
        │
    POST /api/v1/intent
      { text, source, participant_id, client_hint }
        │
    GET  /api/v1/intent_detail?intent_id=   （每 5s，直到 succeeded / failed）
```

- Brain 两个地址槽：LAN 默认 `http://192.168.3.84:9527`，Cloud 默认 `http://115.190.153.53:9527`。节点页和设置里用 **按网络自动 / 锁定局域网 / 锁定云端**；点「更改连接方式」预览后再确认，不会一碰就改。对话顶栏显示当前环境。自动时家庭局域网且 `/api/v1/ping` 通 LAN 则走 LAN，否则走 Cloud。路径变化或回到前台才重新探测；发出意图前再确认一次。
- `client_hint` 本机稳定（`living-room-android-…`）；`participant_id` 来自登记回执。
- 主界面底栏「互动 · 系统 · 能力 · 实体 · 节点」；互动顶部分段「对话 | 扫描 | 拍照 | 文件 | 录音」。
- **Android Camera Runtime**：启动即进拍照页，申请相机权限，屏幕常亮。心跳广告 `android.camera` → `camera.capture`。**相机 / 麦克风默认关闭**，须点取景区中央大按钮分别开启后，远程 `camera.capture` 或语音发意图才可用。开启相机且保持本页前台时，CameraX 直接出 JPEG，写入 inbox `capture_ref`，再走 `asset.upload`（或复合 `camera.capture_and_upload`）。**不打开系统相机 App，不模拟点击快门。**
- **GoPro 拍照**：仍广告 `gopro.camera` → `camera.capture`。本机 CameraX 不可用时 Runtime 才 fallback。与 iPhone 一样 **不切网**，须已连 GoPro 热点。
- **扫描**：顶部「扫描」→ 系统文档扫描仪 → `POST /api/v1/assets/upload`（`upload_intent=document.scan`）。**不经 Planner**，也不进对话列表。Brain 派 `document.scan` 时同样打开扫描仪（Console 须在前台）。
- **本机快门**：拍照页也可手动点快门 → inbox + `upload_intent=android.photo`。与 Runtime `camera.capture` 共用同一套 CameraX，不是系统相机。
- **文件**：顶部「文件」→ 系统文件选择器 → `upload_intent=android.file`。不经 Planner。
- **录音**：顶部「录音」。暂停不上传；「停止并上传」才 `upload_intent=android.audio`。离开录音页且仍在录（未暂停）时会停止并上传。
- **打电话**：设置里维护「可呼叫的人」（姓名 + 号码）。说「给妈妈打电话」由 Brain 派 `phone.call`，本步必填 `name`；plugin 只查这份目录，不读通讯录、不捡前序 step。已授 `CALL_PHONE` 则直接拨，否则打开拨号盘。
- 图结果只认 `presentation.asset_ref`：`GET /api/v1/assets/{id}/content?intent_id=`（聊天默认 `preview`，点大图再 `original`）。
- 下拉刷新：`GET /api/v1/intents?participant_id=&before_id=&limit=`，每次最多 **5** 条本机历史。
- 语音在本机转成中文后再 POST。

## 明确不做（本期）

- MPEG-TS 直播
- `light.set` / 海信 climate
- Wi‑Fi 切网（GoPro 不停在热点上控相机，不把 Mac 的切网搬过来）
- `display.photo` / 投电视（仍由 Mac Cast）
- HomeAgent Admin

现场管理中控是另一个 App（iOS `HomeAgentAdmin`）。不要把开关塞进 Console 底栏。
