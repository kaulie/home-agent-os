# HomeAgentRelay

iPhone 上的最小 HTTP / WebSocket 中继。用于验证：

**Tesla 浏览器 → iPhone Personal Hotspot → iPhone `NWListener`** 能否建立 TCP/HTTP。

不使用第三方网络库、Network Extension、VPN、Bonjour、TLS。

## 打开工程

```bash
python3 ios/HomeAgentRelay/generate_xcodeproj.py
open ios/HomeAgentRelay/HomeAgentRelay.xcodeproj
```

或：Xcode → File → New → App（SwiftUI, Swift, iOS 16+），把 `HomeAgentRelay/*.swift` 和 `Info.plist` 拷进去。

## 第一阶段怎么测

1. 用 Xcode 装到真机 iPhone（模拟器没有 Personal Hotspot）。
2. Signing & Capabilities 里选你的 Team。
3. 打开 App（启动时自动 Start Server）。
4. iPhone 开启 Personal Hotspot。
5. Tesla 加入该热点。
6. App 上应出现类似 `http://172.20.10.1:8080/receiver`（IP 以界面列出的为准）。
7. Tesla 浏览器打开该 URL，应看到 **Hello Tesla**。
8. iPhone 日志出现 `GET /receiver`。

若第 7 步失败：点 **Dump Diagnostics**，把 IPv4、NWListener state/error、connection attempt、是否出现 `172.20.10.x` 记下来。先不要改架构——热点客户端访问宿主有时是 iOS 网络隔离，不是代码绑错口。

## 端口

| 服务 | 地址 | 路径 |
|---|---|---|
| HTTP | `0.0.0.0:8080` | `/` 状态页，`/receiver` Hello Tesla，`/health` JSON |
| WebSocket | `0.0.0.0:8081` | `/present` |

App 必须保持前台。锁屏或切后台后 listener 可能被系统挂起。
