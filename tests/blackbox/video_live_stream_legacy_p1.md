# LivingRoomLegacy P1 — video.live_stream（仅视频）

> **维护**：`@quality`  
> **实现**：`@ui`（`ios/LivingRoomLegacy/.../VideoLiveStream/`）  
> **Mac ingest**：`mac/src/mac_edge/plugins/video_live_ingest.py`（:8790）  
> **协调**：Chatbox `@ui` #113 / sha `b4dbff6`

Console「互动 → 直播」；`includesAudio=false`；目标 **640×480** h264 MPEG-TS → Mac ingest。

---

## 前置

| 项 | 要求 |
|----|------|
| Mac | `mac_edge`；`GET http://<mac-lan>:8790/api/v1/video-live/status` → 200 |
| iPhone | LivingRoomLegacy 已装 `b4dbff6+`；家长页 Mac ingest URL = `http://<mac-lan>:8790` |
| 网络 | iPhone 与 Mac 同 Wi‑Fi |

---

## P1 步骤

1. **基线** — `curl -s http://127.0.0.1:8790/api/v1/video-live/status`
2. **开流** — Legacy：互动 → 直播 → **Start**；界面 **LIVE**
3. **增长** — `GET .../status?stream_id=STREAM_ID`；`bytes_received` 单调增长（poll 2–3 次，间隔 3s）
4. **停流** — **Stop**
5. **探针** — `ffprobe -hide_banner -show_streams mac/data/video-live/STREAM_ID.ts`
   - **通过**：`codec_type=video`，`codec_name=h264`
   - **通过**：`width=640`，`height=480`（Legacy 目标分辨率）
   - **不要求** audio（P1 video-only）

---

## 交卷

| 字段 | 内容 |
|------|------|
| case id | **VL-P1** |
| 快照 | `run_results_video_live_legacy_p1.json` |
| `[release]` | `@controller [release] stage=tested sha=b4dbff6 result=pass\|fail note=Legacy P1 live stream` |

---

## 状态

| 日期 | 结果 | 备注 |
|------|------|------|
| 2026-08-29 | **失败** | #124 sha `b4dbff6`；无 Legacy 新 .ts；bytes 无增长 |
| 2026-08-29 | **待执行** | #113 派单；ingest OK；无 Legacy 新 .ts |
