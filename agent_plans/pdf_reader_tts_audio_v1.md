# Plan：新增 `pdf.reader` 能力（PDF Asset → 可播放 TTS 音频）

> 落盘：task-6fa5db01b045488f · 开发分支 `feature/task-6fa5db01b045488f` · 交付方式：PR 到 main
>
> 需求原文：「实现一个 pdf.reader 功能，输入是一个 pdf 文件的 asset，输出是一段可以播放的 tts 音频」

## 1. 目标与定位

新增一个独立能力 `pdf.reader`：把本步已有的 **PDF/document Asset** 的文字抽出来，
合成为**一段可播放的 TTS 音频**，上传 Brain 登记为 **audio Asset**，产出 `asset_ref`。

- 用户场景：`念一下这份 PDF` / `把这份文档读给我听` / `朗读这个 PDF`。
- 交付闭环：语音入口把 `presentation` 设为 `{type: audio, from: asset_ref}`，
  Brain 组装后由发出端（iPhone 等）播放这段音频（现有 `IntentPresentation.audio`
  已支持带 asset 的音频播放，无需改端）。
- 与既有 PDF 能力分层：`pdf.to_images`（渲染图片）、`display.pdf`（投屏翻页）、
  `pdf.rotate`（旋转）、`printer.print`（打印）都不碰文字；`pdf.reader` 只做
  **抽文字 → 合成音频 → 登记 audio Asset**，不投屏、不打印、不 OCR、不播放。

## 2. 已确认决策汇总

| 维度 | 决策 |
|---|---|
| wire 能力 | `pdf.reader`（kind=`action`，group=`convert`，service_id=`local.pdf.reader`） |
| 执行层 | Mac Edge 插件（`mac_edge.plugins.pdf_reader`），Brain 只规划路由，不新增 server 依赖 |
| 输入 | `asset_ref`（必填，type=document）+ 可选 `page_start`/`page_end`/`lang`/`voice`/`speed`/`max_chars`/`name` |
| 输出 | `asset_ref`（audio）+ `page_count`/`page_start`/`page_end`/`chars`/`chars_total`/`truncated`/`duration_sec`/`engine`/`voice`/`text_preview`/`status_text` |
| 抽文字 | PyMuPDF `page.get_text()`，复用 `plugins/pdf_render.py`（与 `pdf.to_images` 同源） |
| 合成引擎 | `edge-tts` 神经音色（默认，mp3）；失败回退 macOS `say`（AAC/m4a） |
| 长文处理 | 按句切块（≤1000 字）→ 逐块合成 → 按 MP3 帧拼接（无 ffmpeg 依赖） |
| 页码语义 | 1-based；越界钳到边界；单次上限 200 页（与 `pdf.to_images` 一致，抽成共享函数） |
| 字数上限 | 默认 12000 字（≈40 分钟语音），按句边界截断并 `truncated=true`；`max_chars=0` 不截断 |
| 扫描件 | 抽不到文字 → 明确中文失败，提示先 `pdf.to_images` + `image.ocr`；本能力不 OCR |
| 依赖门控 | `pymupdf` 可导入 **且** 有可用 TTS 引擎（edge-tts 或 macOS say）才广告 |
| 执行超时 | 合成总时长默认 240s（`MAC_EDGE_PDF_READER_TIMEOUT_SEC`），小于 `MAC_EDGE_CAPABILITY_TIMEOUT_SEC`（300s） |

## 3. 能力标识与契约

- plugin id：`pdf-reader` · service_id：`local.pdf.reader` · group：`convert`
- wire capability：`pdf.reader` · kind：`action`
- 执行方：Mac Edge laptop（`mac_edge.plugins.pdf_reader`）

| 方向 | 内容 |
|------|------|
| 输入 | `asset_ref`（必填，AssetRef，`type=document` PDF）；`page_start`/`page_end`（可选，1-based 闭区间，缺省整份）；`lang`（默认 zh_CN）；`voice`；`speed`（默认 1.0，钳制 0.5–2.0）；`max_chars`（默认 12000）；`name` |
| 输出 | `asset_ref`（audio AssetRef，mime `audio/mpeg` / `audio/mp4`）；`page_count`；`page_start`/`page_end`；`chars`；`chars_total`；`truncated`；`duration_sec`；`engine`；`voice`；`text_preview`；`status_text` |

失败口径（明确中文、不产脏 Asset）：缺 `asset_ref` / 非 document / 物化失败 /
加密 / 空 PDF / 页范围无效 / 超 200 页 / 所选页无文字 / 合成失败（不上传半成品）/
上传登记失败。

## 4. 技术方案

- **抽文字**：`mac_edge/plugins/pdf_render.py` 新增
  `extract_page_texts(path, start, end)`（PyMuPDF `get_text("text")`）与共享页范围
  归一化 `normalize_page_range(...)`；`pdf_to_images.parse_page_range` 改为调用它
  （对外签名/失败文案不变，`what="渲染"`），`pdf.reader` 用 `what="朗读"`。
- **合成**：新增 `mac_edge/plugins/tts_file.py`（文本 → 音频文件，只合成不播放）：
  - `edge`：`edge_tts.Communicate(text, voice, rate)` 逐块合成 mp3 →
    `concat_mp3()` 去 ID3v2/ID3v1 后按帧拼接（实测 afplay/ffprobe 时长=各段之和）；
  - `say`：`say -v <voice> -r <rate> --file-format=m4af --data-format=aac -o x.m4a -f text.txt`
    （离线、一次性，长文走文件参数）；
  - `probe_duration_sec()`：ffprobe 优先，macOS 回退 `afinfo`；
  - edge 失败且 `MAC_EDGE_PDF_READER_TTS_FALLBACK_SAY`≠0 → 回退 say，
    `TtsResult.fallback_reason` 记录原因，`status_text` 会说明。
- **能力入口**：`mac_edge/plugins/pdf_reader.py` 的 `read_from_params(params, *, asset, ...)`
  ：校验 CapAsset → `require_ref`（必须 document）→ `materialize_file` →
  `pdf_page_count` → 页范围 → 抽文字 → 规整/拼接 → 字数截断 →
  `synthesize_speech` → `asset.upload_file(..., producer="pdf.reader", asset_type="audio")`
  → 汇总输出。
- **产物路径**：`MAC_EDGE_DATA_DIR/pdf-reader/<asset_id>/`（或 tempdir）。

## 5. 代码改动清单（逐文件）

1. `mac/src/mac_edge/plugins/pdf_render.py`：新增 `normalize_page_range` /
   `extract_page_texts`；docstring 扩为「渲染 + 文字提取」
2. `mac/src/mac_edge/plugins/pdf_to_images.py`：`parse_page_range` 改为复用共享函数
3. `mac/src/mac_edge/plugins/tts_file.py` 新建（共享合成底层）
4. `mac/src/mac_edge/plugins/pdf_reader.py` 新建（`pdf.reader`）
5. `mac/src/mac_edge/services.py`：`LOCAL_PDF_READER_SERVICE` + `_LAPTOP_SERVICE_ORDER`
   + `default_services()` 里按 `pdf_reader_available()` 门控广告
6. `mac/src/mac_edge/capability_ads.py` + `server/capability_ads.py`：`pdf.reader` 广告（同步）
7. `mac/src/mac_edge/executor.py`：import + `pdf.reader` 分发分支
8. `server/edge_services.py`：`KNOWN_CAPABILITIES['pdf.reader']`（schema 与 plugin 一致）
9. `plugins/pdf-reader/capability.md` + `manifest.yaml` 新建
10. `mac/tests/test_pdf_reader.py` / `mac/tests/test_tts_file.py` 新建单测
11. `agent_plans/pdf_reader_tts_audio_v1.md` 本计划落盘

不改：Brain 规划提示词（能力靠心跳 catalog + ads 发现）、iOS/Android、`server/` 其它逻辑
（`/api/v1/assets/upload` 已支持 `type=audio`）。

## 6. 测试

`mac/tests/test_tts_file.py`（新）：
- 切块：长文按句边界切、单句超长硬切、空文本 → `[]`；
- 截断：不超上限不动、`max_chars=0` 不截断、句边界截断、无边界硬切；
- 语速：默认/钳制/非法中文失败；音色：按语言默认 + 显式/环境覆盖；
- MP3 拼接：后续块去 ID3v2、去 ID3v1 尾巴、顺序保留、空段失败；
- 合成：空文本/未知后端中文失败；edge 假模块分块拼接成功；
  edge 失败回退 say（`fallback_reason`）；关掉回退则抛错；
  say 命令含 `--file-format=m4af --data-format=aac -f`、`-r` 随 speed 变、超时中文失败。

`mac/tests/test_pdf_reader.py`（新）：
- happy path：整份/指定页范围（越界钳制）→ 产出 audio `asset_ref`、上传参数
  `asset_type=audio`/`producer=pdf.reader`/文件名后缀随 mime；
- 失败：非 document / 缺 asset_ref / 页范围无效 / 超 200 页（且不上传）/
  无文字层（提示 OCR）/ 合成失败（不上传）/ 上传失败；
- 截断：`max_chars` 参数与 env 默认都生效、`status_text` 说明、`chars`/`chars_total`；
- 回退：`engine=say` + `duration_sec=None` + 「回退本机语音」文案；
- 有 pymupdf 时真 PDF 走默认抽字（中英文），否则 skip；
- 执行器分发 `pdf.reader`（成功 + 失败透传）；
- 广告门控：`pdf_reader_available()` 真/假 → `local.pdf.reader` 出现/消失。

回归：`cd mac && python3 -m unittest discover -s tests -p 'test_*.py' -q`（新 41 条全绿，
其余失败与 `main` 基线逐条一致）；`cd server && BRAIN_SKIP_LLM_WORKER=1 python3 -m unittest
discover -s tests -q`（与基线一致）。
真机验证（本机 venv 装 pymupdf/edge-tts）：真 PDF 3 页 → 抽字 → say 合成 m4a（`afinfo`
时长 7.2s）→ 模拟上传 `type=audio` 成功；edge-tts 分块拼接 mp3 时长 = 各段之和，`afplay`
可播。

## 7. 明确不做（另开任务）

- OCR：扫描件不识别（失败口子指向 `pdf.to_images` + `image.ocr`）；
- 播放编排：本能力只产出音频 Asset；「投到音箱/电视播」需要播放器能力（另开）；
- 语音克隆 / 多音色风格；逐页多音频资产；原文高亮跟读；
- 改 Brain 规划提示词或端上 UI（audio presentation 已支持）；
- 本任务只交付分支与 PR，不自行 merge、不触发 release/deploy。

## 8. 交付流程

任务工作区 `task-6fa5db01b045488f`，分支 `feature/task-6fa5db01b045488f`，
实现并单测 → `git commit` → `git push -u origin HEAD` → `gh pr create`，
PR URL 交给用户等待合入。


