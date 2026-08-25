# character-service

静图「指到哪个字」。不知道 HomeAgent Asset、Brain、Planner。

云上目录：`/root/chat-gateway/character-service`  
只绑回环：`127.0.0.1:9189`。OCR 走本机已有 `ocr-service`（`127.0.0.1:9188`）。

V1 只做**一张图**。没有 Image Stream、没有连续帧。尚未登记 Planner 能力。

## 拍法（不满足就失败，不猜）

- 近似俯拍书页，书页占画面主体
- 食指完整入画，指尖对着字（不要用客厅斜视摄像头）
- 大字、字间距明显的识字绘本（密排课文不是 V1 验收材料）

## API

`GET /health`

`POST /v1/point_to_character`

- JSON：`{"image_base64":"...","language":"zh","return_debug":false}`
- 或 raw `image/jpeg`

成功：

```json
{"status":"ok","character":"吃","bbox":[180,40,220,90],"score":0.81}
```

认不出：

```json
{"status":"uncertain","character":null,"reason":"low_margin"}
```

`no_hand` / `no_text` / `failed` 同样 JSON，不抛成「猜一个字」。

`return_debug: true` 时多 `debug_png_base64`（射线 + 字框叠图）。

## 启动（cloud-server）

先确认 `ocr-service` 已在 `127.0.0.1:9188`。

```bash
cd /root/chat-gateway/character-service
docker compose up -d --build
curl -sS http://127.0.0.1:9189/health
```

不改 systemd。Compose `restart: unless-stopped`。

几何权重用环境变量：`READING_MAX_ANGLE_DEG`、`READING_MIN_SCORE`、`READING_MIN_MARGIN`、`READING_MAX_DIST_FRAC`。
