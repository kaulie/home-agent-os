# Server stubs — Edge wire protocol (`services[]`)

本目录 Flask stub 已按最新 Edge 协议对齐。生产 Brain 部署时对照下列改动点落地。

## 契约摘要

心跳 / 注册 **只认** `services[]`（不再写顶层 `skills` / 扁平 `capabilities`）：

```text
services[]
  service_id / display_name / version / group
  capabilities[]
    capability_id / description
    input_schema / output_schema
```

| Edge | service_id | group | capability_id |
|------|------------|-------|---------------|
| Chromecast | `netease.music` | `music` | `music.play` … |
| iPhone | `gopro.camera` | `camera` | `camera.capture`, `take_video` |
| iPhone | `chromecast.display` | `display` | `display.photo`（Cast Sender） |
| Mac | `local.notify` | `notify` | `notify.speak`（本机 TTS / `say`） |

`music.play` 参数：`song` / `artist` / `album`（均可选，至少填一个）。  
勿再使用 `author`、`singer_name`、`song_name`。  
`camera.capture` 输出：`photo_url`（必填）、`photo_local_path`、`saved_as`。流水线：快门 → 下最新图 → 上传 → **iPhone Cast 到 Chromecast**。  
`photo_url` 形如 `http://115.190.153.53:8080/{saved_as}`。  
`display.photo` 参数：`photo_url`（必填）；由 **iPhone** 经 Google Cast API 投到电视（需与 Chromecast 同局域网）。  
`notify.speak` 参数：`text`（必填）、`lang`（可选，如 `zh_CN`）；仅 Mac Edge；定时提醒用 step 上 `execution_timing`。

旧 id（`music.playback` / `take_photo` 等）入队会被 stub **拒绝**；Edge 侧也会 skip/fail。

## 执行时机 `execution_timing` + `base_time`

- Intent 根字段 `base_time`：入库 Unix **毫秒**时间戳。
- Step 字段 `execution_timing`：`immediate` | `delay`(`exec_time`) | `interval`(`interval_sec`+`first_exec_time`) | `cron`。
- **禁止**下发 `delay_sec`；相对延迟只在 Brain 语义阶段换算成绝对 `exec_time`。
- Heartbeat 带 `client_time_ms`；响应回 `brain_time_ms`。偏差 **>5 分钟** → `schedule_eligible=false`，路由跳过该节点（Brain 可改派 `assigned`）。
- 补做窗口（未开始执行）：单次 ≤15min；周期 ≤ `min(间隔/2, 15min)`。Edge 用同步后的 Brain 时间判定。

## 能力路由（单节点）

大脑根据心跳里的 capability registry，为整份 `execution_plan` 选定 **一个** `assigned_edge_id`（不做跨 Edge 拆分）：

1. 收集 plan 内全部 `capability`。
2. 在线 Edge 中筛选 **同时具备全部 capability** 的节点。
3. 偏好：`preferred_edge_id` → 同 `room` → `edge_id` 字典序。
4. 无候选 → 入队失败（HTTP 400 / intent reply 带 error）。

拉取：

- `GET /api/v1/devices/living-room/intents` **必须**带 `?edge_id=<本节点>`，否则返回 `{ "intents": [] }`。
- 每个 intent 含 `assigned_edge_id`；Edge 再比对本地 id，不一致则不执行。

## 文件对照

| 文件 | 职责 |
|------|------|
| [`edge_services.py`](edge_services.py) | normalize / validate / capability 索引 / `resolve_edge_for_plan` / execution_plan |
| [`edge_heartbeat_flask.py`](edge_heartbeat_flask.py) | register / heartbeat / `GET /edges` / `GET /capabilities` |
| [`device_commands_flask.py`](device_commands_flask.py) | intents 队列；路由写 `assigned_edge_id`；强制 `edge_id` 拉取 |
| [`intent_dispatch_flask.py`](intent_dispatch_flask.py) | 文本意图 → plan → 路由入队 |
| [`brain_app.py`](brain_app.py) | **推荐入口**：同进程挂载 heartbeat + intents + intent |
| [`edge_report_flask.py`](edge_report_flask.py) | 调试 `POST .../capabilities`（body=`services`） |

```bash
# 统一 Brain（同进程，路由可读心跳）
cd server && python brain_app.py
```

## 生产必改

1. **Register / Heartbeat**：解析并持久化 `services`；丢弃顶层 `skills`/`capabilities`；`GET edges` 主字段为 `services`。
2. **能力索引**：从 `services[*].capabilities[*]` 建索引（`GET /api/v1/capabilities?group=music`）。
3. **execution_plan**：用 `camera.capture` / `music.play` / `notify.speak` + 对应入参；勿再下发 `music.playback` 或 `skill+action`。
4. **Planner**：按 registry 选单节点；整份 plan 绑一个 `assigned_edge_id`。
5. **拉取**：Edge 必须传 `edge_id`，并校验响应里的 `assigned_edge_id`。

## 验收

```bash
# 启动统一 app 后：先 register + heartbeat 带 services，再：

# 能力索引
curl -s 'http://127.0.0.1:9527/api/v1/capabilities?capability=camera.capture'
curl -s 'http://127.0.0.1:9527/api/v1/capabilities?capability=notify.speak'

# 入队拍照（需在线节点具备 camera.capture）
curl -s -X POST http://127.0.0.1:9527/api/v1/devices/living-room/intents \
  -H 'Content-Type: application/json' \
  -d '{"execution_plan":[{"capability":"camera.capture","step":1}]}'

# 入队语音提醒（需 Mac 在线且具备 notify.speak）
curl -s -X POST http://127.0.0.1:9527/api/v1/devices/living-room/intents \
  -H 'Content-Type: application/json' \
  -d '{"execution_plan":[{"capability":"notify.speak","step":1,"input_constrict":{"text":"该吃饭了","lang":"zh_CN"}}]}'

# 入队投屏（需 iPhone 在线且具备 display.photo；与 Chromecast 同 Wi‑Fi）
curl -s -X POST http://127.0.0.1:9527/api/v1/devices/living-room/intents \
  -H 'Content-Type: application/json' \
  -d '{"execution_plan":[{"capability":"display.photo","step":1,"photo_url":"http://115.190.153.53:8080/EXAMPLE.jpg"}]}'

# 不带 edge_id → 空
curl -s 'http://127.0.0.1:9527/api/v1/devices/living-room/intents?intent_status=intent_parsed'

# 带本节点 edge_id → 仅 assigned 匹配的项
curl -s 'http://127.0.0.1:9527/api/v1/devices/living-room/intents?edge_id=YOUR_EDGE_ID&intent_status=intent_parsed&peek=1'

# 入队放歌
curl -s -X POST http://127.0.0.1:9527/api/v1/devices/living-room/intents \
  -H 'Content-Type: application/json' \
  -d '{"execution_plan":[{"capability":"music.play","step":1,"song":"十年","artist":"陈奕迅"}]}'

# 旧 id 应 400
curl -s -X POST http://127.0.0.1:9527/api/v1/devices/living-room/intents \
  -H 'Content-Type: application/json' \
  -d '{"execution_plan":[{"capability":"music.playback","step":1}]}'
```
