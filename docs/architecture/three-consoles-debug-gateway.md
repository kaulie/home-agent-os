# 三类 Console 与 Agent Debug Gateway

本文档定义 User / Business / Dev 三类入口的职责边界，以及 **Agent Debug Gateway** 如何把「问题现场」转交 Dev Agent。

## 1. 三类 Console

| Console | 核心问题 | 典型用户 |
|---------|----------|----------|
| **User Console** | 我要使用什么？ | 家庭用户 |
| **Business Console** | 业务系统现在运行得怎么样？ | 业务管理员 |
| **Dev Console / Dev Task** | 为什么有问题？怎么修？ | 开发 / 底层运维 |

三者共享 Runtime / Agent 基础设施，**职责与权限隔离**。

## 2. User Console — 一键报 Bug

用户认为执行结果不正确时：

- 提供 **「一键报 Bug」**，不要求填写技术信息。
- 客户端只提交当前会话关联的 `intent_id` + `participant_id`（可选 `client_snapshot`）。
- **禁止**在 User Console 人工拼装「请检查 intent #xxx」类 Dev 提示词。

用户侧仅展示：

> **已提交问题，正在分析。**

### API

`POST /api/v1/debug/report`

```json
{
  "intent_id": 1475,
  "participant_id": "living-room-android",
  "source": "user_console",
  "user_summary": "",
  "client_snapshot": { "journey_logistics": "…" }
}
```

响应：

```json
{
  "ok": true,
  "issue_id": 182,
  "intent_id": 1475,
  "status": "analyzing",
  "task_id": 42,
  "message": "已提交问题，正在分析。"
}
```

## 3. Agent Debug Gateway

User / Business Console **不直接**操作 Dev Agent。

统一经 Gateway 建立链路：

```
User Session → Intent → Execution → Issue → Dev Task → Dev Agent
```

Gateway 从 Brain 自动收集执行现场（MVP 已实现字段）：

- User Input、`session_id`、`intent_id`
- Intent 状态、error、context
- `execution_plan`、`step_log`、`status_log`
- presentation / outputs
- Runtime `edge_id`、节点信息
- 客户端可选 `client_snapshot`（物流时间线等）

然后：

1. 创建 `DebugIssue`（`server/debug_issue_store.py`）
2. 生成 Dev Agent 提示词（`server/debug_gateway.py`）
3. 调用现有 `submit_agent_task` → agent-bridge → Cursor Agent

Dev Admin API（需 `X-Admin-Token` 若 Brain 配置了 `BRAIN_ADMIN_TOKEN`）：

- `GET /api/v1/admin/debug/issues`
- `GET /api/v1/admin/debug/issue/<issue_id>`

### Dev Task 多轮会话（thread）

同一问题可在 **一条会话** 里继续追问，避免列表里散成多条无关任务：

- 每条 Dev Task 有 `thread_id`（会话根任务 id）与可选 `parent_task_id`（上一轮）。
- `POST /api/v1/admin/dev_task` 新任务：`text`；续聊加 `continue_task_id`（或 `parent_task_id`）指向上一轮任务 id。
- `GET /api/v1/admin/dev_task/<id>` 返回 `thread_messages`：该会话内按时间排序的全部轮次。
- 列表默认 `roots_only=1`，只显示会话根；点进详情可看全文 + 底部「继续讨论」。
- Mac 侧 agent-bridge 对同一会话 resume Cursor `agent_id`，Agent 保留上文。

### Dev Task 分类（category）

会话根任务带类别标签，列表可筛选、详情醒目展示：

| `category` | 标签 |
|------------|------|
| `bug_fix` | Bug 修复 |
| `feature` | 功能开发 |
| `tech_discuss` | 技术探讨 |
| `ops` | 运维部署 |
| `chat` | 闲聊 |
| `other` | 其他 |

- 新会话：`POST` 传 `category`（续聊自动继承，无需再传）。
- 列表筛选：`GET /api/v1/admin/dev_tasks?category=bug_fix`
- 改类别：`PATCH /api/v1/admin/dev_task/<id>/category` `{"category":"tech_discuss"}`
- 类别清单：`GET /api/v1/admin/dev_task/categories`
- User 一键报 Bug 自动创建的任务类别为 `bug_fix`。

## 4. Business Console（Phase 3）

关注 Runtime 健康、Capability 注册与健康、Session/Intent 成功率、用户反馈趋势。

**不展示**：代码、Git Diff、Agent 修改过程、Sandbox 内部细节。

业务 Issue 可 `source=business_console` 经同一 Gateway 转交 Dev Task。

## 5. Dev Console / Dev Task（Phase 1–2）

核心对象：Issue、Agent Context、Code、Git、Sandbox、Test、Candidate Version、Deployment。

Dev Agent 闭环（目标）：

```
Issue → Analyze → Reproduce → Locate → Modify → Build → Sandbox → Test → Regression → Candidate Version
```

失败则 Sandbox 内迭代，**禁止** Agent 直接改 Production。

### Deploy 权限分离

| Dev Agent 可做 | Dev Agent 不可做 |
|----------------|------------------|
| 改代码、Patch、Candidate、跑测试、提交发布申请 | 自主 Production 发布、绕过审批 |

最终上线须 **Deploy Authority** 批准。

### 手机 Dev Console（Phase 2）

展示 Issue 状态、Agent 进度、测试结果、Code Diff、「批准上线」— 无需人工重述问题。

**Deploy Tab（已落地 MVP）：** 聚合 Chatbox `[release]` 节点（commit → test → approve → deploy）；`awaiting_approval` 时老板可批准/拒绝；批准后 wake `@deploy`。API：`GET/POST /api/v1/admin/releases*`。

## 6. Sandbox（Phase 1 后续）

Agent 修改默认只进 Sandbox / Candidate：

- Build、单元 / 集成测试
- 原 Bug 重现与回归、相关功能回归
- Runtime 模拟、结果记录

通过后产出 **Candidate Version**。

## 7. MVP 实现顺序

### Phase 1（当前）

- [x] User Console「一键报 Bug」UI（Android Console 对话页）
- [x] Gateway `POST /api/v1/debug/report`
- [x] 自动收集 Intent 现场 + Issue 存储
- [x] Dev Task 创建（agent-bridge）
- [ ] Dev Agent 自动改码 / Sandbox / 自动测试 / Candidate Version

### Phase 2

- Dev Console 手机端（HomeAgent Admin 扩展 Issue 视图）
- Issue 实时状态、Diff、测试结果、Deploy 批准

### Phase 3

- Business Console（Node、Capability、健康度、业务趋势）

## 8. 设计原则

1. 用户不需理解技术细节。
2. Context 随问题上报，管理员不必重找 Intent / 日志。
3. Agent 可自主 Debug / 修复（在 Sandbox 边界内）。
4. Production Deploy 必须显式授权。
5. Business Admin 与 Dev Admin 分离。
6. 三 Console 共享基础设施，不共享职责与权限。

完整闭环：

```
User → Business → Dev → Sandbox → Candidate → Production
```

## 相关代码

| 模块 | 路径 |
|------|------|
| Gateway | `server/debug_gateway.py` |
| Issue 存储 | `server/debug_issue_store.py` |
| Dev Task | `server/dev_task.py` |
| Brain 路由 | `server/home_brain.py` |
| Android 一键报 Bug | `android/living-room-android/.../ConsoleViewModel.kt`, `ChatScreens.kt` |
| iOS Dev Console | `ios/HomeAgentDev/` |
| iOS Business Admin | `ios/HomeAgentAdmin/`（无 Dev Task Tab） |
