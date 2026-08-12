# Mac Edge Runtime

客厅 **Mac Edge** 后台进程（无 UI）：对接 Brain 做 **注册 / 心跳 / 轮询 intent**。  
`display.photo` 通过薄 Cast plugin 转发到**独立** Cast HTTP 服务（不同进程）。

本目录已并入 monorepo：[`smart_home_control/mac`](.)（与 `ios/`、`android/` 并列）。

## 身份与能力

| 字段 | 默认值 |
|------|--------|
| `client_hint` | `living-room-mac` |
| `display_name` | `客厅 · Mac Edge` |
| `device_type` | `mac` |
| `room` | `living-room` |
| `services` | `chromecast.display` → `display.photo`；`local.notify` → `notify.speak`（优先 edge-tts 男声 `zh-CN-YunxiNeural`，失败回退 `say`） |

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

默认 Brain：`http://115.190.153.53:9527`，循环默认 **3s**（可用 `MAC_EDGE_INTERVAL_SEC` 覆盖）。  
`edge_id` 持久化在 `data/edge_id.json`（已 gitignore）。

Context 从 intent 的 **`ctx_param`**（兼容 `context` / `outputs`）hydrate，再解析 `$photo_url`。

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

见 [`.env.example`](.env.example)：`MAC_EDGE_BRAIN_URL`、`MAC_EDGE_CAST_DISPLAY_URL` 等。

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
