# LivingRoomPickup（拾音）

iOS 12 UIKit 独立拾音 App：把麦克风 PCM 经 HAP1 推到家里 Mac `voice.stream`（默认 `:8792`）。

与 [`HomeAgentPickup`](../HomeAgentPickup/)（iOS 16 SwiftUI）并行；本工程只服务老机。

| 项 | 值 |
|---|---|
| Bundle ID | `com.gaolei.livingroom.pickup` |
| 显示名 | 拾音 |
| 最低系统 | iOS 12.0 |

```bash
python3 ios/LivingRoomPickup/generate_xcodeproj.py
# 或一键装到 6 Plus：
bash ios/LivingRoomPickup/deploy_ios12.sh
```

设置里可改 Mac host / port、静音门限、可选 participant_id。

## 端点（切句）与 Mac 的分工

只有语音会上传（端上能量门丢静音）。Mac 的切句按「收到的字节」算静音，所以端上
**必须在门关闭时补一条 HAP1 `quiet` 帧**（`type=5`，`{"ms":400}`，= hangover 实测静音），
Mac 会把它还原成等长零 PCM 再切句——否则每条 clip 都要跑满 2.8s 唤醒上限才进 STT，
「面条面条 → 我在呢」会慢 1.4s 以上。详见
[`agent_plans/phone_wake_latency_v1.md`](../../agent_plans/phone_wake_latency_v1.md)。

- `hangoverMs`（默认 400）必须 ≥ Mac 的 `MAC_VOICE_PHONE_WAKE_SILENCE_MS`（350），
  这样一条 quiet 帧就能切唤醒。
- 关掉静音门（设置里）时检测仍运行，quiet 帧照发，只是静音音频也一起上传。
