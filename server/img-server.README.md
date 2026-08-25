# LAN img-server

Canonical code: [`img-server/`](../img-server/) at the repo root (`python3 img-server/serve.py`). Not a capability. Do not deploy to cloud.

Default listen `0.0.0.0:8080`. Files go in `img-server/img/`. Public URL for other devices: `http://192.168.3.73:8080/{saved_as}` (or `PHOTO_PUBLIC_BASE`).

```bash
curl -s http://127.0.0.1:8080/health
curl -s -F "file=@a.jpg" http://127.0.0.1:8080/api/v1/photos/upload
curl -OJ http://127.0.0.1:8080/<saved_as>
```

This directory's [`photo_upload_server.py`](photo_upload_server.py) is the older Brain-adjacent copy. Prefer the repo-root img-server on this Mac.
