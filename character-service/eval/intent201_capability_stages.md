# Intent 201 — `reading.point_to_character` 内部阶段 dump

识字能力从**图片喂进去之后**的流水线，不是 Brain planner。

| | |
|---|---|
| **intent_id** | 201（LAN Brain，utterance「看一下最新的照片上手指的那个字是什么字」） |
| **asset_id** | `asset_e080b636a5e20a0d4786e710` |
| **图片路径** | `/Users/gaolei/Projects/smart_home_control/img-server/img/3f089bec_upload_1787701987925.jpg` |
| **正确字** | **崭**（「崭新局面」；指甲盖正下方） |
| **201 实际返回** | **力**（「倾力支持」，上一行、射线左侧） |
| **Mac** | `07:58:23` 起跑 → `07:58:55` `point_to_character ok status=ok char=力 total_ms=31682` |
| **OCR** | HunyuanOCR Q4 @ `127.0.0.1:8082`（llama-server） |
| **本 dump 目录** | [`character-service/eval/intent201_capability_stages/`](intent201_capability_stages/) |

产物文件：`01_decoded.jpg`、`03_ocr_window_*.jpg`、`05_confirm_crop.png`、`06_overlay.png`，以及各阶段 JSON。

---

## 阶段总表（intent 201 当时）

| # | 阶段 | 起止 (UTC+8) | cost | 是否影响 201 执行 | 产物 |
|---|---|---|---|---|---|
| 0 | Mac 取图 + POST | 07:58:23.8 → 07:58:23.8 | 取图 ≪1s | 是 | JPEG 658 719 B，EXIF Orientation=**1**（无旋转） |
| 1 | `decode_bgr` | 含在 POST 内 | ~0.5 s | 是 | 解码 **2897×2763**（宽×高），横图。与 200 的双 EXIF 问题无关 |
| 2 | MediaPipe 食指 | ~07:58:23.8 | **0.42 s** | 是 | TIP=(1326.6, 1600.8)；MCP→TIP 方向 **(-1.00, -0.005)** 几乎朝左 |
| 3 | OCR 窗裁剪 | 紧接 | ≪0.1 s | 是 | 窗0 指尖 600px；窗1 沿射线左移 260px（**崭被移出窗外**） |
| 4 | Hunyuan ×4（双窗双跑） | 07:58:24.2 → 07:58:49.5 | **25.1 s** | 是 | 行级 JSON；原文**未落盘**（plugin `return_debug=false`） |
| 5 | 拆字 + `rank_characters` | 07:58:49.5 | ≪0.05 s | 是 | 崭若在射线「后方」会被直接丢掉 |
| 6 | confirm re-OCR（top1 放大裁） | 07:58:49.5 → 07:58:55.5 | **6.0 s** | 是 | 第 5 次 Hunyuan；201 未改写 top1 |
| 7 | `decide` + plugin 文案 | 07:58:55 | ≪1 ms | 是 | `status=ok` `character=力` →「手指指的是「力」。」 |

Hunyuan 五次墙钟（`local-rt/logs/llama_cpu.log`，相对时钟已对齐到 07:58）：

| call | 墙钟结束 | prompt eval | eval | total | 角色 |
|---|---|---|---|---|---|
| 1 窗0 pass1 | 07:58:37.3 | 11467 ms / 476 tok | 1559 ms / 74 tok | **13026 ms** | 冷图 |
| 2 窗0 pass2 | 07:58:38.9 | 20 ms / 1 tok（cache） | 1541 ms / 75 tok | **1561 ms** | 同窗重跑 |
| 3 窗1 pass1 | 07:58:47.9 | 7512 ms / 476 tok | 1503 ms / 73 tok | **9015 ms** | 左移窗 |
| 4 窗1 pass2 | 07:58:49.5 | 22 ms / 1 tok | 1461 ms / 73 tok | **1483 ms** | 同窗重跑 |
| 5 confirm | 07:58:55.5 | 5520 ms / 384 tok | 450 ms / 25 tok | **5970 ms** | top1 放大裁 |
| **合计** | | | | **31055 ms** | 对上 Mac 31682 ms（余量 = 手检 + HTTP） |

`llama_cpu.log` **只记 timing，不记 OCR JSON**。201 当时 plugin 硬编码 `return_debug: false`，所以当时的 blocks / ranked **没有原文**。下面几何与裁窗来自**同一张图的直播 replay**（MediaPipe 对静图基本稳定，可代表 201 的手/射线）。Hunyuan 行框每次会抖。

---

## 1. Image ingest / `decode_bgr`

```json
{
  "bytes": 658719,
  "exif_orientation": 1,
  "decoded_wh": [2897, 2763],
  "upright": false
}
```

Android `document.scan` 出品，Orientation=1，OpenCV 不再二次旋转。解码图：[`01_decoded.jpg`](intent201_capability_stages/01_decoded.jpg)。这**不是** intent 200 那种双 EXIF 横过来的失败。

---

## 2. MediaPipe 手：landmarks / MCP / TIP / ray

来自直播 replay（`02_hand.json`），像素坐标相对 2897×2763：

| joint | idx | (x, y) |
|---|---|---|
| INDEX_MCP | 5 | (1402.25, 1601.14) |
| INDEX_PIP | 6 | (1362.43, **1516.62**) ← 最高点 |
| INDEX_DIP | 7 | (1330.21, 1553.70) |
| INDEX_TIP | 8 | (1326.60, **1600.79**) |

`finger_ray` 优先 **MCP → TIP**（`geometry.py`：弯指时用最长稳定基线）：

```
origin (TIP) = (1326.6, 1600.8)
direction    = (-0.999989, -0.004641)   # 几乎朝左，水平夹角 0.27°
max_distance = 2201.8 px  (0.55 × 对角线)
```

肉眼：手指从画面下方伸入，**指甲盖顶在「崭」下沿**，指向偏上。

MediaPipe：PIP 是最高点，TIP 弯回与 MCP 几乎同一高度 → MCP→TIP 变成**水平朝左**，不是朝上对着「崭」。

叠图（红点=TIP，红箭头=射线）：[`06_overlay.png`](intent201_capability_stages/06_overlay.png)。

---

## 3. OCR 窗口

`OCR_WINDOWS = ((600, 0), (600, 260))`：指尖中心 600px，再沿**射线方向**前移 260px。射线朝左，所以第二窗继续往左切。

| 窗 | shift | 中心 | 全图 bbox | 文件 | 窗内有没有「崭」 |
|---|---|---|---|---|---|
| 0 | 0 | (1327, 1601) | [1027, 1301, 1627, 1901] | [`03_ocr_window_0_size600_shift0.jpg`](intent201_capability_stages/03_ocr_window_0_size600_shift0.jpg) | **有**：`集工作的崭新局`，指甲在「崭」下 |
| 1 | 260 沿射线 | (1067, 1600) | [767, 1300, 1367, 1900] | [`03_ocr_window_1_size600_shift260.jpg`](intent201_capability_stages/03_ocr_window_1_size600_shift260.jpg) | **没有**：切到「高度重视与倾力 / 信息采集工作的」，「崭」在窗右外侧 |

窗1 的设计本意是「沿指向再切一刀、把指尖前方的字包进来」。射线反了之后，这一刀切的是「倾力」，把正确字切掉。

---

## 4. Hunyuan 调用

**201 原文 JSON 不在任何日志里。** 只有上表 timing。模型：`local-rt/models/HunyuanOCR.Q4_K_M.gguf`，prompt 为行级 spotting（`hunyuan_ocr.py` `SPOTTING_PROMPT`），坐标归一化 [0,1000] 再乘回裁窗像素，再 `shift_ocr_blocks` 加回全图原点。

直播 replay（2026-08-26 08:28，同一服务）的**合并行块**（双窗双跑，12 blocks）：

```
见与倾力支持，不
集工作的崭新局面     ← 含正确字「崭」
采
高度重视与倾力主
息采集工作的牵
采
```

（每行因双跑出现两次，框略抖。）完整 blocks：[`00_live_replay.json`](intent201_capability_stages/00_live_replay.json) / [`04_ocr_and_rank.json`](intent201_capability_stages/04_ocr_and_rank.json)。

这次 replay 的 Hunyuan：窗四次各 ~3.3–4.3 s（cache 热），confirm 冷图 **25.0 s**。`timing.geometry_ranking_s=25.1` 其实几乎全是 confirm OCR（计时包在 `rank` 之后）。

---

## 5. Ranking / finger_ray 分数（崭 vs 的 vs 力）

拆字后关键框（直播 replay；201 的框会因 VLM 抖动略有不同，几何关系一样）：

| 字 | bbox | 中心 | 相对 TIP (1327, 1601) | ray/cone | lateral | 进 ranked？ |
|---|---|---|---|---|---|---|
| **崭** | [1329, 1403, 1404, 1504] | (1367, 1454) | **右** 40px、**上** 147px | **null** | **null** | **否** |
| **的** | [1254, 1403, 1329, 1504] | (1292, 1454) | 左 35px、上 147px | cone 0.28 | **lateral 0.52** | #1 |
| **力** | [1254, 1301, 1330, 1390] | (1292, 1346) | 左 35px、上 256px | cone 0.26 | **lateral 0.51** | #2 |
| 新 | [1404, 1403, 1480, 1504] | (1442, 1454) | 更右 | null | null | 否 |

「崭」被丢掉的原因：`score_character` / `lateral_score` 都要求 `dot(center - TIP, direction) > 0`（字在射线前方）。方向是朝左，崭在 TIP **右侧** → dot ≈ **-39** → 直接 `None`，连 top-3 都进不去。

「的」「力」在左侧 = 射线前方，走 **lateral**（水平朝左、夹角 0.27° ≤ 32° 的「指尖邻字」通道）。两者分差只有 0.011。

直播 replay `decide`：

```
status = ok_with_alternatives
top1 = 的  0.5246  lateral
top2 = 力  0.5135  lateral
top3 = 作  0.4532  lateral
margin = 0.011  (< 0.06)
崭 not in ranked
```

**201 当时** `status=ok` 且 top1=力、没有 alternatives：说明那一轮 Hunyuan 的框让「力」的分比第二名高出 ≥0.06（例如「力」吃到 ray 命中，或「的」框更偏）。同一几何、VLM 一抖，top1 就会在 力 / 的 / 崭 之间跳。

同图后来两次直播（都不是 201）：

| 何时 | status | character | total_ms | 备注 |
|---|---|---|---|---|
| 07:58:55 **intent 201** | ok | **力** | 31682 | 用户看到的 |
| 08:03:47 另一次 POST | ok_with_alternatives | **崭** | 36847 | 同一服务；框若把「崭」切到 TIP 左侧就能进 ranked |
| 08:29:05 本次 dump | ok_with_alternatives | **的** | 42387 | 崭检出但被射线后方规则丢掉 |

---

## 6. 最终（201）

```
status       = ok
character    = 力
answer_text  = 手指指的是「力」。
plugin       = mac_edge.point_to_character  07:58:55  total_ms=31682
Brain step 2 = succeeded；presentation 同上句
```

Confirm 裁（本次 replay 的 top1=的，pad=0.5）：[`05_confirm_crop.png`](intent201_capability_stages/05_confirm_crop.png)。裁里**同时能看见** 力、的、崭，指甲在崭正下。`_confirm_char_from_ocr` 只在「窗内恰好 1 个 CJK」时才加候选，这里多个字 → confirm 空操作。201 的 confirm 同样救不了。

---

## 分析：为什么是力不是崭

根因在 **第 2 阶段射线**，不是 Hunyuan 没看见「崭」。

1. 指尖 grope / 末指节弯曲：PIP 最高，TIP 弯回纸面。MCP→TIP 变成水平朝左，和指甲指向（朝上、对着崭）几乎反向。
2. 几何把「射线后方」的字全部丢弃 → 崭（TIP 右侧、正上方）永远 0 分，除非 VLM 把崭的框切到 TIP 左边（08:03 那种运气）。
3. 第二 OCR 窗沿错误射线再左移 260px，主动把崭切出窗外；四次 Hunyuan 有一半在看「倾力」。
4. 力 / 的 都在「前方」lateral 带里，分差极小。201 抽到了力且 margin 够大，于是 `ok` 而不是 `ok_with_alternatives`。

OCR 本身：窗0 行文本「集工作的崭新局面」是对的。失败发生在 **射线方向 × 前方过滤 × 窗偏移**。

时间：201 的 31.7 s 里 **31.1 s 是五次 Hunyuan**。手检 0.4 s。双窗双跑 + confirm 是既定成本；其中窗1 在这条射线上是浪费的。

---

## 优化选项（只分析，不改代码）

按对 201 这类「俯拍、指尖顶在字下沿、食指略弯」的收益排序：

1. **射线改用「指向」而不是 MCP→TIP 直线。** PIP 明显高于 TIP 时，朝向应取 TIP → 远离掌心/沿末指节延伸（朝上），或 TIP 沿「PIP 为最高点」的反弯方向。现在的 MCP→TIP 注释写的是「弯指更稳」，本案恰好把指向拧成水平。
2. **指尖接触带不要用 `dot>0` 一刀切。** 崭中心只在 TIP 右侧 40px、上方 147px，肉眼就是指甲顶着的字。给 TIP 周围一个 pad（已有 `CONTACT_PAD_PX=8`，太小）或「TIP 正上、x 最近」的邻字通道，崭能进 ranked。
3. **第二窗不要盲从射线。** 水平射线时 shift=260 会切掉指尖上方的字。可改为沿「纸面向上」（减小 y）再切一窗，或检测到方向与 PIP 最高点矛盾时取消 shift 窗。
4. **confirm 允许多字。** 当前 confirm 裁其实已经框进了崭，却因为「必须恰好 1 个 CJK」扔掉。按几何在 confirm 裁里再 rank 一次，201 这种图能收回。
5. **时间：** 双跑第二 pass 在 201 上各 ~1.5 s，有用但不是主因；窗1 在错误射线上白烧 10.5 s；confirm 在热 cache 时 6 s、冷时可达 25 s。先修射线，窗1/confirm 才会切到正确字。

**不要**靠换 Q8 / 改 planner。Planner 选 `asset.inventory` + `reading.point_to_character` 是对的；错在能力内部几何。

---

## 文件索引

```
character-service/eval/intent201_capability_stages.md          ← 本报告
character-service/eval/intent201_capability_stages/
  dump_stages.py                 复现脚本（POST return_debug + 本地裁窗）
  00_live_replay.json            本次直播全文（无 debug_png）
  01_ingest.json / 01_decoded.jpg
  02_hand.json
  03_ocr_windows.json
  03_ocr_window_0_size600_shift0.jpg
  03_ocr_window_1_size600_shift260.jpg
  04_ocr_and_rank.json           行块 / 拆字 / 崭·的·力 分数
  05_confirm_crop.png
  06_overlay.png                 射线 + 字框
  07_final.json
```
