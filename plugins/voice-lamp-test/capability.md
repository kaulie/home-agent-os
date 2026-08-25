# Service: local.voice_test

台灯语音控制 **实验**插件（`voice-lamp-test`），group=`experiment`。  
本文件是试验的 Plugin 契约。整体测试技术方案（拓扑、分阶段、怎么跑）：[`docs/voice-lamp-test.md`](../../docs/voice-lamp-test.md)。

**Brain 不执行**；只通过心跳看到 `voice_test.run_trial`，再把 plan 派到具备该能力的 Edge（Mac laptop）。

**与 `light.set` 独立**：日常「开灯 / 关灯」仍派 `light.set`。本能力只做识别率实验，禁止拿来当灯控。  
**与 `notify.speak` 独立**：`notify.speak` 仍是用户播报；本步内部按 VoiceProfile 生成+播放，不改 `notify.speak` 契约。  
**与 `camera.capture` 的关系**：验证图默认 **复用** 客厅 iPhone 已广告的 `camera.capture`（GoPro，iPhone 停在相机热点上，不切 Mac 网）。本插件只通过 Brain 入队「拍张照」，不复制 GoPro HTTP。本机 ffmpeg webcam 仅作 fallback。

## 规划自描述

心跳结构化字段（`description` 非权威）：

| 字段 | 值 |
|------|-----|
| role | 台灯语音控制实验器 |
| planner_recognize | 用可配置语音参数播唤醒词和开灯命令，再用摄像头判断台灯是否亮起，记录单次实验结果 |
| typical_triggers | `测试台灯语音识别成功率`、`测一下语音控制台灯`、`跑一轮台灯语音测试` |
| do_not_dispatch | 日常开灯、关灯、知识问答、投屏、给用户看照片 |

用户说「打开台灯 / 开灯」→ **不要**派本能力，派 `light.set`。

## 标识

| 字段 | 值 |
|------|-----|
| plugin id | `voice-lamp-test` |
| service_id | `local.voice_test` |
| group | `experiment` |
| wire capability | `voice_test.run_trial` |
| 执行方 | Mac Edge laptop（`mac_edge.plugins.voice_test`） |

## 契约

本能力 **只看本步入参**（缺省则读 VoiceProfile 配置文件 / 环境变量）。  
播放成功 **不是** SUCCESS。`result=SUCCESS` 仅当 Verification 判定台灯已亮。

| 方向 | 内容 |
|------|------|
| **输入** | 全部可选。试验变量：`voice` / `speed` / `volume` / `pitch`（仅 edge） / `backend` / `wake_word_pause_ms`（小书小书→打开台灯/关闭台灯） / `settle_ms`（命令后等灯再拍）。另有 `wake_word` / `command` / `experiment_id`。缺省见 `plugins/voice-lamp-test/profiles/default.yaml`。 |
| **输出** | `result`（SUCCESS / FAIL / INVALID，必填）；`answer_text`（必填，人类摘要）；`verification_result`；`error_reason`；`latency_ms`；`timeline_text`（每步时间点）；可选 `asset_ref`（验证图） |

内部协议（Phase 1 单次闭环，开环不听「在呢」）：

1. （可选）**复用** `camera.capture`（客厅 iPhone / GoPro）拍 **before**；已亮 → `INVALID`
2. 生成并播放唤醒词（默认「小书小书」）
3. sleep `wake_word_pause_ms`（默认 1500；暂停窗内 USB 麦 STT 听「在呢」，记 `wake_reply_heard`，**不是** SUCCESS）
4. 生成并播放命令（默认「打开台灯」）
5. sleep `settle_ms`（默认 1500）
6. 再派 `camera.capture` 拍 **after**（不复制 GoPro 实现、不切 Mac Wi‑Fi）
7. **复用** `vision.ask` 判断落地/书桌台灯灯头是否自发光（不要把天花板主灯当成功）
8. 写入 `mac/data/voice_tests/trials.jsonl`

`capture_backend=gopro`（默认）通过 Brain `POST /api/v1/intent` 文案「拍张照」调度 iPhone 的 `camera.capture`。`webcam` 才用本机 ffmpeg。

Verification 是可替换模块（`LampVerifier`）。当前实现：摄像头 + `vision.ask`。未来可换成台灯 API / 电流传感器，不改 Runtime。

`say` 后端不支持 pitch（记入 profile，忽略）。`edge` 后端可设 pitch（如 `+0Hz`）。音量一律在 `afplay -v` 播放时生效。

## Wire

```json
{
  "capability": "voice_test.run_trial",
  "step": 1,
  "assigned_edge_id": "<laptop-edge-id>",
  "input_constrict": {},
  "output_constrict": {
    "result": { "type": "string", "data_dest": "context" },
    "answer_text": { "type": "string", "data_dest": "context" },
    "verification_result": { "type": "string", "data_dest": "context" },
    "error_reason": { "type": "string", "data_dest": "context" }
  }
}
```

用户说「测试一下现在这套语音控制台灯的识别成功率」→ 本能力。不要派 `light.set` 或 `notify.speak`。

Phase 1 只跑 **一次**试验。批量、网格搜索、报表是后续 Phase；不要在本步内循环几十次（Runtime 无 loop，也不为此改 Runtime）。

## 入口

- Mac：`mac/src/mac_edge/plugins/voice_test/` + `services.py` 广告 `local.voice_test`
- 协议登记：`server/edge_services.py` 的 `KNOWN_CAPABILITIES["voice_test.run_trial"]`（仅索引，不跑实验）
- 本地 CLI：`cd mac && PYTHONPATH=src python -m mac_edge.plugins.voice_test --once`

## 架构缺口（最小方案，未改 Runtime）

当前仓库 **没有 Workflow / 循环原语**。Planner 只能产出线性 `execution_plan`。

| 缺口 | 为何不能硬套现有能力 | Phase 1 最小做法 |
|------|----------------------|------------------|
| 无 loop | 网格 N×M 次会变成上百 step | 单次 `voice_test.run_trial`；批量留到后续 Phase 的编排能力 |
| `notify.speak` | 生成即播放；无 speed/volume/pitch；无音频文件 | 本插件 `say -o` + `afplay -v`，不改 `notify.speak` |
| `camera.capture` | Mac home-server 切网太慢；验证必须用客厅那台相机 | 入队 iPhone 已广告的 `camera.capture`（不复制实现） |
| `light.set` | 开环，硬编码「开灯」，播放成功即步骤成功 | 实验走本能力；日常开灯仍 `light.set` |
| 无 wait 能力 | 唤醒词间隔 / 灯响应等待 | 写在本步内部（与 `light.set` 相同） |

叶子函数（generate / play / capture / verify / record）已拆开，后续可升为独立 capability，由 Planner 用 `$asset_ref` 串联。Phase 1 不广告它们，避免 Planner 只播不验。
