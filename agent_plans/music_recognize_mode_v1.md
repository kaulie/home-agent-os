# 识曲模式 · Music Recognize Mode — v1

Status: Approved & implemented baseline
Date: 2026-09-03

## 目标

用户经客厅语音入口（wake word「面条 面条」→「我在呢」已存在）说「打开识曲模式 /
这是什么歌」后：

1. （可选确认语）「好，开始识曲，我最多听 30 秒」
2. 麦连续收录**最短 10 秒、最长 30 秒**的环境声音（客厅任意外放背景音乐）
3. 每 `retry_every` 秒用**最近 min_sec 的滚动窗口**做一次识曲，命中即停
4. 命中：播报「这首歌是《title》artist」；满 30s 未命中：播报失败；自动退出本轮

范围边界：
- **不做**本机 ncm/网易云联动（识别对象是客厅任意外放音乐）
- 暂无第三方识曲密钥 → Provider 插槽 + mock 自测；拿到 key 即插即用
- 单次会话，识别一首即退出，不进入常驻多首模式

## 架构（方案 A：Brain 一次性能力 `music.recognize`）

- 新增 wire capability `music.recognize`（service `music.recognize`，group `music`）
- 语音意图走 Brain → planner 单步 `music.recognize` → Mac Edge 执行采集+滚动识曲
- 能力输出 `answer_text`/`matched`/`song_title`/`artist`/`confidence`
  - `answer_text` 登记进 output_schema → Brain 自动在发出端追加 `notify.speak $answer_text`
  - 即结果播报默认回到「原设备喇叭」（Source Affinity），无需额外 notify 步骤
- 采集由 Mac Edge 在 step 内部完成（复用 mac_voice 同款 sounddevice 16k/mono 输入）

## 文件改动

- `plugins/music-recognize/`：`manifest.yaml` + `capability.md`
- `mac/src/mac_edge/plugins/music_recognize/`：`__init__/config/capture/wav/providers/orchestrate`
- `mac/src/mac_edge/services.py`、`executor.py`：广告 + 路由
- `server/edge_services.py`、`server/capability_ads.py`、`server/home_brain.py`：协议登记 + planner 元数据 + presentation 播回
- `mac_voice`：命令确认语（本地播报，不建 intent）
- `mac/.env.example`：新配置项（含识曲服务密钥占位）
- 测试：`mac/tests/test_music_recognize.py` + server 回归

## 配置

| env | 默认 | 说明 |
|---|---|---|
| `MAC_EDGE_MUSIC_RECOGNIZE_PROVIDER` | `none` | `none/mock/audd/acrcloud/shazam` |
| `MAC_EDGE_MUSIC_RECOGNIZE_MIN_SEC` | `10` | 最短收录（首次识曲窗口） |
| `MAC_EDGE_MUSIC_RECOGNIZE_MAX_SEC` | `30` | 硬上限，超时自动退出 |
| `MAC_EDGE_MUSIC_RECOGNIZE_RETRY_EVERY_SEC` | `5` | 滚动重试间隔 |
| `MAC_EDGE_MUSIC_RECOGNIZE_AUDD_TOKEN` | - | audd.io 密钥（占位） |
| `MAC_EDGE_MUSIC_RECOGNIZE_ACR_ACCESS_KEY/SECRET/HOST` | - | ACRCloud（占位） |
| `MAC_EDGE_MUSIC_RECOGNIZE_SHAZAM_KEY/HOST` | - | Shazam/RapidAPI（占位） |
| `MAC_EDGE_MUSIC_RECOGNIZE_INPUT_DEVICE` | 跟随 `MAC_VOICE_INPUT_DEVICE` | 采集输入设备 |

## 验收

- 无密钥时默认不广告能力；设 `=mock` 可在真实麦上跑通：10s+ 后播「测试歌曲」
- 识别服务拿到 key 后设 provider + 密钥即启用，代码零改动
