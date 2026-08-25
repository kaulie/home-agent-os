# Chromecast Cast Presentation Protocol (V1)

Status: Implementation Spec  
Scope: Home Agent Cast **Sender** ↔ custom **Web Receiver** HTML  
Receiver HTML **本地管理**：[`plugins/chromecast-display/receiver/index.html`](../plugins/chromecast-display/receiver/index.html)（你部署到公网；Cast Console 指到该 URL）。

Aligns with: [`endpoint-contract.md`](endpoint-contract.md), [`asset-contract.md`](asset-contract.md)  
Plugin: [`plugins/chromecast-display/`](../plugins/chromecast-display/)

---

## 1. Fixed Cast coordinates

| Item | Value |
|------|--------|
| Receiver App ID | `F7649303` (custom CAF; not Default Media Receiver) |
| Message namespace | `urn:x-cast:local.image` |
| Wire capabilities (Edge) | `display.photo`, `display.slideshow` |
| Primary sender (V1) | iPhone Cast SDK (`CastSessionController`) |
| Mac path | `GET :9095/endpoint/display?url=` — **legacy URL-only**; prefer iPhone Cast for Presentation Protocol |

---

## 2. Legacy vs V1 messages (same namespace)

**Legacy (still accepted by old HTML):**

```json
{"url": "http://192.168.x.x:.../photo.jpg"}
```

**V1 Presentation Command (Sender sends this; HTML should prefer it):**

```json
{
  "type": "command",
  "protocol_version": 1,
  "command_id": "cmd_01H…",
  "action": "present",
  "payload": {
    "presentation_id": "p_01H…",
    "content": {
      "type": "image",
      "asset": {
        "asset_id": "asset_…",
        "access": {
          "url": "http://192.168.x.x:.../…",
          "expires_at": 0
        }
      }
    },
    "options": {
      "fit": "contain",
      "background": "black"
    }
  }
}
```

Compatibility: Sender may include top-level `"url"` equal to `payload.content.asset.access.url` so old HTML keeps working until you update the page.

### Other V1 actions

| `action` | Meaning |
|----------|---------|
| `present` | Show content (`image` / `text` / `video`) |
| `clear` | Stop renderer, clear stage |
| `stop` | Stop playback / presentation |
| `pause` / `resume` | Video (optional V1) |

**Slideshow (wire `display.slideshow`):** Sender issues sequential `present` commands (one image each) with shared or per-slide `presentation_id`; do not invent a second Cast namespace.

---

## 3. Receiver → Sender events (same namespace)

```json
{"type": "event", "event": "receiver.ready", "receiver": {"version": "1.0"}, "capabilities": ["present.image", "present.text", "present.video"]}
{"type": "event", "event": "presentation.started", "command_id": "cmd_…", "presentation_id": "p_…"}
{"type": "event", "event": "presentation.completed", "command_id": "cmd_…", "presentation_id": "p_…"}
{"type": "event", "event": "presentation.error", "command_id": "cmd_…", "presentation_id": "p_…", "error": {"code": "ASSET_LOAD_FAILED", "message": "…"}}
{"type": "event", "event": "presentation.cleared", "command_id": "cmd_…"}
{"type": "event", "event": "receiver.heartbeat", "ts": 0}
```

Rules:

- `sendTextMessage` success = **accepted**, not displayed.
- Step success should wait for `presentation.started` (or fail on `presentation.error` / timeout).
- Duplicate `command_id` → return current status; do not re-render.

---

## 4. IDs

| ID | Scope |
|----|--------|
| `command_id` | One Cast command |
| `presentation_id` | One on-screen presentation lifecycle |

Sender generates both (ULID / UUID with `cmd_` / `p_` prefix).

---

## 5. Asset access

- Canonical identity: `asset_id` (AssetRef).  
- V1 Cast payload may embed temporary LAN `access.url` resolved by Runtime / sender.  
- Chromecast must reach that LAN URL (not public `115.190.153.53:8080` for large JPG).

---

## 6. HTML checklist / 本地源码

Receiver 源码在仓库：[`plugins/chromecast-display/receiver/index.html`](../plugins/chromecast-display/receiver/index.html)。  
部署步骤见同目录 [`README.md`](../plugins/chromecast-display/receiver/README.md)。

已实现：

1. 监听 `urn:x-cast:local.image`
2. V1 `type=command` + legacy `url` 双兼容
3. `present` image / text / video；`clear` / `stop`
4. `presentation.started` / `error` / `cleared`；启动与连上 sender 时 `receiver.ready`；心跳
5. `command_id` 幂等
6. 单页长期运行，不整页刷新

---

## 7. Sender behaviour (this repo)

- Build V1 command JSON; dual-write top-level `url` during migration.
- Listen for events on the same channel; map to capability outputs / step_log (`cast_status`: `accepted` → `started` | `error` | `timeout`).
- Default wait for `presentation.started`: ~20s after send (configurable).

---

## 8. Definition of done (V1 vertical slice)

- `display.photo` with AssetRef → Cast V1 command → TV shows image  
- Sender observes `presentation.started` or `presentation.error`  
- Old HTML still works via dual `url` field until you cut over  
- Docs + `capability.md` state custom Receiver (not DMR)
