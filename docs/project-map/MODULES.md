# MODULES

接到 Task 时：先用文首速查定位模块，再读该模块的「负责 / 不负责 / 入口」。不要从仓库根目录全文扫描。

层归属见 [BOUNDARIES.md](BOUNDARIES.md)。运行方式见 [RUNTIME.md](RUNTIME.md)。

## Task → 模块

| 我要改… | 先看模块 | 关键文件 | 不要动 | 怎么验 |
|---------|----------|----------|--------|--------|
| 心跳超时 / 节点掉线 | Brain 控制面 | `server/home_brain.py` `ONLINE_TTL_SEC`；各端 heartbeat 周期 | plugin、发出窗文案 | `server/tests/test_home_brain.py` 里 TTL 用例 |
| 「现在几点了」规划规则 | Planner | **只** `server/prompts/task_planner_system_prompt.md.en`；shortcut：`server/shortcut_mode/rules.py` | 禁止在 `home_brain.py` 写规划长文 | `server/tests/test_system_capabilities.py`、`test_shortcut_mode.py` |
| `clock.now` 执行（读钟） | System capabilities **或** Mac plugin | Brain：`server/system_capabilities.py`；Mac：`mac/src/mac_edge/plugins/clock_now.py` | `query.content` 不得编时刻 | Brain 测 + `mac/tests/test_clock_now.py`。**CONFLICT：** 双路径，见 Notes |
| `display.slideshow` 缺图 | Capability 契约 + Mac/Cast plugin | `plugins/chromecast-display/capability.md`；`mac/src/mac_edge/plugins/chromecast_display.py` | 禁止从前序 `camera.capture` 拼列表；契约要 `asset_refs` 不是 `photo_urls` | `mac/tests/test_capability_asset_refs.py` |
| hydrate `$var` / 前序门 | Mac Edge Runtime（及各端同构） | `mac/src/mac_edge/runtime_context.py`；iOS：`IntentClient.hydrateParams` | Brain 规划、plugin 自己读 `step_outputs` | `mac/tests/` runtime/context 相关 |
| iPhone 聊天窗 / 物流 UI | iOS Console（**已迁出** → [home-agent-cli](https://github.com/kaulie/home-agent-cli)） | `home-agent-cli: ios/LivingRoomEdge/.../Intent/`、`App/ContentView.swift` | Brain、Mac plugin | XCUITest（若有覆盖）+ 真机点一次 |
| iPhone 发 intent / 轮询 | iOS Console（同上，已迁出） | `Brain/IntentClient.swift` | 改 plan 结构 | 黑盒 `tests/blackbox/` |
| 云 Brain 发一版 | 部署（非模块实现） | `.cursor/rules/cloud-deploy.mdc` | 未测工作区、`db.py`/`sql/`/`data/`/`admin/` | `[release] stage=deployed` + `/health` |
| schema / 迁移 | DBA（见 BOUNDARIES） | `server/sql/`、`docs/db-schema.md` | 未经点名改 Edge JSON | `@dba` + Brain 单测 |
| Chat 点名 / 徽章 | Chatbox | `chat/mentions.py`、`chat/serve.py` | Brain DB | `python3 -m unittest chat.tests.test_chat` |
| wake Fleet worker | agent-bridge | `agent-bridge/src/agent_bridge/` | 产品 intent 路径 | `cd agent-bridge && PYTHONPATH=src python -m unittest discover -s tests` |
| OCR / 指字 | Sidecars | `ocr-service/`、`character-service/`；Brain `image.ocr` 只调服务 | 把 OCR 逻辑写进 plugin | sidecar 自测 + `server/tests/test_image_ocr.py` |
| 语音唤醒 / 拾音 | Mac Voice | `mac/src/mac_voice/` | 顺手改其它产品面门槛 | Mac 测 + 现场听 |

---

## Module: Brain 控制面

### Purpose

家庭意图的理解、规划、选边、入队、组装 presentation。产品控制面的唯一生产入口。

### Responsibilities

- 对外 Brain API（intent / edge-register / heartbeat / intent_detail / assets / admin）
- 把自然语言变成 `execution_plan`（每步 `assigned_edge_id`）
- 维护 `jobs`、participant、registration、capability map
- `kind=system` 步就地执行
- 全部 capability 步完成后 `assemble_presentation`

### Non-responsibilities

- Plugin / 设备 I/O
- 发出窗、物流 UI、Cast Receiver
- Mac 运维脚本、sidecar 进程
- 未经点名改 schema（归 `@dba`）

### Dependencies

- SQLite（`server/db.py`、`server/sql/`）
- Planner 提示词与 Ark
- 在线 Edge 心跳（没有心跳就没有可调度 catalog）
- 可选：OCR sidecar、agent-bridge（仅 `source=dev`）

### Dependents

- 所有 Intent Source / Runtime / Endpoint
- Admin HTML、Dev Console
- 黑盒测试

### Entry Points

- 根 [`home_brain.py`](../../home_brain.py) → [`server/home_brain.py`](../../server/home_brain.py)
- 别名 [`server/brain_app.py`](../../server/brain_app.py)
- 绑定 `0.0.0.0:9527`

### Important Files

- `server/home_brain.py` — `dispatch_intent`、`do_execution_plan`、`assemble_presentation`、`notify_step_status_update`、`ONLINE_TTL_SEC`
- `server/db.py`
- `server/capability_ads.py`、`server/edge_services.py`
- `server/shortcut_mode/`
- `server/dev_task*.py`、`server/agent_fleet.py`（Dev 控制面，混在同一进程）

### Runtime Behavior

LAN：`BRAIN_ORIGIN=lan`。Cloud：工作目录 `/root/chat-gateway`，systemd `doubao_skill`。dotenv：`server/.env` 否则仓库根 `.env`。需要 `ARK_API_KEY` 才能真实规划。

### Tests

`cd server && BRAIN_SKIP_LLM_WORKER=1 python -m unittest discover -s tests -v`

主文件 `server/tests/test_home_brain.py` 体量很大（约 5k 行）。

### Modification Risk

High。单体约 8k 行 / 66 路由。拆分方案未开工：[docs/architecture/brain-simplification-plan.md](../architecture/brain-simplification-plan.md)。

### Notes

Dev Console Admin API 与家务控制面同进程。改 intent 物流时不要误伤 `source=dev` 任务路径。

---

## Module: Planner

### Purpose

把用户话变成可执行的 capability 步骤列表，并约束选边与 presentation 意图。

### Responsibilities

- 唯一 system 消息：`server/prompts/task_planner_system_prompt.md.en`（`compact_prompt()`）
- 可选 Qwen shadow：`task_planner_system_prompt.qwen-small.md.en`
- 输出 plan JSON；结构不对就失败，不兜底拆包

### Non-responsibilities

- 执行任何 capability
- 在 Python 里维护规划规则长文
- 读 Entity Registry（一期 **未** 喂给 planner）

### Dependencies

- 在线 capability catalog（心跳 + system caps）
- `ARK_API_KEY`

### Dependents

- Brain `llm_worker` / `do_execution_plan`

### Entry Points

- `call_ark()`、`extract_llm_plan()`、`make_execution_plan()`（`home_brain.py`）
- shortcut 命中时不走 LLM：`server/shortcut_mode/rules.py`

### Important Files

- `server/prompts/task_planner_system_prompt.md.en`
- `server/prompt_loader.py`
- `server/execution_timing.py`
- `.cursor/rules/planner-prompt-source.mdc`

### Runtime Behavior

后台 worker 消费 `task_queue`。测试可设 `BRAIN_SKIP_LLM_WORKER=1`。

### Tests

`server/tests/test_shortcut_mode.py`、`test_planner_cache.py`、`test_intent_complexity.py`

### Modification Risk

High。改 md 即改线上规划行为；部署须 rsync `server/prompts/`。

### Notes

问「现在几点了」应规划 `clock.now`，不要派 `query.content` 当钟。

---

## Module: System capabilities

### Purpose

不绑 Runtime、不做设备 I/O 的控制面能力，由 Brain 就地跑。

### Responsibilities

`SYSTEM_CAPABILITY_IDS`：`capabilities.summary`、`asset.inventory`、`image.ocr`、`clock.now`、`map.route.estimate`。`assigned_edge_id=system`。

### Non-responsibilities

- 设备侧 TTS / 投屏 / 拍照
- 替代 Edge 上同名能力的广告（见 CONFLICT）

### Dependencies

- Brain 进程时钟；`image.ocr` 依赖 `OCR_SERVICE_URL`（默认 sidecar `:9188`）

### Dependents

- Planner catalog
- `try_run_system_steps`

### Entry Points

- `server/system_capabilities.py` — `is_system_capability`、`run_system_step`

### Important Files

- `server/system_capabilities.py`
- `server/sdk/image_ocr.py`

### Runtime Behavior

入队后 Brain 先跑 system 步，再等 Edge 跑其余步。

### Tests

`server/tests/test_system_capabilities.py`、`test_image_ocr.py`、`test_map_route.py`

### Modification Risk

Medium。

### Notes

**CONFLICT：** Mac 仍广告并实现 `clock.now`（`mac/src/mac_edge/plugins/clock_now.py`）。Brain 在 `is_system_capability` 时优先 `assigned_edge_id=system`。不要假设只有一条执行路径。

---

## Module: Mac Edge Runtime

### Purpose

客厅 Mac 上的 Runtime Agent：心跳、拉 intent、调度、hydrate、执行 plugin、双 Brain 注册。

### Responsibilities

- 向 LAN / Cloud Brain register + heartbeat
- peek intents、本地 ledger、intent 级 scheduler
- `$var` hydrate、前序步全成功才跑本步
- 监督 mac_voice / 视频 ingest / 小度 TTS

### Non-responsibilities

- 改 Brain 规划 / presentation 组装
- App UI
- 定义跨端 capability 契约原文（契约在 `plugins/*/capability.md`）

### Dependencies

- Brain `:9527`
- `mac/.env`（`MAC_EDGE_BRAIN_URL` 可为双 Brain JSON）
- 按角色：GoPro SSID（home-server）、Cast、img-server 等

### Dependents

- Mac plugins
- 手机拾音（voice ingest `:8792`）

### Entry Points

- `mac/run_mac_edge.sh` → `python -m mac_edge`
- 停止：`mac/stop_mac_edge.sh`

### Important Files

- `mac/src/mac_edge/agent.py` — `EdgeAgent`
- `mac/src/mac_edge/scheduler.py` — `intent_scheduled` → `intent_dispatched`
- `mac/src/mac_edge/executor.py`
- `mac/src/mac_edge/runtime_context.py` — `resolve_params`
- `mac/src/mac_edge/local_ledger.py`
- `mac/src/mac_edge/services.py`、`multi_brain.py`、`asset/manager.py`

### Runtime Behavior

无独立「Edge HTTP 端口」。随进程带起 `:8792` / `:8790` / `:8000`。角色 `laptop` vs `home-server` 广告的能力不同（laptop 不广告 GoPro）。

### Tests

```bash
cd mac && python3 -m unittest discover -s tests -p 'test_*.py' -q
```

### Modification Risk

High。

### Notes

Scheduler 状态名与 db-schema **CONFLICT**，见 [ARCHITECTURE.md](ARCHITECTURE.md)。

---

## Module: Mac Voice

### Purpose

唤醒、STT、把语音变成 intent；手机拾音 ingest。

### Responsibilities

- `--live --post-intent` 听写并 POST Brain
- 拾音 HTTP `:8792`

### Non-responsibilities

- 规划、Cast、发出窗 UI（手机拾音 App 归 `@ui`）

### Dependencies

- 本机 `edge_id`；Brain URL
- 常由 Mac Edge 监督拉起（`MAC_EDGE_VOICE` 非 `0`）

### Dependents

- HomeAgentPickup / LivingRoomPickup

### Entry Points

`PYTHONPATH=src python -m mac_voice --live --post-intent`

### Important Files

- `mac/src/mac_voice/`（含 `listen.py` — **多产品面共享，改动必须最小**）

### Runtime Behavior

监督日志：`mac/logs/mac_voice.supervised.out.log`

### Tests

`mac/tests/` 中 voice 相关；现场听一次才算数。

### Modification Risk

High（共享文件）。

### Notes

影响唤醒门槛 / 路由 / UI 的改动，只做本任务验收所需最小点，其余留给归属层。

---

## Module: iOS Console

### Purpose

家里的人用的主发出端：Intent Source + Endpoint，并带有限 Runtime（GoPro 拍照、客厅灯）。

### Responsibilities

- `POST /api/v1/intent`，轮询 `intent_detail`
- 呈现 `presentation`（图走 `GET /api/v1/assets/{id}/content`）
- 物流时间线
- 预装 Runtime：`camera.capture`、`light.set`（心跳广告这两项并执行）

### Non-responsibilities

- `display.photo` / 投电视（Mac Cast）
- 执行其它 capability
- 业务 Admin / Dev Console（独立 App）

### Dependencies

- Brain LAN/Cloud（设置里可切）
- 登记 + 心跳，发出前心跳失败则不出单

### Dependents

- 用户；黑盒 / XCUITest

### Entry Points

```bash
# iOS 客户端已迁出本仓 —— 见 https://github.com/kaulie/home-agent-cli
#   python3 ios/LivingRoomEdge/generate_xcodeproj.py
#   open ios/LivingRoomEdge/LivingRoomEdge.xcodeproj
```

### Important Files

- `ios/LivingRoomEdge/LivingRoomEdge/Brain/IntentClient.swift` — 发出、peek、hydrate、前序门
- `ios/LivingRoomEdge/LivingRoomEdge/Intent/IntentLogisticsTimelineView.swift`
- `ios/LivingRoomEdge/LivingRoomEdge/App/ContentView.swift`、`AppModel.swift`
- `ios/LivingRoomEdge/LivingRoomEdge/GoPro/`、`Light/LivingRoomLight.swift`

### Runtime Behavior

iOS 16+。Brain 自动 / 局域网 / 云。Legacy iOS 12 用 `ios/LivingRoomLegacy/`（仅文字 intent）。

### Tests

真机 / 模拟器；UI 自动化主要在 HomeAgentDev，Console 覆盖 `[UNKNOWN]` 是否有独立 XCUITest target。

### Modification Risk

High。

### Notes

**CONFLICT：** 根 README 仍写 iPhone「非 Edge、只发 intent」。以本模块与 [home-agent-cli 的 ios/README.md](https://github.com/kaulie/home-agent-cli/blob/main/ios/README.md) 为准。

---

## Module: iOS Admin / Dev / Pickup

### Purpose

三套独立 App，不要塞进 Console 底栏。

> **已迁出本仓** → <https://github.com/kaulie/home-agent-cli>（路径仍是 `ios/<App>/`）。本节保留为职责说明。

| App | 路径（在 `home-agent-cli` 仓） | 职责 |
|-----|------|------|
| HomeAgent Admin | `ios/HomeAgentAdmin/` | 业务运行态：节点 / 角色 / 事件 |
| HomeAgent Dev | `ios/HomeAgentDev/` | 开发任务、Fleet、调试、服务 Tab |
| HomeAgent Pickup | `ios/HomeAgentPickup/` | 手机麦 → Mac `voice.stream` `:8792` |
| LivingRoomPickup | `ios/LivingRoomPickup/` | iOS 12 拾音 |
| HomeAgentRelay | `ios/HomeAgentRelay/` | 热点 HTTP 中继实验 |

### Responsibilities

各 App 只做上表。Dev 可 wake Fleet（经 Brain → bridge）。

### Non-responsibilities

- 把开关塞进 LivingRoomEdge 底栏
- 在 Relay 里实现 Cast `:9095`（**CONFLICT** 见 FINDINGS）

### Dependencies

Brain；Dev 还依赖 agent-bridge（云上经隧道）。

### Dependents

`@boss`、Fleet、`@controller`

### Entry Points

**已迁出本仓** → <https://github.com/kaulie/home-agent-cli>（各目录 `generate_xcodeproj.py` 后 `open *.xcodeproj`）。

### Important Files

各 App `README.md`；Dev UITests 见 [docs/testing/xcuitest.md](../testing/xcuitest.md)。

### Runtime Behavior

HomeAgentDev 可同网段探测 LAN Brain，不依赖写死 IP。

### Tests

```bash
cd ios/HomeAgentDev
xcodebuild test -scheme HomeAgentDev \
  -destination 'platform=iOS Simulator,name=iPhone 17' \
  -only-testing:HomeAgentDevUITests/HomeAgentDevSmokeUITests
```

### Modification Risk

Medium。

### Notes

三控制台设计：[docs/architecture/three-consoles-debug-gateway.md](../architecture/three-consoles-debug-gateway.md)。

---

## Module: Android Console / Edge

### Purpose

Android 上的 Intent Source + Endpoint + Runtime。

### Responsibilities

当前文档主路径：`android/living-room-android/`（`EdgeAgent.kt`、`IntentPipeline.kt`）。

### Non-responsibilities

- 替代 iPhone Console
- 未经确认把 `app/` 或 `app-v2` 当唯一生产包

### Dependencies

Brain URL（`config/endpoints.json` 经 `tools/sync_endpoints.py` 写入）

### Dependents

Android 用户

### Entry Points

`android/` Gradle：`:living-room-android`、`:app-v2`、`:app`

### Important Files

- `android/living-room-android/`
- `android/app-v2/` — Chromecast / 旧 Edge 路径仍在仓库
- `android/app/` — legacy

### Runtime Behavior

`[UNKNOWN]`：`app` / `app-v2` 现场是否仍安装生产包，仓库内无单一 deploy 真源。Cast 主路径文档写 iPhone Cast Sender，不是 app-v2 默认安装。

### Tests

模块内测 + 黑盒（按 participant）。**[UNKNOWN]** 是否有统一 Gradle 测试入口。

### Modification Risk

Medium。

### Notes

**CONFLICT：** 根 README 把 `android/app-v2` 写成主 Chromecast Edge。

---

## Module: Capability 契约

### Purpose

跨端能力的 wire schema 与说明。规划器和各端实现应对齐这里，而不是对齐某一端的私有字段。

### Responsibilities

每个插件目录：`capability.md` + `manifest.yaml`。声明 input/output、必填、禁止项（如不得收 `photo_url`）。

### Non-responsibilities

- 发出 UI
- Brain 入队 / 选边算法
- 在契约里写「从前序 step 收集」

### Dependencies

无运行时依赖。Asset 身份规则见 [docs/asset-contract.md](../asset-contract.md)。

### Dependents

Planner ads、Mac/iOS/Android 实现、`@quality` 回归。

### Entry Points

`plugins/<name>/capability.md`

### Important Files

- `plugins/chromecast-display/capability.md` — `display.photo` / `display.slideshow`
- `plugins/gopro-camera/`、`plugins/clock-now/`、`plugins/query-content/` 等
- `plugins/runtime-agent-sdk/` — iOS 共享 SDK
- `plugins/chromecast-display/receiver/` — CAF Receiver HTML

### Runtime Behavior

契约本身不运行。Receiver 需部署到 HTTPS；Cast App ID `F7649303`。

### Tests

`mac/tests/test_capability_descriptions.py`、`test_capability_asset_refs.py`；黑盒 [docs/capability-regression-standard.md](../capability-regression-standard.md)

### Modification Risk

High。改 schema 等于改跨端协议。

### Notes

Capability 独立：[`.cursor/rules/capability-independent.mdc`](../../.cursor/rules/capability-independent.mdc)。

---

## Module: Mac plugins

### Purpose

Mac Edge 上的 capability 实现。只看本步已 resolve 的 params。

### Responsibilities

执行 `services.py` 广告出去的能力：相机、Cast 转发、TTS、vision、query、灯、空调、音乐、直播 ingest 等。

### Non-responsibilities

- Hydrate（Runtime 的事）
- 规划
- 把 filesystem path 当 asset 身份

### Dependencies

Mac Edge executor；部分依赖 sidecar / 设备局域网。

### Dependents

Mac Edge Runtime

### Entry Points

`mac/src/mac_edge/executor.py` 按 `capability` 分发。

### Important Files

`mac/src/mac_edge/plugins/*.py` — 例如 `gopro_camera.py`、`chromecast_display.py`、`notify_speak.py`、`vision_perceive.py`、`query_content.py`、`clock_now.py`

### Runtime Behavior

失败必须带可读 `msg`。Vision 输出不得拆包兜底。

### Tests

`mac/tests/test_*.py` 按插件名。

### Modification Risk

High。

### Notes

`display.slideshow`：契约要 `asset_refs`。`xiaomi_tv_display.py` 仍出现 `photo_urls` 字样，改时对齐契约，不要把旧字段当新协议。

---

## Module: Asset Manager

### Purpose

以 `asset_id` 管理字节的存储与授权。Capability 不碰 filesystem / 永久 URL。

### Responsibilities

- 登记、授权（`asset_grants`）、按 intent 取 content
- Edge 侧后端（img-server 等）

### Non-responsibilities

- 规划谁该拍照
- 把 URL 当 identity 写进 plan

### Dependencies

Brain assets 表；img-server `:8080`

### Dependents

拍照 / 扫描 / 投屏 / presentation

### Entry Points

Brain：`/api/v1/assets/*`。Mac：`mac/src/mac_edge/asset/manager.py`

### Important Files

- [docs/asset-contract.md](../asset-contract.md)、[docs/asset-manager-design.md](../asset-manager-design.md)
- `server/home_brain.py` 中 asset 路由（体量大，混在单体里）

### Runtime Behavior

presentation 只认 `asset_ref`。Cast 传输可用**临时** LAN URL，那是 representation，不是 identity。

### Tests

Brain / Mac asset 相关单测；黑盒带图用例。

### Modification Risk

High。跨节点复制 **尚未完成**（设计文档超前于代码）。

### Notes

一期未点名不要改 Asset 模型。

---

## Module: Sidecars

### Purpose

给 Brain / Edge 用的本地 HTTP 辅进程，不是 Edge。

| 服务 | 端口 | 入口 |
|------|------|------|
| img-server | 8080 | `python3 img-server/serve.py` |
| ocr-service | 9188 | `cd ocr-service && ./run.sh` |
| character-service | 9189 | `cd character-service && ./run.sh`（须 `local-rt/venv` python3.11） |
| pronunciation-service | 9190 | 可选，非常驻 |

### Responsibilities

存图、OCR、指字几何、发音打分。

### Non-responsibilities

- 规划、选边、发出 UI

### Dependencies

character-service **必须**先有 ocr-service。OCR 模型路径见各 README。local-rt llama 默认 `:8082`。

### Dependents

`image.ocr`、指字复合能力、照片 URL

### Entry Points

见上表。Docker Compose 仅 ocr/character/pronunciation 目录内，无根 compose。

### Important Files

各服务 `README.md`、`main.py` / `serve.py`

### Runtime Behavior

拓扑：[docs/service-topology.md](../service-topology.md)

### Tests

`character-service`：`pytest tests/test_geometry.py tests/test_stages.py`；eval 脚本见该 README。

### Modification Risk

Medium。

### Notes

**CONFLICT：** 可观测性文档写 local-rt `:8081`；`local-rt/run_llama.sh` 默认 `LLAMA_PORT=8082`。

---

## Module: Chatbox

### Purpose

Agent 之间的协调信箱。不是 Brain，不是产品 intent 路径。

### Responsibilities

`push_msg` / `pull_msg` / ack 徽章。库：`chat/data/agent_chat.sqlite3`。

### Non-responsibilities

- 家务规划
- 改 Brain DB

### Dependencies

无。本机 `python3 chat/serve.py`

### Dependents

全体 Fleet handle、`@boss` 页面、agent-bridge 进度推送

### Entry Points

`http://127.0.0.1:8787/` — `chat/serve.py`

### Important Files

`chat/serve.py`、`chat/mentions.py`、`chat/db.py`。[docs/agent-coordination.md](../agent-coordination.md)

### Runtime Behavior

`CHAT_HOST` / `CHAT_PORT` / `CHAT_DB_PATH` 可改。旧 Markdown 信箱 [docs/agent-mailbox.md](../agent-mailbox.md) **已停用**。

### Tests

`python3 -m unittest chat.tests.test_chat`

### Modification Risk

Medium。不要改水位文件以外的协调逻辑（controller 规则）。

### Notes

正式 `@` 要 `[status]` + ✅ recv；`cc @` 只 👌 got。

---

## Module: agent-bridge

### Purpose

把 Chat / Dev Task / `@controller` wake 变成 headless `cursor-agent` Fleet 执行。

### Responsibilities

`POST /api/v1/agents/{handle}/wake`；run 进度推 Chatbox `[fleet]` / `[dev-task]`。

### Non-responsibilities

- 产品 intent
- 替 handle 写非本层代码

### Dependencies

`AGENT_BRIDGE_TOKEN`、可选 `CURSOR_API_KEY`；Chatbox URL

### Dependents

Brain `source=dev`、Dev Console、`@controller`

### Entry Points

`cd agent-bridge && ./run.sh` → `:9540`

### Important Files

`agent-bridge/src/agent_bridge/`；`agent-bridge/agent_profiles/*.md`；`agent-bridge/tunnel/reverse-tunnel.sh`

### Runtime Behavior

云 Brain 经 `127.0.0.1:19540` 隧道打到本机 9540。

### Tests

`cd agent-bridge && PYTHONPATH=src python -m unittest discover -s tests -v`

### Modification Risk

Medium。

### Notes

**CONFLICT：** 部分 Cursor 规则写 `BRIDGE_AUTH_TOKEN`；代码与 `.env.example` 为 `AGENT_BRIDGE_TOKEN`。

---

## Module: Admin HTML

### Purpose

本机浏览器里的现场管理页。代理 Brain `/api/v1/admin/*`。

### Responsibilities

本地 UI。默认 Brain `http://127.0.0.1:9527`。

### Non-responsibilities

- 不上云（`cloud-deploy` 明确排除 `admin/`）
- 不替代 iOS Admin App

### Dependencies

LAN Brain

### Dependents

现场调试

### Entry Points

`python3 admin/serve.py` → `:8788`

### Important Files

`admin/serve.py`、`admin/static/index.html`

### Runtime Behavior

`BRAIN_URL` / `ADMIN_PORT` 可覆盖。

### Tests

`[UNKNOWN]` 无独立测试目录。

### Modification Risk

Low。

### Notes

**CONFLICT：** `server/README.md` 曾写 admin 默认代理云 Brain；代码默认本机 9527。

---

## Module: Quality

### Purpose

对外行为验收。不改产品功能代码。

### Responsibilities

- API 黑盒：`tests/blackbox/`
- App UI 自动化：先 XCUITest（HomeAgentDev）

### Non-responsibilities

- 实现功能
- 为验收加 `accessibilityIdentifier` 时未通知 `@ui`

### Dependencies

跑着的 Brain / 真实或夹具 Edge；`participant_id` 常为黑盒必填

### Dependents

发布门禁（`tested` 节点）

### Entry Points

```bash
python3 tests/blackbox/run_suite.py
python3 tests/blackbox/run_p0_dual_brain.py
```

### Important Files

`tests/blackbox/run_*.py`、`cases.md`、`report.md`；[docs/testing/xcuitest.md](../testing/xcuitest.md)

### Runtime Behavior

默认打 `http://127.0.0.1:9527`。无根 Makefile。

### Tests

本模块就是测试。

### Modification Risk

（产品代码）N/A。改用例本身 Medium。

### Notes

修复须验收：实现方报完工后必须经 `@quality`，不得自报结案。
