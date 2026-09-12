# 黑盒：PDF 投屏小米电视（display.pdf / display.pdf.page / pdf.to_images）

- 日期：2026-09-12 10:22–10:26（UTC+8）
- 被测版本：main `bae14f8`（PR #39）
- 环境：LAN Brain（本机 :9527）+ 客厅 Mac Edge（`edge-node-IAtuhLSy`，`MAC_EDGE_DISPLAY_BACKEND=xiaomi`，pymupdf 1.28.2）
- 发起方：`edge-node-blackbox-q01`（quality-blackbox，先 `edge-heartbeat` 再发 intent）
- 测试资产：3 页 PDF（每页大字页码），`asset_92a2a692319ba267fd9dd312`，经 `POST /api/v1/assets/upload` 登记（upload_intent=blackbox.pdf_display）

## 用例

### B1 「把最新的PDF投屏到电视上」→ intent 685

- 计划：`1:asset.inventory@system` → `2:display.pdf@edge-node-IAtuhLSy`（正确：先取最新 document 资产，再投屏）
- `asset.inventory` 命中测试 PDF（最新 document）
- Edge 执行 `display.pdf`：物化 PDF → 渲染第 1 页 → PNG 上传登记 `asset_9d56d5270ca7970843430efd`（`pdf-page-...-p1.png`，106 KB）→ 进入 DLNA 投放
- 结果：**step failed** —— `投电视失败：发现了 DLNA 设备，但没有匹配的小米电视。请设置 MAC_EDGE_XIAOMI_TV_NAME 或 HOST。`
- 判定：链路（规划→资产→渲染→上传→DLNA 发现）全通；失败点为环境（电视未开机，LAN 上仅有小度音箱一台 DLNA 设备，名称匹配正确拒绝）。中文报错 actionable ✅

### B2 「下一页」→ intent 686

- 计划：单步 `display.pdf.page@edge-node-IAtuhLSy`（正确识别为翻页，无需 asset_ref）
- Edge：会话延续（B1 的投屏会话在 TV 投放失败后保留），推进到第 2 页 → 渲染 → 上传 `asset_03eb8ae0c1178f5b3ef3a051`（`pdf-page-...-p2.png`，110 KB）
- 结果：同样止步于 DLNA 投放（电视未开机）
- 判定：翻页机制（会话连续、页码推进、懒渲染、按 intent 重传授权）全通 ✅

### B3 能力广告

- `GET /api/v1/capabilities`：`display.pdf` / `display.pdf.page` / `pdf.to_images` 均由 `客厅 · Mac Edge` 广告（pymupdf 门控生效）
- 未装 pymupdf 时三条不广告（单测覆盖）

## 未闭环项

- **DLNA 上屏**：小米电视开机后重发 B1/B2 即可补验（无需改码）。若电视 friendlyName 不含 `小米/xiaomi/mitv/电视/s pro`，在 `mac/.env` 设 `MAC_EDGE_XIAOMI_TV_NAME=<电视名子串>` 或 `MAC_EDGE_XIAOMI_TV_HOST=<IP>`。
- 云 Brain 侧仅做登记核对（`KNOWN_CAPABILITIES` 含三条新能力，`doubao_skill` active）；云链路投屏依赖边缘在线场景，未单独跑。

## 单测 / 回归（随 PR #39）

- 新增 46 例：`test_pdf_render.py` / `test_pdf_display.py` / `test_pdf_to_images.py` 全过
- mac 全量 743 passed（3 failed 为存量：`test_interval_rearm`×2、`test_voice_test`×1，base 同样失败）
- server 全量 374 passed（24 failed 均为存量，失败集与 base 完全一致）
