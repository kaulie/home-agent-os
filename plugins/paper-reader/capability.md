# Service: local.paper.read

论文听读插件（`paper-reader`），group=`read`。

把已有的 `type=document`（PDF 论文）Asset 的指定页范围（缺省整份）解析成 **Paper
Structure**（章节结构），再按阅读模式产出 **适合连续听读的 spoken content**，合成为
**一段可播放的 TTS 音频**（edge-tts 神经音色 mp3；网络/引擎不可用时回退 macOS `say`
AAC），上传 Brain 登记为 **audio Asset**，产出 `asset_ref`。

```text
PDF/OCR Document → Paper Structure → paper.read → Spoken Content → TTS → Audio Artifact

paper.read ├── original   # 原文听读（v1 已交付，全程不调 LLM）
           └── explain    # AI 解析讲解（v1 保留未交付：调用即明确中文失败）
```

用户场景：`把这篇论文念给我听` / `听读这篇 paper` / `这篇论文太长了听一遍`。语音入口
默认把 presentation 设为 `{type: audio, from: asset_ref}`，发出端（iPhone 等）直接播放。

**与 `pdf.reader` 的分工**：`pdf.reader` 管「念一下这份 PDF」这类通用短文档（不做结构、
不跳 References）；`paper.read` 管**论文 / 长文献**的结构化听读（识别章节、跳 References
与页眉页脚、不念图表说明、回 `sections[]` 索引）。两者并存，由 planner 按触发词分工。

**Brain 不执行**；只通过心跳看到 `paper.read`，再把 plan 派到广告了该能力的 Mac Edge
（`mac_edge.plugins.paper_read`）。本机可 import pymupdf 且存在可用 TTS 引擎
（`edge-tts` 或 macOS `say`）时才广告。

## 规划自描述

| 字段 | 值 |
|------|-----|
| role | 论文听读器（论文/长文献 → 结构化听读音频） |
| planner_recognize | 把已有的论文 PDF/document Asset 转成适合连续听读的音频：用户说「把这篇论文念给我听 / 听读这篇 paper / 这篇论文太长了听一遍 / 帮我听读这篇研究」时用本步。与 pdf.reader 的分工：pdf.reader 只管「念一下这份 PDF」这类通用短文档；本步面向论文/长文献，会做结构（识别章节、跳过 References 与页眉页脚、不念图表说明），并回 sections[] 索引。入参 asset_ref（必填，type=document，常为 $asset_ref）；mode 默认 original（原文听读），可选 page_start/page_end、speed、voice、max_chars（lang 不传时按正文语言自动选音色）。产出 audio AssetRef。用户没指定哪篇论文时，先排 asset.inventory 取最新 document 再接本步。mode=explain v1 保留未交付，传了会明确失败；扫描件（无文字层）会失败，要先 pdf.to_images + image.ocr |
| typical_triggers | `把这篇论文念给我听`、`听读这篇 paper`、`这篇论文太长了，听一遍`、`帮我听读这篇研究`、`朗读这篇论文` |
| do_not_dispatch | 念一份普通 PDF/说明书（用 pdf.reader）、论文总结 / Markdown 报告、论文问答、打印、投屏、OCR 识别、PDF 转图片、PDF 旋转、提醒/公告短句播报、放歌 |

## 标识

| 字段 | 值 |
|------|-----|
| plugin id | `paper-reader` |
| service_id | `local.paper.read` |
| group | `read` |
| wire capability | `paper.read` |
| kind | `action` |
| 执行方 | Mac Edge laptop（`mac_edge.plugins.paper_read`） |

## 契约

| 方向 | 内容 |
|------|------|
| **输入** | `asset_ref`（必填，AssetRef，`type=document` PDF 论文）；`mode`（可选，默认 `original`；`explain` v1 保留未交付）；`depth`（可选，explain 的层数 `overview`/`method`/`deep`，original 忽略）；`page_start` / `page_end`（可选，1-based 闭区间，缺省整份，越界钳到边界，单次上限 200 页）；`lang`（可选，`zh_CN` / `en_US`；不传则按正文语言自动判定）；`voice`（可选音色名，如 `en-US-AvaMultilingualNeural`）；`speed`（可选语速倍率，默认 1.0，钳制 0.5–2.0）；`max_chars`（可选字数上限，默认 12000，0=不截断）；`name`（可选音频展示名） |
| **输出** | `asset_ref`（**audio** AssetRef）；`mode` / `depth`（回显）；`title`（识别到的论文标题，可为 null）；`page_count`；`page_start` / `page_end`；`sections[]`（`{index, type, heading, chars, page_start, page_end, est_offset_sec}`）；`sections_count`；`chars` / `chars_total` / `truncated`；`duration_sec`；`engine`（edge/say）；`voice`；`text_preview`；`status_text`（中文一句话） |

缺 `asset_ref` / 非 `document` / 读不了文件 / 加密 / 空 PDF / 页范围无效 / 超 200 页 /
所选页无正文（扫描件）/ 合成失败 / `mode=explain`（v1）→ **明确中文失败**，不产生脏
Asset（合成失败时不上传半成品）。

## Paper Structure（v1：确定性规则，不调 LLM）

1. **阅读顺序**：block 先按双栏检测排序（中缝带无块 + 左右各有 ≥3 块 → 双栏），避免跨栏串行；
2. **去页眉 / 页脚 / 页码**：页边界高度带（上 8% / 下 8%）内的短块、`^\d{1,4}$`、跨页重复文本；
3. **章节识别**：`abstract / introduction / related_work / method / experiment / results /
   discussion / conclusion / references / acknowledg / appendix` + 编号（`3.2`、`IV.`）+ 字号/加粗启发；
   保留原 heading，拿不准 → `other`；识别不到标题 → 全篇单节 `full`；
4. **References 硬截断**：命中 references/bibliography 标题即停止（`references_dropped`）；
5. **Figure / Table caption**：只识别 + 记页码（original **不念**）。

## Original Mode（忠实听读，全程不调 LLM）

允许的清理（全部规则化、可单测）：断词修复（`meth-\nod` → `method`）、续行拼接、删 URL /
邮箱、删引文编号（`[12]` / `[3-5]` / `[Smith et al. 2020]`）、删页码与版式噪声（arXiv 戳 /
Preprint / Copyright）、公式语音化（`$$…$$` → 「公式」；`$x$` → 保留变量名）、图表引用自然化
（中文正文：`Fig. 2` → 图二；英文正文：`Fig. 2` → `Figure 2`）、标题朗读化（中文「下面是<标题>部分。」/ 英文「Next, the <标题> section.」——脚手架话术跟随正文语言）、
多空格/多空行归一。caption 不进正文。

**Original 红线**（代码与文档同时约束）：不总结作者观点、不加作者没说的结论、不改技术含义、
不删关键实验结果、不对方法加自己的解释、不用类比替换概念、不补论文外知识。

## Explain Mode（v1 保留未交付）

接口、`depth` 三层与输出 schema 已固定在 `mac_edge/plugins/paper_explain.py`，plan 见
`agent_plans/paper_read_v1.md` §6。v1 调用 `mode=explain` → **明确中文失败**（不静默降级
成 original，不产半成品音频）。下一版实现要点：LLM 走 edge 既有 `query_providers`（ARK）、
喂段按 depth 裁剪、输出 `{"narration":[{section, kind: fact|synthesis|inference, text}]}`、
数字白名单校验、`inference` 必须显式标注。

## 音频语义与引擎

- **长文**：按句边界切块（每块 ≤ 3000 字），逐块合成后按 **MP3 帧** 拼接成一个 mp3（无需
  ffmpeg）——`afplay` / `AVPlayer` / 浏览器都能整段播放。`say` 后端一次性合成 .m4a。
- **音色**：按**正文语言**自动选（`lang` 不传时）：中文→`zh-CN-XiaoxiaoNeural`，英文→`en-US-AvaMultilingualNeural`（edge-tts 神经音色）。显式 `voice` 参数 > env 全语言 `MAC_EDGE_PDF_READER_VOICE` > env 分语言 `MAC_EDGE_PDF_READER_VOICE_ZH` / `..._VOICE_EN` > 该语言默认。一篇英文论文用中文音色朗读会带明显口音——所以别把 `lang` 写死成 `zh_CN`。
- **上限**：单次 ≤ 200 页、≤ `max_chars`（默认 12000 ≈ 40 分钟语音；截断落在句边界，
  `truncated=true` 并在 `status_text` 提示可分段听读）；合成总时长 ≤
  `MAC_EDGE_PDF_READER_TIMEOUT_SEC`（默认 240s）。
- **sections[]**：单音频 + section 索引（`est_offset_sec` 按字符占比 × 时长估算）；
  端上按节跳转需要新契约（v2）。

## 技术实现

- **结构**：`mac_edge/plugins/paper_structure.py`（PyMuPDF `get_text("dict")`，复用
  `mac_edge.plugins.pdf_render._fitz`）；**清洗**：`mac_edge/plugins/paper_clean.py`；
  **合成**：共享 `mac_edge/plugins/tts_file.py`；**上传**：`CapAsset.upload_file`
  （`producer=paper.read`、`type=audio`）。
- **产物落盘**：`MAC_EDGE_DATA_DIR/paper-reader/<asset_id>/`。

## 入口

- Mac：`mac/src/mac_edge/plugins/paper_read.py`；`services.py` 广告 `local.paper.read`
  （laptop 角色且 `paper_read_available()` 为真时广告）
- 执行器：`mac/src/mac_edge/executor.py` 的 `paper.read` 分支
- 协议登记：`server/edge_services.py` 的 `KNOWN_CAPABILITIES["paper.read"]`；
  `server/capability_ads.py` 与 `mac/src/mac_edge/capability_ads.py` 同步广告
- 单测：`mac/tests/test_paper_structure.py` / `test_paper_clean.py` / `test_paper_read.py`
