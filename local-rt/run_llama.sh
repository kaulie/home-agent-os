#!/usr/bin/env bash
# llama.cpp llama-server 启动脚本（HunyuanOCR-1.5，纯 CPU）。
#
# 关键：--mlock 把模型权重锁在 RAM，OS 不准 swap/evict。
# 这是削掉"闲置后冷启 30s 尖刺"的关键——权重常驻，下次推理不用重新 page-in。
# 注意：--mlock 治的是冷启增量（~7s），不是 CPU prefill 本身（476 token 热态仍 ~23s），
# 那是算力问题，要 GPU / 更小窗口 / 更激进量化才能压。
#
# 启动后会自动发一次 warm-up 请求（一张小图 + spotting prompt），
# 强制把权重 page-in 锁住、把 vision encoder + compute graph 一次性建好，
# 这样第一个真实 OCR 请求不付冷启费。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
BIN="$ROOT/llama.cpp/build-cpu/bin/llama-server"
MODEL="$ROOT/models/HunyuanOCR.Q4_K_M.gguf"
MMPROJ="$ROOT/models/HunyuanOCR.mmproj-f16.gguf"
LOG="$ROOT/logs/llama_cpu.log"
HOST="127.0.0.1"
PORT="${LLAMA_PORT:-8082}"
THREADS="${LLAMA_THREADS:-6}"

[ -x "$BIN" ] || { echo "missing llama-server binary: $BIN" >&2; exit 1; }
[ -f "$MODEL" ] || { echo "missing model: $MODEL" >&2; exit 1; }
[ -f "$MMPROJ" ] || { echo "missing mmproj: $MMPROJ" >&2; exit 1; }
mkdir -p "$ROOT/logs"

# 停掉旧实例（同端口）
echo "stopping any existing llama-server on :$PORT ..."
lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | xargs -r kill 2>/dev/null || true
sleep 1

echo "starting llama-server with --mlock (model locked in RAM) ..."
nohup "$BIN" \
  --model "$MODEL" \
  --mmproj "$MMPROJ" \
  --host "$HOST" --port "$PORT" \
  --ctx-size 2048 \
  --n-predict 512 \
  --parallel 1 \
  -t "$THREADS" \
  --load-mode mlock \
  > "$LOG" 2>&1 &
SRV_PID=$!
echo "llama-server PID=$SRV_PID"

# 等健康检查
echo "waiting for /health ..."
for i in $(seq 1 60); do
  if curl -s --max-time 2 "http://$HOST:$PORT/health" >/dev/null 2>&1; then
    echo "healthy after ${i}s"
    break
  fi
  sleep 1
  if [ "$i" = 60 ]; then
    echo "ERROR: llama-server not healthy after 60s" >&2
    tail -20 "$LOG" >&2
    exit 1
  fi
done

# 确认 mlock 生效：日志里应有 "mlock: locked ..." 之类
echo "=== mlock status in log ==="
grep -iE "mlock|locked|model loaded" "$LOG" | tail -5 || true

# Warm-up：一张小图 + spotting prompt，强制 page-in 权重 + 建 vision encoder graph。
# 重试若干次：模型刚 load 完时 /chat/completions 可能短暂 503（slots 还没就绪）。
echo "sending warm-up request (page-in weights + build vision graph) ..."
PY="${LLAMA_WARMUP_PY:-$ROOT/venv/bin/python3.11}"
[ -x "$PY" ] || PY="python3"
"$PY" - "$HOST" "$PORT" <<'PYEOF' || echo "WARN: warm-up request failed (non-fatal)"
import base64, io, json, sys, time, urllib.request, urllib.error
host, port = sys.argv[1], sys.argv[2]
try:
    from PIL import Image
    img = Image.new("RGB", (32, 32), (200, 200, 200))
    buf = io.BytesIO(); img.save(buf, format="JPEG", quality=80)
    img_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
except Exception:
    img_b64 = "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////2wBDAf//////////////////////////////////////////////////////////////////////////////////////wAARCAABAAEDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZW5naGVqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQ8L/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExEgJBUTJhcRIjQlJjQ4QyRjU3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZW5naGVqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD3+aaaaap/9k="
prompt = "检测并识别图中所有的文字行。输出格式为 JSON 数组。"
body = json.dumps({
    "model": "HYVL",
    "messages": [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
        {"type": "text", "text": prompt},
    ]}],
    "max_tokens": 16, "temperature": 0.0,
}).encode()
url = f"http://{host}:{port}/v1/chat/completions"
last = None
for attempt in range(10):
    try:
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=180) as r:
            d = json.loads(r.read().decode())
        print("warm-up ok:", str(d.get("choices", [{}])[0].get("message", {}).get("content", ""))[:60])
        sys.exit(0)
    except urllib.error.HTTPError as e:
        last = e
        if e.code in (503, 502, 504):
            time.sleep(2); continue
        print("warm-up HTTPError", e.code, e.read()[:200]); sys.exit(1)
    except Exception as e:
        last = e; time.sleep(2)
print("warm-up failed after retries:", last)
sys.exit(1)
PYEOF

echo "=== llama-server ready (mlock + warm-up done) ==="
echo "log: $LOG"
