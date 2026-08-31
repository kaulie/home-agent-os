# Markdown 阅读器 UX 复验（#350 → #353）

- **sha:** `95f5423`
- **环境:** HomeAgentDev · iPhone 17 Simulator · LAN Brain
- **日期:** 2026-08-29

## #350 三条改进

| # | 改进 | 结果 | 现象 |
|---|------|------|------|
| 1 | 文档 Tab 提前至主栏（Issue/Chat/**文档**/…） | **pass** | `testDocsTabOnMainBarNotOverflow` 绿；无需 More→文档 |
| 2 | Chat InlineDocSheet 导航栏统一纸感 chrome | **pass** | `devMarkdownReadingChrome` + palette.canvas；Chat `[[doc:]]` 用例绿 |
| 3 | 字号显示档位+百分比（如「大 · 112%」） | **pass** | A+/A- 后标签含 `·` 与 `%`；`@AppStorage` 持久 |

## XCUITest

```bash
cd ios/HomeAgentDev
xcodebuild test -scheme HomeAgentDev \
  -destination 'platform=iOS Simulator,name=iPhone 17' \
  -only-testing:HomeAgentDevUITests/MarkdownReaderUITests
```
