# FINDINGS

Project Map 建立时的考察结论（2026-09-03）。地图正文已尽量按**代码**书写；本页集中放不一致、未知、架构债和导航验收，避免把推测写进 ARCHITECTURE。

## 项目认知总结

Home Agent OS 是「异构家庭设备上的 感知→理解→规划→执行」运行时。生产控制面是 Brain `:9527`（LAN + Cloud 各一进程）。执行在 Edge（Mac 为主，iPhone/Android 带有限 Runtime）。用户结果走 `intent_detail.presentation`。

同一仓库里还有第二套系统：Chatbox `:8787` + agent-bridge `:9540` + Fleet。那是写代码的人，不是家里的 Runtime。

新 Agent 最短路径： [README.md](README.md) → [PROJECT.md](PROJECT.md) → [MODULES.md](MODULES.md) 文首表 → [BOUNDARIES.md](BOUNDARIES.md) → 打开表里的文件。

## 发现的架构问题

1. **`home_brain.py` 单体过大**（约 8k 行 / 66 路由），家务控制面与 Dev Admin / asset 代理 / 遗留 skill 同文件。已有拆分方案，未开工。见 [docs/architecture/brain-simplification-plan.md](../architecture/brain-simplification-plan.md)。
2. **Entity Registry 未进 planner**。一期 Device API 存在；规划仍只看 capability catalog。见 [docs/entity-model.md](../entity-model.md)。
3. **Asset 跨节点复制未完成**。契约要求 `asset_id`；Cast/img-server 仍用临时 URL 做传输。设计超前于实现。
4. **Cast `:9095` 进程来源不清**。环境变量与拓扑提到该口，仓库无启动脚本。主路径已是 iPhone Cast Sender。
5. **`clock.now` 双路径**：Brain `kind=system` 与 Mac plugin 同时存在。Planner 优先 system 边，但 Mac 仍广告，容易让 Agent 改错文件。
6. **Intent 状态枚举文档滞后**（见 CONFLICT）。运行中的 scheduler 名与 schema 表不一致，排障时会对不上。

## 文档与代码不一致（CONFLICT）

以代码为准。下列是建立地图时核对过的：

| # | 文档怎么说 | 代码 / 权威配置怎么说 |
|---|------------|------------------------|
| 1 | 根 README：iPhone「非 Edge，只 POST intent」 | [ios/README.md](../../ios/README.md) 与 `IntentClient.swift`：Intent Source + Endpoint + Runtime（`camera.capture` / `light.set`） |
| 2 | 根 README：`android/app-v2` 是主 Chromecast Edge | 当前文档主路径是 `living-room-android`；Cast 主路径是 iPhone Sender。`app-v2` 是否仍现场生产 → UNKNOWN |
| 3 | [docs/db-schema.md](../db-schema.md) §5.1：`scheduled` / `assigned` | Mac `scheduler.py` 上报 `intent_scheduled` / `intent_dispatched` |
| 4 | `.cursor/rules/*` 写 `BRIDGE_AUTH_TOKEN` | `agent-bridge` / Brain 代码与 `.env.example` 为 `AGENT_BRIDGE_TOKEN` |
| 5 | `server/README.md`：admin 默认代理云 Brain | `admin/serve.py` 默认 `http://127.0.0.1:9527` |
| 6 | 部分旧文 / ATS 曾写死家用 IP | `config/endpoints.json` 与 topology：mDNS 名；ATS 走 `NSAllowsLocalNetworking` |
| 7 | [docs/ops/service-stability-observability.md](../ops/service-stability-observability.md)：local-rt `:8081` | `local-rt/run_llama.sh` 默认 `:8082` |
| 8 | 可观测性把 Cast `:9095` 联到 HomeAgentRelay | `ios/HomeAgentRelay` 听 `:8080` / `:8081`（热点实验），不是 `:9095` |
| 9 | `clock.now` 作为 system cap 叙述 | Mac `services.py` 仍广告 `clock.now`，plugin 仍实现 |

根 README 的能力一览表同样偏旧（未反映 iPhone 有限 Runtime、双 Brain、presentation 契约）。本次只在文档索引加了 Project Map 入口，**没有**重写整份根 README。

## UNKNOWN

无法从本仓库代码/配置确认，禁止当成事实：

- 如何启动 Mac Cast HTTP `:9095`（无脚本）。
- 云上 `doubao_skill` unit 文件全文（仓库没有；仅知 WorkingDirectory / ExecStart / restart 命令）。
- `scripts/ops/` 与端口 `:8799`：可观测性文档提到，目录不存在 → 按未落地处理。
- `android/app` 与 `app-v2` 是否仍为现场生产安装包。
- LivingRoomEdge 是否有独立 XCUITest target（自动化文档主写 HomeAgentDev）。
- `admin/` 是否有自动化测试。
- 全量 `server/tests` 的「官方一条命令」——测试文件存在，README 没有单一 target；地图写的是 `unittest discover` 推断模式。

## 导航验收

模拟新 Agent「我要改 X」，用地图应能落到：模块 → 文件 → 边界 → 测试。

### 1. heartbeat timeout 应该在哪里修改？

| 步 | 地图给出的答案 |
|----|----------------|
| 模块 | Brain 控制面 |
| 文件 | `server/home_brain.py` `ONLINE_TTL_SEC = 60`；各端 heartbeat 周期（iOS README ~45s） |
| 边界 | `@brain`；不要改 plugin |
| 测试 | `server/tests/test_home_brain.py` TTL 用例 |
| 验证 | 过期后 capability map 不再选该边；Edge 日志 heartbeat |

**结论：** 能定位。入口：[MODULES.md](MODULES.md) 文首表第一行。

### 2. 「现在几点了」规划规则改哪？

| 步 | 答案 |
|----|------|
| 模块 | Planner |
| 文件 | **只** `server/prompts/task_planner_system_prompt.md.en`；确定性捷径 `server/shortcut_mode/rules.py` |
| 边界 | 禁止在 `home_brain.py` 内联规划长文；执行读钟是 `system_capabilities.py`（及 Mac 双路径） |
| 测试 | `test_shortcut_mode.py`、`test_system_capabilities.py` |
| 验证 | 新 intent 的 plan 为 `clock.now`，不是 `query.content` |

**结论：** 能定位。注意 CONFLICT：改「读钟实现」不要只改 Mac plugin。

### 3. `display.slideshow` 缺 `photo_urls` / 图列表

| 步 | 答案 |
|----|------|
| 模块 | Capability 契约 + Mac/Cast plugin |
| 文件 | `plugins/chromecast-display/capability.md`（必填 `asset_refs`）；`mac/src/mac_edge/plugins/chromecast_display.py` |
| 边界 | `@capability`；禁止从前序 `camera.capture` 拼列表；Runtime 才 hydrate |
| 测试 | `mac/tests/test_capability_asset_refs.py` |
| 验证 | 缺 `asset_refs` 本步失败且有 `msg` |

**结论：** 能定位。契约已不用 `photo_urls` 当身份；若 Task 仍写 photo_urls，先读契约再改。

### 4. iPhone 聊天窗物流 UI

| 步 | 答案 |
|----|------|
| 模块 | iOS Console |
| 文件 | `ios/LivingRoomEdge/.../Intent/IntentLogisticsTimelineView.swift`、`App/ContentView.swift` |
| 边界 | `@ui`；不要改 Brain 组装 presentation 的算法（除非物流字段缺失来自 Brain） |
| 测试 | 真机点「进度」；HomeAgentDev XCUITest 不一定覆盖 Console |
| 验证 | 气泡下物流与 `intent_detail` 一致 |

**结论：** 能定位。

### 5. 云 Brain 怎么发一版

| 步 | 答案 |
|----|------|
| 模块 | 部署，不是功能模块 |
| 文件 | `.cursor/rules/cloud-deploy.mdc`、[RUNTIME.md](RUNTIME.md) |
| 边界 | `@deploy`；须 sha；禁止 rsync `db.py`/`sql/`/`data/`/`admin/` |
| 测试 | 先 `[release] stage=tested` |
| 验证 | `ssh cloud-server` health + `agent_access.log` 同行 sha |

**结论：** 能定位。

以上五问均能从地图落到文件。若以后某问对不上，改 MODULES 文首表，而不是加长百科。

## 建议后续补充的认知（本次不做）

1. 核对并更新根 README 能力一览（iPhone Runtime、双 Brain、presentation）。
2. 统一 token 名：规则改为 `AGENT_BRIDGE_TOKEN`，或代码同时认旧名。
3. 对齐 db-schema §5.1 与 Mac scheduler 状态名。
4. 写清 `:9095` 是遗留并删除死引用，或补启动脚本。
5. 标明 `android/app` / `app-v2` 生产状态。
6. 补 `clock.now` 单路径（只 system 或只 Edge）。
7. 若希望 Agent 强制走地图：再加 `.cursor/rules` 启动协议（本次明确不加）。
8. 可观测性 `:8799` / `scripts/ops/`：要么落地，要么从文档删除。
