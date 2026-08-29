# XCUITest（@quality · App UI 自动化）

> 老板定稿：自动化 UI 验收写入 `@quality` 职责；**先 XCUITest**，Maestro 以后再说。

## 职责边界

| 可以 | 不可以 |
|------|--------|
| 新建/维护 `*UITests` target、测试用例、跑模拟器/真机脚本 | 改产品功能、重做 UI 交互 |
| 要求或补 `accessibilityIdentifier`（补 id 须知会 `@ui`） | 把 UI 测当 API 黑盒的替代（两套都要） |
| 结果写入 `tests/ui/` 或 `tests/blackbox/` 旁的 UI 报告，并 Chat `[release] stage=tested` | 自报产品结案 |

## 推荐落点（P0）

1. **目标 App：** `ios/HomeAgentDev`（Dev Console：文档阅读器优先）。
2. **工程：** 增加 `HomeAgentDevUITests` target（Xcode）；用例放 `ios/HomeAgentDev/HomeAgentDevUITests/`。
3. **稳定选择器：** 给 Tab「文档」、阅读器大纲/字号控件加 `accessibilityIdentifier`（与 `@ui` 对齐）。
4. **首批冒烟（Markdown 阅读器）：**
   - 打开 Docs Tab，能进入一篇文档并滚动
   - 打开大纲，点击一项能跳转（若 UI 已交付）
   - 调节字号，控件状态变化可断言（若 UI 已交付）
5. **运行：** `xcodebuild test -scheme HomeAgentDev -destination 'platform=iOS Simulator,name=…'`（具体机型写进 README）。
6. **文档：** 本文件 + `ios/HomeAgentDev/README.md` 补「如何跑 UITests」。

## 与 API 黑盒关系

- Intent / Brain 行为 → 仍 `tests/blackbox/`。
- 纯端上交互（阅读器、字号、大纲）→ XCUITest。
- 同一功能可两边都有：API 验数据，UI 验呈现。

## 渐进

- P0：HomeAgentDev UITests 骨架 + 至少 1 条能绿的冒烟（哪怕先只断言进 Docs Tab）。
- P1：覆盖阅读器三项（打开 / 大纲 / 字号）。
- P2：Legacy / LivingRoomEdge 按需加 target；再评估 Maestro。
