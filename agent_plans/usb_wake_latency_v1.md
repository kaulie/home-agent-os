# USB 唤醒延迟优化 — v1

## 目标

在不影响唤醒/指令精度的前提下，缩短「面条面条 → 我在呢」体感延迟。

## 做法

对齐 Home Mic：USB 增加唤醒/指令两套切句静音。

| 场景 | silence | 说明 |
|------|---------|------|
| 猎唤醒（默认） | 400ms | 比原 1000ms 约省 0.6s |
| 应答后指令句进行中 | 1000ms（原 `MAC_VOICE_SILENCE_MS`） | 中间停顿不误切 |

切换：唤醒应答后 `begin_command_listen`；`notify.speak` 的 PlaybackMute 结束时同样开窗。窗内未开口仍用短静音（便于再唤），开口后用长静音。

## 不改

- STT / WakeGate / debounce / 全局只降 `MAC_VOICE_SILENCE_MS`
- Phone 路径默认值
