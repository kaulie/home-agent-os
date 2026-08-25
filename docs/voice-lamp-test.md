# 台灯语音控制：自动化试验技术方案

问题：真人直接对台灯说话，识别成功率较高；Mac 播放 TTS / 录音时成功率明显下降。  
目标：用可重复的试验闭环，自动扫语音参数，找出台灯更容易听懂的 VoiceProfile。  
**当前只测一条命令：打开台灯。**

本文件是试验的整体方案。Plugin 契约见 [`plugins/voice-lamp-test/capability.md`](../plugins/voice-lamp-test/capability.md)。不改 Runtime。

---

## 1. 成功怎么定义

播放成功 **不是** 台灯控制成功。

| 结果 | 含义 |
|------|------|
| `SUCCESS` | 独立 Verification 判定目标台灯（落地/书桌台灯灯头）已亮 |
| `FAIL` | 语音已播出，但验证判定仍灭 / 看不清 |
| `INVALID` | 试验无效，例如开始前台灯已经亮着（`lamp_already_on`） |

天花板主灯、电视、窗外自然光 **不算** 台灯亮。

### 怎么确认语音真的播出了

`afplay` / `say` 退出码 0 **不够**（静音、打到错误输出设备、系统音量为 0 都会成功退出）。

试验在播放时用 **USB 麦（reSpeaker）回录**，和播放前一小段环境底噪比 RMS：

- `play_rms / ambient_rms >= 2.5` 且 `play_rms` 超过静音地板 → 认为扬声器出声了
- 否则试验基础设施失败：`扬声器没有被麦克风听到`（不是台灯 `FAIL`）
- 回录 WAV 与 `*.loopback.json`（`heard` / `rms_ambient` / `rms_play` / `ratio`）写入试验目录

这只证明 **房间里有一声比底噪明显的播放**，不证明台灯听懂了。台灯听懂仍只看视觉 Verification。

自检：`python -m mac_edge.plugins.voice_test --probe-play`

日常用户说「开灯」仍走 `light.set`。本方案只做识别率实验。

---

## 2. 现场拓扑

```text
Mac laptop（试验控制节点）
  ├── 扬声器  →  对台灯喊唤醒词 + 命令（TTS / 录音）
  ├── USB 麦（reSpeaker）→ 回录，确认扬声器真的出声
  ├── 本机 TTS（macOS say / 可选 edge-tts）
  └── vision.ask（看图判断亮灭）
           ↑
           │ Brain 入队「拍张照」
           │
客厅 iPhone（停在 GoPro Wi-Fi 上）
  └── camera.capture  →  GoPro 拍客厅广角图
           │
台灯（语音识别设备）
  └── 听 Mac 扬声器，执行「打开台灯」
```

发出端（POST `/api/v1/intent`）用已注册的 Intent Source。当前拍照入队默认 issuer：客厅 iPhone `edge-node-JzvEe287`。

Mac home-server 的 `camera.capture` 要切网，不适合试验循环。本机 FaceTime 对不准客厅台灯。验证图必须用客厅那台 GoPro。

---

## 3. 为何不硬套现有能力

仓库 **没有 Workflow / 循环原语**。Planner 只能产出线性 `execution_plan`。本试验 **不改 Runtime**。

| 已有能力 | 为何不能单独当试验 | 本方案怎么用 |
|----------|-------------------|--------------|
| `notify.speak` | 生成即播放；无 speed / volume / 音频文件 | 试验自己 `say -o` + `afplay -v`，不改播报契约 |
| `light.set` | 开环；硬编码「开灯」；播出即步骤成功 | 日常开灯仍用它；实验禁止派这条 |
| `camera.capture` | 必须在客厅 iPhone 上跑 | **复用**：Brain 入队「拍张照」，不复制 GoPro HTTP |
| `vision.ask` | 开放看图问答 | **复用**：问灯头是否自发光，解析「亮 / 灭」 |
| 本机 webcam | FaceTime 对不准灯；权限易卡住 | 仅 `capture_backend=webcam` fallback |

叶子函数已经拆开（generate / play / capture / verify / record）。Phase 1 只广告 `voice_test.run_trial`，避免 Planner 只播不验。

---

## 4. 单次试验闭环（Phase 1，已落地）

```text
（可选）before 拍照 ──► 已亮？──► INVALID（不再喊命令）
                │否
                ▼
        两句都先合成好（不占两句之间的间隔）
                │
                ▼
        播放唤醒词（默认「小书小书」）
                │
                ▼
        只等待 wake_word_pause_ms（暂停窗内 USB 麦录音听「在呢」；转写挪到第二句开口之后）
                │
                ▼
        立即播放命令（默认「打开台灯」，不再先等 0.35s 底噪、不再现场合成）
                │
                ▼
        等待 settle_ms（默认 1500）
                │
                ▼
        camera.capture（after）
                │
                ▼
        vision.ask → 亮 / 灭 / 不知道
                │
                ▼
        写 JSONL ──► SUCCESS / FAIL
```

拍照在第一句之前和两句都说完之后，**不会**插在「小书小书」和「打开台灯」中间。两句之间应接近配置的 `wake_word_pause_ms`（默认 1500，一般不要超过 2000）。

三路信号分开记，不要混：

| 字段 | 含义 | 不是 |
|------|------|------|
| `wake_loopback.heard` | 扬声器出声（RMS） | 不是唤醒成功 |
| `wake_reply_heard` | 暂停窗 STT 听到「在呢 / 我在呢」 | 不是台灯 SUCCESS |
| `result=SUCCESS` | `vision.ask` 判定灯头亮 | 不是播过音、不是听到在呢 |

Capability 步骤失败只表示试验基础设施坏了（TTS / 拍照 / 视觉）。灯没亮是 **有效测量**，记 `FAIL`，步骤仍成功。`wake_reply_heard=null` 表示 STT/麦缺口，不改 lamp 结果。

---

## 5. VoiceProfile

参数 **不写死在代码里**。合并顺序：默认值 < 配置文件 < 环境变量 < capability / CLI 入参。

默认文件：[`plugins/voice-lamp-test/profiles/default.yaml`](../plugins/voice-lamp-test/profiles/default.yaml)

| 字段 | 默认 | 说明 |
|------|------|------|
| `backend` | `say` | **试验变量**：TTS 引擎 `say` 或 `edge`。可 `--backends say,edge` |
| `voice` | `Tingting` | **试验变量**：say 音色名；edge 时为 Neural 音色。可 `--voices Tingting,Mei-Jia` |
| `speed` | `1.0` | **试验变量**：语速倍率；`say` 映射为约 175 wpm。可 `--speeds 0.8,1.0,1.2` |
| `volume` | `0.8` | **试验变量**：`afplay -v`，0.0–1.0。可 `--volumes 0.6,0.8,1.0` |
| `pitch` | 空 | **试验变量**（仅 `edge` 生效；`say` 记入 profile 但忽略）。可 `--pitches +0Hz,+10Hz,-10Hz` |
| `wake_word` | `小书小书` | 当前阶段固定 |
| `command` | `打开台灯` | 当前阶段唯一命令 |
| `wake_word_pause_ms` | `1500` | **试验变量**：唤醒词「小书小书」与命令「打开台灯 / 关闭台灯」之间。**>2000ms 视为命令窗口高风险**（灯常已退出唤醒）。推荐扫描 500/800/1200/1500/2000，3000 作负对照。不是拍照等待，也不是两轮试验之间的间隔 |
| `settle_ms` | `1500` | **试验变量**：命令播完后、拍照前（等灯响应）。可 `--settles 1000,1500,2000`。与唤醒-命令间隔分开 |
| `capture_backend` | `gopro` | `gopro` = Brain→iPhone `camera.capture`；`webcam` = 本机 ffmpeg |
| `capture_before` | `true` | 喊命令前先拍一张；已亮则 `INVALID` |
| `wake_audio` / `command_audio` | 空 | 有文件则加载录音，否则 TTS |

环境变量前缀 `MAC_EDGE_VOICE_TEST_*`，拍照 issuer：`MAC_EDGE_VOICE_TEST_ISSUER`。

---

## 6. Verification（可替换）

独立模块 `LampVerifier`。当前实现：`VisionAskVerifier`，内部调用 `vision.ask`，**不是** 另一套视觉系统。

问句约束：只看落地/书桌台灯灯头是否自发光。解析：

- 「亮」→ `on`
- 「灭」→ `off`
- 「我不知道」→ `unknown` → 记 `FAIL` / `verify_unknown`

未来替换（仍是普通 capability / 模块，不升成 Runtime 机制）：

- 台灯 API 状态
- 电流 / 电源
- 其它传感器

验证图身份走 `asset_ref`（Asset Contract）。GoPro 预览图从 Brain `GET /api/v1/assets/{id}/content?intent_id=…&representation=preview` 拉取（原图走 LAN 容易卡住）。

---

## 7. 数据

每次试验追加一行 [`mac/data/voice_tests/trials.jsonl`](../mac/data/voice_tests/)（gitignore）。音频与截图放在 `voice_tests/{experiment_id}/{trial_id}/`。

至少记录：

`before_asset_id` / `after_asset_id` · `playback`（`tts` 标准人声 / `clip` 录音） · `pickup_transcripts` / `pickup_text`（第一句回录、暂停窗、第二句回录的 STT 全文）

系列报告按 VoiceProfile 试验变量给出台灯 `k/N`：`by_voice` / `by_speed` / `by_volume` / `by_pause_ms` / `by_settle_ms` / `by_backend` / `by_pitch`，以及格子 `by_cell`。`>2000ms` 间隔标 `pause_risk=high_risk`。

之后用来分析：哪个 voice / 音量 / 语速最好；失败在唤醒、命令、响应慢，还是视觉误判。

`error_reason` 例：`lamp_not_on` · `lamp_already_on` · `verify_unknown` · `verify_skipped`。

---

## 8. 分阶段

按增量做。**每阶段先跑通真实试验，再进入下一阶段。** 不做贝叶斯 / 强化学习，直到网格搜索不够用。

| Phase | 内容 | 状态 |
|-------|------|------|
| **1** | 单次闭环：生成/加载 → 播放 → 等待 → 拍照 → 验证 → 落盘 | **已落地并实测** |
| **2** | 同一 VoiceProfile 重复 N 次，出成功率 `k/N` | **CLI `--repeat N` 已落地** |
| **3** | VoiceProfile 全部可配置（文件 + CLI + 入参） | Phase 1 已有骨架；网格文件未做 |
| **4** | 字段齐全的持久化（JSONL；后续可加汇总表） | Phase 1 已写 JSONL |
| **5** | Exhaustive grid：voice × speed × volume × pitch × backend × wake_word_pause_ms × settle_ms，每格 N 次 | CLI 笛卡尔积已能扫这些维；全网格仍按需开跑 |
| **6** | 汇总报告：最佳 VoiceProfile + 失败分布 | 未做 |

Phase 5 示例网格（数字可改）：

```text
Voice A / B（`--voices`）
  speed  0.9 / 1.0 / 1.1
  volume 0.6 / 0.8 / 1.0
  pitch  +0Hz / +10Hz（仅 edge）
  wake_word_pause_ms  500 / 800 / 1200 / 1500 / 2000 / 3000（>2000 负对照）
  settle_ms  1000 / 1500 / 2000
每格 N=20
```

输出形如：`success=18/20  success_rate=90%`，再给出最佳 profile。

批量循环放在试验编排能力 / CLI 里，**不要**让 Planner 展开上百个 step，也 **不要** 为此给 Runtime 加 loop。

---

## 9. 怎么跑

CLI（Mac，需能访问 Brain；拍照时 iPhone 须在线且连着 GoPro Wi-Fi）：

```bash
cd mac
# 只拍照+验证，不喊开灯（当前灯灭时应为 FAIL / lamp_not_on）
PYTHONPATH=src .venv/bin/python3 -m mac_edge.plugins.voice_test --once --skip-play

# 完整单次：小书小书 → 打开台灯 → 拍照 → 视觉验收
PYTHONPATH=src .venv/bin/python3 -m mac_edge.plugins.voice_test --once

# 同一 profile 连续 N 轮，出 k/N（SUCCESS 后会喊「关闭台灯」以免下一轮 INVALID）
PYTHONPATH=src .venv/bin/python3 -m mac_edge.plugins.voice_test --repeat 5

# 把「小书小书」到「打开台灯」的间隔当试验变量（每档 --repeat 次）
PYTHONPATH=src .venv/bin/python3 -m mac_edge.plugins.voice_test --repeat 2 --pauses recommended

# 间隔 × 语速 × 音量 × 音色 网格（笛卡尔积；--repeat 是每个格子的次数）
PYTHONPATH=src .venv/bin/python3 -m mac_edge.plugins.voice_test --repeat 1 \
  --voices Tingting,Mei-Jia --pauses 800,1500 --speeds 0.8,1.0 --volumes 0.6,0.8

# 只合成播放，不控制灯
PYTHONPATH=src .venv/bin/python3 -m mac_edge.plugins.voice_test --dry-run
```

参数例：`--voice Tingting --speed 0.9 --volume 0.8 --wake-pause-ms 1500 --capture gopro`。  
`--gap-ms` 只是两轮试验之间的休息，不要和 `--wake-pause-ms` 混用。

Planner 路径：用户说「测试一下现在这套语音控制台灯的识别成功率」→ 派 `voice_test.run_trial`。Mac Edge laptop 需重启后心跳才会广告 `local.voice_test`。日常「打开台灯」仍派 `light.set`。

单元测试：`cd mac && PYTHONPATH=src python3 tests/test_voice_test.py`。

---

## 10. 已验证的事实（2026-08-21）

- TTS：`say` Tingting 生成 + `afplay` 播放可用。
- 本机 FaceTime 拍照在开发机上超时，放弃作为主路径。
- iPhone `camera.capture` 在线（`edge-node-JzvEe287`），intent 269 / 后续 trial 均 `succeeded`，约 11–19s。
- 广角图里天花板主灯亮、左侧落地台灯灯头灭。
- `--once --skip-play`：`vision.ask` 答「灭」，`result=FAIL` / `lamp_not_on`（未喊命令，符合预期）。未把吊灯误判成台灯亮。

完整「喊开灯再验收」已实测一轮（2026-08-21 15:27，`4a8f2e842878`）：回录 heard，视觉仍「灭」，`FAIL` / `lamp_not_on`。

---

## 11. 明确不做

- 不改 Runtime 调度 / hydrate / 前序门。
- 不把 Verification 做成 Runtime 特殊机制。
- 不把本实验当 `light.set`。
- 不在 `vision.ask` 上做 JSON 拆包兜底；结构不对就失败。
- 不一次实现网格搜索和强化学习。
- 不上云半成品 Brain；本试验跑在 Edge + 已部署的 Brain API。
