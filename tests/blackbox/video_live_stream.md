# video.live_stream 黑盒验收（iPhone Console 直播 + 音频）

> **维护**：`@quality`  
> **实现**：`@ui`（`ios/LivingRoomEdge/.../VideoLiveStream/`）  
> **Mac ingest**：`mac/src/mac_edge/plugins/video_live_ingest.py`（MPEG-TS 透传 + ffmpeg HLS 中继）  
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

## VL2 两机观看（HLS，LAN）

### 前置

- Mac 上 `ffmpeg` 在 PATH（`MAC_EDGE_VIDEO_INGEST_HLS` 默认开）
- 两台 iPhone（A 推 B 看）或 A 推、同机切到「观看」段（仅看列表，真机优先）
- 两台手机与 Mac 同一 Wi‑Fi；两台设置里 **Mac ingest URL** = `http://<mac-lan>:8790`

### 步骤

1. **A 推流** — iPhone A：互动 → 直播 → **自己直播** → Start Stream；界面 **LIVE**。
2. **Mac 确认 HLS 就绪**：
   ```bash
   curl -s "http://127.0.0.1:8790/api/v1/video-live/status?stream_id=STREAM_ID"
   ```
   **通过**：`status=streaming` 且出现 `"playback_url": "http://<mac-lan>:8790/api/v1/video-live/hls/<stream_id>/playlist.m3u8"`。
   ```bash
   curl -sI "http://127.0.0.1:8790/api/v1/video-live/hls/STREAM_ID/playlist.m3u8" | head -1
   # HTTP/1.0 200 OK
   ```
3. **B 观看** — iPhone B：互动 → 直播 → **观看**。
   **通过**：列表 ~3s 内出现 A 的会话（stream_id 短码、Console、已收字节增长）。
4. **播放** — 点击会话进入播放器。
   **通过**：数秒内（允许 4–8s 延迟）HLS 画面出现且与 A 取景一致；有音频更好，无音频不判失败（VL1 已知 AAC mux 问题，视频优先）。
5. **短码快照** — 可再 `curl status`，确认 `playback_url` 仅在 streaming 时出现。
6. **停流** — A 点 **Stop Stream**。
   **通过**：B 列表项消失（或变 idle/无数据）；HLS 路由返回 404：
   ```bash
   curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:8790/api/v1/video-live/hls/STREAM_ID/playlist.m3u8"
   # 404
   ```

### 负例

- `MAC_EDGE_VIDEO_INGEST_HLS=0`（或 Mac 无 ffmpeg）：status 无 `playback_url`；HLS 路由 404
- B 在「观看」列表点击时推流方还没送出首帧 → 播放器显示「流尚未就绪」，短轮询后自动出画

### 直播中三态（Event 整场回看）

1. A 推流一段时间（>10s）后，B 进「直播中」→ 点开会话
2. **跟随最新** — **通过**：播放器默认从**最新画面**开始（不再从窗口起点）；画面与 A 取景一致
3. **从头看** — **通过**：点右上「从头看」→ 从开播时刻（seg_00000）开始播
4. **任意时间点** — **通过**：拖 scrubber 可回到整场任意位置；拖到最新附近后点原生「LIVE」回最新

### 停流后回放

1. A 点 **Stop Stream**
2. **通过**：B「观看」页出现「回放」段，列出该场（短码、来源、起止时间、时长、段数）
3. 点进回放 → **通过**：从**开头**播整场（视频优先；音频受 VL1 影响可无声）
4. 拖 scrubber → **通过**：可跳到任意时间点回看
5. Mac 侧确认文件保留：`ls mac/data/video-live/hls/<stream_id>/`（playlist + 全部 seg_*.ts），`curl /status` 的 `replays[]` 含该场
6. （若配置了 `HLS_RETENTION_MINUTES`/`HLS_MAX_SESSIONS`）到点/超限后回放消失、文件清理

### 交卷材料

| 字段 | 内容 |
|------|------|
| case id | **VL2** |
| 指令 | A Start/Stop Stream；B 观看列表 + 播放 |
| 探针 | `status` JSON（含 `playback_url`）、playlist HTTP 状态码、B 端延迟估计 |
| 终态 | **通过**（出画）/ **部分**（列表可看但无画/无声）/ **失败** |

`[release]`（验收后）：`@controller [release] stage=tested sha=<short> result=pass|fail note=VL2 video.live_stream HLS watch`

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
| 2026-08-29 | **失败** | #121 sha `5ad4b99`；无新 capture；`68f21751` 仍 PID 0x101=0 包 |
| 2026-08-29 | **失败** | 无 a174070+ 新 capture；复测 `68f21751`（23:45，~104s）仍 PID 0x101 **0 包**、mp4 无 audio。#109 云部署 no-op（iOS-only） |
| 2026-08-28 | **失败** | sha `ce42234`；`video_stream_258b158e`（~12.5s）：h264 OK；ffprobe 见 aac PID 0x101 但 **0 个 audio TS 包**、channels=0；mp4 无 audio。见 [`run_results_video_live_vl1.json`](run_results_video_live_vl1.json) |
| 2026-08-28 | **待执行** | `@controller` #88 派单；iOS 代码侧已有 `AacAudioEncoder` + `muxAudio`；待装包 + 现场 Start Stream |
