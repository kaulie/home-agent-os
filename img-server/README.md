# img-server

本机 **LAN 图片 HTTP 存储**。不是 capability、不上云、不进 Brain systemd。

Mac / iPhone 的 `asset.upload` 和 `camera.capture` 把 Runtime Asset 推到这里（`dest=img_server` / `lan`）。云端静态站仍是 `http://115.190.153.53:8080`。

## 启动

```bash
python3 img-server/serve.py
```

默认 `0.0.0.0:8080`，文件落在 `img-server/img/`。

```bash
curl -s http://127.0.0.1:8080/health
curl -s -F "file=@a.jpg" http://127.0.0.1:8080/api/v1/photos/upload
# 其它设备用公网/LAN URL（PHOTO_PUBLIC_BASE，默认本机 LAN IP）
curl -OJ http://192.168.3.73:8080/<saved_as>
```

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `PHOTO_UPLOAD_HOST` | `0.0.0.0` | 监听地址 |
| `PHOTO_UPLOAD_PORT` | `8080` | 端口 |
| `PHOTO_UPLOAD_DIR` | `img-server/img` | 落盘目录 |
| `PHOTO_PUBLIC_BASE` | `http://<lan-ip>:8080` | 写入 JSON `url`、给电视/手机拉图。Mac 上传可用 `127.0.0.1`，对外必须是 LAN IP |

旧 home-server `192.168.3.65:8080` 不再是默认；需要时把 Edge 的 `MAC_EDGE_LAN_PHOTO_*` 指回去。
