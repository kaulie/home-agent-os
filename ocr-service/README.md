# OCR Service

独立的图片 OCR HTTP 服务（PaddleOCR / PP-OCRv5_server）。  
**不知道** HomeAgent Asset、Brain DB、Runtime。只收图片字节，返回结构化文字 + bbox。

部署目录（云）：`/root/chat-gateway/ocr-service/`  
只绑本机回环：`127.0.0.1:9188`。不要放到 Mac Edge，也不要放到 LAN。

## API

`GET /health`

```json
{"status":"ok","engine":"paddleocr","model":"PP-OCRv5_server","model_version":"PP-OCRv5"}
```

`POST /v1/ocr`

- `application/json`：`{"image_base64":"...","language":"zh","options":{"return_bbox":true,"return_confidence":true}}`
- `multipart/form-data`：文件字段
- `image/*` / `application/octet-stream`：原始字节

响应：

```json
{
  "engine": "paddleocr",
  "model": "PP-OCRv5_server",
  "model_version": "PP-OCRv5",
  "language": "zh",
  "text": "小明今天去公园玩。",
  "blocks": [{"text": "小明", "bbox": [120, 80, 260, 140], "confidence": 0.98}]
}
```

缓存键：`sha256(image + language + options + model_version)`。

## 启动（cloud-server）

不改 systemd。Docker Compose `restart: unless-stopped`：

```bash
cd /root/chat-gateway/ocr-service
docker compose up -d --build
curl -sS http://127.0.0.1:9188/health
```

Brain `.env`：`OCR_SERVICE_URL=http://127.0.0.1:9188`

HomeAgent 对外能力是 `image.ocr`（Brain 薄包装），不是 PaddleOCR。
