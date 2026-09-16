# 局域网地址「探测优先」v1 — 小度 / 小米 / 本机供流地址不再写死

**状态：** 已实现，待合并/部署
**版本：** v1（2026-09-16）
**触发：** 用户提出「优化：小度和小米的局域网地址采用探测的方式寻找，不再写死地址」

---

## 1. 实测现状（先量事实，再改）

| 目标 | 现在怎么拿地址 | 实测 |
|---|---|---|
| 小度音箱 | 写死 env `MAC_EDGE_XIAODU_IP=192.168.3.47` | 现在碰巧还是 .47，但 DHCP 一换（或音箱重启换 IP）就静默失效 |
| 小度能访问的「本机供流地址」 | 写死 env `MAC_EDGE_XIAODU_PUBLIC_HOST=192.168.3.73` | **已经错了**：本机现在是 `192.168.3.84`（`ifconfig` 实测），现网日志也一直在播 `public_host=192.168.3.73` → 小度拿到的 MP3 URL 指向不存在的地址 |
| 小米电视 | 已经**不写死**：`xiaomi_tv_display.py` = location 缓存 → 单播重取描述（探测）→ SSDP 多轮 → 配了 MAC 时 WoL | 这次 SSDP 扫描里电视没应答（网络待机/深度休眠），符合代码注释里写的行为 |

SSDP 实测（`M-SEARCH ST=urn:schemas-upnp-org:device:MediaRenderer:1`，本机执行）：

```
192.168.3.47   Linux/4.9.54, UPnP/1.0, Portable SDK    loc=http://192.168.3.47:49494/description.xml
               usn=uuid:6ca6cae6-e861-410b-9e83-f708e4cb89fe::urn:schemas-upnp-org:device:MediaRenderer:1
192.168.3.59   Linux/5.15.170-android14（Android TV/Chromecast）  loc=http://192.168.3.59:8008/ssdp/device-desc.xml
192.168.3.1    Huawei-ATP-IGD（路由器）
```

小度 `description.xml`（探测拿到的身份信息，可用来精确匹配）：

```xml
<friendlyName>小度智能音箱-8432</friendlyName>
<manufacturer>DuerOS</manufacturer>
<modelName>DuerOS-Render</modelName>
<UDN>uuid:6ca6cae6-e861-410b-9e83-f708e4cb89fe</UDN>
<serviceType>urn:schemas-upnp-org:service:AVTransport:1</serviceType>
<controlURL>/upnp/control/rendertransport1</controlURL>
<URLBase>http://192.168.3.47:49494/</URLBase>
```

## 2. 设计

新增**共用探测层** `mac/src/mac_edge/plugins/lan_discovery.py`（纯标准库，可单测）：

| 函数 | 作用 |
|---|---|
| `ssdp_search(st, timeout_sec, rounds)` | 组播 M-SEARCH，返回 `{ip, location, st, usn, server}` 去重列表 |
| `fetch_device_description(location)` | 拉 UPnP 描述 → `friendly_name / manufacturer / model_name / udn / url_base / services{type: control_url}` |
| `local_ip_for(peer_ip)` | **按目标地址探测本机出口 IP**：UDP connect 到 peer 再 `getsockname()`（比连 8.8.8.8 可靠，且拿到的是能直达该设备的那个接口） |
| `local_ips()` / `is_local_ip(ip)` | 本机所有 IPv4 网卡地址；用来**拒绝过期的写死覆盖值** |
| `read_cache / write_cache` | `mac/data/*.json` 小缓存（带 `saved_at`） |

**小度（`xiaodu_speaker.py`）**：

1. 地址解析顺序：调用方 `du_ip` → env `MAC_EDGE_XIAODU_IP`（**降级为可选覆盖**）→ 缓存 → **SSDP 探测**；
2. 每一级都**先探测再采信**：拿描述 + `GetTransportInfo` SOAP 探活（真的能控制才返回）；
3. 发现结果落盘 `mac/data/xiaodu_renderer.json`（ip / location / control_url / friendly_name / saved_at）；
4. 识别小度：`manufacturer` 含 `DuerOS` 或 `friendlyName` 含「小度 / xiaodu / duer」（多台可用 `MAC_EDGE_XIAODU_NAME` 指定）；
5. 控制地址用**描述里的 `controlURL` + `URLBase`**（不再写死 `:49494/upnp/control/rendertransport1`；只在「只给了 IP」的老式覆盖下才按老路径拼）；
6. `speak()` 播放失败 → 丢缓存、重新探测、重试一次（自愈）；
7. 供流地址 `public_host()`：env `MAC_EDGE_XIAODU_PUBLIC_HOST` **只在它确实是本机网卡 IP 时才用**，否则自动按「能直达小度的那个接口」探测，并 warn 说明忽略了一个过期值。

**小米电视**：保持「缓存 → 探测 → SSDP → WoL」不变（本来就是探测式），把它的 `_ssdp_search` 收敛到共用层，语义等价。

**广告门控**：`xiaodu.speaker` 不再要求 env IP —— `MAC_EDGE_XIAODU=0` 关闭；否则「有覆盖 / 有缓存 / 现场探测到」任一成立就广告（日志写清依据）。

## 4. 验收（真机）

- 单测：`test_lan_discovery` 20 个 + `test_xiaodu_speaker` 12 个全绿；全量 `mac/tests` 915 个，
  失败集合是 `origin/main` 基线（879 个）的**子集**（无回归，基线多出的那条是并发跑出的 mDNS flake）。
- 真机探测（本机执行，非 mock）：

```
local_ips()                     -> ['192.168.3.84']
is_local_ip('192.168.3.73')     -> False          # 写死的过期值被识别
is_local_ip('192.168.3.84')     -> True
resolve_public_host('192.168.3.47', override='192.168.3.73')
                                -> '192.168.3.84'  # 忽略过期覆盖 + warn
ssdp_search()                   -> 192.168.3.47 http://192.168.3.47:49494/description.xml
fetch_device_description(...)   -> 小度智能音箱-8432 / DuerOS / DuerOS-Render
probe_av_transport(control_url) -> True
```

- 全链路（真小度音箱，地址与供流地址**全部来自探测**）：

```
INFO  小度 用缓存 小度智能音箱-8432 @ 192.168.3.47 [cache] via http://192.168.3.47:49494/upnp/control/rendertransport1
INFO  xiaodu.speak uri=http://192.168.3.84:61455/tts_1789548464.mp3 ...
DEBUG xiaodu-tts http "GET /tts_1789548464.mp3 HTTP/1.1" 200 -     ← 音箱真的从 .84 拉到了音频
```

（`GET ... 200` 是音箱发出的请求，证明「探测出来的控制地址 + 探测出来的本机 IP」整条链路可用。）

## 5. 明确不做

- 不做全网段 IP 扫描（ARP/nmap 扫 /24）——组播 SSDP 已够，且扫描会打扰邻居设备。
- 不改小米电视的「唤醒」策略（WoL 仍需 `MAC_EDGE_XIAOMI_TV_MAC`，这是另一件事）。
- 不删环境变量：`MAC_EDGE_XIAODU_IP` / `MAC_EDGE_XIAOMI_TV_HOST` 保留为**可选覆盖**（显式指定时优先），只是不再是必需项。
