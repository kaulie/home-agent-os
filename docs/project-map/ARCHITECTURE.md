# ARCHITECTURE

系统怎么转。细节契约链到已有文档，这里只保留导航所需的骨架。

## 两套系统

```text
产品运行时                         开发协调（非产品路径）
User                               @boss / Dev Console
  → Intent Source                    → Chatbox :8787
  → Brain :9527                      → @controller
  → Edge Runtime                     → agent-bridge :9540
  → Capability / Device              → Fleet workers（写代码的人）
  → Endpoint / presentation
```

本文默认讲**产品运行时**。Fleet 见 [docs/agent-roster.md](../agent-roster.md)。

## 系统组件

```text
User
  ↓ 自然语言 / 语音 / 扫描 / 拍照
Intent Source（iPhone / Android / Mac voice / Admin）
  ↓ POST /api/v1/intent
Brain（server/home_brain.py）
  ├── shortcut_mode（命中则跳过 LLM）
  ├── Planner LLM（Ark；可选 Qwen shadow）
  ├── do_execution_plan（每步 assigned_edge_id）
  └── kind=system 步：Brain 就地执行
  ↓ jobs 行（SQLite），status=intent_parsed
Runtime Agent（Mac / iOS / Android Edge）
  ↓ peek GET /api/v1/devices/living-room/intents?edge_id=
  ↓ hydrate $var + 前序门
Capability / Plugin
  ↓ 设备 I/O 或模型调用
POST .../intent/<id>/step/<n>/status
  ↓ Brain assemble_presentation
Endpoint / Intent Source UI
  ↓ GET /api/v1/intent_detail  （或 Cast 推送）
User 看见结果
```

物理节点不是抽象。同一个 iPhone 可以同时是 Intent Source + 有限 Runtime + Endpoint。模型见 [docs/participant-model.md](../participant-model.md)。

### 双 Brain

同一套代码，两个进程 / 两个 domain：

| 实例 | 地址权威 | 标识 |
|------|----------|------|
| LAN | `config/endpoints.json` → `http://brain.local:9527`（HTTP 用发现到的 IPv4；本机 loopback） | `BRAIN_ORIGIN=lan` |
| Cloud | `115.190.153.53:9527` | 云路径 `/root/chat-gateway` 暗示 cloud |

Runtime 可向两个 Brain 分别 register / heartbeat。Heartbeat 属于 **Registration** `(participant_id, domain)`，不属于 Runtime 本身。详见 [docs/architecture/dual-brain-runtime.md](../architecture/dual-brain-runtime.md)。

Cloud Brain 调本机 Fleet：SSH 反向隧道把云 `127.0.0.1:19540` 映到 Mac `:9540`。

## 数据流

### 输入从哪来

主入口：`POST /api/v1/intent`，body 含 `text`、`source`、`participant_id`（或历史 `edge_id`）、可选 `session_id` / `asset_ref`。

实现：`dispatch_intent()` → `new_intent()` → `jobs` 行，初始 `status=intent_received`。

其它入口：

- 遗留队列：`POST /api/v1/devices/living-room/intents`
- 语音唤醒：`dispatch_voice_wake`
- `source=dev`：开发任务，走 `submit_agent_task`，**不是**家务 plan

发出端：LivingRoomEdge、LivingRoomLegacy、Android Console、Mac `mac_voice`。

### 在哪产生 Task

没有独立队列表。`jobs.status` 就是队列。

规划路径：

1. 可选 shortcut（[`server/shortcut_mode/`](../../server/shortcut_mode/)）→ 固定 plan，不调 LLM。
2. 否则 `task_queue` → `llm_worker()` → `call_ark()`。
3. System prompt **只**来自 [`server/prompts/task_planner_system_prompt.md.en`](../../server/prompts/task_planner_system_prompt.md.en)，经 `compact_prompt()`。禁止在 `home_brain.py` 内联规划长文。
4. Catalog：在线心跳 + `kind=system`（[`server/system_capabilities.py`](../../server/system_capabilities.py)、[`server/capability_ads.py`](../../server/capability_ads.py)）。
5. `extract_llm_plan` → `make_execution_plan` → `do_execution_plan` 写入 `jobs.execution_plan`。

某步无在线节点具备该 capability → **入队失败**（system 步除外，`assigned_edge_id=system`）。

### 谁执行

Edge **peek**（不删除）`GET /api/v1/devices/living-room/intents?edge_id=`。

Mac：`EdgeAgent._control_tick` → `LocalLedger.ingest_peek` → `IntentScheduler.handle` → `executor` / `resolve_params`。

跨 Edge handoff：step 2 所在节点会再次 peek 到同一 intent（step 1 已成功之后）。

Plugin 收到的是已经 hydrate 过的 params。缺必填 → 该步失败。禁止插件自己去读前序 step。

### 结果回哪

Edge：`POST /api/v1/intent/<id>/step/<n>/status`。

Brain：`_apply_step_status_record` → `_maybe_finalize_intent_after_step`。全部 capability 步终态后 `assemble_presentation`，写入 `jobs.presentation`。任一步失败则 fail-fast，放弃未跑步。

客户端拉 `GET /api/v1/intent_detail`。推送路径：`pending_delivery` + Mac `delivery.py` / Cast `display.*`。

存储：Brain SQLite `server/data/brain.sqlite3`（`BRAIN_DB_PATH`）。Mac 另有 `local_ledger.json` 作为本机未完成工作账本。Schema 合同：[docs/db-schema.md](../db-schema.md)。

## 控制流

| 谁 | 负责 | 不负责 |
|----|------|--------|
| Brain | 理解、规划、按步选边、入队、组装 presentation、system 步 | 设备 I/O、plugin 实现、发出窗 UI |
| Runtime Agent | 心跳广告、peek、hydrate、前序门、调 plugin | 改 plan、替 Brain 做 presentation |
| Capability / Plugin | 执行本步已 resolve 的入参 | 读其它 step、碰 filesystem 当身份、自己拼 URL 列表 |
| Endpoint | 按声明的类型呈现 presentation | 规划、执行别人的 capability |
| Intent Source | 发自然语言、信 `intent_detail` | 注册成「全家 Runtime」、替电视投屏（除非本机声明了该 cap） |
| Observer（产品 Role） | 消费运行事件 | 不是 Cursor `@coordinator` |

Brain **不探测设备**。可调度集合来自心跳：`DECLARED ∧ AVAILABLE`，再叠加 `exposure_policy` 与 admin `edge_control_policy`。见 [docs/architecture/capability-availability.md](../architecture/capability-availability.md)。

## 核心状态

### Intent（`jobs.status`）

文档合同（[docs/db-schema.md](../db-schema.md) §5.1）：

```text
intent_received → intent_parsed → (hub_received / scheduled / assigned) → running → succeeded | failed
```

另有旁路 `intent_waiting`（不占流水线序号）。

别名（`home_brain.py` `_STATUS_ALIASES`）：`uploaded`→`intent_received`，`waiting`→`intent_waiting`，`success`/`completed`→`succeeded`，`error`→`failed`。

**CONFLICT：** Mac `IntentScheduler` 上报的是 `intent_scheduled` → `intent_dispatched`（[`mac/src/mac_edge/scheduler.py`](../../mac/src/mac_edge/scheduler.py)）。这两个名字不在 db-schema §5.1 表里。Brain `notify_intent_status_update` 接受规范化字符串，没有按 schema 表做硬白名单。wire 以 scheduler 名为准；schema 文档滞后。

### Step

整数：`0` waiting · `1` running · `2` succeeded · `3` failed。

### Edge / Registration

- 身份：`participants.participant_id`（Runtime 生成；wire 常叫 `edge_id`）
- 存活：`registrations(participant_id, domain)` — `online_status`、`services_snapshot`、`schedule_eligible`
- 声明：`participants.services`（稳定）
- 可用性：心跳 `capabilities[].available`。`DECLARED=true / AVAILABLE=false` 合法，不进可调度 map
- Brain 在线 TTL：`ONLINE_TTL_SEC = 60`（[`server/home_brain.py`](../../server/home_brain.py)）
- Endpoint 呈现 TTL：`ENDPOINT_TTL_SEC = 5 * 60`

### Participant 角色

正交 flag：`role_intent_source` / `role_runtime` / `role_endpoint` / `role_observer`。

### Asset

身份是 `asset_id`。步间只传 `asset_ref`。禁止把 path / 永久 URL 当 identity。库状态：`available|pending|expired|deleted`。授权：`asset_grants(asset_id, intent_id)`。设计：[docs/asset-contract.md](../asset-contract.md)。

## 关键入口（代码）

| 阶段 | 符号 | 文件 |
|------|------|------|
| HTTP 入口 | `dispatch_intent` | `server/home_brain.py` |
| 入队 | `do_execution_plan` | 同上 |
| Presentation | `assemble_presentation` | 同上 |
| 步回报 | `notify_step_status_update` | 同上 |
| System 步 | `run_system_step` | `server/system_capabilities.py` |
| Mac Agent | `EdgeAgent` | `mac/src/mac_edge/agent.py` |
| Mac 调度 | `IntentScheduler.handle` | `mac/src/mac_edge/scheduler.py` |
| Hydrate | `resolve_params` | `mac/src/mac_edge/runtime_context.py` |
| iOS 发出 / 有限 Runtime | `IntentClient` | `ios/LivingRoomEdge/.../Brain/IntentClient.swift` |
