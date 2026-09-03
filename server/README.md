# Brain — `home_brain.py`

本目录 **唯一** Brain 进程是 [`home_brain.py`](home_brain.py)（火山生产文件落地后继续改这一份）。[`brain_app.py`](brain_app.py) 只转调同一 `app`。不要再开并行 stub。

```bash
export ARK_API_KEY=...
cd server && python home_brain.py
# 等价：python brain_app.py
```

`:9527`。现场管理 HTML **不上云、不由 Brain 提供**：本机 `python3 admin/serve.py` → <http://127.0.0.1:8788/>（默认代理云上 Brain `/api/v1/admin/*`）。`POST /api/v1/intent` 立刻返回 `intent_received`，后台 `llm_worker` 调方舟，写入 `execution_plan` 后升到 `intent_parsed`（空 plan 或规划失败为 `failed`，`msg`/`error` 必填）。每单写入 `intent_origin`（`lan` 或 `cloud`）：受理该单的 Brain 控制面，由本进程 `BRAIN_ORIGIN` 决定（未设时：`/root/chat-gateway` → `cloud`，否则 `lan`）。客户端可选 POST 该字段，Brain 仍以本机 origin 为准。规划 prompt：[`prompts/task_planner_system_prompt.md.en`](prompts/task_planner_system_prompt.md.en)。选边：心跳 last-writer-wins（`capability_id → edge_id`），每步 `assigned_edge_id`。密钥只读 `ARK_API_KEY`，不要写进代码。

权威状态在 SQLite，对照 [`docs/db-schema.md`](../docs/db-schema.md)：`jobs`（物流）、`participants`（注册+心跳）、`intent_reviews`（按次追加，含 `session_id`）。重启后续同一 `intent_id` / `participant_id`（同 `client_hint` 不重签）；`intent_received` 未规划单会重新入队。库文件默认 `server/data/brain.sqlite3`（`BRAIN_DB_PATH`）。日志写到 `server/llm_logs/brain.log`（按天切割，`BRAIN_LOG_DIR` 可改路径），不打控制台。**Brain 进程不建库、不迁移**；空库由 `@dba` 执行 `python db.py init`。备份：`python db.py backup /path/to/brain.sqlite3.bak`。Mac Edge 的 `local_ledger.json` / `edge_id.json` 仍是 JSON。

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
| Chromecast / Mac | `chromecast.display` | `display` | `display.photo` / `display.slideshow` |
| Mac home-server | `gopro.camera` | `camera` | `camera.capture`（`MAC_EDGE_GOPRO_SSID` 时广告；无感切 Wi‑Fi） |
| Mac laptop | `local.notify` | `notify` | `notify.speak`（本机 TTS / `say`） |
| Mac laptop | `local.vision` | `vision` | `vision.perceive`（场景结构）；`vision.ask`（图+问句 → `answer_text`） |
| Mac laptop | `local.query` | `query` | `query.content`（Edge 本地问答；不知道就说不知道；与 vision 零代码依赖） |

iPhone 是 **Intent Source**：只发自然语言、只轮询 `intent_detail`，**不注册 Edge**、不广告 `gopro.camera` / Cast。

`music.play` 参数：`song` / `artist` / `album`（均可选，至少填一个）。  
勿再使用 `author`、`singer_name`、`song_name`。  
`camera.capture` 输出：`photo_url`（必填）、`photo_local_path`、`saved_as`。默认 `upload_dest=lan`；投屏/电视禁止 `cloud`。  
`photo_url` 形如 `http://<mac-lan-ip>:8080/{saved_as}`（本机 img-server；LAN IP 自动探测，可用 `PHOTO_PUBLIC_BASE` 覆盖）。  
`display.photo` 参数：`photo_url`（必填，须 LAN，Chromecast 在家里 Wi‑Fi 拉取）。  
`display.slideshow` 参数：`photo_urls`（必填 JSON 数组）、`interval_sec`（默认 5）、`order`（`array_asc` 默认 / `array_desc` / `alphabet_asc` / `alphabet_desc` / `random`）。轮播用本能力，不要拆成多个 `display.photo`。不传 `photo_urls` 则失败。  
`notify.speak` 参数：`text`（必填）、`lang`（可选，如 `zh_CN`）；仅 Mac Edge；定时提醒用 step 上 `execution_timing`。`text` 支持内嵌 `$photo_url`；视觉结果用 `$summary`（也兼容旧写法 `$perception_json.summary`）。  
`vision.perceive`：**输入** `photo_url`（必填）；**平铺输出** `summary` / `people` / `spatial` / `actions` / `posture` / `lighting`（复杂字段为 JSON 字符串）。Brain 按 step 的 `output_constrict` 把对应键写入 `ctx_param`，无视觉专用纠偏；由 **Mac Edge 本地**调视觉模型。  
`vision.ask`：**输入** `photo_url` + `query`（均必填）；**输出** `answer_text`。只根据图中可见内容回答「这个字读啥」这类指向问题；看不清就说不知道。与 `vision.perceive` 独立 schema，不产出场景字段。下游 `notify.speak`（`$answer_text`）。  
`query.content`：**输入** `query`（必填）；**平铺输出** `answer_text`（必填）、`photo_url`（可选）、`citations`（JSON 字符串）。不知道就直说不知道；科普/健康/医药等专业域须引用来源，禁止编造。独立 LLM/生图栈，**不依赖** `vision.perceive`。下游可用 `notify.speak`（`$answer_text`）或 `display.photo`（`$photo_url`）。

旧 id（`music.playback` / `take_photo` 等）Edge 侧 skip/fail。

## 执行时机 `execution_timing` + `base_time`

- Intent 根字段 `base_time`：入库 Unix **毫秒**时间戳。
- Step 字段 `execution_timing`：`immediate` | `delay`(`exec_time`) | `interval`(`interval_sec`+`first_exec_time`) | `cron`(`cron_expr`+`timezone`+`first_exec_time`)。
- **禁止**下发 `delay_sec`；相对延迟只在 Brain 语义阶段换算成绝对 `exec_time`。
- Heartbeat 带 `client_time_ms`；响应回 `brain_time_ms`。偏差 **>5 分钟** → `schedule_eligible=false`，路由跳过该节点（Brain 可改派 `assigned`）。
- 补做窗口（未开始执行）：单次 ≤15min；周期 ≤ `min(间隔/2, 15min)`。Edge 用同步后的 Brain 时间判定。

## 能力路由（按步选边）

心跳里每个 `capability_id` last-writer-wins 记到 `capability_edge_mapping`。规划落地时每步写 `assigned_edge_id`（不同步可以不同边）。时钟偏差 ≥5 分钟的心跳 HTTP 400，不入库。

拉取：`GET /api/v1/devices/living-room/intents` **必须**带 `?edge_id=`，否则 `{ "intents": [] }`。按 `intent_status` 过滤后，只返回该节点出现在某步 `execution_plan[].assigned_edge_id`（或 `pending_delivery.edge_id`）的最近 N 条（`last`，最大 10）。

能力目录（在线且可调度）：

- `GET /api/v1/capabilities` — 扁平列表，每项含 `capability_id`、`description`、`input_schema`、`output_schema`、`service_id`、`group`、`edge_id`、`assigned_edge_id`。可选 `?capability_id=`、`?edge_id=` 过滤。
- `GET /api/v1/services` — 按 `service_id` 分组，嵌套 `capabilities[]`。
- `GET /api/v1/edges` — 参与者 + 心跳快照（含 `services[]`）。

## 文件对照

| 文件 | 职责 |
|------|------|
| [`home_brain.py`](home_brain.py) | **唯一 Brain**：intent / 规划 / 心跳 / 照片 / services |
| [`brain_app.py`](brain_app.py) | 转调 `home_brain.app` |
| [`db.py`](db.py) | SQLite：jobs / participants / 序号 |
| [`prompts/task_planner_system_prompt.md.en`](prompts/task_planner_system_prompt.md.en) | 方舟规划 prompt |

心跳偏差 **>5 分钟** → HTTP 400。Intent 根字段 `intent_base_time` 为 Unix **毫秒**。

连通性 / 对表：`GET /api/v1/ping`（别名 `/ping`）→ `server_time_ms`；可选 `?client_time_ms=` 回 `skew_ms`（server−client）。不鉴权、不碰 DB。

## 验收

```bash
# 连通性 / 对表
curl -s 'http://127.0.0.1:9527/api/v1/ping'
curl -s "http://127.0.0.1:9527/api/v1/ping?client_time_ms=$(python3 -c 'import time; print(int(time.time()*1000))')"
# 注册 + 心跳 + 发意图 + 查详情
curl -s -X POST http://127.0.0.1:9527/api/v1/edge-register
curl -s 'http://127.0.0.1:9527/api/v1/services'
curl -s 'http://127.0.0.1:9527/api/v1/capabilities'
curl -s -X POST http://127.0.0.1:9527/api/v1/intent \
  -H 'Content-Type: application/json' \
  -d '{"text":"现在几点了","source":"text"}'
curl -s 'http://127.0.0.1:9527/api/v1/intent_detail?intent_id=1'
curl -s 'http://127.0.0.1:9527/api/v1/devices/living-room/intents?edge_id=YOUR_EDGE_ID&intent_status=intent_parsed&last=5'
```
