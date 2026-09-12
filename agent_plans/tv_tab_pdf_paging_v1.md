# Plan v1：iOS Console 电视 Tab + PDF 翻页按钮（intent 接口直派扩展）

> 落盘：task-d1a3cf0d · 开发分支 `feature/tv-tab-pdf-paging` · 交付方式：PR 到 main

## 目标

iOS HomeAgent Console（`ios/LivingRoomEdge`）底栏新增「电视」tab，内含「上一页 / 下一页」
按钮，控制电视正在投屏的 PDF 翻页（`display.pdf.page`）。按钮通路复用现有
`POST /api/v1/intent`，扩展 `capability` + `params` 入参实现直派（绕过 LLM 规划，
毫秒级），**不新增接口**。

## 数据流

```text
电视 tab 按钮
  │ POST /api/v1/intent {capability:"display.pdf.page", params:{action:next/prev}}
  ▼
Brain dispatch_intent：capability 非空 → 直派分支（跳过 shortcut 拦截与 LLM 队列）
  │ 单步计划 + do_execution_plan（按能力广告选边）
  ▼
Mac Edge display.pdf.page → 小米电视翻页
  │
  ▼
Console 轮询 intent_detail，显示「第 x / 共 N 页」
```

## 改动

### 1. Brain：`server/home_brain.py`

- `dispatch_intent` POST 分支解析新入参：`capability`（str）、`params`（dict）；
  `capability` 非空时 `text` 允许为空，缺省填 `直派 <capability>`
- 直派分支挂在 `shortcut_intercept` 之前：
  - `online_capability_providers(capability)` 无在线提供者 → 失败回路
    （`mark_intent_failed` + `intent_status=failed` + 中文报错）
  - 构造 `InterceptResult(kind="plan", plan=[{step:1, capability, input_constrict:params,
    output_constrict:{}}], presentation={"type":"text"}, planner_meta={source:"direct_invoke"})`
    复用 `_dispatch_shortcut_intent`
- `_dispatch_shortcut_intent` 加可选形参 `task_kind="shortcut"`，直派传 `"direct_invoke"`
- 安全边界：v1 不做能力白名单，以「至少一个在线 edge 广告该能力」为门禁

### 2. iOS：`ios/LivingRoomEdge/LivingRoomEdge/`

- `Brain/IntentClient.swift` `dispatch(...)` 加可选形参 `capability`/`params`；
  capability 非空时跳过 text 非空守卫，payload 加这两个字段
- 新增 `App/TVView.swift`：上一页/下一页按钮 → dispatch；轮询 intent_detail 至终态，
  从 step outputs 读 `page`/`page_count`/`status_text` 显示「第 x / 共 N 页」，
  失败显示中文原因；风格对齐 `EdgeTheme`
- `App/RootTabView.swift`：`EdgeTab` 加 `case tv`，tabItem `Label("电视", systemImage: "tv.fill")`
- 重跑 `python3 ios/LivingRoomEdge/generate_xcodeproj.py`（自动 glob，只重新生成工程）

### 3. 测试

- `server/tests/` 新增直派用例：正常直派（绕过 LLM、单步、task_kind=direct_invoke）/
  无在线提供者失败 / 无 capability 走原 LLM 路径不回归 / text 空但 capability 非空受理
- iOS：`xcodebuild` 编译验证；真机翻页用户点验
- mac 侧零改动，跑全量防回归

### 4. 发布链路（release-pipeline.mdc）

分支提交 → 测试 → PR → `[release]` 留痕 → 合入后部署：LAN + 云 Brain 重启
（rsync `server/home_brain.py`，记 agent_access.log）；iOS 端 Xcode 真机安装。
黑盒：curl 直派「下一页」验证毫秒级响应 + 电视实际翻页。

## 明确不做

- Android Console（`android/living-room-android`）
- 图片轮播（display.slideshow）手动翻页——需 edge 侧轮播会话化，另立任务
- 语音翻页 shortcut 拦截（按钮通路已解决翻页延迟）
