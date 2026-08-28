# GEN45 Q4 泛化评估（30–45° 倾斜拍摄）

归档时间：2026-08-25  
模型：生产 Q4（`HunyuanOCR.Q4_K_M.gguf`）  
图集：`fingure_imgs/45_degree/` — IMG_8049–8054（相对昨日正俯视角倾斜约 30–45°）  
几何 / pipeline：与 `eval/q4` 基线相同（未改代码）

## 多轮稳定性（6 图 × 5 轮 = 30 次）

**无 GT** — 先出 top1/top3 供人工核对；验收口径仍是「正确字进 top-3」。

| 图 | top1 众数 | 5轮 top1 | top3 并集 | top1 稳定 |
|---|---|---|---|---|
| IMG_8049 | 零 | 零×5 | 零, 七, 样 | Y |
| IMG_8050 | 的 | 的×4, 患×1 | 的, 之, 患, 而 | N |
| IMG_8051 | 辎 | 辎×5 | 辎, 带, 重 | Y |
| IMG_8052 | 柔 | 柔×5 | 柔, 然, 军 | Y |
| IMG_8053 | 一 | 一×5 | 一, 统, 到 | Y |
| IMG_8054 | 代 | 代×5 | 代, 迭, 的 | Y |

- **5/6 图 top1 五轮完全稳定**；仅 8050 有 1 轮 top1 从「的」跳到「患」。
- 全 30 轮均有有效 `replay`（指尖 + blocks + chars + ranked + verdict），无超时/ERR。
- 首轮冷启动约 170–185s；热轮常见 ~7–60s（与昨日 Q4 量级一致）。

## 文件

- `stability.log`：每轮明细
- `stability_raw.json`：每轮结构化记录
- `summary.md`：短表
- `replay/<img>_r<n>.json`（30 份）：完整阶段 I/O
  - `landmarks` / `origin` / `direction`
  - `blocks`（OCR 行块）→ `chars`（拆字）→ `ranked` → `verdict`
  - 已去除 `debug_png_base64`

## 离线 replay

```python
import json
from geometry import rank_characters
d = json.load(open("replay/IMG_8049_r1.json"))
r = d["replay"]
ranked = rank_characters(
    r["chars"], tuple(r["origin"]), tuple(r["direction"]),
    max_angle_deg=r["max_angle_deg"], max_distance=r["max_distance"],
)
```

## 下一步

1. 用户确认每图正确字（可多解，如昨日 娘/姑、剧/本）。
2. 填 GT 后算 top1/top3 通过率；失败 case 用 replay 离线调几何，不轻易动 VLM。
