# Plan: LAN Service Discovery / mDNS 迁移（v2）

> 源契约：`/Users/gaolei/devspace/home-agent-docs/service_discovery.md`
> 版本：v2（2026-08-31）
> 状态：Phase 0 实施中（发布层已上线验证）
>
> v2 变更：well-known **service type** 因 RFC 6763 §7.1（label ≤ 15 字节）从
> `_home-agent-gateway._tcp`（17 字符，不合法）等改为紧凑前缀 `_ha-*`；
> `brain.local`/`gateway.local` hostname 不受影响。

## 1. 目标与边界

- Identity（runtime_id/hostname）与 Endpoint（IP:port）解耦，IP 仅作动态状态。
- Well-known：
  - hostname：`brain.local`、`gateway.local`、`runtime-<id>.local`、`img-server.local`
  - service type（label ≤ 15 字节，RFC 6763 §7.1）：
    - `_ha-brain._tcp`（Brain，:9527）
    - `_ha-gateway._tcp`（mac_edge gateway，TXT 携带 voice/video/img/tts 端口）
    - `_ha-runtime._tcp`（mac_edge runtime identity）
    - `_ha-img-server._tcp`（img-server，:8080）
- 只迁移「局域网设备间通信」→ mDNS；本机 localhost / 云端 / 第三方强制 IP 不动。
- 发现 ≠ 认证：Onboard 认证/pairing 保留。
- 增量迁移，Minimal Change + Clear Boundary，最后删除固定 IP。
- 一个进程可发布多个 service（多重身份），同 type 多端口用实例名或 TXT 子端点区分。

## 2. 现状盘点

| 角色 | 当前实现 | 端口 |
|------|----------|------|
| Brain | server/home_brain.py (Flask) | 9527 |
| img-server | img-server/serve.py | 8080 |
| Runtime | mac_edge (Python) / iOS LivingRoomEdge (Swift) | — |
| Gateway | **mac_edge 兼任**（voice 8792 / video 8790 等） | TXT |

需迁移的硬编码 LAN IP（后续阶段）：
- config/endpoints.json（brain.lan=192.168.3.84:9527, mac.lan_host=192.168.3.84）
- plugins/runtime-agent-sdk/ios/AssetManager/AssetHTTPTransport.swift（192.168.3.73:8080）
- server/home_brain.py:5387（photo public base）
- server/img-server.plist（PHOTO_PUBLIC_BASE）
- ios/LivingRoomEdge/Info.plist（ATS 例外 192.168.3.72/73/84）

保留不动：127.0.0.1（本机）、115.190.153.53（云端）、Chromecast 192.168.3.59（第三方）。

## 3. 决策记录

- [x] D1 Gateway 归属：**mac_edge 兼任 gateway.local**（voice/video receiver）；debug_gateway 单独处理、暂不动
- [x] D3 img-server：**纳入 well-known service**，publish `_ha-img-server._tcp`
- [x] D4 优先级：**先做 Brain + Gateway**（发布 + 发现）；照片链迁移延后
- [x] D2 依赖：**python-zeroconf**（mac venv 已有；server/img-server 走 dns-sd 兜底）
- [x] D5（v2 新增）：service type 采用 `_ha-*`（RFC 6763 ≤15 字节约束）

## 4. 实施

### Phase 0 — 发布层（进行中）
- [x] 共享模块 `server/mdns_service.py`：publish（zeroconf / dns-sd 双后端）+ discover
- [x] mac_edge 发布 `_ha-runtime._tcp` + `_ha-gateway._tcp`（TXT: edge_id/voice_port/video_port/img_port/tts_port）——**已线上验证**
- [x] img-server 发布 `_ha-img-server._tcp`（:8080）——**已线上验证**
- [x] Brain 发布 `_ha-brain._tcp`（:9527）+ `brain.local`（home_brain.py / brain_app.py 已接入；待 Brain 主机重启验证）
- [ ] 单测：`mac/tests/test_mdns_service.py`（roundtrip + dns-sd 参数 + 类型 ≤15 字节）——**已通过**
- [ ] `dns-sd` 冒烟（已完成 python-zeroconf discover 验证）

### Phase 1 — 发现层（未开始）
- mac_edge：Brain 解析改 Discovery-first（zeroconf 查 `_ha-brain._tcp` → `brain.local` → `127.0.0.1` dev-only → backoff 重连）
- iOS LivingRoomEdge：`NWBrowser` 浏览 `_ha-brain._tcp` / `_ha-gateway._tcp`；设置页「自动发现」+ 手动兜底；Info.plist 加 NSBonjourServices
- Brain Onboard/Register 增 hostname/endpoint 字段（IP 仅诊断状态）

## 5. 延后项
- 照片链硬编码迁移（AssetHTTPTransport / photo public base）
- ATS 旧 IP 例外清理
- debug_gateway 单独处理

## 6. 验收（AC-1..10 子集）
- mac 单测：discovery 解析、backoff、hostname 优先、localhost 保持
- iOS 编译 + 自动发现流程
- 黑盒：AC-1（brain 可发现）、AC-3（runtime 不依赖固定 IP）、AC-6（IP 变化上层无感）
