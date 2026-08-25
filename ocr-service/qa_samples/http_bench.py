#!/usr/bin/env python3
import json
import os
import time
import urllib.error
import urllib.request

ROOT = "/tmp/ocr_bench"
URL = "http://127.0.0.1:9188/v1/ocr"


def walk_images(root: str) -> list[str]:
    out = []
    for dirpath, _, files in os.walk(root):
        for name in files:
            if name.startswith("._"):
                continue
            if name.lower().endswith((".png", ".jpg", ".jpeg")):
                out.append(os.path.join(dirpath, name))
    return sorted(out)


def ocr_file(path: str, timeout: int) -> tuple[dict, int]:
    ctype = "image/jpeg" if path.lower().endswith((".jpg", ".jpeg")) else "image/png"
    data = open(path, "rb").read()
    req = urllib.request.Request(URL, data=data, headers={"Content-Type": ctype})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"error": str(e)}, int((time.time() - t0) * 1000)
    return payload, int((time.time() - t0) * 1000)


def main() -> None:
    results = []
    paths = walk_images(ROOT)
    print(f"n_images={len(paths)}", flush=True)
    for i, path in enumerate(paths):
        timeout = 300 if i == 0 else 120
        print(f"[{i+1}/{len(paths)}] {path}", flush=True)
        payload, ms = ocr_file(path, timeout)
        blocks = payload.get("blocks") or []
        confs = [float(b["confidence"]) for b in blocks if isinstance(b.get("confidence"), (int, float))]
        results.append(
            {
                "file": os.path.basename(path),
                "path": path,
                "text": payload.get("text") or "",
                "n_blocks": len(blocks),
                "avg_conf": round(sum(confs) / len(confs), 4) if confs else None,
                "latency_ms": ms,
                "error": payload.get("error"),
                "model": payload.get("model"),
            }
        )
    out = "/tmp/ocr_bench_results.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("WROTE", out, flush=True)
    print(json.dumps(results, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
