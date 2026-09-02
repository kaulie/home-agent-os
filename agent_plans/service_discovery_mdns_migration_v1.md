# Plan: LAN Service Discovery / mDNS 迁移（v1）

> 源契约：`/Users/gaolei/devspace/home-agent-docs/service_discovery.md`
> 版本：v1（2026-08-31）
> 状态：已定稿，待执行

## 1. 目标与边界

- Identity（runtime_id/hostname）与 Endpoint（IP:port）解耦，IP 仅作动态状态。
- Well-known：`brain.local`/`_home-agent-brain._tcp`、`gateway.local`/`_home-agent-gateway._tcp`、
  `runtime-<id>.local`/`_home-agent-runtime._tcp`、`img-server.local`/`_home-agent-img-server._tcp`。
- 只迁移「局域网设备间通信」→ mDNS；本机 localhost / 云端 / 第三方强制 IP 不动。
- 发现 ≠ 认证：Onboard 认证/pairing 保留。
- 增量迁移，Minimal Change + Clear Boundary，最后删除固定 IP。
- 一个进程可发布多个 service（多重身份），同 type 多端口用实例名或 TXT 子端点区分。

## 2. 现状盘点

| 角色 | 当前实现 | 端口 |
|------|----------|------|
| Brain | server/home_brain.py (Flask) | 9527 |
| img-server | img-server/serve.py + server/photo_upload_server.py | 8080 |
| Runtime | mac_edge (Python) / iOS LivingRoomEdge (Swift) | — |
| Gateway | **mac_edge 兼任**（voice 8792 / video 8790 等） | 见 TXT |

需迁移的硬编码 LAN IP（后续阶段）：
- config/endpoints.json（brain.lan=192.168.3.84:9527, mac.lan_host=192.168.3.84）
- plugins/runtime-agent-sdk/ios/AssetManager/AssetHTTPTransport.swift（192.168.3.73:8080）
- server/home_brain.py:5387（photo public base）
- server/img-server.plist（PHOTO_PUBLIC_BASE）
- ios/LivingRoomEdge/Info.plist（ATS 例外 192.168.3.72/73/84）

保留不动：127.0.0.1（本机）、115.190.153.53（云端）、Chromecast 192.168.3.59（第三方）。

## 3. 决策记录

- [x] D1 Gateway 归属：**mac_edge 兼任 gateway.local**（voice/video receiver）；debug_gateway 单独处理、暂不动
- [x] D3 img-server：**纳入 well-known service**，publish `_home-agent-img-server._tcp`
- [x] D4 优先级：**先做 Brain + Gateway**（发布 + 发现）；照片链迁移延后
- [ ] D2 依赖：默认 **python-zeroconf**（待最终确认）

## 4. 实施（本期：Phase 0 + Phase 1 收窄）

### Phase 0 — 发布层
- server（Brain）：发布 `_home-agent-brain._tcp`（:9527）+ `brain.local` hostname 别名（尽力而为）
- mac_edge：发布 `_home-agent-runtime._tcp` + `_home-agent-gateway._tcp`（TXT 携带 voice_port=8792 / video_port=8790 等子端点）
- img-server：发布 `_home-agent-img-server._tcp`（:8080）
- 验证：dns-sd 冒烟 + 单测

### Phase 1 — 发现层
- mac_edge：Brain 解析改 Discovery-first（zeroconf 查 `_home-agent-brain._tcp` → `brain.local` → `127.0.0.1` dev-only → backoff 重连）
- iOS LivingRoomEdge：`NWBrowser` 浏览 `_home-agent-brain._tcp` / `_home-agent-gateway._tcp`；设置页「自动发现」+ 手动兜底；Info.plist 加 NSBonjourServices
- Brain Onboard/Register 增 hostname/endpoint 字段（IP 仅诊断状态）

## 5. 延后项
- 照片链硬编码迁移（AssetHTTPTransport / photo public base）
- ATS 旧 IP 例外清理
- debug_gateway 单独处理

## 6. 验收（AC-1..10 子集）
- mac 单测：discovery 解析、backoff、hostname 优先、localhost 保持
- iOS 编译 + 自动发现流程
- 黑盒：AC-1（brain.local 可发现）、AC-3（runtime 不依赖固定 IP）、AC-6（IP 变化上层无感）
