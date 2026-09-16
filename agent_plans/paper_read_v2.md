# paper.read v2 — 用户确认与 v1 实际交付范围

**状态：** 已确认并开工（v1 交付 original 原文模式）
**版本：** v2（2026-09-16）
**前一版：** [`paper_read_v1.md`](paper_read_v1.md)（设计与落地计划，5 个决策点）—— 除范围外均按 v1 执行

---

## 1. 用户确认（2026-09-16）

> 「先做 original 模式，explain 保留，其他安妮[按你]的默认来」

| # | 决策（v1 §11） | 结论 |
|---|---|---|
| 范围 | v1 首发深度 | **只交付 `original` 原文模式**；`explain` **保留**（契约固定、调用即明确中文失败），实现留到下一版 |
| A | 与已上线 `pdf.reader` 的关系 | 采纳默认：**并存 + planner 分工**（pdf.reader 管通用短文档，paper.read 管论文/长文献） |
| B | TTS 是否拆成独立 capability | 采纳默认：**v1 内部复用 `tts_file`**，不拆（拆了动 pdf.reader，风险外溢） |
| C | Explain 的 LLM 路径 | 采纳默认：复用 edge `query_providers`（ARK）；失败**明确失败**，不静默降级 |
| D | section 音频粒度 | 采纳默认：**单个 audio Asset + `sections[]` 索引** |
| E | 首发深度范围 | 被「先做 original」覆盖：`explain.overview` / `explain.method` 顺延到 explain 交付时一起做 |

## 2. 本次交付清单（实际落地）

```text
mac/src/mac_edge/plugins/paper_structure.py   # PDF → PaperStructure（deterministic，不调 LLM）
mac/src/mac_edge/plugins/paper_clean.py       # original 清洗规则（纯函数）
mac/src/mac_edge/plugins/paper_read.py        # 入口 read_from_params
mac/src/mac_edge/plugins/paper_explain.py     # explain 契约保留（v1 调用即明确失败）
plugins/paper-reader/manifest.yaml + capability.md
mac/tests/test_paper_structure.py / test_paper_clean.py / test_paper_read.py   # 47 个单测
接线五处：executor.py / services.py（+ _LAPTOP_SERVICE_ORDER）/ capability_ads.py /
        server/capability_ads.py / server/edge_services.py（KNOWN_CAPABILITIES）
```

与 v1 §7 的差异：**不新增** `explain` 的实现（只留契约）；其余文件与接线点完全按 v1 执行。
`wire`/`service_id`/输入 schema 与 v1 §3 一致（`mode` 默认 `original`，`depth` 已预留）。

## 3. 验收证据

- 单测：`mac/tests/test_paper_*.py` **47 个全绿**；全量 `mac/tests` 879 个的失败集合与改动前
  **完全一致**（无回归，失败项均为环境缺依赖 / 既有 interval_rearm 用例）。
- 真 PDF（合成论文页：双栏、页眉、页码、图表题注、References）：
  `references_dropped=true`、caption 只记不念、页码/页眉剔除、
  正文句中「Table 3 … 8 datasets / 92.5」**保留**（红线）。
- 真链路（真实 pymupdf + 真实 edge-tts）：产 mp3 194 KB / **32.4 秒**，`engine=edge`，
  `status_text` = 「已按原文模式听读《…》第 1–1 页（共 1 页，4 节）共 339 字，约 32 秒…」。

## 4. 下一版（explain）

按 v1 §6 实现：`paper_explain.py` 已把 `depth` 三层、narration schema（fact/synthesis/inference）、
数字白名单与失败口径写死；LLM 走 `mac_edge.plugins.query_providers`（ARK）。
planner 侧无需改动（`mode` / `depth` 已在 `input_schema` 里）。
