# Agent Fleet 名册

本文件是 **Cursor handle 与职责** 的快速索引。协调协议见 [`agent-coordination.md`](agent-coordination.md)；产品分层见 [`participant-model.md`](participant-model.md)。

## 运行模式（定稿）

| 组件 | 数量 | 说明 |
|------|------|------|
| **IDE** | **1** | 标题 `dev controller agent`（`@controller`）；用户对话、hook、任务编排 |
| **Fleet workers** | **10 handle** | `cursor-agent` CLI 池；每 handle 独立 `agent_id`（`agent-bridge/data/agents/{handle}.json`） |
| **Chatbox** | 1 | `http://127.0.0.1:8787/` |
| **agent-bridge** | 1 | `http://127.0.0.1:9540/` |

**不要**为 `@brain`、`@ui` 等另开 IDE 窗口。需要专员时由 `@controller` 调用 `POST /api/v1/agents/{handle}/wake`。

## Handle 表

| 全称（Fleet / 可选 IDE 标题） | handle | 职责 |
|------|--------|------|
| system coordinator agent | `@coordinator` | 协调、仲裁、催办、架构/需求/文档汇总、质检看板。不写产品代码。 |
| dev controller agent | `@controller` | **唯一常驻 IDE**；分析任务、wake Fleet、汇总进度；手机 Dev Task 入口。 |
| brain agent | `@brain` | 规划、选边、入队、对外 Brain API；`server/home_brain.py`、`server/prompts/`。 |
| runtime dev agent | `@runtime` | 调度 / hydrate / 前序门；失败 `msg`；Mac/Android edge runtime。 |
| UI dev agent | `@ui` | **全部用户交互面**：Intent 发出窗口、物流 UI、Endpoint/Cast 呈现、Receiver、管理端 UI。 |
| capability dev agent | `@capability` | Plugin 契约与实现（非 UI 呈现面）。 |
| quality agent | `@quality` | 黑盒验收：对外 API（`tests/blackbox/`）+ **App UI 自动化验收**（先 XCUITest，后可扩展 Maestro）。不改产品功能代码；可为验收加 `accessibilityIdentifier` 时须 `@ui` 知情或由 `@ui` 补。 |
| deploy agent | `@deploy` | 云 Brain 部署（rsync + restart）；须带 git sha；见 `cloud-deploy.mdc` / `release-pipeline.mdc`。 |
| sre agent | `@sre` | 本机/边缘运维、双 Brain、local-rt、架构 runbook。 |
| dba agent | `@dba` | schema / SQL（Brain SQLite；Edge JSON 未经点名不改）。 |

页面发件人是 `@boss`（不是 Fleet handle）。`@owner` / `@user` 视为 `@boss`。

## 别名（Chatbox 解析）

| 写法 | 映射 |
|------|------|
| `@intent` | `@ui` |
| `@endpoint` | `@ui` |
| `@observer` | `@coordinator` |

历史会话标题 `Intent dev agent`、`endpoint agent` 已合并为 **UI dev agent** / `@ui`。

## 派单口诀

| 事项 | handle |
|------|--------|
| Plugin / capability 契约 | `@capability` |
| 调度 / hydrate / 前序门 / 失败 msg | `@runtime` |
| 发出窗口 / 物流 UI / Cast / Receiver / 端上交互 | `@ui` |
| 规划 / 选边 / 入队 / Brain API | `@brain` |
| 黑盒 API / App UI 自动化验收 | `@quality` |
| 云部署 | `@deploy` |
| 运维 / 本机服务 | `@sre` |
| schema / 迁移 | `@dba` |
| 跨层争议 / 催办 | `@coordinator` |

## agent-bridge API（摘要）

```bash
# 列出 Fleet 状态
curl -s -H "Authorization: Bearer $BRIDGE_TOKEN" http://127.0.0.1:9540/api/v1/agents

# 唤醒专员
curl -s -X POST -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text":"修复 planner 选边"}' \
  http://127.0.0.1:9540/api/v1/agents/brain/wake
```

Dev Task 带 `target_handle` 时 bridge 直接 wake 对应 worker；进度推 Chatbox：`@controller [dev-task]` 或 `@controller [fleet] handle=…`。产品改动另推 `[release]` 节点（commit → test → deploy），见 [`.cursor/rules/release-pipeline.mdc`](../.cursor/rules/release-pipeline.mdc)。

**层隔离 + 单 WIP：** 不写非本层代码；未提交完当前需求前，新需求进 pending 并上报 `@controller`/`@boss`。见 [`.cursor/rules/agent-wip-discipline.mdc`](../.cursor/rules/agent-wip-discipline.mdc)。

## 日报

每天 23:00 前（UTC+8）各 handle `@coordinator` 交日报。汇总：[`daily-reports.md`](daily-reports.md)。列含 `controller`、`deploy`、`sre`。
