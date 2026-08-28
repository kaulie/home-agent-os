# Git Commit 规范

本仓库 **commit-msg hook** 会校验格式与 feature scope。安装：`bash scripts/git/install-hooks.sh`。

## 标题（必填，第一行）

```text
<type>(<scope>): <summary>
```

| 字段 | 说明 |
|------|------|
| `type` | `feat` 新功能 · `fix` 修 bug · `docs` 文档 · `refactor` 重构 · `test` 测试 · `chore` 杂项 · `deploy` 部署 · `perf` 性能 |
| `scope` | 与暂存区 **primary** 目录一致，见下表 |
| `summary` | 4–72 字，说清「改了什么」；中文或英文均可；不以句号结尾 |

### scope 对照表

| scope | 路径 |
|-------|------|
| `agent-bridge` | `agent-bridge/` |
| `chat` | `chat/` |
| `server` | `server/`、`home_brain.py` |
| `ios-dev` | `ios/HomeAgentDev/` |
| `ios-admin` | `ios/HomeAgentAdmin/` |
| `ios-living` | `ios/LivingRoomEdge/`、`ios/LivingRoomLegacy/` |
| `ios-other` | `ios/` 其余 |
| `android` | `android/` |
| `mac` | `mac/` |
| `plugins` | `plugins/` |
| `character-service` | `character-service/` |
| `ocr-service` | `ocr-service/` |
| `games` | `games/` |
| `admin` | `admin/` |
| `local-rt` | `local-rt/` |
| `docs` | `docs/` |
| `repo` | `.githooks/`、`scripts/git/`、根目录元文件 |

`docs/`、`.cursor/` 可与任一 primary **同次提交**；标题 scope 仍写本次主改动所在的 primary。

## 正文（可选）

空一行后写原因 / 风险 / 验收方式。每行建议 ≤ 72 字。

## 页脚（可选）

```text
Refs: #42
Scopes: server, ios-dev
```

| 标签 | 何时写 |
|------|--------|
| `Refs: #<id>` | 关联 issue / 手机 Dev Task / 调试单 |
| `Scopes: a, b` | **一次提交故意跨多个 primary**（与 scope hook 对齐） |

## 示例

**单 feature：**

```text
feat(server): 新增 agent_fleet 管理 API

Brain 代理本机 bridge，供 HomeAgentDev Fleet 页调用。

Refs: #42
```

**仅文档：**

```text
docs(agent-coordination): 登记 Agent Fleet 单 IDE 模式
```

**修 hook / 脚本：**

```text
chore(repo): 增加 commit scope 与 message 校验
```

**跨层同一 issue（分支名也需含 issue id，如 `feature/42-fleet`）：**

```text
fix(ios-dev): Fleet 页展示 bridge 运行状态

Refs: #42
Scopes: server, ios-dev
```

## 禁止

- 第一行无 `type(scope):`（Merge / Revert 除外）
- 一次提交混入无关 primary（如 `server` + `character-service`）且未写 `Scopes:` / `Refs`
- 用 `wip`、`update`、`fix bug` 等空洞摘要

## 跳过校验（仅紧急）

正文含 `[skip-scope-check]`，或：

```bash
SKIP_SCOPE_CHECK=1 git commit ...
```

## 相关实现

- 格式 + scope：[`scripts/git/commit_scope_check.py`](../scripts/git/commit_scope_check.py)
- scope 规则：[`scripts/git/commit_scope_rules.json`](../scripts/git/commit_scope_rules.json)
- 提交模板： [`.githooks/commit-template.txt`](../.githooks/commit-template.txt)
