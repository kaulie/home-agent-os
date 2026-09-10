# Plan：修复 web.scraper 消费 url 资产时 content URL 解析为空

> 落盘：task-54b2ed92 · 开发分支 `fix/task-54b2ed92-webscraper-url-content` · 交付方式：PR 到 main
> 触发：intent 676「把最新的URL转成PDF」step2 web.scraper 失败，报
> `url 资产解析出的 content URL 为空`（#34 修复 MultiBrainClient.config 后暴露的第二个 bug）。

## 1. 目标

`CapAsset.http_url(ref)` 返回的是 **URL 字符串**（内部 `return rep.url`），但
`web_scraper.scrape_from_params` 用 `str(getattr(rep, "url", "") or "")` 取值——
字符串没有 `.url` 属性 → 永远为空 → 抛 “url 资产解析出的 content URL 为空”。
现网单测把 `http_url` mock 成带 `.url` 的对象，掩盖了该契约不匹配。

修复：把 `http_url` 返回值当字符串用（同时兼容带 `.url` 的对象），并把单测 mock
改为返回真实契约（URL 字符串），使用例能回归该 bug。

## 2. 已确认决策

| 维度 | 决策 |
|---|---|
| 主改动 | `mac/src/mac_edge/plugins/web_scraper.py`：兼容 str / `.url` 对象 |
| 契约 | `CapAsset.http_url` 返回 str；对象形态仅向后兼容 |
| 测试 | `mac/tests/test_web_scraper.py::test_pdf_article_via_url_asset_ref` mock 改回 URL 字符串，并断言 fetch 使用该 content URL |

## 3. 改动文件

- `mac/src/mac_edge/plugins/web_scraper.py`
- `mac/tests/test_web_scraper.py`

## 4. 验收

- 修改后的测试在未打补丁时复现原错误（`content URL 为空`），打补丁后通过；
- `test_web_scraper` 整模块 43 例全绿。
