# PROJECT

读完本页，应能在几十秒内回答：我进了什么项目、它为什么存在、现在做到哪。

## 名称

**Home Agent OS**

本地目录仍叫 `smart_home_control`。远程仓库：[`kaulie/home-agent-os`](https://github.com/kaulie/home-agent-os)。

## 目标

在异构家庭设备上，把一次家务贯通 **感知 → 理解 → 规划 → 执行**。

家庭不是单一 App 的闭环，而是手机、电视 / Chromecast、相机、Mac、扬声器等互不相同的端。本项目要解决的是这类场景里的端到端闭环，而不是再做一个智能家居控制面板。

## 解决的问题

1. **异构**：多设备、多能力、多网络形态并存。Edge 按真实能力注册，Brain 按在线能力选人。
2. **四层贯通**：不只下发一条指令，而是覆盖 Sense / Understand / Plan / Act。
3. **统一协议**：Edge 上报 `services[] → capabilities[]`；Brain 下发带每步 `assigned_edge_id` 的 `execution_plan`。

## 核心用户

| 谁 | 用什么 | 做什么 |
|----|--------|--------|
| 家里的人 | User Console（iPhone / Android） | 用自然语言下家务：拍照、投屏、报时、开灯、问内容 |
| 现场管理者 | HomeAgent Admin | 看节点、角色、运行态 |
| 开发者 | HomeAgent Dev + Agent Chatbox + Fleet | 派开发任务、看调试、验收、上线 |

页面发件人是 `@boss`，不是 Fleet handle。

## 当前阶段

客厅可用闭环已落地：发 intent → Brain 规划 → 多 Edge 分步执行 → `intent_detail.presentation` 回到发出端 / Endpoint。

仍是演进中的系统，不是冻结架构：

- Brain 生产入口仍是单体 [`server/home_brain.py`](../../server/home_brain.py)（约 8k 行）。拆分方案在 [docs/architecture/brain-simplification-plan.md](../architecture/brain-simplification-plan.md)，**规划-only，未开工**。
- 双 Brain（LAN `:9527` + Cloud `:9527`）已作为 Runtime 基线。
- Asset 以 `asset_id` 为身份；跨节点复制与完整 Asset Manager 仍在落地中。
- Entity Registry 一期已有 API；**尚未喂给 planner**。

## 核心能力（产品主路径）

| 层 | 典型能力 |
|----|----------|
| 感知 | `camera.capture`、语音入口、文档扫描、直播 ingest |
| 理解 / 规划 | `POST /api/v1/intent` → planner → `execution_plan` |
| 执行 | `display.photo` / `display.slideshow`、`notify.speak`、`light.set`、`music.*`、`climate.set` |
| 控制面（Brain 就地） | `clock.now`、`image.ocr`、`capabilities.summary`、`asset.inventory`（`kind=system`） |

## 核心设计原则

1. **Participant + Role + Contract**，不是以设备类型为中心。四种正交 Role：Intent Source / Runtime Agent / Endpoint / Observer。详见 [docs/participant-model.md](../participant-model.md)。
2. **Brain 只理解与规划**。模型密钥与设备执行在 Edge。例外：`kind=system` 控制面能力由 Brain 就地执行，不绑 Runtime。
3. **每步一个 `assigned_edge_id`**。某步无在线节点具备该 capability → 入队失败（system 步除外）。
4. **Capability 只看本步已 resolve 的入参**。禁止从前序 step / `step_outputs` 自己去捡。
5. **Vision / LLM 原始 JSON 即为契约**。结构不对就失败，禁止拆包兜底。
6. **用户可见结果由 Brain `intent_detail.presentation` 交付**。`notify.speak` 仅纯提醒或 voice TTS 钩；投电视仍走 `display.*`。

## 两套系统，不要混

本仓库里有两套并行系统。改代码前先分清自己在哪一套。

**产品运行时（家里真正干活的）：**

```text
User → Intent Source → Brain :9527 → Edge Runtime → Capability → Device / Endpoint
```

**开发协调（Cursor Fleet，不是产品路径）：**

```text
@boss / Dev Console → Chatbox :8787 → @controller → agent-bridge :9540 → Fleet workers
```

Fleet handle（`@brain` `@runtime` `@ui` …）是**写代码的人**，不是家里的 Runtime Agent。产品 Role **Observer** ≠ Cursor `@coordinator`。

## 当前主要工作方向

- 保持客厅闭环可验收：失败有 `msg`、成功有 presentation / 产出。
- Brain 单体可维护性（拆分尚未开工）。
- Asset / Presentation 契约收口（禁止 path / 永久 URL 当身份）。
- 发布链路：commit → 测试 → 部署，Chatbox `[release]` 留痕。

## 仓库结构（一层）

| 路径 | 是什么 |
|------|--------|
| `server/` | Brain |
| `mac/` | Mac Edge + mac_voice |
| `ios/` | User / Admin / Dev / Pickup 等 App |
| `android/` | Android Console + Edge |
| `plugins/` | Capability 契约（及部分端实现） |
| `admin/` | 本机 Business Admin HTML（不上云） |
| `chat/` | Agent Chatbox |
| `agent-bridge/` | Fleet HTTP bridge |
| `img-server/` `ocr-service/` `character-service/` | 照片 / OCR / 指字 sidecar |
| `tests/blackbox/` | 对外 API 黑盒 |
| `docs/` | 架构与协调文档 |
| `config/endpoints.json` | LAN/Cloud 地址权威源 |
