# Markdown 阅读器门禁 #340 / #343

- **sha:** `7042b16`（基线 `d07a700`）
- **环境:** HomeAgentDev · iPhone 17 Simulator · LAN Brain `192.168.3.73:9527`
- **自动化:** `HomeAgentDevUITests/MarkdownReaderUITests.swift`（4 cases，全绿）
- **日期:** 2026-08-29

## #340 功能验收

| # | 项 | 结果 | 现象 |
|---|-----|------|------|
| 1 | Docs Tab 打开文档并滚动 | **pass** | More→文档→`presentation-cleanup.md` 可进阅读器，双次 swipe 流畅 |
| 1 | Chat `[[doc:]]` 打开同一阅读器 | **pass** | Chat #349 链接 `📄 presentation-cleanup.md` 弹出 InlineDocSheet，含目录/字号控件 |
| 2 | 大纲点击跳转标题 | **pass** | 目录 sheet（导航栏「目录」）列出 H1–H3，点第 2 项后回到正文 |
| 3 | 字号可调且持久化 | **pass** | A+×3 标签 中→大；杀进程重进仍为「大」（`@AppStorage dev.markdown.fontScale`） |

## XCUITest 命令

```bash
cd ios/HomeAgentDev
xcodebuild test -scheme HomeAgentDev \
  -destination 'platform=iOS Simulator,name=iPhone 17' \
  -only-testing:HomeAgentDevUITests/MarkdownReaderUITests
```
