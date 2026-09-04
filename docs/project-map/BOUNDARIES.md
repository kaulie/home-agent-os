# BOUNDARIES

给多 Agent 协作用。接到 Task 后先确认本 handle 的 `can_modify`；越界不要改，转交。

产品 Role（Intent Source / Runtime / Endpoint / Observer）≠ Cursor handle。Observer ≠ `@coordinator`。

## 模块边界（产品）

```text
Brain 规划 / API     ── 不实现 plugin，不画发出窗
Runtime hydrate/执行 ── 不改 planner 规则，不改 App UI
Capability 实现      ── 不读前序 step，不改入队
UI 发出/呈现         ── 不改 Brain 选边，不改 schema
DBA schema           ── 不改业务行为
Deploy rsync         ── 不改未提交工作区，不动 sql/data
```

共享文件只改验收所需最小点：`mac/src/mac_voice/listen.py`、`config/endpoints.json`。

## Handle 权限

### agent: controller

常驻 IDE。编排、小改、写跨层文档（如本地图）。

- can_modify：编排所需的 docs / `.cursor/rules`（协调逻辑除外）、明确的一层内小改
- should_not_modify：为赶工覆盖其它 handle 的未提交 WIP
- requires_review：改 Chatbox 水位文件以外的协调逻辑 — **禁止**（见 orchestration 规则）

### agent: brain

```text
can_modify:
  - server/          # 含 prompts、选边、入队、对外 API
  - home_brain.py    # 根入口
should_not_modify:
  - plugins/ 实现与端上 Skill
  - ios/ android/ admin/ 用户 UI
  - mac/ 运维脚本与 Edge 执行器（非 Brain 客户端）
requires_review:
  - server/sql/、server/db.py、docs/db-schema.md   # @dba
  - 云 rsync                                      # @deploy + sha
```

Planner 规则：**只改** `server/prompts/*.md`。

### agent: runtime

```text
can_modify:
  - mac/src/mac_edge/agent.py scheduler.py executor.py runtime_context.py local_ledger.py
  - 各端 hydrate / 前序门 / 失败 msg（iOS IntentClient 执行环、Android EdgeAgent）
should_not_modify:
  - server/ 规划与入队
  - App 发出窗 / 物流 UI / Cast Receiver 呈现
  - plugins/*/capability.md 契约原文（归 @capability；实现可协同）
requires_review:
  - mac/src/mac_voice/listen.py     # 多产品面
```

### agent: ui

```text
can_modify:
  - ios/                 # Console / Admin / Dev / Pickup / Legacy / Relay
  - android/             # 用户交互面
  - admin/               # 本机管理页
  - plugins/chromecast-display/receiver/
should_not_modify:
  - server/home_brain.py 规划与入队
  - plugin 非 UI 实现
  - server/sql/
requires_review:
  - 为自动化加 accessibilityIdentifier 时知会 @quality 或由本层补
```

`@intent` / `@endpoint` 是 Chatbox 别名，都映射到 `@ui`。

### agent: capability

```text
can_modify:
  - plugins/*/capability.md
  - plugins/*/manifest.yaml
  - mac/src/mac_edge/plugins/
  - 各端 Skill 实现（非发出窗）
should_not_modify:
  - 发出窗 / 物流 UI
  - Brain 入队 / 选边
  - tests/blackbox/ 作为「替代实现」
```

缺必填入参 → 失败。禁止「从上一步收集」。

### agent: quality

```text
can_modify:
  - tests/blackbox/
  - ios/*/UITests 等自动化
should_not_modify:
  - 产品功能代码
```

identifier 除外且须 `@ui` 知情。

### agent: deploy

```text
can_modify:
  - 云 /root/chat-gateway 树内、已测 commit 的允许 rsync 范围
should_not_modify:
  - 未提交工作区
  - db.py / sql/ / data/ / admin/ / .env / gopropics/
  - /etc/systemd 与仓库外路径
```

部署正文必须带 sha。

### agent: sre

```text
can_modify:
  - docs/service-topology.md
  - local-rt/
  - 双 Brain / 隧道 / 本机拉起脚本
should_not_modify:
  - 产品功能（规划、plugin、App UI）
```

### agent: dba

```text
can_modify:
  - server/sql/
  - docs/db-schema.md
  - 经点名的 server/db.py 迁移配合
should_not_modify:
  - Edge JSON / local_ledger 未经用户点名
  - 规划规则、plugin
```

### agent: coordinator

**不写产品代码。** 仲裁、催办、拆单、日报。结案确认请别人 `cc`，不要正式 `@` 互刷。

## API Contract

对外家务协议以 Brain 路由与 `plugins/*/capability.md` 为准，不是某一端的私有 JSON。

稳定入口：

- `POST /api/v1/intent`
- `GET /api/v1/intent_detail`
- `GET /api/v1/devices/living-room/intents?edge_id=`
- `POST /api/v1/intent/<id>/step/<n>/status`
- `POST /api/v1/edge-register`、`POST /api/v1/edge-heartbeat`
- `GET /api/v1/assets/{id}/content`

改这些视为跨端协议，需要 `@brain` + 实现方 + `@quality`。

Asset：只传 `asset_ref` / `asset_id`。Cast 临时 URL 是 representation。

## 数据库边界

| 库 | 路径 | 谁动 |
|----|------|------|
| Brain SQLite | `server/data/brain.sqlite3` | `@dba` 结构；`@brain` 读写逻辑 |
| Chatbox SQLite | `chat/data/agent_chat.sqlite3` | Chat 服务；**不是** Brain DB |
| Mac 歌曲库 | `mac/` 本地 ncm sqlite | 见 `docs/mac-ncm-songs-db.md` |
| Mac ledger | `local_ledger.json` | `@runtime`；未经点名不要当 schema 改 |

禁止为图省事把 Chatbox 消息写入 Brain DB，或反过来。

## 部署边界

唯一云可写范围：`/root/chat-gateway`。禁止改该目录以外（含 `/etc/systemd`）。unit 名 `doubao_skill` 不在仓库里，不要「顺手改 unit」。

LAN 地址：只改 `config/endpoints.json` 为权威，再 sync。不要在客户端源码里手写一份新 IP。

## 测试边界

`@quality` 拥有 `tests/blackbox/` 的验收叙事。实现方可以在本层 `server/tests/`、`mac/tests/` 加单测，但对外行为以黑盒为准。
