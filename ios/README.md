# iPhone 意图窗口

iPhone App 是 **Intent Source + Endpoint**：多轮聊天发出意图，声明本机屏幕可收 image/text，然后每 **5 秒** 拉一次进度。不注册 Runtime，不执行 GoPro / 投屏。

## 做什么

```text
启动 / 改 Brain URL
        │
        ▼
 POST /api/v1/edge-register
   roles: intent_source + endpoint
   endpoints: iphone.display → image, text
   services: []（不广告 camera.capture / display.photo）
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

- 默认 Brain：`http://115.190.153.53:9527`
- `client_hint` 本机稳定（`living-room-iphone-…`）；`participant_id` 来自登记回执
- 主界面是聊天窗；物流时间线挂在用户气泡下的「进度」浮窗里
- 当前一轮未到终态（succeeded / failed）前，输入框锁定
- 下拉刷新：`GET /api/v1/intents?participant_id=&before_id=&limit=`，每次最多 **5** 条本机历史
- 语音在本机转成中文后再 POST

## 明确不做

- Runtime 角色、心跳广告能力、`camera.capture` / `display.photo`
- 拉取并执行 `execution_plan`
- GoPro、Chromecast、相册、图片上传

拍照、投屏、播报由已注册 **Runtime** 的 Participant（例如 Mac Edge）执行。本机只发意图、收 `intent_detail` 展示。

## 打开工程

```bash
python3 ios/LivingRoomEdge/generate_xcodeproj.py
open ios/LivingRoomEdge/LivingRoomEdge.xcodeproj
```

- Bundle ID：`com.gaolei.livingroom.edge.iphone`
- 最低系统：iOS 16
- 真机需麦克风 + 语音识别权限；语音请用真机

改完 Swift 文件列表后重新跑 `generate_xcodeproj.py`。

## 目录

```text
ios/LivingRoomEdge/LivingRoomEdge/
  App/       SwiftUI 入口、聊天窗、进度浮窗
  Brain/     IntentClient（登记 Participant、POST intent、GET detail）
  Intent/    进度时间线
  Speech/    本机语音转写
  Net/       HTTP 计时
```
