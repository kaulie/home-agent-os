# Living Room Control v2 (Edge Agent + Skill)

独立 APK：`applicationId = com.smarthome.livingroom_v2`（`versionName` 见 `build.gradle.kts`）。  
**不修改** 旧 module `:app`（`com.smarthome.livingroom`）。

能力心跳协议（与 Mac / iPhone / Console 对齐）：每个 capability 发  
`kind` / `role` / `planner_recognize` / `typical_triggers[]` / `do_not_dispatch[]` + schema；  
`description` 可选，不是规划契约。源：`plugins/netease-music/android` + `EdgeJson.encodeCapabilities`。

注册 / 心跳同时声明 Participant 角色（默认 `runtime` + `endpoint`）：`roles[]`、`role_*`、`intent_sources[]`（本机为空）、`endpoints[]`（`chromecast.display`，`supported_presentation=image,text,video`）、`participant_id`。  
**不**广告 `display.photo` 为 Runtime capability（投屏由 iPhone Cast Sender 执行）；本机只广告已安装的 `netease.music`。

## 五层架构

| 层 | 名称 | 本期状态 |
|----|------|----------|
| 1 | Intent（语音/文本/定时/事件） | 未做，后续 |
| 2 | AI Brain（中控大脑） | `CompositeBrainClient`：Http register/heartbeat（无本地 Plan 队列） |
| 3 | Service / Capability | `ServiceDescriptor` → `CapabilityDescriptor`（含 schema） |
| 4 | Edge Agent Runtime | register → heartbeat → **CommandHandler** → Skill |
| 5 | Skill | **SPI +** 插件 `plugins/netease-music/android`（`netease.music`）；`display.photo` 在 **iPhone Cast Sender**，本机不安装 |

```text
【标准意图管线】
GET /devices/living-room/intents?intent_status=intent_parsed
        │  expand execution_plan → Command[] + intent_id
        ▼
 CommandHandler → Scheduler → intent_status 上报 → LocalEdgeRuntime → Skill.execute(capabilityId)

【本地单点调试】（搜歌 / 播控等）
 UI 按钮 → EdgeAgent.invokeLocalSkillAction → Skill.execute(capabilityId)
        （不经 CommandHandler，不上报 intent_status）
```

与 iOS 意图窗口共用 intents / `execution_plan` / `intent_status` 契约。**无本地 Mock Plan**；本地按钮与意图下发是两条独立路径。

心跳 / 注册 body 含 `services[]` + Participant 字段（`roles` / `intent_sources` / `endpoints` / `participant_id`），不再发顶层 `skills` / 扁平 `capabilities`。

## 包结构

```text
com.smarthome.livingroom_v2
  app/           Application + 调试 MainActivity
  data/          AppSettings、EdgeIdStore
  service/       EdgeAgentController + EdgeAgentService + BootCompletedReceiver
  command/       CommandHandler、HttpCommandSource、IntentStatusClient、Scheduler、Dispatcher、LocalEdgeRuntime
  edge/          EdgeAgent, SkillRegistry, PlanExecutor
  brain/         BrainClient, HttpEdgeReporter, CompositeBrainClient, MockBrainClient, dto/
  skill/         Skill SPI + music / speaker
  capability/    Capabilities 常量
```

## Command 管线（对齐 iOS）

- 拉取 URL：`BuildConfig.DEFAULT_COMMANDS_PULL_URL`  
  `http://192.168.3.73:9527/api/v1/devices/living-room/intents?intent_status=intent_parsed`
- 响应：`{ "intents": [ { "id", "status", "execution_plan": [{ "capability", "step" }] } ] }`  
  → 展开为带 `intent_id` 的 `Command[]`（兼容旧 `{ "commands": [...] }`）
- Agent 每个 tick：heartbeat → **拉服务器 intents** → CommandHandler（标准意图管线）  
- Instant：立刻 dispatch；Cron/Event：可 `schedule`/`cancel`/`debugFire` 骨架  
  **生产意图调度**走 `execution_plan[].execution_timing`（`immediate` / `delay` / `interval` / `cron`+`cron_expr`），由 `IntentPipeline` + `ExecutionTimingGate` 门控，不是旧 `ScheduleSpec.Cron` 骨架。
- intent 状态上报：`POST /api/v1/intent/<id>/status`（`IntentStatusClient`，base=`DEFAULT_INTENT_URL`）  
  阶段：`hub_received` → `scheduled` → `assigned` → `running` → `succeeded`/`failed`  
  Chromecast 收到非本机安装 capability（如 `camera.*` / `display.photo`）会 skip 并上报 `failed`；已安装：`music.*`
- **本地单点**：Skill 面板按 `service.capabilities` 渲染 → `invokeLocalSkillAction` → 直调 Skill（搜歌/播控调试，不进意图管线）
- 日志关键字（意图）：`Command received` → `Task decomposed` → `Scheduled` → `Dispatched` → `Executed`  
  日志关键字（本地）：`LocalAction …` → `LocalAction done`

## Edge → Brain（对齐 iOS / Console）

1. 本地无 `edge_id` → `POST /api/v1/edge-register`（`client_hint=living-room-chromecast`，roles=`runtime`+`endpoint`）  
2. Brain 签发 `edge_id`（= `participant_id`）→ 写入本地（`EdgeIdStore`），以后启动复用、**不再重复 register**  
3. 每 **15 秒** `POST /api/v1/edge-heartbeat`（必须带已签发 id + `participant_id` + `endpoints`；同 tick 拉 intents）  
4. 调试 Skill：UI 按钮走 `invokeLocalSkillAction`（单点，非意图管线）；业务任务靠真服 intents 拉取 

默认服务器：`http://192.168.3.73:9527`（`BuildConfig.DEFAULT_BRAIN_BASE_URL`）。

调试：UI「清除本地 edgeId」可强制下次重新 register。

## 后台 Agent（服务优先）

Agent 以 `EdgeAgentService`（前台通知保活）在后台持续 register/heartbeat。  
MainActivity 的 **启动 / 停止** 只是对后台服务的干预，不是生命周期本体。

| 状态 | 行为 |
|------|------|
| 勾选「开机自启并后台持续运行」 | 立刻后台启动；开机拉起；**进程被杀后重新创建也会按勾选恢复轮询** |
| 点「启动 Agent」 | 本次进程起服务（不改变开机自启勾选） |
| 点「停止 Agent」 | **仅本次进程**停轮询；**不取消**开机自启勾选；进程仍存活时不会因 onResume 自动再起 |
| 取消勾选开机自启 | 只影响开机 / 下次进程重建；不自动停当前会话 |
| 停止后进程被杀再拉起 | 看开机自启是否勾选：勾选 → 恢复轮询；未勾选 → 保持停止 |

**不会**因开机自启打开调试全屏 UI；通知栏常驻，点击可打开 App。

步骤：

1. Sideload 安装 `app-v2`，完成系统引导后 **手动打开一次** App  
2. 勾选 **开机自启并后台持续运行**（或点启动；Android 13+ 需通知权限）  
3. 离开 UI：后台继续 15s 心跳 / intents 拉取  
4. 重启 Chromecast：仍勾选则自动拉起；未勾选则不自启  
5. 需要停时点 **停止 Agent**  

已知限制：部分机顶盒可能限制自启动；需 sideload 且完成引导，非「替换系统 Launcher」。

## 本地验证

```bash
cd android
# Android Studio: Run configuration → app-v2
```

1. 打开「客厅中控 v2」  
2. 点 **启动 Agent** → 日志应出现 register / heartbeat（或复用本地 edge_id）  
3. 服务端 `GET /api/v1/edges` 可见在线（TTL 内）  
4. 真服入队 intent 后，tick 应出现 `Pulled N server intent step(s)` + CommandHandler 日志  
5. UI Skill 按钮 = 本地单点 LocalAction（日志前缀 `LocalAction`），与意图拉取无关  

## 本期边界

- 网易云：`API 搜歌 → 手机版深链 → 媒体键`（**无障碍不做**）  
- 注册 service：**仅** `netease.music`（group=`music`，caps=`music.play|pause|stop|next|previous`，`kind=action`）；Marshall 定义保留但不 install  
- 角色：`runtime` + `endpoint`；广告 `chromecast.display`（image/text/video）。**不**广告 `display.photo`  
- 意图拉取 / status 上报已接真服；无本地 Mock Plan 队列  
