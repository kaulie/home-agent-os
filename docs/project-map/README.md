# Project Map

给刚进入仓库的人 / Agent 用的导航，不是代码百科。

地图用来建立方向；**代码用来确认事实**。不要把本文档当成实现的替代品。

事实优先级：实际代码 > 配置 > 测试 > 运行拓扑 > 现有文档 > 推断。冲突标 `CONFLICT`，无法确认标 `[UNKNOWN]`。

## 读哪份

| 文件 | 回答的问题 |
|------|------------|
| [PROJECT.md](PROJECT.md) | 这是什么项目、做到哪一阶段 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 系统怎么转、数据和控制怎么流 |
| [MODULES.md](MODULES.md) | 模块职责、Task 该去哪 |
| [BOUNDARIES.md](BOUNDARIES.md) | 本 handle 能改什么、不能改什么 |
| [RUNTIME.md](RUNTIME.md) | 怎么启动、测试、看日志、部署 |
| [DEVELOPMENT.md](DEVELOPMENT.md) | 改代码前必须遵守的工程规则 |
| [CHANGELOG.md](CHANGELOG.md) | 最近发生了哪些结构性变化 |
| [FINDINGS.md](FINDINGS.md) | 文档与代码不一致、UNKNOWN、架构债 |

深层契约不复制，按需再读：

- 参与者模型：[docs/participant-model.md](../participant-model.md)
- 本机拓扑：[docs/service-topology.md](../service-topology.md)
- Handle 名册：[docs/agent-roster.md](../agent-roster.md)
- Schema：[docs/db-schema.md](../db-schema.md)
- 协调协议：[docs/agent-coordination.md](../agent-coordination.md)

## Agent 启动协议

进入本仓库、准备改代码之前：

1. Load [PROJECT.md](PROJECT.md)
2. Load [ARCHITECTURE.md](ARCHITECTURE.md)
3. Load 本 handle 角色（[docs/agent-roster.md](../agent-roster.md)）
4. Load Task 上下文
5. 按 Task 查 [MODULES.md](MODULES.md)
6. 查 [BOUNDARIES.md](BOUNDARIES.md)
7. 查 [RUNTIME.md](RUNTIME.md) / [DEVELOPMENT.md](DEVELOPMENT.md)
8. 定位相关代码
9. 阅读实际代码
10. 用代码验证自己的认知
11. 开始执行 Task

改完后：若本次变更改变了架构 / 模块职责 / 运行方式 / 边界，更新对应 Map 文件（见 [CHANGELOG.md](CHANGELOG.md) 维护约定）。
