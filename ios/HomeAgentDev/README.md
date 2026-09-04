# HomeAgent Dev

**Dev Console** 独立 iPhone App：查看 User 一键报 Bug 产生的 **Issue**、跟踪 **Dev Task** / Agent 分析，并可手动下发开发任务到 Mac Cursor Agent。

与 **HomeAgent Admin**（业务运行态：节点、策略、事件流）分离。

## 打开工程

```bash
python3 ios/HomeAgentDev/generate_xcodeproj.py
open ios/HomeAgentDev/HomeAgentDev.xcodeproj
```

- 主屏幕名称：`HomeAgent Dev`
- Bundle ID：`com.gaolei.homeagent.dev`
- 最低系统：iOS 16
- Signing：Xcode 里选你的 Team

改完 Swift 后重新跑 `generate_xcodeproj.py`。

## 页面

| Tab | 做什么 |
|-----|--------|
| **Issue** | User Console 经 Debug Gateway 上报的问题；每 3 秒刷新进行中 Issue |
| **Dev Task** | agent-bridge 开发任务列表 + 手动下发（可指定 `target_handle`） |
| **Fleet** | Agent Fleet 状态：各 handle 在线/运行中、最近 run、一键唤醒 |
| **统计** | Dev Task token 消耗总览、按类别拆分；**云服务调用**（`usage.cloud_calls` 埋点，与 token 分开） |
| **连接** | Brain URL + 管理员令牌 |

## XCUITest（@quality）

`HomeAgentDevUITests` target；用例在 `HomeAgentDevUITests/`。稳定选择器见 `HomeAgentDev/DevAccessibilityID.swift`（由 `@ui` 维护）。

**前提：** 模拟器/真机能访问 Dev Brain（LAN 走 mDNS `brain.local` 或云端）；本机 Brain / `home_brain.py` 已起。

```bash
cd ios/HomeAgentDev

# P0 冒烟：进入「文档」Tab 并加载列表
xcodebuild test -scheme HomeAgentDev \
  -destination 'platform=iOS Simulator,name=iPhone 17' \
  -only-testing:HomeAgentDevUITests/HomeAgentDevSmokeUITests

# P1：Markdown 阅读器（打开 / 大纲 / 字号 / Chat [[doc:]]）
xcodebuild test -scheme HomeAgentDev \
  -destination 'platform=iOS Simulator,name=iPhone 17' \
  -only-testing:HomeAgentDevUITests/MarkdownReaderUITests
```

说明与职责边界：[`docs/testing/xcuitest.md`](../../docs/testing/xcuitest.md)。

## API

默认：与 User Console 相同 — **按网络自动**（在家且 LAN `/api/v1/ping` 通则局域网，否则云端）。顶栏始终显示当前实际环境；切换需进确认页。

| 连接方式 | 说明 |
|----------|------|
| 按网络自动 | 推荐 |
| 锁定局域网 | 始终走已发现的 LAN Brain IPv4（身份 `brain.local`） |
| 锁定云端 | 始终 `115.190.153.53:9527`（可改） |

- `GET /api/v1/admin/debug/issues`
- `GET /api/v1/admin/debug/issue/<issue_id>`
- `POST /api/v1/admin/dev_task`
- `GET /api/v1/admin/dev_tasks`
- `GET /api/v1/admin/dev_task/<task_id>`
- `GET /api/v1/admin/dev_task/usage?days=7`
- `GET /api/v1/admin/agent_fleet` — Fleet 状态（经 Brain 代理本机 bridge）
- `POST /api/v1/admin/agent_fleet/<handle>/wake` — 唤醒 Fleet worker
- 可选头 `X-Admin-Token`

Mac 需运行 **agent-bridge**（`cd agent-bridge && ./run.sh`）。

## 相关文档

[`docs/architecture/three-consoles-debug-gateway.md`](../../docs/architecture/three-consoles-debug-gateway.md)
