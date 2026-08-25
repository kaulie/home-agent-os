# Chromecast Web Receiver（本地管理）

Cast App ID：`F7649303`  
Namespace：`urn:x-cast:local.image`  
协议：[`docs/chromecast-cast-protocol.md`](../../../docs/chromecast-cast-protocol.md)

## 文件

| 文件 | 说明 |
|------|------|
| [`index.html`](index.html) | 完整 Receiver 页（单文件，含 CSS/JS） |

支持：

- Legacy `{"url":"…"}`
- V1 Presentation Command（`present` image/text/video、`clear`/`stop`）
- 回传 `receiver.ready` / `presentation.started` / `presentation.error` / `presentation.cleared` / `receiver.heartbeat`
- `command_id` 幂等

## 部署到公网（你操作）

1. 把本目录的 `index.html` 上传到 HTTPS 静态站点（Cast Console 通常要求 HTTPS；局域网 `http://192.168.x.x` 常被拒）。
2. Cast Developer Console → Application `F7649303` → Receiver URL 指向该页面。
3. 保存后等数分钟传播；必要时重启 Chromecast。
4. 用 iPhone LivingRoomEdge / Cast Sender 投一张图，Sender 日志应出现 `cast_status=started`（而不是 `accepted_no_event`）。

本地预览（仅看版式，Cast SDK 在浏览器里不会完整工作）：

```bash
cd plugins/chromecast-display/receiver
python3 -m http.server 8765
# 打开 http://127.0.0.1:8765/
```

## 注意

- Chromecast 拉图仍须能访问 **LAN 临时 Asset URL**；公网 8080 大图不可靠。
- 本页不连 Brain DB / LLM。
- 改协议时先改 Sender + 本 HTML，再部署。
