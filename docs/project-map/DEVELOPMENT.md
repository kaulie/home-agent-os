# DEVELOPMENT

Agent 改代码之前必须知道这些。细节以链过去的规范为准，这里只列「会踩坑」的条目。

## 先读地图，再读代码

顺序见 [README.md](README.md) 启动协议。地图给方向，代码确认事实。

## 层隔离 + 单 WIP

[`.cursor/rules/agent-wip-discipline.mdc`](../../.cursor/rules/agent-wip-discipline.mdc)

- 只改本 handle 职责范围内的路径。越层 `push_msg` 转交，禁止顺手改。
- 同一时间只有一个进行中需求。未写完先写完并提交；新需求进 pending 并通知 `@controller` / `@boss`。
- 禁止为赶新需求覆盖未提交半成品。

可写范围：[BOUNDARIES.md](BOUNDARIES.md)。Handle 名册：[docs/agent-roster.md](../agent-roster.md)。

## 目录与契约

| 规则 | 位置 |
|------|------|
| Planner 规则只改 md | `.cursor/rules/planner-prompt-source.mdc` |
| Plugin 只看本步入参 | `.cursor/rules/capability-independent.mdc` |
| Vision/LLM 禁止兜底 | `.cursor/rules/vision-llm-no-fallback.mdc` |
| 文档用标准 Markdown | `.cursor/rules/docs-markdown.mdc` |
| 地址先改 `config/endpoints.json` 再 sync | `config/README.md` |

共享高风险文件（如 `mac/src/mac_voice/listen.py`）：只改本任务验收所需最小点。

Plan 落盘：确定执行前写到 `agent_plans/<name>_v<N>.md`（[AGENT_README.md](../../AGENT_README.md)）。升版本另存，不覆盖旧文件。

## Commit

[docs/git-commit-convention.md](../git-commit-convention.md)

```text
<type>(<scope>): <summary>

agent: <handle>
```

- 安装 hook：`bash scripts/git/install-hooks.sh`
- `scope` 必须对上暂存区 primary 目录
- `agent:` 必填，无 `@`
- 一次故意跨多个 primary 时加 `Scopes: a, b`

不要提交 `.env`、密钥、`agent_access.log`、本机 DB。

## 发布链路

[`.cursor/rules/release-pipeline.mdc`](../../.cursor/rules/release-pipeline.mdc)

产品代码：实现 → git 提交（拿到 sha）→ 测试 → 部署。未提交 = 未交付。缺节点不要对用户报「已上线」。

每完成一节点 Chatbox `[release]`，`@controller`，按需 `@quality` / `@deploy`。

`stage`：`committed` | `test_requested` | `tested` | `deploy_requested` | `deployed` | `skipped`（须说明为何跳过，如仅 docs）。

## 测试要求

- 对外行为变更必须 `@quality` 验收，更新 `tests/blackbox/` 或 UI 测试报告。不得自报结案。
- Brain 单测常设 `BRAIN_SKIP_LLM_WORKER=1`。
- 黑盒默认打本机 `:9527`；缺 `participant_id` 会 400。
- 命令见 [RUNTIME.md](RUNTIME.md)。没有「一条 make test 跑完全仓」。

## 部署规范

云 Brain 只由 `@deploy` 在可追溯 sha 且测试通过后 rsync。禁止把工作区当正式上线。排除名单见 [RUNTIME.md](RUNTIME.md) / `cloud-deploy.mdc`。

`admin/` 只在本机 `python3 admin/serve.py`，不上云。

## Debug

- 意图物流：`GET /api/v1/intent_detail`、`jobs.msg`、`step_log`
- Brain：`llm_logs/brain.log`
- Edge：心跳、`mac/data/mac_edge.out`
- 规划问题先改 prompt，不要先改 executor
- Dev Console / debug gateway：[docs/architecture/three-consoles-debug-gateway.md](../architecture/three-consoles-debug-gateway.md)

## 协调（改代码的人仍要会）

- 协调只走 Chatbox `http://127.0.0.1:8787/`，不进别人的 Cursor 会话。
- 每次 pull 前读一遍 [docs/agent-coordination.md](../agent-coordination.md)。
- 正式 `@`：先 `[status]` 再 ✅ 收到。`cc @`：只 👌 知道了。
- 结案用 `cc @coordinator`，不要正式 `@` 互刷。
- `@controller` 是唯一常驻 IDE；不要为 `@ui` / `@brain` 让用户再开 IDE。

## 改完是否更新 Project Map

本次代码变更是否改变项目认知？

- 否 → 不动 Map
- 架构变 → [ARCHITECTURE.md](ARCHITECTURE.md)
- 模块职责变 → [MODULES.md](MODULES.md)
- 运行方式变 → [RUNTIME.md](RUNTIME.md)
- 权限/边界变 → [BOUNDARIES.md](BOUNDARIES.md)
- 结构性变化 → 追加 [CHANGELOG.md](CHANGELOG.md)
