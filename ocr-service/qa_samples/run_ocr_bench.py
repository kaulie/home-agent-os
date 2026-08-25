import glob
import json
import os
import time

from paddleocr import PaddleOCR

ocr = PaddleOCR(
    lang="ch",
    ocr_version="PP-OCRv5",
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=False,
)
out = []
paths = sorted(
    p
    for p in glob.glob("/tmp/ocr_bench/**/*.*", recursive=True)
    if p.lower().endswith((".png", ".jpg", ".jpeg"))
)
for p in paths:
    t0 = time.time()
    raw = ocr.predict(p)
    ms = int((time.time() - t0) * 1000)
    texts, scores = [], []
    if raw:
        d = dict(raw[0])
        texts = [str(t) for t in (d.get("rec_texts") or [])]
        try:
            scores = [float(s) for s in (d.get("rec_scores") or [])]
        except Exception:
            scores = []
    text = "".join(texts)
    avg = (sum(scores) / len(scores)) if scores else None
    out.append(
        {
            "file": os.path.basename(p),
            "text": text,
            "n_blocks": len(texts),
            "avg_conf": None if avg is None else round(avg, 4),
            "latency_ms": ms,
        }
    )
print(json.dumps(out, ensure_ascii=False))
