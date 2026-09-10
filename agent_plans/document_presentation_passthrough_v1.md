# Plan: document Presentation 透传（URL → PDF 成功后展示 PDF）_v1

**问题**：issue id=677「把最新的URL转成PDF」执行成功，但发起端只看到 step1 的
`asset.inventory` 文案（「这是按登记顺序的第 1 张url。」），**看不到新产出的 PDF**。

## 根因（已用现网数据/日志定位）

1. 规划器（ARK）**已经给出** `presentation: {"type":"document","from":"asset_ref"}`，
   与 `server/prompts/task_planner_system_prompt.md.en` 的约定一致（prompt 明确列出
   `text | image | audio | document`）。
2. 但控制面的 `_normalize_presentation_plan()` 允许列表只有 `("text","image","audio")`，
   于是 `extract_llm_presentation()` 把 document 骨架**归一化成 `{}` 丢掉**；
   `_PLANNER_OUTPUT_SCHEMA` / `_PLANNER_PRESENTATION_SCHEMA` 的 `type` 也**没写 document**
   （schema 与 prompt 自相矛盾）。
3. `presentation` 没了 → `assemble_presentation()` 只能按 `execution_plan` 的 capability 兜底：
   `asset.inventory` 分支 → `text/answer_text` → 客户端展示盘点文案，从不展示 PDF。
4. 其它辅助事实：
   - 生产端 `web.scraper` 正常：`asset_60d5486539964a596adf1b71`（document/application/pdf，
     7 页，chrome 渲染，`assets.origin_intent_id=677`）。
   - 发起端（`客厅 iPhone` / `edge-node-JzvEe287`）声明
     `supported_presentation: [image, text, audio, document]`，iOS `LivingRoomEdge`
     里有 PDFKit 的 document 气泡（`ContentView.swift:DocumentBubblePreview`）→ 客户端本就支持。
   - 关键词兜底 `_user_asked_see_document()` 只在用户说「看一下/显示/预览 + pdf/文档」时才升
     document；「把…转成 PDF」不含看的关键词，所以连兜底也不触发。

## 改动（server-only）

1. `_normalize_presentation_plan()`：允许 `document`（与 prompt 一致）。
2. `_PLANNER_PRESENTATION_SCHEMA` / `_PLANNER_OUTPUT_SCHEMA.presentation.type`：
   `text | image | audio | document`（schema 与 prompt 对齐）。
3. `assemble_presentation()` 两条规则：
   - **guard**：`type=document` 但当前 `asset_ref` 还不是可预览文档（典型：`asset.inventory`
     先给出 `type=url` 资产，mime `text/uri-list`）→ 这一帧退回文字，**绝不把 url 资产当 PDF 推给客户端**。
   - **upgrade**：本次 intent **自己产出**了可预览文档（`assets.origin_intent_id == intent_id`）
     且非 voice 发起 → 升为 `document` 预览（发起端「输入源亲和」）。voice 发起保持原有
     「念一句」的对称交付不变。
4. 单测：`server/tests/test_home_brain.py` 覆盖
   normalize 保 document / plan kind 取 document / url 资产不冒充 PDF /
   本 intent 产出的 PDF 升 document / 语音发起不抢成 document。

## 不做（本轮）

- 语音发起 + 「转成PDF」是否要「既念一句又展示 PDF」（需要复合交付），先不改，交用户定。
- 其它客户端（Chromecast / Kindle）对 document 的支持，不在本轮。
