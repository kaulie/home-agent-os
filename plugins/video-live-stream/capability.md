# Service: iphone.video（capability: video.live_stream）

iPhone **实时视频输入**（`kind=input`）。把本机摄像头编成 H.264 MPEG-TS，经局域网 TCP 推到 Mac Edge ingest。

- **不是**计划步；误派则失败并带可读 msg
- **不做**视觉理解、抽帧、上云
- Mac 同一口也可接 **Larix Broadcaster**（MPEG-TS / TCP）

## Wire

| 字段 | 值 |
|------|-----|
| service_id | `iphone.video` |
| capability_id | `video.live_stream` |
| kind | `input` |
| transport | `mpegts_tcp` |
| encoding | `h264` |

## 行为

1. Console「互动 → 直播」开本地取景（未推流）
2. Start Stream → `POST {mac}/api/v1/video-live/prepare` → 推 MPEG-TS
3. Stop Stream / 离开页 → 停编码、关 TCP、`POST …/stop`
4. 不要作为用户任务的计划逐步执行

## Mac ingest（LAN）

随 `mac_edge` 启动（`MAC_EDGE_VIDEO_INGEST=0` 可关）。

| 接口 | 作用 |
|------|------|
| `POST /api/v1/video-live/prepare` | 开短时 MPEG-TS TCP 口，返回 `stream_id` + `endpoint`（`tcp://<lan-ip>:<port>`） |
| `GET /api/v1/video-live/status?stream_id=` | 会话状态 |
| `POST /api/v1/video-live/stop` | `{stream_id}` 关闭 |

常驻 Larix 口默认 **5004**（`MAC_EDGE_VIDEO_INGEST_LARIX_PORT`）。控制 HTTP 默认 **8790**。

码流写入 `mac/data/video-live/<stream_id>.ts`。`MAC_EDGE_VIDEO_INGEST_PREVIEW=1` 时连接后弹 ffplay。

## 配置

| 变量 | 含义 |
|------|------|
| `MAC_EDGE_VIDEO_INGEST` | `1`/`0` 是否启动 ingest（默认开） |
| `MAC_EDGE_VIDEO_INGEST_HTTP_PORT` | 控制 HTTP，默认 8790 |
| `MAC_EDGE_VIDEO_INGEST_LARIX_PORT` | Larix 常驻 MPEG-TS TCP，默认 5004 |
| `MAC_EDGE_VIDEO_INGEST_PREVIEW` | `1` 时用 ffplay 预览 |

## 实现

- iOS：`ios/LivingRoomEdge/LivingRoomEdge/VideoLiveStream/` + `App/LiveStreamWorkspaceView.swift`
- Mac ingest：`mac/src/mac_edge/plugins/video_live_ingest.py`
- 拒计划步：`mac/src/mac_edge/plugins/video_live_stream.py`；iOS `RuntimeLoop`

## 如何在 Mac 侧测试

```bash
cd mac
source .venv/bin/activate
PYTHONPATH=src python -m mac_edge
# 另开终端：
curl -s http://127.0.0.1:8790/api/v1/video-live/status
# 应见 "status": "idle"（及 Larix 常驻 listening）
```

准备一条 Console 会话并看端口：

```bash
curl -s -X POST http://127.0.0.1:8790/api/v1/video-live/prepare
# {"stream_id":"video_stream_…","endpoint":"tcp://192.168.x.x:NNNN",…}
ffplay -fflags nobuffer -f mpegts tcp://127.0.0.1:NNNN
```

或开预览：`MAC_EDGE_VIDEO_INGEST_PREVIEW=1` 后让 Console / Larix 推上来，Mac 弹窗出画。

## Larix Broadcaster

- Connection：**MPEG-TS**
- Mode：**TCP**
- Host：Mac 局域网 IP
- Port：常驻 **5004**，或 prepare 返回的端口
- Video：**H.264**（不要 HEVC）

## 如何验证 iPhone → Mac 打通

1. 电脑与手机同一 Wi‑Fi；Mac 跑 `mac_edge`
2. Console 设置填写 `http://<Mac-LAN-IP>:8790`
3. 互动 → 直播 → Start Stream，状态 LIVE
4. Mac 上 `ffplay` 或 `.ts` 文件能看到与取景一致的运动画面
5. Stop Stream 后两端 idle

（Larix 推 5004 也可单独验收，不经过 Console。）
