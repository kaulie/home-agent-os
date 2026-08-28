# Service: local.pronunciation

整段英文朗读评测插件（`pronunciation-assess`），group=`pronunciation`。
输入两段音频 Asset（标准朗读 + 小朋友跟读），输出整段朗读评价。

**Brain 不执行、不持有密钥**；只通过心跳看到 `pronunciation.assess`，再把 plan 派到具备该能力的 Edge。

**能力独立**：本步只看本步已 resolve 的入参 `reference_audio` + `student_audio`。缺必填 → 失败，禁止从前序 step / `step_outputs` 自己去捡两段音频。两段音频 Asset 必须由上游（iPhone 上传步）产出并经 `output_constrict` publish 进 context，由 Brain 用 `$reference_audio` / `$student_audio` 接进本步 `input_constrict`。

## 规划自描述

心跳结构化字段（planner 契约；`description` 非权威）：

| 字段 | 值 |
|------|-----|
| role | 整段英文朗读评测器 |
| planner_recognize | 给定标准朗读音频和小朋友跟读音频，做整段→整段的发音评测，给出总分、发音准确度、流利度、完整度、韵律、重点问题单词/音素及时间位置。入参 reference_audio + student_audio（均为音频 AssetRef）。自己不录音、不上传音频、不 TTS、不投屏 |
| typical_triggers | `评测这段跟读`、`给这次朗读打分`、`评估发音`、`assess my reading`、`pronunciation check` |
| do_not_dispatch | 录音本身、上传音频、TTS、投屏、单句打分、知识问答 |

## 标识

| 字段 | 值 |
|------|-----|
| plugin id | `pronunciation-assess` |
| service_id | `local.pronunciation` |
| group | `pronunciation` |
| wire capability | `pronunciation.assess` |
| 执行方 | Mac Edge（`mac_edge.plugins.pronunciation_assess`），转调本机 sidecar `pronunciation-service` :9190 |

## 契约

| 方向 | 内容 |
|------|------|
| **输入** | `reference_audio`（必填，音频 AssetRef `{asset_id, type:"audio", mime_type?}`）；`student_audio`（必填，音频 AssetRef）。禁止 path / 永久 URL / base64。常为 `$reference_audio` / `$student_audio` |
| **输出** | `overall_score`（必填，number 0..100）；`accuracy_score`、`fluency_score`、`completeness_score`、`prosody_score`（必填，number 0..100）；`duration`（必填，object `{reference, student}`）；`problem_words`（必填，array `{word, score, start, end, phoneme_errors, reason?}`）；`problem_phonemes`（必填，array）；`fluency`（必填，object `{speech_rate, pause_count, long_pause_count, repetition_count}`）；`raw_alignment`（必填，array）；`feedback_text`（必填，string，给人看的中文一句话总结，供 Brain 组装 presentation） |

本能力 **只看本步入参**。缺任一音频 → 失败。**禁止**从前序 step 收集音频、禁止自己录音/上传。sidecar 不可达 → 失败并带可读 `msg`。成功后 Brain 组装 `intent_detail.presentation`（如「本次朗读 84 分，需要注意 environment」）；纯提醒仍可 `notify.speak`。

## Wire

```json
{
  "capability": "pronunciation.assess",
  "step": 2,
  "assigned_edge_id": "<mac-edge-id>",
  "input_constrict": {
    "reference_audio": "$reference_audio",
    "student_audio": "$student_audio"
  },
  "output_constrict": {
    "overall_score": { "type": "number", "data_dest": "context" },
    "accuracy_score": { "type": "number", "data_dest": "context" },
    "fluency_score": { "type": "number", "data_dest": "context" },
    "completeness_score": { "type": "number", "data_dest": "context" },
    "prosody_score": { "type": "number", "data_dest": "context" },
    "duration": { "type": "object", "data_dest": "context" },
    "problem_words": { "type": "array", "data_dest": "context" },
    "problem_phonemes": { "type": "array", "data_dest": "context" },
    "fluency": { "type": "object", "data_dest": "context" },
    "raw_alignment": { "type": "array", "data_dest": "context" },
    "feedback_text": { "type": "string", "data_dest": "context" }
  }
}
```

上游必须先把两段音频注册成 Asset 并 publish 进 context（iPhone 上传步 → `asset_ref`），Brain 再用 `$reference_audio` / `$student_audio` 接进本步。本步不负责准备这两段音频。

## 入口

- Mac：`mac/src/mac_edge/plugins/pronunciation_assess.py` + `services.py` 广告 `local.pronunciation`（仅当本机 `pronunciation-service` :9190 可达时广告）
- sidecar：`pronunciation-service/`（Docker，:9190，WhisperX 基线 + MFA/GOPT 升级钩子）
- 协议登记：`server/edge_services.py` 的 `KNOWN_CAPABILITIES["pronunciation.assess"]`（仅索引，不跑评测）
