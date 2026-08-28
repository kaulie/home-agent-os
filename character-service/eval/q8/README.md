# Q8 评估存档（HunyuanOCR.Q8_0.gguf）

归档时间：2026-08-25
模型：`/root/hunyuan-gguf/HunyuanOCR.Q8_0.gguf` + `HunyuanOCR.mmproj-f16.gguf`
几何版本：与 Q4 基线相同（`geometry.py` lateral_score + bbox 去重），**未针对 Q8 重调**
pipeline：同 Q4（双窗口 × 双跑 + 复核 re-OCR，每图最多 5 次 VLM 调用）
llama-server：`ctx-size=1536`（Q4 为 2048），以降低 OOM 风险

## 多轮稳定性（6 图 × 5 轮 = 30 次调用）

| 图 | 正确 | top3 通过 | top1 正确 | 平均耗时 |
|---|---|---|---|---|
| 7832 | 渊 | 4/5 | 4/5 | 63.4s |
| 8022 | 因 | 2/5 | **0/5** | 179.9s |
| 8023 | 娘/姑 | 5/5 | 5/5 | 89.9s |
| 8024 | 霸 | 5/5 | 5/5 | 62.7s |
| 8025 | 剧/本 | 5/5 | 5/5 | 58.2s |
| 8026 | 碾 | 5/5 | 5/5 | 55.7s |
| **合计** |  | **26/30 (87%)** | **24/30 (80%)** | — |

- 7832 r1：VLM 调用超时（无 replay 文件），其余 4 轮 top1=渊 ✓
- 8022：top1 全是「《」，5 轮 0 命中；「因」仅 r2/r5 进 top3

## Q4 vs Q8 对比

| 图 | Q4 top1 | Q8 top1 | Q4 耗时 | Q8 耗时 |
|---|---|---|---|---|
| 7832 | 5/5 ✓ | 4/5 ✓ | 18.9s | 63.4s |
| 8022 | 5/5 ✓ | **0/5 ✗** | 95.1s | 179.9s |
| 8023 | 5/5 ✓ | 5/5 ✓ | 46.1s | 89.9s |
| 8024 | 5/5 ✓ | 5/5 ✓ | 16.2s | 62.7s |
| 8025 | 5/5 ✓ | 5/5 ✓ | 10.6s | 58.2s |
| 8026 | 5/5 ✓ | 5/5 ✓ | 17.9s | 55.7s |
| **合计 top1** | **30/30 (100%)** | **24/30 (80%)** | — | — |
| **合计 top3** | **30/30 (100%)** | **26/30 (87%)** | — | — |

## 结论

- **准确率**：Q8 全面劣于 Q4。唯一失败点 8022 在 Q4 上是专门修好的 case（top1=因），Q8 的 VLM 行框分布与 Q4 不同，把那套几何打穿——top1 变「《」，「因」连 top3 都常进不去。
- **速度**：Q8 平均慢约 3–4 倍。瓶颈是 CPU 上 prompt eval（~8 tok/s，Q4 更快）。冷调用 ~180–200s/图，热调用 ~10–75s/图。
- **稳定性**：Q8 出现 1 次超时（7832 r1）；内存压力更大（Q8 常驻 ~5G/7G，多次逼近 1G 可用）。
- **判定**：**保留 Q4 为生产模型**。Q8 不启用。若要用 Q8，需针对 Q8 的 VLM 输出重新调几何（lateral_score / 行框拆分阈值），性价比低于继续优化 Q4。

## 文件

- `stability.log`：每轮明细（top1/top3/ok/耗时）
- `stability_raw.json`：每轮结构化记录
- `replay/<img>_r<n>.json`（29 份，缺 7832_r1）：每次调用的完整阶段 I/O
  - 字段同 Q4：`landmarks / origin / direction / blocks / chars / ranked / verdict`
  - 注：已去除顶层及 replay 层的 `debug_png_base64`（叠加图），几何 replay 不需要

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
