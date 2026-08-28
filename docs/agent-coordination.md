# Agent 协调规范

团队 agent **不进对方的 Cursor 会话**。协调只通过本机 **Agent Chatbox**（HTTP + SQLite）。本文件是约定；实现见 [`chat/`](../chat/)。

**每次 pull 之前，先完整读一遍本文件**，不要凭记忆。

## 1. Chat server

```text
http://127.0.0.1:8787/
```

本机启动：`python3 chat/serve.py`（`CHAT_HOST` / `CHAT_PORT` / `CHAT_DB_PATH` 可改）。库文件 `chat/data/agent_chat.sqlite3`，**不是** Brain 的 `server/data/brain.sqlite3`。

| 接口 | 谁用 | 作用 |
|------|------|------|
| `GET /` | 用户浏览器 | 管理页：看全员对话、派活。每 5 秒刷新。 |
| `POST /api/v1/push_msg` | 用户页面 / 任意 agent | JSON `{from, body}` 发一条。服务器解析正文里的 `@handle`。 |
| `GET /api/v1/pull_msg?handle=brain&since_id=0` | agent | 公共消息 + **@自己**。成功后推进水位，并把本批可见消息标为该 handle **已读**。 |
| `GET /api/v1/messages?since_id=0` | 仅页面 | 时间线全量，含 `read` / `unread`。不推进 agent 水位、不自动已读。 |
| `POST /api/v1/mark_read` | 页面 / agent | JSON `{from, ids}` 把指定消息标为已读。页面打开后会把 @boss 未读标掉。 |
| `POST /api/v1/recall_msg` | 发件人 | JSON `{from, id}`。发出 **1 分钟内**且 **除自己外无人已读** 才能撤回。成功后正文清空，pull 不再返回。 |

旧 Markdown 信箱 [`docs/agent-mailbox.md`](agent-mailbox.md) **已停用**，不要再追加、不要再加文件锁。

## 2. Handle 与 Fleet

**运行模式（定稿）：** 只维护 **1 个 Cursor IDE**（标题 `dev controller agent` / `@controller`）。其余 handle 由 **agent-bridge Fleet**（`cursor-agent` CLI）headless 唤醒，每 handle 独立会话状态。名册见 [`docs/agent-roster.md`](agent-roster.md)。

Cursor **会话标题**（Fleet worker 或历史 IDE）须与下表「全称」一致。对外只写短名 `@handle`。不要用已废弃全称：`Intent dev agent`、`endpoint agent`、`intent source dev agent`、`home agent testing agent`、`质检员`、`system observer agent`。

| 全称（会话标题） | handle | 职责 |
|------|--------|------|
| system coordinator agent | `@coordinator` | 协调、仲裁、催办、架构/需求/文档汇总、质检看板。不写产品代码。用户交代的越界事项 `@` 到对应 handle。其他 agent 的预期外情况 `@coordinator`。旧称 `@observer` 仅历史信箱有效；chat 里 `@observer` 视为 `@coordinator`。 |
| dev controller agent | `@controller` | **唯一常驻 IDE**；分析任务、调用 bridge wake Fleet、汇总进度；手机 Dev Task 入口。见 `.cursor/rules/controller-orchestration.mdc`。 |
| brain agent | `@brain` | 组件注册（Edge `services[]`/`capabilities[]`）；意图 / 事件 / 定时路由；选边、`execution_timing`、每步 `assigned_edge_id`；对外 API。入口 `server/home_brain.py`。规划与控制面。不改 plugin / 发出 UI / 未经点名的 schema。 |
| runtime dev agent | `@runtime` | 调度 / hydrate / 前序门；失败 `msg` |
| UI dev agent | `@ui` | **全部用户交互面**：发出窗口与物流 UI（产品层仍叫 Intent Source）、Endpoint/Cast 呈现、Chromecast Receiver、管理端/Dev 端用户可见 UI。合并原 `@intent` + `@endpoint`。 |
| capability dev agent | `@capability` | Plugin 契约与实现（非 UI 呈现面） |
| quality agent | `@quality` | 黑盒：只打对外 API，不改代码 |
| deploy agent | `@deploy` | 云 Brain 部署（rsync + restart）；见 `cloud-deploy.mdc` |
| sre agent | `@sre` | 本机/边缘运维、双 Brain、local-rt、架构 runbook |
| dba agent | `@dba` | schema / SQL。Brain 一期 SQLite：`server/data/brain.sqlite3`。Edge JSON 未经用户点名不要改。 |

**Chatbox 别名：** `@intent` → `@ui`；`@endpoint` → `@ui`。

未列入上表不得自造 handle。要加人，由 `@coordinator` 改本表、`chat/mentions.py` 与 [`docs/agent-roster.md`](agent-roster.md)。

页面发件人是 `@boss`（不是 Cursor handle）。旧称 `@owner` / `@user` 视为 `@boss`。

架构参与者模型（与上表 Cursor handle 分开）：[`docs/participant-model.md`](participant-model.md)。文中 Role **Observer** 是系统事件消费者，不是本表 `@coordinator`。

Asset 公约（资源层，未点名不改代码）：[`docs/asset-contract.md`](asset-contract.md)。Capability 传 `asset_id`，不传 path/永久 URL；存储与授权归 Runtime Asset Manager。

产品层「Intent Source」≠ agent 名。实现者是 **UI dev agent** / `@ui`（`@intent` 为别名）。

## 3. 水位

每个 agent 在库里有 `last_pull_id`。`pull_msg` 只返回 `id` 大于 `max(since_id, last_pull_id)` 且受众包含自己或 `@all` 的消息，然后把水位推到当前库最大 `id`（没有可见消息也推进，表示已巡过）。本批真正返回的消息对该 handle 记 **已读**。

每条消息按接收人记已读/未读：派给谁谁未读，直到对方 `pull_msg` 或 `mark_read`。`@boss` 的未读由页面打开后 `mark_read` 清除。侧栏数字是该 agent 还没读的条数。发件人可在 **1 分钟内**撤回，前提是除自己外无人已读；撤回后原文清空，`pull_msg` 不再返回。

不要自己改别人的水位。`GET /api/v1/messages` 给页面用，不改 agent 已读。

## 4. 消息与 @ 规则

传统对话：一条就是一段正文，可多行。用正文里的 `@handle` 指定接收人，不再使用 Tab 六字段、ack 分子分母、主题 `收到`。

| 写法 | 谁该处理 |
|------|----------|
| 用户未 @ 任何人 | **agent 不处理**（页面仍显示，当笔记） |
| `@brain 去看 intent 71` | 仅 `@brain` 的 `pull_msg` 能拿到 |
| `@brain @intent …` | 列出的每一个 |
| `@all` / `@所有人` / `@everyone` | 全部已注册 agent |
| agent 发言且未 @ | 公共房间消息，所有 agent 都能 pull 到 |

`from` 必须是自己的 handle（或页面的 `@boss`）。不要写 `@dev`、`@testing` 等未登记名；非法 @ 会被忽略。

回复就是再 `push_msg` 一条，并 `@` 对方。不要再写 ack 列。

## 5. 轮询（每 30 分钟 pull；禁止五分钟空转）

**pull 仍是每 30 分钟一次**（有急事可随时多 pull）。**禁止**五分钟空转心跳（`sleep 300`）。`@coordinator` 用 **30 分钟** wake 做完整 pull，不是空过。其他 agent 有工作、做完一件、或用户来信时再 pull；不要为保活每 5 分钟叫醒会话。**页面**每 5 秒刷新只给用户看，agent 不要学这个间隔。

**每次 pull 之前，先完整读一遍本文件。**

**到点时若手头有未完成的具体工作：先做完这一件，再读约定、再 pull 并回复。** 超过 **1 小时** 仍无 `last_seen_at` 更新，`@coordinator` 按闲置催办。

0. 先读本约定。
1. `GET /api/v1/pull_msg?handle=<自己>`。
2. 其中别人发给自己的（含 `@all`）：先 `push_msg` 回一句（可 `@` 对方），再按正文做事。自己发的公共消息可跳过执行。
3. 用户未 @ 的笔记不会出现在 pull 结果里，不要处理。
4. 没有新消息则本轮结束，不要为了「表明还活着」给 `@all` 发空聊。

Cursor 停会话不会被 HTTP 叫醒；**Fleet worker** 由 agent-bridge `POST /api/v1/agents/{handle}/wake` 唤醒。**Controller IDE** 由 hook（`sessionStart` / `stop`）或用户发消息时 pull `[dev-task]` / `[fleet]` 跟进。

## 6. 说话

催办、仲裁、派工、回告完成/阻塞，都走 `push_msg`，不要指望对方 Cursor 会话能听到本会话里的话。

`@coordinator` 催办也写成 chat 消息（`@ui` 等），不要只写在质检看板里。

用户在 HTML 页面派活：必须 `@` 某个/某几个 agent 或 `@all`，否则无人处理。

## 7. 处理约定

- 读到发给自己的消息：先回复，再做事；做不了或越层，再 `@` 发件人说明。
- `@coordinator` 不写产品代码；需要实现时 `@runtime` / `@ui` / `@capability`；需要黑盒时 `@quality`；部署 `@deploy`；运维 `@sre`。
- 用户对 `@coordinator` 说的非协调事项：coordinator `@` 转到对应 handle（plugin→`@capability`；调度/hydrate/前序门/失败 msg→`@runtime`；发出窗口 / 物流 UI / Cast / Receiver→`@ui`；黑盒 API→`@quality`；规划/选边/入队/Brain API→`@brain`；云部署→`@deploy`；运维→`@sre`；schema→`@dba`）。
- 预期外情况 **第一时间** `@coordinator`，由 coordinator 集中仲裁/拆单。不要自行跨层改。
- `@quality` 只打对外 API。修复须验收：实现方报完工后 `@quality` 请验收；结果写入 `tests/blackbox/`。不得自报结案。
- 不要在 chat 里贴密钥、`.env`、完整 token。

## 7.1 发布链路（强制）

产品代码：**git 提交 → 测试 → 部署上线**。未 commit 不算交付；未记录节点不算上线。细则与 Chatbox 格式见 [`.cursor/rules/release-pipeline.mdc`](../.cursor/rules/release-pipeline.mdc)；commit 格式见 [`git-commit-convention.md`](git-commit-convention.md)。

| 节点 | 谁 | 留痕 |
|------|-----|------|
| `committed` | 实现方（含 `@controller` 小改） | `[release] stage=committed sha=…` |
| `tested` / `test_requested` | 实现方自测；对外行为 `@quality` | `[release] stage=tested\|test_requested sha=…` |
| `deploy_requested` / `deployed` | 实现方申请；`@deploy`（或端上发布方）执行 | `[release] stage=deploy_* sha=… target=…` |

禁止用工作区脏改动 / 私下 rsync 冒充上线。部署流水线管控后续接入；在此之前以 `[release]` + Dev Console **Deploy** Tab + git log 为审计源。结案前 `@controller` 须能看到完整节点（或合法 `stage=skipped` + 原因）。老板在 Deploy Tab「批准上线」= Deploy Authority。

## 8. 并发

SQLite WAL + 进程内锁。**不要**再对 Markdown 信箱整文件覆盖。不要用 `docs/agent-mailbox.lock`。

## 9. 日报

每天 **23:00 前**（UTC+8）各 handle 交日报。汇总文档：[`docs/daily-reports.md`](daily-reports.md)。

- `push_msg`：`@coordinator` 正文以 `日报` 开头，单行 `完成：…｜阻塞：…｜明日：…｜待验收：…`。
- `@coordinator` **22:50** `@all` 催办。23:00 后写入当日汇总；未交标「缺交」。
- `@coordinator` 自己的日报直接写入汇总文档。
- 日报不是验收，不结案。禁止用 5 分钟空转代替交日报。
