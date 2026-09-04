# Mac Edge Runtime

客厅 **Mac Edge** 后台进程（无 UI）：对接 Brain 做 **注册 / 心跳 / 轮询 intent**。  
`display.photo` / `display.slideshow` 通过薄 Cast plugin 转发到**独立** Cast HTTP 服务（不同进程）。

本目录已并入 monorepo：[`smart_home_control/mac`](.)（与 `ios/`、`android/` 并列）。

## 身份与能力

| 字段 | 默认值 |
|------|--------|
| `client_hint` | `living-room-mac` |
| `display_name` | `客厅 · Mac Edge` |
| `device_type` | `mac` |
| `room` | `living-room` |
| `services` | `MAC_EDGE_ROLE=laptop`（本机默认）：`chromecast.display`、`local.notify`、`local.vision`、`local.query`、`local.clock`。`MAC_EDGE_ROLE=home-server`：`gopro.camera`（需 `MAC_EDGE_GOPRO_SSID`）+ `livingroom.ceiling_light`（客厅大路灯 `light.set`，不依赖 GoPro）。用户可见结果由 Brain 组装 `intent_detail.presentation`；语音播报是 `execution_plan` 里的 `notify.speak`，由 Runtime 当普通 capability 执行。 |

## Cast plugin（薄转发）

Edge **不**内嵌 pychromecast，也**不**监听 9090。须先启动你的独立 Cast 服务。

Plugin 唯一动作：

```http
GET http://127.0.0.1:9095/endpoint/display?url={urlencoded_photo_url}
```

基址可用 `MAC_EDGE_CAST_DISPLAY_URL` 覆盖。

## 协议

- `POST {BRAIN}/api/v1/edge-register`
- `POST {BRAIN}/api/v1/edge-heartbeat`
- `GET  {BRAIN}/api/v1/devices/living-room/intents?edge_id=…&peek=1`

默认 Brain：本机 `http://127.0.0.1:9527`（与 Brain 同机；见 [`config/endpoints.json`](../config/endpoints.json) 的 `brain.local` 身份），空闲轮询默认 **3s**（`MAC_EDGE_INTERVAL_SEC`）。  
有 pending `execution_timing` 时改为 **deadline sleep**：`min(10s, 剩余时间/2)`，临近到点会越睡越短；`notify.speak` 在独立 worker 线程执行，不堵主循环。  
`edge_id` 持久化在 `data/edge_id.json`（已 gitignore）。

Context 从 intent 的 **`ctx_param`** / **`step_outputs`**（兼容 `context` / `outputs` / 计划步上的 `outputs`）hydrate，再解析 `$photo_url` / `$summary` / `$answer_text`（支持句内嵌；`$lighting.whole` 走 JSON path；旧 `$perception_json.summary` 落到 `$summary`；`$photoURL` 落到 `photo_url`）。

## 启动

```bash
cd /Users/gaolei/Projects/smart_home_control/mac
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 先启动独立 Cast HTTP（:9095），再：
PYTHONPATH=src python -m mac_edge
```

## 环境变量

见 [`.env.example`](.env.example)：`MAC_EDGE_BRAIN_URL`、`MAC_EDGE_CAST_DISPLAY_URL`、`MAC_EDGE_GOPRO_*`、`MAC_EDGE_QUERY_*` 等。

Mac 广告 `local.vision`：`vision.perceive`（场景结构）与 `vision.ask`（图+问句 → `answer_text`）。`vision.ask` 入参 `photo_url` + `query`；只根据图中可见内容作答，指向类问题须落到具体对象。与 `vision.perceive` 独立 prompt/schema，**不** import 该插件。

## `query.content`（独立问答）

Mac 广告 `local.query` / `query.content`。入参 `query`；输出 `answer_text`（必填）、可选 `photo_url`、`citations`。不知道就直说不知道；专业域须引用来源。自有 `query_providers/`，**不** import `vision.perceive`。

## `clock.now`（本机墙上时钟）

Mac 广告 `local.clock` / `clock.now`。读本机时刻（可选 IANA `timezone`），产出 `now_iso` 与 `time_text`。**禁止 LLM**；问几点不要派 `query.content`。成功后 Brain 组装 `presentation`；纯提醒仍 `notify.speak`。

## GoPro `camera.capture`（无感切网）

与 iPhone 同一 wire：`gopro.camera` / `camera.capture`。Mac 无蜂窝，流水线为：

1. 记录当前家里 SSID  
2. CoreWLAN 加入 `MAC_EDGE_GOPRO_SSID`（不用 `networksetup`：LaunchAgent 里即使用 sudo 也会弹管理员框）  
3. gpControl 快门 → 下载最新静图到 `data/gopro/`  
4. 切回家里 Wi‑Fi → `POST` 上传 → 返回 `photo_url` / `saved_as`

可选入参 `upload_dest`：默认 **lan**（本机 img-server `img-server.local`，Mac 上传走 `127.0.0.1:8080`）。投屏/电视必须 `lan`，禁止 `cloud`。仅用户明确要求公网时才填 `cloud`。未传时读 `MAC_EDGE_PHOTO_UPLOAD_DEST`。已有 Asset 再传到图床/云端用 `asset.upload`（`dest=img_server|cloud`）。

必填：`MAC_EDGE_GOPRO_SSID`、`MAC_EDGE_GOPRO_PASSWORD`。失败时尽量恢复家里网。

## 局域网 ping 监控（runtime，非 capability）

Edge 启动后默认开启后台探测，结果写入独立文件 `logs/intranet_ping.log`（不进主 agent log）。

| 变量 | 默认 | 说明 |
|------|------|------|
| `MAC_EDGE_INTRANET_PING` | `1` | `0` 关闭 |
| `MAC_EDGE_INTRANET_PING_MODE` | `gateway` | `gateway` / `targets` / `lan` |
| `MAC_EDGE_INTRANET_PING_TARGETS` | — | `targets` 模式必填，逗号分隔 IP |
| `MAC_EDGE_INTRANET_PING_INTERVAL_SEC` | `5` | 主循环周期 |
| `MAC_EDGE_INTRANET_PING_STATS_INTERVAL_SEC` | `60` | 写 1m/5m 窗口统计 |
| `MAC_EDGE_INTRANET_PING_DISCOVER_INTERVAL_SEC` | `300` | `lan` 模式 peer 发现刷新 |
| `MAC_EDGE_INTRANET_PING_LOG` | `logs/intranet_ping.log` | 独立日志路径 |

- `gateway`：只 ping 默认网关  
- `targets`：只 ping 指定 IP  
- `lan`：周期性发现同网段在线机，再对 peer 列表做周期 ping  

日志行示例：`SAMPLE host=… ok=1 rtt_ms=…`；`STATS window=1m host=… count=… avg_ms=…`。

## mac_voice（voice.stream · kind=input）

挂在客厅 **Mac Runtime** 上的常驻语音入口，**不是**独立 edge。

- 心跳广告：`local.voice` / `voice.stream`（`MAC_EDGE_VOICE=0` 可关）
- 进程：可由 `mac_edge` 自动监督拉起，也可手动跑；共用 `mac/data/edge_id.json`
- `kind=input` → 可 `POST /api/v1/intent`。唤醒应答「又咋了」是本机 TTS 回复语，不建 intent、不走理解；STT 回声若整句就是这句也会丢掉。正文指令仍 `POST /api/v1/intent`。
- 生命周期自管理：`MAC_VOICE_LISTEN_MODE=wake_word`（默认，整句里出现两次 **面条** 或近音即唤醒，中间可夹其它词；喇叭回「又咋了」；**下一句**须在唤醒回复结束后 5 秒内开口才当指令）| `always_on`（调试：任意语音都发）| `wait_command`（未实现，不会静默开麦）

```bash
cd mac
source .venv/bin/activate
# 通常只需跑 mac_edge（会监督 mac_voice）。单独调试：
export MAC_EDGE_EDGE_ID=$(python -c "import json;print(json.load(open('data/edge_id.json'))['edge_id'])")
PYTHONPATH=src python -m mac_voice --live --post-intent
```

STT 默认 `volc_sauc`。换厂商只加 `mac_voice/stt/*.py`。

## video.live_stream ingest（MPEG-TS over TCP）

Mac 收 iPhone Console「直播」或 **Larix Broadcaster** 的 H.264 MPEG-TS。不广告 `video.live_stream`（该 cap 在 iPhone 心跳上）；本机只做 LAN ingest。

```bash
cd mac
source .venv/bin/activate
PYTHONPATH=src python -m mac_edge
curl -s http://127.0.0.1:8790/api/v1/video-live/status
```

控制口默认 `:8790`，Larix 常驻 MPEG-TS TCP `:5004`。详见 [`plugins/video-live-stream/capability.md`](../plugins/video-live-stream/capability.md)。
`MAC_EDGE_VIDEO_INGEST=0` 可关；`MAC_EDGE_VIDEO_INGEST_PREVIEW=1` 连接后弹 ffplay。
