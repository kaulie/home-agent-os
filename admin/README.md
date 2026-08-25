# Home Agent 现场管理（本机）

**不上云。** 页面只在你这台 Mac 上开。

```bash
python3 admin/serve.py
```

浏览器打开 <http://127.0.0.1:8788/>。

默认把 `/api/v1/admin/*` 转到本机 Brain `http://127.0.0.1:9527`。可改：

- `ADMIN_HOST` / `ADMIN_PORT`（默认 `127.0.0.1:8788`）
- `BRAIN_URL`（要管哪套 Brain）
- 页面上的管理员令牌对应 Brain 的 `BRAIN_ADMIN_TOKEN`（没设则可空）

若未来在管理页展示 asset 图片，须走 Brain `GET /api/v1/assets/{id}/content?intent_id=` 流式代理，禁止直链 `storage.url` / img-server 永久 URL。
