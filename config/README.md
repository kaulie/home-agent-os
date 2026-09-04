# Home network endpoints

**LAN 身份：** [`endpoints.json`](endpoints.json) 只写 well-known mDNS 名（`brain.local` / `gateway.local` / `img-server.local`），**不写死局域网 IP**。IP 是发现结果，DHCP 变了上层无感。

**谁在跑、怎么起：** [`docs/service-topology.md`](../docs/service-topology.md)

| Key | Meaning |
|-----|---------|
| `brain.lan` | LAN Brain 身份（`http://brain.local:9527`） |
| `brain.cloud` | Cloud Brain base（公网 IP 可以写死） |
| `mac.lan_host` | Mac Edge gateway（`gateway.local`：voice / video / TTS） |
| `mac.img_host` | img-server（`img-server.local`） |
| `mac.*_port` | Service ports |

本机与 Brain 同机：Mac Edge HTTP 走 `http://127.0.0.1:9527`，不要用 `.local` 当 loopback。手机/其它设备：mDNS 发现后用解析出的 IPv4 发 HTTP。

## Change an address

1. Edit `config/endpoints.json`（只改 hostname / 端口 / 云地址）
2. Run `python3 tools/sync_endpoints.py`（重写移动端/脚本 **defaults**）
3. Mac：`run_mac_edge.sh` 已是 loopback；不要把 LAN IP 写进 `.env`
4. 手机里已经存过旧 IP 的，设置里改回自动发现或重装

## Override priority

1. **Runtime** — Mac `MAC_EDGE_BRAIN_URL` / 手机设置里的已解析 IPv4
2. **Synced identity** — 本 JSON 的 hostname（via sync / 冷启动默认）
3. **Mac fallback** — `http://127.0.0.1:9527`
