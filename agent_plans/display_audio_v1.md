# display.audio：把已有音频交给电视 DLNA 出声（v1）

> 触发：intent **781**「把最新的音频在小米电视上放出来」→ 只回了一句
> 「这是按登记顺序的第 1 张audio。」，电视没出声。

## 1. 现场证据（现网 DB / brain.log）

| 项 | 值 |
|----|-----|
| intent | `781`（voice / lan / `edge-node-JzvEe287`），`succeeded` |
| plan | 只有 1 步：`asset.inventory{type=audio, newest_first, index=1}` |
| outputs | `{"type":"text","answer_text":"这是按登记顺序的第 1 张audio。"}` |
| LLM 自述 | `missing_capabilities: [{"capability":"display.audio","reason":"当前可用的小米电视 DLNA 能力仅支持图片投屏、PDF 投屏和幻灯片轮播，没有把已有 audio Asset 投到小米电视播放的音频投屏/播放能力。"}]` |

结论：不是链路坏了，是**能力缺失**——显示服务只有 `display.photo` /
`display.slideshow` / `display.pdf*`（全是图），规划器只能「盘点 + 说一句」。
顺带暴露一个文案 bug：`inventory_answer_text` 一律用「第 N 张<noun>」，
音频/链接会说成「第 1 张audio」。

## 2. 决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 能力名 | `display.audio`（不是 `xiaomi.tv.audio_play`） | 显示族的动词前缀；wire 名与后端解耦，Cast 以后支持音频可共用 |
| 后端范围 | **只挂小米电视 DLNA** | Chromecast 侧是自定义 CAF 接收器（只认图片）；Cast 上执行明确中文失败，不静默降级 |
| 播放方式 | DLNA `SetAVTransportURI` + `CurrentURIMetaData`(DIDL `audioItem.musicTrack`) + `Play` | 与图片投屏同一渲染器发现/控制链路；DIDL 让电视按音频选播放器 |
| 音频 URL | `CapAsset.http_url(ref)` → Brain `/api/v1/assets/<id>/content` | 与 `display.photo` 同一条授权链路（电视拉流时 Brain 按 `ctx_param`/`step_outputs` 里的 `asset_ref` 补授权） |
| 规划路径 | 新增 P0 规则 `latest_audio_cast`：`asset.inventory(type=audio)` + `display.audio` | 「最新音频 + 电视」是固定两步链路，不必每次等 LLM；`do_not_dispatch` 把歌/音乐/视频/照片/PDF 排除，不让规则截胡 music.* 与 display.pdf |
| 回话 | `presentation {type: text|audio, from: status_text}` = 「已在小米电视播放最新音频」 | 电视是**执行**目标，回给发声端只给一句确认；绝不再把同一音频在手机播一遍（避免双响） |
| 顺带修 | `assemble_presentation` 不认识 `status_text` 字段 | 原先 tv_pdf_page/zoom 的 status_text 确认语根本填不进 presentation（空壳），一并补上 |

## 3. 落地清单

- mac：`plugins/xiaomi_tv_display.py`（`play_audio` / `audio_current_uri_metadata` /
  `audio_from_params`，`play_photo` 与它共用 `_play_uri`）、`capability_ads.py`（planner ad）、
  `services.py`（`AUDIO_DISPLAY_CAPABILITIES`，只在 xiaomi 后端广告）、
  `executor.py`（dispatch；Cast 后端明确失败）
- server：`capability_ads.py`（ad 对齐）、`intent_complexity/matcher.py`（别名）、
  `shortcut_mode/rules.py`（`latest_audio_cast`）、`home_brain.py`（presentation 认
  `display.audio` → `status_text`；`assemble_presentation` 收 `status_text`）
- 文案：`system_capabilities.inventory_answer_text` 按类型用量词（张/段/条/份/个）
- 文档：`plugins/xiaomi-tv-display/capability.md`、`plugins/asset-inventory/capability.md`
- 测试：`mac/tests/test_xiaomi_tv_display.py`（11 个新增：DIDL / SOAP / from_params /
  广告门控 / executor 分发）、`server/tests/test_shortcut_mode.py`（4 个）、
  `server/tests/test_system_capabilities.py`（4 个）、`server/tests/test_home_brain.py`（2 个）

## 4. 验收

- 单测：mac 738 个（失败集合 = origin/main 基线 12 条，新增 11 个全绿）；
  server 438 个（失败集合 = 基线 24 条，新增 10 个全绿）
- L3 黑盒（需真机）：`把最新的音频在小米电视上放出来` → 期望
  plan `asset.inventory(type=audio) → display.audio`，电视出声，发出端听/看到
  「已在小米电视播放最新音频」；负例：`把最新的歌在电视上放出来` 仍走 `music.play`。

## 5. 未做 / 后续

- Cast（Chromecast）后端音频播放：需要接收器侧支持 audio media，另开能力。
- 音量/暂停/继续等音频传输控制（`display.audio.pause` 等）：本次不做。
- `paper.read` 一步到位「生成即投电视」：本次只做「已有音频 → 电视」，听读链路不动。
- **风险（待真机确认）**：Brain `/api/v1/assets/<id>/content` 返回 200 + `Content-Length`，
  不支持 `Range`（图片投屏、小度 TTS 拉流都是这条链路，实测可用）。若小米电视的 DLNA
  播放器要求 206 才能播/拖动，退路是像 `xiaodu_speaker` 那样在 Mac 本地起一个带 Range
  的文件服务，把 `CapAsset.materialize_file(ref)` 的文件喂给电视。
