# paper.read v1 — 论文听读能力（设计 + 落地计划）

**状态：** 待确认（代码未开工，先落盘 plan）
**版本：** v1（2026-09-16）
**近邻：** [`plugins/pdf-reader/capability.md`](../plugins/pdf-reader/capability.md)（已上线的 `pdf.reader`）
**参考：** `mokawa3018-ctrl/paper-reader-skill`（结构化解析）· `soumyasj/pdf2speech`（朗读清洗）· `techdou/paper-reading`（Explain 阅读链）· `dayangxing/Paper-reader-skill`（三层深度）

---

## 1. 目标与边界

一句话：**Read an academic paper and produce faithful or explanatory spoken content optimized for continuous listening.**

| 负责 | 不负责 |
|---|---|
| 论文 → 适合**连续听读**的 spoken content，并合成一段可播放音频 | PDF 解析（复用 `pdf_render` / PyMuPDF） |
| Original：忠实原文的听觉重排 | TTS 实现（复用 `tts_file`） |
| Explain：证据约束的 AI 讲解 | Markdown 报告 / 知识卡片 / 播客（其它 capability） |

不做：`Paper → Markdown Report`、`Paper → Summary`、`Paper → Podcast`。

---

## 2. 本仓现状映射（不另起炉灶）

| 概念（你 spec 里） | 本仓落点 | 现状 |
|---|---|---|
| Document Asset | Brain `assets` 表 `type=document` + `mac_edge/asset/sdk.py` | ✅ 已有（pdf.reader 在用） |
| Paper Structure | 新增 `mac_edge/plugins/paper_structure.py` | 🆕 |
| Text Cleaning（Original） | 新增 `mac_edge/plugins/paper_clean.py` | 🆕 |
| Paper Understanding（Explain） | 新增 `mac_edge/plugins/paper_explain.py`；LLM 走既有 `mac_edge/plugins/query_providers/`（ARK / OpenAI 兼容，`ARK_API_KEY` / `MAC_EDGE_QUERY_*`） | ♻️ 复用 provider 栈 |
| TTS | `mac_edge/plugins/tts_file.py`（edge-tts mp3，失败回退 macOS say） | ♻️ 复用 |
| Audio Artifact | `asset.sdk.register_img_server(..., metadata={...})` → audio Asset（metadata 可放 section 索引） | ♻️ 复用 |
| 播放 / 端上呈现 | `presentation={type: audio, from: asset_ref}`（iOS `AudioBubblePlayer`） | ♻️ 复用（端上已支持） |
| 能力广告 / 路由 | `mac_edge/services.py` + `mac_edge/capability_ads.py` + `server/{capability_ads,edge_services}.py` | 仿 `pdf.reader` 五处接线 |

**结论：paper.read 不需要新依赖、不需要改端**（v1）；它是「论文结构 + 两种模式」这一层的新能力。

---

## 3. Capability 定义（wire）

```text
paper.read   kind=action   group=read   service_id=local.paper.read
```

**输入 schema（planner 可见）**

| 参数 | 必填 | 说明 |
|---|---|---|
| `asset_ref` | ✅ | AssetRef JSON，`type=document`（PDF，需有文字层） |
| `mode` | | `original`（默认，忠实听读）/ `explain`（证据约束讲解） |
| `depth` | | explain 时用：`overview`（默认）/ `method` / `deep` |
| `page_start` / `page_end` | | 1-based 闭区间，页码语义与 `pdf.to_images` / `pdf.reader` 同源 |
| `lang` / `voice` / `speed` | | 同 `pdf.reader`（默认 zh_CN / zh-CN-XiaoxiaoNeural） |
| `max_chars` | | 合成字数上限（默认与 pdf.reader 一致 12000，0=不截断） |
| `name` | | 音频展示名 |

**输出**

| 字段 | 说明 |
|---|---|
| `asset_ref` | audio AssetRef（presentation `{type:audio, from:asset_ref}` 直接播） |
| `mode` / `depth` | 回显 |
| `sections[]` | `{index, type, heading, chars, est_offset_sec}` —— section 级索引（放 asset metadata + step outputs） |
| `duration_sec` / `chars` / `truncated` / `engine` / `voice` | 同 pdf.reader 口径 |
| `status_text` | 中文一句话（含模式、时长、是否截断、讲解层数） |

---

## 4. Paper Structure（v1：deterministic，不调 LLM）

`paper_structure.py`，输入 PDF 路径，输出：

```python
PaperStructure(
  meta={"title": str|None, "pages": int},
  sections=[Section(type, heading, paragraphs[], pages, chars)],
  figures=[Figure(caption, page)], tables=[...],
  references_dropped=True,
)
```

步骤与规则：

1. **阅读顺序**：PyMuPDF blocks 先按「双栏检测」排序（移植 `pdf2speech` 的 `_detect_column_margins` / `_sort_blocks_two_column` 思路），避免跨栏串行。
2. **去页眉 / 页脚 / 页码**：页边界高度带内重复文本 + `^\d{1,4}$` 行剔除。
3. **章节识别**：新增 `DEFAULT_SECTION_TYPES` 映射表（借 mokawa `section-patterns.md`）+ 正则 + 字号/加粗启发：
   `introduction / related_work / method / experiment / results / discussion / conclusion / references`，**保留原 heading，拿不准 → `other`**。
4. **丢掉 References 及其后**（v1 硬截断）。
5. **Figure / Table caption**：v1 只识别 + 记位置（Explain 用），Original **不念**。

---

## 5. Original Mode（忠实听读，**全程不调 LLM**）

「不调 LLM」是本模式的关键设计：保真 = 不引入幻觉，且快（一篇 20 页论文秒级出脚本）。

**允许**（可以做的清理）：

| 规则 | 实现（借 `pdf2speech.preprocess_text`） |
|---|---|
| 断词修复 | `(\w)-\n(\w)` → 合并（`meth-\nod` → `method`） |
| 续行拼接 | `\n(?=[a-z,;])` → 空格 |
| 删 URL / 邮箱 | `https?://\S+`、`\S+@\S+\.\S+` |
| 删引文编号 | `\[\d[\d,\s\-–]*\]`、`\[[A-Z][^]]{1,40}\d{4}\]` |
| 删页码 / 页眉页脚 | 结构层已去 + `(?m)^\d{1,4}$` |
| 公式语音化 | `$$…$$` → 「公式」，inline `$x$` → 保留变量名（读作「变量 x」） |
| 图表引用自然化 | `(Fig(ure)?|Table|Eq(uation)?|Algorithm)\.?\s*\d+` → 「图三 / 表二 / 公式四」（中文数字，规则化，不调 LLM） |
| 标题朗读化 | ALL CAPS / 独立行标题 → 「下面是<标题>部分。」 |
| 排版合并 | 多空格/多空行归一；不把 caption 混进正文 |

**禁止**（Original 红线，写进 capability 文档与代码注释）：

- 不总结作者观点、不加作者没说的结论、不改技术含义
- 不删关键实验结果、不对方法加自己的解释、不用类比替换概念
- 不补论文外知识（含模型自身知识）

> Faithful to the paper, optimized for listening.

---

## 6. Explain Mode（证据约束讲解）

**LLM 路径**：复用 `query_providers`（默认 `ark`，`ARK_API_KEY` 已在 `mac/.env`），**不复用** `query.content` 的 prompt（自带 prompt + 自己的输出 schema）。

**Prompt 结构（三层）**：每层 = 任务 + 已选 section 片段 + 硬约束 + JSON schema。
输入按 depth 裁剪（不喂全文，控制 token 与幻觉面）：

| depth | 喂给 LLM 的 section | 回答的问题（spec §4） |
|---|---|---|
| `overview` | Abstract + Intro 首尾段 + Conclusion + 主结果段 | 解决什么问题 / 为什么重要 / 核心思想 / 主要结果 / 真正贡献 |
| `method` | Method/Approach 全节（+ 关键公式上下文） | 架构 / 核心模块 / 数据流 / 算法流程 / 模块关系 →「它到底怎么工作」 |
| `deep` | Method + Experiment + Ablation + Limitations（v1.1） | 公式细节 / 参数变量 / baseline / 实验设计 / limitations / 可复现性 |

**输出 schema（保真关键）**：

```json
{"narration":[{"section":"Method","kind":"fact|synthesis|inference","text":"…"}]}
```

- `fact` —— 只能直述论文写了什么（「作者提出…」「实验显示…」）
- `synthesis` —— Agent 的归纳，必须显式措辞（「这里的意图可以理解为…」）
- `inference` —— Agent 的推测，必须标注（「（以下是我的推测）」）
- 行文按顺序拼成 spoken script；**不允许把 inference 写成作者观点**

**硬约束**（prompt + 代码双保险）：

1. 出现的每个**数字/指标/数据集/对比**必须能在原文找到（代码做白名单校验，命中不了就丢该句并记 warning）
2. 原文没写就直说「论文里没有写」
3. 不补论文外知识；确需背景时单列一段且措辞标注（可选，默认关）
4. 公式：v1 只讲「这个公式在算什么」，不逐符号展开（symbol-level 留给 v1.1 deep）
5. 温度低（0.2）、只输出一层 JSON、必须中文（英文术语保留原词）

**失败口径**：无 key / 超时 / JSON 解析失败 → 明确中文失败（不产半成品音频）；**可选**降级为 `original`（决策点 C）。

---

## 7. 接线点（文件级）

**新增**

```text
mac/src/mac_edge/plugins/paper_structure.py     # PDF → PaperStructure（deterministic）
mac/src/mac_edge/plugins/paper_clean.py         # Original 清洗规则（纯函数，好测）
mac/src/mac_edge/plugins/paper_explain.py       # Explain 选段 + prompt + LLM + 校验
mac/src/mac_edge/plugins/paper_read.py          # entry: read_from_params(params, asset=…)
plugins/paper-reader/manifest.yaml              # 仿 plugins/pdf-reader/manifest.yaml
plugins/paper-reader/capability.md              # 仿 plugins/pdf-reader/capability.md
mac/tests/test_paper_structure.py
mac/tests/test_paper_clean.py
mac/tests/test_paper_read.py                    # LLM 用 fake provider，不联网
```

**改动（五处接线，逐条对齐 pdf.reader）**

| 文件 | 改动 |
|---|---|
| `mac/src/mac_edge/executor.py` | import + `if cap == "paper.read":` 分支（对齐 L1624 的 `pdf.reader`） |
| `mac/src/mac_edge/services.py` | 新增 `service_id=local.paper.read` 契约 + 广告门控（`pymupdf` + TTS 引擎 + explain 需 LLM key） |
| `mac/src/mac_edge/capability_ads.py` | 新 ad（role/planner_recognize/typical_triggers/do_not_dispatch） |
| `server/capability_ads.py` | 同上（Brain 规划用） |
| `server/edge_services.py` | `KNOWN_CAPABILITIES['paper.read']` |

**`planner_recognize` 分工（与 pdf.reader 明确划界）**：

- `pdf.reader` = 通用短文档「念一下这份 PDF」，不结构、不讲解
- `paper.read` = **论文/长文献**的结构化听读（`original`）或讲解（`explain`），触发词含「这篇论文/paper/研究/论文讲解/帮我看懂这篇 paper」

---

## 8. 分阶段

| 阶段 | 范围 |
|---|---|
| **v1（本次）** | `original` + `explain.overview` + `explain.method`；单 audio Asset + `sections[]` 索引；Mac Edge 执行 |
| v1.1 | `explain.deep`；`text.to_speech` 拆成独立 wire capability；per-section 音频（可跳节）；OCR / text Asset 输入；arXiv / HTML / Markdown 输入 |
| v2 | 端上按 section 跳转（iOS 需新契约）；跨论文对比；追问式深读（「Method 第二部分再讲一遍」） |

---

## 9. 测试与验收

- **单测（不联网）**：结构（双栏/页眉页码/章节切分/References 截断）、清洗（每条正则 1 case）、prompt 组装 + `kind` 约束 + 数字白名单、LLM 失败路径、异常输入（加密/无文字层/页范围非法/超页数）
- **黑盒**：库里现成 `strips.pdf`（20 页、45,489 字，有文字层）+ 一份双栏论文 → 出音频、听开头/中段、检查 `status_text` 与 `sections[]`
- **回归**：`pdf.reader` 必须无回归（共用 `pdf_render` / `tts_file` 底层）

---

## 10. 风险

1. **长文 TTS 时长**：论文 4.5 万字 → 默认 `max_chars=12000` 会截断（status_text 说明）；合成总预算仍受 `MAC_EDGE_CAPABILITY_TIMEOUT_SEC` 约束 → v1 建议「默认截断 + 明确提示 + 支持 page 范围/分段」
2. **讲解幻觉**：数字白名单 + `kind` 标注是主要防线；Explain 出稿前不落音频（失败即明确失败）
3. **双栏 / 公式重排**：v1 只做保守重排（拿不准不动），bad case 记进 `mac/tests` fixtures
4. **端上跳节**：`sections[]` 只是 metadata，iOS 要能「跳到 Method」需 v2 改端

---

## 11. 待用户确认（5 项，均附我的默认建议）

| # | 决策 | 我的默认 |
|---|---|---|
| **A** | 与已上线 `pdf.reader` 的关系 | **并存 + planner 分工**（pdf.reader 管通用短文档，paper.read 管论文/长文献） |
| **B** | 本次是否就把 TTS 拆成独立 capability `text.to_speech` | **v1 先内部复用 `tts_file`**，v1.1 再拆（拆了要动 pdf.reader，风险外溢） |
| **C** | Explain 的 LLM 走哪条路 | **复用 edge `query_providers`（ARK）**；失败时**明确失败**（不静默降级 original） |
| **D** | section 音频粒度 | **单个 audio Asset + `sections[]` 索引**（per-section 多文件放 v1.1） |
| **E** | 首发深度范围 | **original + explain.overview + explain.method**（method 是论文听读最有用的一层，成本只是多一段 prompt） |

确认后我按第 7 节的文件清单开工，走同一分支 + PR（不自行合入）。
