# LAN img-server (home-server)

Listens on `0.0.0.0:8080`. Files go in `img/`.

```bash
# health
curl -s http://127.0.0.1:8080/health

# upload
curl -s -F "file=@a.jpg" http://127.0.0.1:8080/api/v1/photos/upload

# Cast-style download
curl -OJ http://127.0.0.1:8080/<saved_as>
```

Public URL for other devices: `http://192.168.3.65:8080/{saved_as}`.
