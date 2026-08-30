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
