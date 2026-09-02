# Agent README（工作约定）

本文件记录与 Agent（Cline）协作时的固定执行原则；后续原则由用户持续追加到此文件下。

## 1. Plan 落盘约定

- 后续所有 plan 在**确定执行前**，必须先落盘到 `agent_plans/` 目录。
- 每个 plan 新建一个文件：
  - 文件名：英文，符合需求内容
  - 格式：Markdown
  - **带版本号**：`<name>_v<N>.md`（如 `service_discovery_mdns_migration_v1.md`）
- plan 有变化时：**升版本号另存新文件**（旧版本保留），变更内容记录在新文件头部。

