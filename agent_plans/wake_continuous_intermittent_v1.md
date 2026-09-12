# 连续「面条面条」偶发失效 — v1

## 现象

连续多次喊唤醒词时，有几次听不到「我在呢」/ 看似没唤醒。

## 根因（代码确认）

### A. 同麦连续再唤被全局 ack debounce 吃掉（主因）

`listen.py` 用全局 `last_ack_say_at` + `_ACK_SAY_DEBOUNCE_S=1.5`。设计本意是 **USB / Home Mic 两路几乎同时唤醒时共享喇叭只播一次**（见 `docs/architecture/voice-wake-per-participant.md`），但实现未区分 gate key：

同一路在 1.5s 内再唤醒（连续测「面条面条」很常见）→ `say=False` → 只 `arm_after_ack`，**不播应答**，体感即「失效」。

### B. listening / acking 下 STT 收成单遍「面条」被当成指令

火山 STT 常把「面条面条」收成「面条」。idle 有时长 ≥1.1s 按两遍计；但在 `listening`/`acking`：

- `hits==1` + 无 remainder → `_reset()` 并 `return leftover`（「面条」当命令）
- 不进 partial、不重播应答

连续再唤且第二句偏短/被收成一遍时，表现为偶发失效。

## 修复

1. Debounce 仅跨不同 `gate_key`（异路）；同 key 连续再唤始终播应答。
2. `listening`/`acking` 下 wake-only（hits>0 且无命令 remainder）→ `_enter_partial`，不当命令。
3. 单测覆盖上述两条。

## 非本轮

- PlaybackMute / STT stale queue：影响「播报后立刻唤」，与纯连续唤醒不同；日志里若大量出现再另开。
