# video.live_stream 黑盒验收（iPhone Console 直播 + 音频）

> **维护**：`@quality`  
> **实现**：`@ui`（`ios/LivingRoomEdge/.../VideoLiveStream/`）  
> **Mac ingest**：`mac/src/mac_edge/plugins/video_live_ingest.py`（只透传 MPEG-TS，不改）  
> **协调**：Chatbox `@controller` #88

**不是**计划步：`video.live_stream` 为 `kind=input`，由 Console「互动 → 直播」自管理，不经 `POST /api/v1/intent`。

---

## 前置

| 项 | 要求 |
|----|------|
| Mac | `mac_edge` 运行中；`GET http://<mac-lan>:8790/api/v1/video-live/status` → 200 |
| 网络 | iPhone 与 Mac 同一 Wi‑Fi |
| iPhone | LivingRoomEdge 已装含音频路径版本；设置里 **Mac ingest URL** = `http://<mac-lan>:8790` |
| 权限 | 相机 + **麦克风** 已授权（`Info.plist` 已有 `NSMicrophoneUsageDescription`） |
| 工具 | Mac 上 `ffprobe`、`ffmpeg`（或 `ffplay`）可用 |

---

## VL1 直播含音频（P2，高打扰）

### 步骤

1. **基线** — Mac：
   ```bash
   curl -s "http://127.0.0.1:8790/api/v1/video-live/status"
   ```
   记录 `status`（通常 `idle` 或 `streaming` 仅 Larix 常驻）。

2. **开流** — iPhone：互动 → 直播 → **Start Stream**；界面 **LIVE**；对着麦克风说话数秒。

3. **增长** — Mac（替换 `STREAM_ID`）：
   ```bash
   curl -s "http://127.0.0.1:8790/api/v1/video-live/status?stream_id=STREAM_ID"
   ```
   **通过**：`bytes_received` 随时间 **单调增长**（可连 poll 2–3 次，间隔 3s）。

4. **停流** — iPhone：**Stop Stream**。

5. **探针** — Mac（`dump_path` 默认 `mac/data/video-live/<stream_id>.ts`）：
   ```bash
   ffprobe -hide_banner -show_streams "mac/data/video-live/STREAM_ID.ts"
   ```
   **通过**：
   - 存在 `codec_type=video`，`codec_name=h264`
   - 存在 `codec_type=audio`，`codec_name=aac`（或 `mp4a`）

6. **回放** — Mac：
   ```bash
   ffmpeg -y -i "mac/data/video-live/STREAM_ID.ts" -c copy "/tmp/STREAM_ID.mp4"
   ffprobe -hide_banner -show_streams "/tmp/STREAM_ID.mp4"
   ```
   **通过**：转出的 mp4 **含 audio 流**；现场听 `/tmp/STREAM_ID.mp4` 有声音（API 无法证实，记「现场已听」或「未证实」）。

### 负例（可选 VL1-N）

- 仅视频旧包：`.ts` 只有 `codec_type=video` → **不符合**（#88 根因场景）
- 拒计划步：对 Brain `POST /api/v1/intent`「开始直播」→ 不应派 `video.live_stream` 为计划步（iOS `RuntimeLoop` 拒执行）

---

## 交卷材料（agent-brief §4）

| 字段 | 内容 |
|------|------|
| case id | **VL1** |
| 指令 | Console Start/Stop Stream（非 intent 文本） |
| 环境 | Mac ingest URL、iPhone 版本、Wi‑Fi、`stream_id` |
| 探针 | `status` JSON、`ffprobe` 输出摘要、mp4 是否有 audio |
| 终态 | 三档：**通过** / **部分**（有 video 无 audio）/ **失败** |
| 快照 | `run_results_video_live_vl1.json`（curl + ffprobe 原文） |

`[release]`（验收后）：`@controller [release] stage=tested sha=<short> result=pass|fail note=VL1 video.live_stream audio`

---

## 状态

| 日期 | 结果 | 备注 |
|------|------|------|
| 2026-08-28 | **失败** | sha `ce42234`；`video_stream_258b158e`（~12.5s）：h264 OK；ffprobe 见 aac PID 0x101 但 **0 个 audio TS 包**、channels=0；mp4 无 audio。见 [`run_results_video_live_vl1.json`](run_results_video_live_vl1.json) |
| 2026-08-28 | **待执行** | `@controller` #88 派单；iOS 代码侧已有 `AacAudioEncoder` + `muxAudio`；待装包 + 现场 Start Stream |
