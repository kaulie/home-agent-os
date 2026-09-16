# Service: local.pdf.reader

PDF 语音朗读插件（`pdf-reader`），group=`convert`。
把已有 `type=document`（PDF）Asset 指定页范围（缺省整份）的**文字**经 **PyMuPDF**
抽出来，再合成为**一段可播放的 TTS 音频**（edge-tts 神经音色 mp3；网络/引擎不可用时
回退 macOS `say` AAC），上传 Brain 登记为 **audio Asset**，产出 `asset_ref`。

用户场景：`念一下这份 PDF` / `把这份文档读给我听` / `朗读这个 PDF`。语音入口默认把
presentation 设为 `{type: audio, from: asset_ref}`，发出端（iPhone 等）直接播放这段
音频；产物也可交下游复用（转存、投设备、再合成等）。

**Brain 不执行**；只通过心跳看到 `pdf.reader`，再把 plan 派到具备该能力的 Edge
（Mac Edge laptop，`mac_edge.plugins.pdf_reader`）。本机可 import pymupdf 且存在可用
TTS 引擎（`edge-tts` 或 macOS `say`）时才广告。

## 规划自描述

| 字段 | 值 |
|------|-----|
| role | PDF 语音朗读器 |
| planner_recognize | 把本步已有的 PDF/document Asset 的文字念成一段语音（TTS 音频 Asset）。入参 asset_ref（必填，type=document，常为 $asset_ref），可选 page_start/page_end、speed、voice、max_chars（lang 不传时按正文语言自动选音色）。产出 audio AssetRef——语音入口把 presentation 设为 `{type:audio, from:asset_ref}` 播放这段朗读；用户没指定哪份 PDF 时，先排 asset.inventory 取最新 document 再接本步。只念文档正文，不是短提醒/公告（那种用 notify.speak）；扫描件（无文字层）会失败，要先 pdf.to_images + image.ocr |
| typical_triggers | `念一下这份 PDF`、`把这份文档读给我听`、`朗读这个 PDF`、`把 PDF 转成语音`、`读一遍这个文档` |
| do_not_dispatch | 打印、投屏、看图理解、OCR 识别、拍照、提醒/公告短句播报、放歌、PDF 转图片、PDF 旋转 |

## 标识

| 字段 | 值 |
|------|-----|
| plugin id | `pdf-reader` |
| service_id | `local.pdf.reader` |
| group | `convert` |
| wire capability | `pdf.reader` |
| kind | `action` |
| 执行方 | Mac Edge laptop（`mac_edge.plugins.pdf_reader`） |

## 契约

| 方向 | 内容 |
|------|------|
| **输入** | `asset_ref`（必填，AssetRef，`type=document` PDF）；`page_start` / `page_end`（可选，1-based 闭区间，缺省整份，越界钳到边界，单次上限 200 页）；`lang`（可选，`zh_CN` / `en_US`；不传则按正文语言自动判定）；`voice`（可选音色名，如 `en-US-AvaMultilingualNeural`）；`speed`（可选语速倍率，默认 1.0，钳制 0.5–2.0）；`max_chars`（可选字数上限，默认 12000，0=不截断）；`name`（可选音频展示名） |
| **输出** | `asset_ref`（**audio** AssetRef，mime `audio/mpeg` 或 `audio/mp4`）；`page_count`；`page_start` / `page_end`；`chars`（实际合成字数）；`chars_total`（抽取总字数）；`truncated`（bool）；`duration_sec`；`engine`（edge/say）；`voice`；`text_preview`；`status_text`（中文一句话） |

本能力 **只看本步入参**。缺 `asset_ref` / 非 `document` / 读不了文件 / 加密 /
空 PDF / 页范围无效 / 超 200 页 / 所选页无文字（扫描件）/ 合成失败 → **明确中文失败**，
不产生脏 Asset（合成失败时不上传半成品）。

## 音频语义与引擎

- **长文**：按句边界切块（每块 ≤ 3000 字），逐块合成后按 **MP3 帧** 拼接成一个 mp3
  （无需 ffmpeg）——`afplay` / `AVPlayer` / 浏览器都能整段播放。`say` 后端一次性
  合成 .m4a（AAC）。
- **音色**：按**正文语言**自动选（`lang` 不传时）：中文→`zh-CN-XiaoxiaoNeural`，英文→`en-US-AvaMultilingualNeural`（edge-tts 神经音色）。显式 `voice` 参数 > env 全语言 `MAC_EDGE_PDF_READER_VOICE` > env 分语言 `MAC_EDGE_PDF_READER_VOICE_ZH` / `..._VOICE_EN` > 该语言默认。一篇英文论文用中文音色朗读会带明显口音——所以别把 `lang` 写死成 `zh_CN`。
- **引擎**：`edge`（默认，`edge-tts`，需外网；中文默认音色 `zh-CN-XiaoxiaoNeural`，英文默认 `en-US-AvaMultilingualNeural`，按正文语言自动选）→
  产物 `audio/mpeg`；`say`（macOS 本机，离线；音色按语言取本机已装）→ 产物
  `audio/mp4`。edge 失败且 `MAC_EDGE_PDF_READER_TTS_FALLBACK_SAY`≠0 时自动回退 say，
  `status_text` 会说明实际引擎。
- **上限**：单次 ≤ 200 页、≤ `max_chars`（默认 12000 ≈ 40 分钟语音；截断落在句边界，
  `truncated=true` 并在 `status_text` 提示可分段朗读）；合成总时长 ≤
  `MAC_EDGE_PDF_READER_TIMEOUT_SEC`（默认 240s，须小于 Edge 的
  `MAC_EDGE_CAPABILITY_TIMEOUT_SEC`，超时出明确中文失败而不是被硬杀）。
- **扫描件**：抽不到文字时明确失败并提示「先 `pdf.to_images` 渲染成图片再 `image.ocr`」，
  本能力不做 OCR、不做图像理解。

## 技术实现

- **抽文字**：共享底层 `mac_edge.plugins.pdf_render`（PyMuPDF）
  `pdf_page_count` / `normalize_page_range` / `extract_page_texts`（页码语义与
  `pdf.to_images` 同源）。
- **合成**：共享底层 `mac_edge.plugins.tts_file`（`synthesize_speech` /
  `split_text_for_tts` / `truncate_text` / `concat_mp3` / `probe_duration_sec`）。
- **取 PDF**：`CapAsset.materialize_file(ref)` 物化本步 document Asset。
- **回传产物**：音频写 `MAC_EDGE_DATA_DIR/pdf-reader/<asset_id>/`（或 tempdir）
  → Brain `/api/v1/assets/upload`（`manager.upload_file`）以 `type=audio`、
  `producer=pdf.reader` 上传登记（现成通道，无需改 Brain）。

## 入口

- Mac：`mac/src/mac_edge/plugins/pdf_reader.py`；`services.py` 广告
  `local.pdf.reader`（laptop 角色且 `pdf_reader_available()` 为真时广告）
- 执行器：`mac/src/mac_edge/executor.py` 的 `pdf.reader` 分支
- 协议登记：`server/edge_services.py` 的 `KNOWN_CAPABILITIES["pdf.reader"]`；
  `server/capability_ads.py` 与 `mac/src/mac_edge/capability_ads.py` 同步广告

