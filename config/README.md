# Home network endpoints

**Source of truth:** [`endpoints.json`](endpoints.json)

| Key | Meaning |
|-----|---------|
| `brain.lan` | LAN Brain base (`:9527`) |
| `brain.cloud` | Cloud Brain base |
| `mac.lan_host` | Living-room Mac (voice ingest / img-server / video-live) |
| `mac.*_port` | Service ports on that Mac |

## Change an address

1. Edit `config/endpoints.json`
2. Run `python3 tools/sync_endpoints.py` (rewrites mobile/script **defaults**)
3. Mac: either unset `MAC_EDGE_BRAIN_URL` so runtime loads this file, or set `.env` to override
4. Phones that already saved a URL in Settings keep the old value until changed/reinstalled

## Override priority

1. **Runtime** — Mac `MAC_EDGE_BRAIN_URL` / mobile Settings  
2. **Synced defaults** — values from this JSON (via sync script / Mac loader)  
3. **Mac fallback** — `http://127.0.0.1:9527`
