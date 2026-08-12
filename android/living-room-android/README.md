# Living Room Android Edge（精简）

手机 Edge，核心能力：

1. **注册 / 心跳**（`client_hint = living-room-android`）
2. **用户意图**：文本输入框 + 本机语音转写 → `POST /api/v1/intent`；物流图跟踪
3. **指定 Wi‑Fi 切换 UI**（调试用；见下方暂停说明）

不做：拍照上传、Chromecast Cast、网易云音乐（那些仍在 iPhone / `app-v2`）。

### 暂停：无感 / 自动切 Wi‑Fi

**当前不继续推进 Android 无感切网。** Android 10+ 普通 App 无法静默切换默认 Wi‑Fi；`WifiNetworkSpecifier` 只做进程绑定且常不改状态栏。GoPro / 上传主路径以 **iOS + 蜂窝上云** 为准；本模块 Wi‑Fi 按钮仅保留作人工调试，不再投入无感切换优化。

## 构建

```bash
cd android
# 使用本机 Gradle 8.9 或 Android Studio
gradle :living-room-android:assembleDebug
adb install -r living-room-android/build/outputs/apk/debug/living-room-android-debug.apk
```

## 服务能力

| service | capability |
|---------|------------|
| `network.wifi` | `network.wifi.join` / `network.wifi.leave` |

收到 `camera.*` / `display.photo` / `music.*` 会 **skip** 并在物流图标为跳过（本 Edge 不执行）。

## UI

- **意图物流图**：pull 到意图后展示阶段（parsed → hub → assigned → running → succeeded/failed）与 plan steps
- **Wi‑Fi**：SSID/密码 → 加入目标网 / 离开回默认网（系统可能弹一次确认）
- **Agent**：启动/停止后台 register+heartbeat+拉意图

## 权限

位置 / 附近的设备（Wi‑Fi）/ 通知。
