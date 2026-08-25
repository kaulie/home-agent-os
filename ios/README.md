# iPhone 意图窗口

iPhone App 是 **Intent Source + Endpoint**，并预装 **Runtime：GoPro `camera.capture` + 客厅灯 `light.set`**。多轮聊天发出意图；打开 runtime 时心跳广告这两项并拉取执行。

## 做什么

```text
启动 / 改 Brain URL
        │
        ▼
 POST /api/v1/edge-register
   roles: intent_source + runtime + endpoint
   endpoints: iphone.display → image, text
   services: gopro.camera / camera.capture；livingroom.ceiling_light / light.set
        │
 POST /api/v1/edge-heartbeat（立刻，之后每 30s；发意图前必须先成功；Brain ONLINE_TTL≈2×）
   edge_id=participant_id, client_time_ms, services 同上
        │
用户（文本 / 语音）
        │
        ▼
 POST /api/v1/intent
   { text, source, participant_id, client_hint }
        │
        ▼
 GET  /api/v1/intent_detail?intent_id=   （每 5s，直到 succeeded / failed）
```

- Brain 两个地址槽：LAN 默认 `http://192.168.3.73:9527`，Cloud 默认 `http://115.190.153.53:9527`。节点页和设置里用 **自动 / 局域网 / 云** 切换；自动时家庭局域网且 `/api/v1/ping` 通 LAN 则走 LAN，否则走 Cloud。强制局域网或云会锁定对应槽，不跟探测走。当前在用地址在「节点」页看。
- 预装 Runtime：`gopro.camera` / `camera.capture`（iPhone **不切网、不填热点 SSID**，直接打相机 HTTP；Mac 切网实现不要混用）；`livingroom.ceiling_light` / `light.set`（本机 TTS：小书小书 → 等 2 秒 → 开灯/关灯）
- `client_hint` 本机稳定（`living-room-iphone-…`）；`participant_id` 来自登记回执
- 登记后立刻心跳，之后约 45 秒一次；发出前心跳失败则不出单
- 主界面底栏「互动」；顶部分段「对话 | 扫描 | 拍照 | 文件 | 录音 | 直播」。对话是聊天窗；扫描页打开系统文档扫描仪（VisionKit）；拍照页后置实时预览，点快门即拍——成片立刻写入本地列表（本机留存 `Documents/local-photos/`），上传在后台自动进行、不阻塞下一次拍摄；上传失败只标记该照片的上传状态（列表行内可重试），不会报成「拍照失败」。文件页从系统文件选择器上传。录音页可暂停（暂停不上传），点停止后 POST `/api/v1/assets/upload`（`upload_intent=iphone.audio`），最近列表可改名、播放本机缓存。直播页全屏取景，Start Stream 把 H.264 MPEG-TS 推到 Mac ingest（不经 Planner）。扫描/拍照/文件/录音完成后 POST `/api/v1/assets/upload`。物流时间线挂在用户气泡下的「进度」浮窗里
- 图结果只认 `presentation.asset_ref`：Endpoint **只**走 `GET /api/v1/assets/{id}/content?intent_id=`（聊天默认 `representation=preview` 缩略图，点大图再拉 `original`）。`camera.capture` **先**登记 preview、标 succeeded，原图蜂窝后台补传后再 PATCH 同一 `asset_id`。
- 下拉刷新：`GET /api/v1/intents?participant_id=&before_id=&limit=`，每次最多 **5** 条本机历史
- 语音在本机转成中文后再 POST

## 明确不做

- `display.photo` / 投电视（仍由 Mac Cast）
- 拉取并执行除 `camera.capture` / `light.set` 以外的 execution_plan
- GoPro / 客厅灯以外的 Runtime 能力、Chromecast、相册

投屏、播报仍由已注册对应能力的 Participant（例如 Mac Edge）执行。

现场管理中控是另一个 App：[HomeAgent Admin](HomeAgentAdmin/README.md)。不要把开关塞进 Console 底栏。

## 打开工程

```bash
python3 ios/LivingRoomEdge/generate_xcodeproj.py
open ios/LivingRoomEdge/LivingRoomEdge.xcodeproj
```

- 主屏幕名称：`HomeAgent Console`
- Bundle ID：`com.gaolei.livingroom.edge.iphone`
- 最低系统：iOS 16
- 真机需麦克风 + 语音识别权限；语音请用真机。录音页另需麦克风以保存音频文件。

改完 Swift 文件列表后重新跑 `generate_xcodeproj.py`。

## 目录

```text
ios/LivingRoomEdge/LivingRoomEdge/
  App/       SwiftUI 入口、聊天窗、扫描/拍照/文件/录音/直播工作台、进度浮窗
  Brain/     IntentClient（登记 Participant、POST intent、GET detail）
  GoPro/     camera.capture 执行
  Light/     light.set（本机 TTS 喊小书）
  Intent/    进度时间线
  Speech/    本机语音转写；录音页 AAC 采集与本地播放
  VisualInput/  系统文档扫描（VisionKit）与本机拍照上传 → assets/upload
  VideoLiveStream/  video.live_stream：采集 / H.264 / MPEG-TS TCP
  Net/       HTTP 计时
```

中控：`ios/HomeAgentAdmin/`（节点列表 / 详情开关 / 管理日志 / 连接）。
