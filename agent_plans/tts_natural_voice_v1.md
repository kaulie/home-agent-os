# TTS 自然度 v1 — 按正文语言选音色 + 减少拼接接缝 + 脚手架语言跟随正文

**状态：** 已实现，待合并/部署
**版本：** v1（2026-09-16）
**触发：** 用户反馈「我可以听到声音了，但是语音阅读不是很自然，有更自然连贯的人声音色吗」

---

## 1. 诊断（对着现网事实核过，不是猜）

| 事实 | 证据 |
|---|---|
| 用户听的那份「PDF 论文」是 **英文** 的 | Asset `asset_ce028c7f3692b41347d53494` = `strips.pdf`（1971 STRIPS 论文，20 页）；用 PyMuPDF 抽字：**CJK 0 / 拉丁 34175**，纯英文 |
| 却用了 **中文音色** `zh-CN-XiaoxiaoNeural` | 现网日志 `mac_edge.out`：`edge-tts ok voice=zh-CN-XiaoxiaoNeural rate=+0% chunks=17 bytes=4955616`、`paper.read ok … engine=edge voice=zh-CN-XiaoxiaoNeural` |
| 根因 | `pdf_reader` / `paper_read` 都写死 `lang = raw_params.get("lang") or "zh_CN"`；`resolve_edge_voice` 只看 `lang`，**从不看正文是什么语言** |
| 次因 1：拼接接缝多 | 切块上限 1000 字 → 这篇 11521 字被切成 **17 块**，每块一次独立合成（语气重置 + 尾静音），长文听感「一顿一顿」 |
| 次因 2：脚手架是中文 | `paper_clean` 的标题行/章节引言/图表引用写死中文：`论文标题：…。`、`下面是 ABSTRACT 部分。`、英文句子里冒出「图一」（脚本 42052 字里有 26 行含中文）——即使换了英文音色，这些中文仍会夹在英文里 |

## 2. 改了什么

| 文件 | 改动 |
|---|---|
| `mac/src/mac_edge/plugins/text_lang.py`（新） | `detect_lang`（CJK 字数 vs 拉丁词数，阈值 0.3：中文论文里的英文术语不会把语言带偏）、`normalize_lang`、`lang_key`。TTS 与脚手架**用同一个判定** |
| `mac/src/mac_edge/plugins/tts_file.py` | 音色优先级：显式 `voice` > env `MAC_EDGE_PDF_READER_VOICE` > 显式 `lang` > **正文语言自动判定** > 该语言默认。新增 env `MAC_EDGE_PDF_READER_VOICE_ZH` / `..._VOICE_EN`；英文默认 `en-US-AriaNeural` → **`en-US-AvaMultilingualNeural`**；切块上限 1000 → **3000 字**（接缝 17 → 6）；`synthesize_speech(lang=None)` = 自动 |
| `mac/src/mac_edge/plugins/pdf_reader.py` | `lang` 缺省改为 None（交给自动判定），显式传入仍以调用方为准 |
| `mac/src/mac_edge/plugins/paper_clean.py` | 引用话术/标题脚手架跟随正文语言：中文「图二 / 下面是…部分。」，英文「Figure 2 / Next, the … section.」；`build_original_pieces(structure, script_lang=…)` 缺省按正文判定 |
| `mac/src/mac_edge/plugins/paper_read.py` | 判一次语言（显式 `lang` 优先，否则正文判定），**脚手架和音色都用它**，不会出现「英文正文 + 中文脚手架/中文音色」 |
| `mac/src/mac_edge/services.py`、`server/edge_services.py` | `lang` / `voice` 入参描述改成「不传则按正文语言自动判定」 |
| `plugins/pdf-reader/capability.md`、`plugins/paper-reader/capability.md` | 同上 + 音色 env 说明 |
| `mac/tests/test_tts_file.py`、`test_paper_clean.py` | 新增：英文正文→英文音色、显式 lang 优先、中英混排判中文、env 分语言音色、英文脚手架/引用；更新 2 个原先把「英文正文 + 中文脚手架」写成期望的用例 |

## 3. 验收

- 单测：`test_tts_file` 29 ✅、`test_paper_clean` / `test_paper_read` / `test_pdf_reader` 共 85 ✅
- 全量 `mac/tests` 887 个：失败集合与 `origin/main` 基线 **逐条一致**（都是既有的 interval_rearm / 环境相关项，无回归）
- 真链路（真 edge-tts）：英文正文 → `voice=en-US-AvaMultilingualNeural`；中文正文 → `voice=zh-CN-XiaoxiaoNeural`；
  真 PDF（strips.pdf 20 页）重跑脚本：**CJK 0 字**（脚手架全英文），1500 字 → 1 块 / 95.6 秒音频
- 样音（局域网可播，见 §4）

## 4. 音色候选（样音已放 `mac/data/xiaodu-tts/`，本机 HTTP `:8000` 直接播）

| # | 文件 | 音色 | 说明 |
|---|---|---|---|
| 1 | `voice-1-xiaoxiao-current.mp3` | `zh-CN-XiaoxiaoNeural` | **现在听到的**（中文女声念英文，对照用） |
| 2 | `voice-2-ava-en.mp3` | `en-US-AvaMultilingualNeural` | 本次默认（女，自然、亲和） |
| 3 | `voice-3-andrew-en.mp3` | `en-US-AndrewMultilingualNeural` | 男，沉稳 |
| 4 | `voice-4-emma-en.mp3` | `en-US-EmmaMultilingualNeural` | 女，对话感 |
| 5 | `voice-5-brian-en.mp3` | `en-US-BrianMultilingualNeural` | 男，随意 |
| 6 | `voice-6-aria-en.mp3` | `en-US-AriaNeural` | 老一代英文女声（对照） |
| A/B | `ab-old-zhvoice.mp3` / `ab-new-envoice.mp3` | — | 同一篇论文开头 45 秒：旧（中文音色念英文）/ 新（英文音色 + 英文脚手架 + 更大块） |

换音色不用改代码：`MAC_EDGE_PDF_READER_VOICE_EN=<音色名>`（或 `MAC_EDGE_PDF_READER_VOICE=<音色名>` 强制所有语言）。

## 5. 下一步（未做，等用户定）

- 音色最终选择（样音听感由用户定，默认给 Ava）。
- 扫描件 OCR 噪声：这篇是 1971 年扫描件，OCR 本身有错（`ARTIFIC~L r~rELUOE~CE`、`spcce`、`n,~del`），
  TTS 会把错的词照念 —— 这是「听感不自然」的另一半原因。要治得做 OCR 纠错层（可能与「不调 LLM」红线冲突，
  需单独决策）。
- 更高音质：edge-tts 只给 24kHz/48kbps mono mp3（现网实测 `bit rate: 48000`）。要真上台阶得换引擎
  （Azure Speech 付费音色 / 本机神经 TTS），本机是 Intel i7 无 GPU，本地方案要单算成本。
