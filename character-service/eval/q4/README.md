# Q4 评估存档（HunyuanOCR.Q4_K_M.gguf）

归档时间：2026-08-25
模型：`/root/hunyuan-gguf/HunyuanOCR.Q4_K_M.gguf` + `HunyuanOCR.mmproj-f16.gguf`
几何版本：`geometry.py` 含 lateral_score（指尖高度 box-containment 高带 + 水平距离主导 + 手指水平度门 32°）+ bbox 去重
pipeline：双窗口(600,0)/(600,260) × 双跑 + 复核 re-ORC（每图最多 5 次 VLM 调用）

## 多轮稳定性（6 图 × 5 轮 = 30 次调用）

| 图 | 正确 | top3 通过 | top1 正确 | 平均耗时 |
|---|---|---|---|---|
| 7832 | 渊 | 5/5 | 5/5 | 18.9s |
| 8022 | 因 | 5/5 | 5/5 | 95.1s |
| 8023 | 娘/姑 | 5/5 | 5/5 | 46.1s |
| 8024 | 霸 | 5/5 | 5/5 | 16.2s |
| 8025 | 剧/本 | 5/5 | 5/5 | 10.6s |
| 8026 | 碾 | 5/5 | 5/5 | 17.9s |
| **合计** |  | **30/30 (100%)** | **30/30 (100%)** | — |

验收口径：正确答案在 top-3 内即通过。**top1 每轮全对**。

## 耗时分解（典型）

| 图 | hand | ocr_vlm(4次) | geom(含复核re-OCR) | total |
|---|---|---|---|---|
| 8022 r1 | 0.1s | 56.5s | 45.8s | 102.4s |
| 8025 r1 | 0.2s | 9.3s | 1.1s | 10.6s |
| 8024 r1 | 0.3s | 4.9s | 1.0s | 6.3s |

瓶颈：VLM 在 CPU 上的 prompt eval。冷调用（KV cache 未命中）大图块 ~45–56s/次；热调用 ~2s/次。几何本身 <0.1s（geom 列含复核 re-OCR 的 VLM 调用）。

## 文件

- `stability.log`：每轮明细（top1/top3/ok/耗时）
- `stability_raw.json`：每轮结构化记录
- `replay/<img>_r<n>.json`（30 份）：每次调用的完整阶段 I/O
  - `landmarks`：食指 MCP/PIP/DIP/TIP 像素坐标
  - `origin` / `direction`：指尖坐标 + 食指单位向量
  - `max_distance` / `max_angle_deg` / `min_score` / `min_margin`：几何参数
  - `blocks`：OCR 行块（text + bbox，原图坐标）
  - `chars`：等分拆出的单字（text + bbox + split + source_text）
  - `ranked`：完整排序（text + bbox + score + mode + split）
  - `verdict`：裁决结果
  - 注：已去除 `debug_png_base64`（叠加图），几何 replay 不需要

## 离线 replay 用法

```python
import json
from geometry import rank_characters
d = json.load(open("replay/IMG_8022_r1.json"))
r = d["replay"]
ranked = rank_characters(
    r["chars"], tuple(r["origin"]), tuple(r["direction"]),
    max_angle_deg=r["max_angle_deg"], max_distance=r["max_distance"],
)
# 不重跑 VLM 即可验证几何改动
```
