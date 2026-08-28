# HomeAgent Legacy（iOS 12）

老 iPhone（**iOS 12.x**，例如 12.5.8）无法安装主 Console [`LivingRoomEdge`](../LivingRoomEdge/)（最低 **iOS 16**、SwiftUI）。本工程是独立的 **UIKit** 轻量版：文字发 Intent、看书拍照、**直播推流（P1 仅视频）**。

可与主 Console **同时安装**（不同 Bundle ID、独立 UserDefaults）。

## 做什么

### Intent（打字）

```text
启动 → register + heartbeat → POST /api/v1/intent → 轮询 intent_detail
```

- 默认连 **家里 WiFi** Brain（`192.168.3.73:9527`）；连不上会自动试 **外面**（云 `115.190.153.53:9527`）
- 「家长」页用 **家里 / 外面** 切换 Brain，无需手填 URL

### 直播（P1，仅视频）

```text
互动 → 直播 → Start Stream
  → POST Mac :8790/api/v1/video-live/prepare
  → MPEG-TS/H.264 over TCP（640×480 @ 15fps ~800kbps）
  → Stop → POST .../stop
```

- **家长 → 更多** 填 **Mac ingest URL**（默认 `http://192.168.3.73:8790`），**不是** Brain `:9527`
- P1 **无音频**；P2 预留 `includeAudio=false` 接口
- 验收：`bytes_received` 增长 + `ffprobe` 见 `h264`（无 audio 也通过）

## 不包含

- 直播音频（P2）
- Runtime（GoPro / 灯）、Cast、双 Brain 自动切换
- Journey 物流浮窗、Issue 反馈、历史拉取

新设备请继续用 [`LivingRoomEdge`](../LivingRoomEdge/)。

## 打开工程

```bash
python3 ios/LivingRoomLegacy/generate_xcodeproj.py
open ios/LivingRoomLegacy/LivingRoomLegacy.xcodeproj
```

- 主屏幕名称：**HomeAgent Legacy**
- Bundle ID：`com.gaolei.livingroom.legacy`
- 最低系统：**iOS 12.0**
- 改 Swift 文件列表后重新跑 `generate_xcodeproj.py`

## 目录

```text
ios/LivingRoomLegacy/LivingRoomLegacy/
  AppDelegate.swift          iOS 12 UIWindow 入口（无 SceneDelegate）
  Services/
    BrainAPI.swift           URLSession 回调 HTTP
    ParticipantStore.swift   UserDefaults（Brain + Mac ingest URL）
    ConnectionManager.swift  register + 45s heartbeat
    IntentPoller.swift       5s 轮询 intent_detail
  VideoLiveStream/           P1 仅视频 MPEG-TS 推流
  ViewControllers/
    ChatViewController.swift
    LiveStreamViewController.swift
    SettingsViewController.swift
  Views/
    ChatMessageCell.swift
```

## iOS 12.5.8 真机部署（Xcode 26 不支持直接 Run）

Xcode 26 **没有** iOS 12 的 Developer Disk Image，点 Run 会报 `could not locate developer disk image`。Legacy 工程本身没问题，需要补 disk image 并用命令行安装。

### 前提

1. 老 iPhone **USB 连接**、**解锁**、点 **信任此电脑**
2. Xcode → **Window → Devices and Simulators** 里能看到 `iPhone (12.5.8)`（不要是 Offline）
3. 工程 **Signing** 已选 Development Team（与其它 App 相同即可）

### 步骤 A：补 DeviceSupport（只需一次）

Apple 未单独发布 12.5.8 镜像，用 **12.4** 复制并改名即可：

1. 浏览器下载 [12.4 (16G73).zip](https://github.com/isatria/Xcode-iOS-DeviceSupport/raw/master/src/12.4%20(16G73).zip)（或 [filsv 镜像](https://github.com/filsv/iOSDeviceSupport) 里的 12.4）
2. 解压得到文件夹 `12.4 (16G73)`
3. **完全退出 Xcode**
4. 终端执行（会要管理员密码）：

```bash
sudo cp -R ~/Downloads/12.4\ \(16G73\) \
  /Applications/Xcode.app/Contents/Developer/Platforms/iPhoneOS.platform/DeviceSupport/
sudo cp -R ~/Downloads/12.4\ \(16G73\) \
  "/Applications/Xcode.app/Contents/Developer/Platforms/iPhoneOS.platform/DeviceSupport/12.5.8 (16H41)"
```

5. 重开 Xcode，Devices 窗口里 12.5.8 设备不应再报 disk image 错误

### 步骤 B：编译并安装

已安装 `ios-deploy`（`brew install ios-deploy`）后：

```bash
cd ios/LivingRoomLegacy
./deploy_ios12.sh
```

或手动：

```bash
python3 ios/LivingRoomLegacy/generate_xcodeproj.py
xcodebuild -project ios/LivingRoomLegacy/LivingRoomLegacy.xcodeproj \
  -scheme LivingRoomLegacy -configuration Debug \
  -destination 'generic/platform=iOS' -allowProvisioningUpdates build

ios-deploy --detect   # 确认列出 12.5.8 设备
ios-deploy --bundle ~/Library/Developer/Xcode/DerivedData/LivingRoomLegacy-*/Build/Products/Debug-iphoneos/LivingRoomLegacy.app --justlaunch
```

### 若 rename 后仍失败

- 确认设备在 `ios-deploy --detect` 里出现
- 换原装/数据线 USB 口，关闭 Xcode 后再跑 `ios-deploy`
- 极少数情况下需旧 Mac + **Xcode 11.x** 才能调试 iOS 12；装包通常补 disk image 即可

## 排障

- 状态栏显示 Brain 地址与心跳；失败时见红色错误文案
- **设置 → 重新登记并心跳**：清空 participant 并重连
- 填局域网 Brain 时，手机须与 Brain **同一网段**

## 验收（开发机已测）

| 项 | 结果 |
|----|------|
| `xcodebuild` iOS 12 Simulator | 通过 |
| Cloud Brain register + heartbeat + intent + intent_detail | 通过（curl 同 payload） |
| iOS 12.5.8 真机安装 | 需连接老设备并在 Xcode **Signing** 选 Development Team 后 Run |

真机步骤：USB 连接 iOS 12 设备 → Xcode 选该设备 → `LivingRoomLegacy` scheme → Run → 等状态栏「心跳 OK」→ 发「现在几点」→ 约 5s 内看到结果。
