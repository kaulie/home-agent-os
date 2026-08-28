# 指字认字 bad cases

识字流水线（`detect_finger` → `ocr_at_finger` → `rank_pointed`）的失败样本。每条写清 **原图、错因、改法**。算法改动仍记 [`../ALGORITHM_CHANGELOG.md`](../ALGORITHM_CHANGELOG.md)；这里只收「当时错了什么」。

| id | 正确字 | 当时答 | 卡在哪一步 | 文档 |
|---|---|---|---|---|
| LAN 239 | **缴**（自来水缴费通知单） | 监 → 后改成多指拒绝 | `detect_finger` | [intent239.md](intent239.md) |
| LAN 201 | **崭**（崭新局面） | 力 | `rank_pointed`（射线后方丢掉接触字） | [../intent201_capability_stages.md](../intent201_capability_stages.md) |
| LAN 200 | （图上有字） | `no_text` | 解码双转 EXIF | changelog「decode_bgr 双 EXIF 旋转」 |

---

## 239 摘要：为什么会被判成 5 根独立伸出的手指

原图副本：[intent239/photo.jpg](intent239/photo.jpg)  
（源文件 `img-server/img/49ce8930_photo_1787751581950.jpg`，`asset_26a331d8527deb3241ffc552`）

这是 **整只左手按在单据上**：拇指压纸，其余四指自然张开，并没有「只伸出一根去点字」。

`is_extended_digit`（`geometry.py`）把「伸出」定义成 **比握拳更直、指尖比指根离手腕更远**，四个门槛都很松：

| 门槛 | 含义 | 阈值 |
|---|---|---|
| `d_tip ≥ 1.12 × d_mcp` | 指尖比掌指关节离手腕更远 | 12% |
| `d_tip ≥ 1.02 × d_pip` | 指尖比 PIP 离手腕更远 | 2% |
| `span ≥ 0.70 × chain` | MCP→TIP 弦长接近折线（不太弯） | 70% |
| `span ≥ 0.28 × palm` | 这一指不要太短 | 28% 掌长 |

按住一张纸条时，五指通常都满足这四条，所以 **thumb / index / middle / ring / pinky 全中**。  
「独立」目前只表示「这一指自己过了伸直门」，**没有**跟邻居比谁更突出、也没有区分「握着纸」和「点着字」。

Live（2026-08-26，`POST /v1/detect_finger`）：

```
status: ambiguous_finger
reason: 图里有多根手指，系统无法判断你指的是哪个字。（thumb、index、middle、ring、pinky）
```

MediaPipe 两只手：hand0 无伸出指；hand1 五指全过门。拇指尖约 `(767, 572)`（更靠近「缴」），食指尖仍是旧的 `(454, 233)`（朝向幻觉框「监」）。

**改法（下一版）**：伸出门要变成「指字门」——例如只有明显比邻指更前伸的那一根才算；四指并排贴纸不算多指；多根真正独立点出去的才 `ambiguous_finger`。详见 [intent239.md](intent239.md)。
