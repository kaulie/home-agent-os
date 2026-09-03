# Service: music.recognize（capability: music.recognize）

声学识曲（听歌识曲）能力：用麦**连续收录**客厅环境声音 **10~30 秒**，识别客厅任意正在外放的背景音乐是哪首歌，命中或超时后自动退出本轮，由 Brain 把结果从**原设备喇叭**播回。

**与 `netease.music` 无关**：不读 ncm 现在播放 / 歌单，**只做声学指纹识曲**。识别服务本身可插拔（Provider：`mock | audd | acrcloud | shazam`），密钥未配置时**不广告**本能力。

**与 `notify.speak` 的关系**：本步输出 `answer_text`（一句话歌名播报），Brain 按 presentation/输出对等原则在**发起语音的 Edge** 追加 `notify.speak $answer_text`。不要在 plan 里再手动加 notify 去念结果。

**执行方**：客厅 Mac Edge（`mac_edge.plugins.music_recognize`）。采集复用 mac_voice 同款 16 kHz/mono USB 麦输入。

## 规划自描述

| 字段 | 值 |
|------|-----|
| role | 识曲器（听歌识曲） |
| planner_recognize | 收录客厅 10~30 秒声音并识别外放的是哪首歌，输出一句话 answer_text；只识别一首 |
| typical_triggers | `打开识曲模式`、`这是什么歌`、`帮我听一下这首歌`、`听歌识曲`、`识别一下现在放的歌` |
| do_not_dispatch | 按歌名点播/暂停/切歌（music.play 等）、连蓝牙、知识问答、读 ncm 正在播放元数据、念答案顶替 |

## 标识

| 字段 | 值 |
|------|-----|
| plugin id | `music-recognize` |
| service_id | `music.recognize` |
| group | `music` |
| wire capability | `music.recognize` |
| kind | `action` |

## 契约

| 方向 | 内容 |
|------|------|
| **输入** | 全部可选：`min_sec` / `max_sec` / `retry_every_sec`（未传用环境变量默认值） |
| **输出** | `answer_text`（必填，给用户的一句话播报）；`matched`（bool）；`song_title`；`artist`；`confidence`；`captured_sec` |

行为（step 内部完成，无 loop 依赖）：

1. 打开 16k/mono 输入流，连续收录，累积最近音频（内存上限 = max_sec）
2. 累计 ≥ `min_sec` 后，每 `retry_every_sec` 对**最近 min_sec 的滚动窗口**做一次识曲（低电平/静音跳过，省配额）
3. 命中 → 立即停止，`matched=true`，组装「这首歌是《title》artist」
4. 满 `max_sec`（默认 30s）仍未命中 → 停止，`matched=false`，播报失败并自动退出

失败原因可读：识别服务未配置 / Provider 无密钥 / 无声源 / Provider 报错。

## Wire

```json
{
  "capability": "music.recognize",
  "step": 1,
  "input_constrict": {},
  "output_constrict": {
    "answer_text": { "type": "string", "data_dest": "context" },
    "matched": { "type": "boolean", "data_dest": "context" },
    "song_title": { "type": "string", "data_dest": "context" },
    "artist": { "type": "string", "data_dest": "context" },
    "confidence": { "type": "number", "data_dest": "context" }
  }
}
```

## 识别服务 Provider（插槽）

| Provider | env（`MAC_EDGE_MUSIC_RECOGNIZE_*`） | 状态 |
|---|---|---|
| `mock` | `PROVIDER=mock` | 自测：录满 min_sec 且有声音即回「测试歌曲 / 测试歌手」 |
| `audd` | `PROVIDER=audd` + `AUDD_TOKEN` | 已实现（httpx multipart → api.audd.io） |
| `acrcloud` | `PROVIDER=acrcloud` + `ACR_ACCESS_KEY/SECRET/HOST` | 已实现（标准 v2 HMAC-SHA1 签名识别） |
| `shazam` | `PROVIDER=shazam` + `SHAZAM_KEY/HOST` | 插槽（拿到所选 RapidAPI 契约后按基座补全） |
| `none`（默认） | 不设 | 能力**不广告**；强行调用返回可读失败 |

拿到任一服务 key：设 `MAC_EDGE_MUSIC_RECOGNIZE_PROVIDER=<name>` + 对应密钥即可，代码零改动。

## 入口

- Mac：`mac/src/mac_edge/plugins/music_recognize/` + `services.py` 广告 `music.recognize`（provider≠none 时）
- 协议登记：`server/edge_services.py` 的 `KNOWN_CAPABILITIES["music.recognize"]`；planner 广告 `server/capability_ads.py` ADS；`server/home_brain.py` presentation 把 `answer_text` 从发出端播回
