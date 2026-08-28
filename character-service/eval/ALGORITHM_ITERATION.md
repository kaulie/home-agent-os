# character-service 指尖检测算法迭代史

> 本文档记录 `reading.point_to_character` 指尖检测管线的算法迭代过程：每个 case 之前为什么失败、做了什么调整、修复后结果、回归影响。
> 详细变更记录见 [`ALGORITHM_CHANGELOG.md`](ALGORITHM_CHANGELOG.md)；失败样本见 [`bad_cases/`](bad_cases/)。

## 概述

`reading.point_to_character` 是「手指指字认字」能力：用户拍一张手指指着汉字的照片，系统识别指尖位置和指向，再用 OCR + 几何排序找出指尖指的是哪个字。

管线分三步：

1. **detect_finger**：检测手指——指尖位置 + 指向方向
2. **ocr_at_finger**：在指尖附近裁窗做 OCR，得到文字框
3. **rank_pointed**：几何排序——射线/锥/侧向/接触四种模式打分，选出指尖指着的字

迭代集中在第 1 步（手指检测）、第 2 步（OCR 调用次数）和第 3 步（几何排序），针对的是真实用户照片中各种非标准构图：EXIF 方向、指尖接触字面、多根手指、指尖-only、不同摄像头肤色等，以及 VLM 调用性能优化。

---

## 迭代时间线

### 第 1 轮：EXIF 双旋转修复（intent 200）

| 项 | 内容 |
|---|---|
| **目标 case** | LAN intent **200**「最新照片里手指指的那个字是什么」。iPhone 医院挂号单，EXIF Orientation=6 |
| **asset_id** | `asset_1cdd70e4c738d45e5550ffe3` · [img-server/img/ba0a4d81_photo_1787672612.jpg](../../img-server/img/ba0a4d81_photo_1787672612.jpg) |
| **修复前症状** | `no_text` / 空 character。照片本身清晰有字 |
| **根因** | OpenCV 4.11 `cv2.imdecode(IMREAD_COLOR)` 已按 JPEG EXIF 转正（3024×4032 竖图）；`hands.decode_bgr` 又跑一遍 `apply_exif_orientation`，图被横过来（4032×3024）。指尖落到画面上沿，600px OCR 窗切到指尖和桌布，窗内无字 |
| **算法调整** | `hands.py` `decode_bgr`：改用 `IMREAD_COLOR \| IMREAD_IGNORE_ORIENTATION`，让 EXIF 旋转只由 `apply_exif_orientation` 做一次。旧 OpenCV 无该 flag 时仍只走 `apply_exif`，行为一致 |
| **修复后结果** | 图正确转正为 3024×4032 竖图，OCR 窗切到单据文字 |
| **回归影响** | 新增单测 `test_exif.py`；不影响几何/OCR |

---

### 第 2 轮：指尖接触带 contact 模式（intent 201）

| 项 | 内容 |
|---|---|
| **目标 case** | LAN intent **201**「看一下最新的照片上手指的那个字是什么字」。扫描件「崭新局面」，正确字 **崭**，指甲盖正下方/右侧 |
| **asset_id** | `asset_e080b636a5e20a0d4786e710` · [img-server/img/3f089bec_upload_1787701987925.jpg](../../img-server/img/3f089bec_upload_1787701987925.jpg) |
| **修复前症状** | 返回 **力**（「倾力支持」）。OCR 已看见「崭新局面」，但崭落在 MCP→TIP 射线后方被丢掉 |
| **根因** | `score_character` / `lateral_score` 凡 `dot(center-TIP, direction) ≤ 0` 一律丢弃。201 食指钩着，射线几乎朝左；崭在 TIP 右上约 40×147px，被当成「后方」。`CONTACT_PAD_PX=8` 只覆盖指尖落在框内的情况，够不到 ~100px 的「指甲顶在字下沿」 |
| **算法调整** | `geometry.py` 新增 `mode=contact` 几何类（与 ray/cone/lateral 并列）：<br>• 指尖邻域 pad 随 **median glyph height** 与 **max_distance** 缩放（约 0.4×600px OCR 窗），不再用固定 8px<br>• 邻域内且在射线后方（或 TIP 落在框内）的字 **不因 dot≤0 丢弃**<br>• contact 分数封顶 0.78，避免压过 8022 因 / 8024 霸 / 8025 剧 的高分 lateral<br>• 手指仰角 >32° 时不走 contact（避免 7832 了 抢走 渊）<br>• 吞掉两个以上邻字中心的错框不进 contact |
| **修复后结果** | 201 top1 = **崭**（`mode=contact`） |
| **回归影响** | Q4 几何 replay **30/30 top1 无回归**；8022 因 / 8024 霸 / 8025 剧 / 7832 渊 全保持；新增单测 `test_intent201_scan_ranks_zhan` 等 |

---

### 第 3 轮：多根手指拒绝（intent 239）

| 项 | 内容 |
|---|---|
| **目标 case** | LAN intent **239**「最新的这张照片里面手指的是哪个字」。自来水缴费通知单，正确字 **缴** |
| **asset_id** | `asset_26a331d8527deb3241ffc552` · [img-server/img/49ce8930_photo_1787751581950.jpg](../../img-server/img/49ce8930_photo_1787751581950.jpg) |
| **修复前症状** | 系统答 **监**——图上没有「监」，是 OCR 在框 `[713,11,756,98]` 上的幻觉。旧逻辑只跟 MediaPipe 食指 5-8，食指射线打中幻觉框 |
| **根因** | `detect_index_landmarks` 默认只跟食指。图里整只左手按在单据上：拇指压纸、其余四指自然张开，是五根独立手指，系统却只跟食指并猜了一个不存在的字 |
| **算法调整** | <br>• `geometry.py`：`pointing_fingers` 按 `is_extended_digit`（腕部距离 + 伸直程度）判断拇指/食指/中指/无名指/小指是否在指，**不**只跟食指<br>• `hands.py`：检出一只手上 21 点（可多手）<br>• `pipeline.detect_finger`：0 根 → `no_hand`；**多于 1 根 → `ambiguous_finger`**；恰好 1 根才给 `finger`（可以是拇指）<br>• Mac plugin：`ambiguous_finger` 时 `PointToCharacterError` 复合步失败 |
| **修复后结果** | 239 → `status=ambiguous_finger`（五指全伸），不再出「监」 |
| **回归影响** | Q4 replay 30/30 无回归；新增单测 `test_detect_finger_ambiguous_when_two_digits` / `test_detect_finger_single_thumb` |

> **注**：此轮引入的「多根即拒」在后续第 5 轮被修正——拇指+食指（标准指字手势）不应判歧义，只有真正相近的多指（如剪刀手）才拒。

---

### 第 4 轮：木桌面 bad case + 用户引导（intent 253）— 已知限制

| 项 | 内容 |
|---|---|
| **目标 case** | LAN intent **253**「看一下最新的一张照片里面手指的那个字是什么」。iPhone 俯拍，只有食指尖到中节入镜，指着「自来水缴费通知单」上的「用户编号：38549」 |
| **asset_id** | `asset_dfe90d94e7ffec6e8ca45673` · [img-server/img/4f83b365_photo_1787757124.jpg](../../img-server/img/4f83b365_photo_1787757124.jpg) |
| **修复前症状** | `no_hand`——图里确实有食指，但 MediaPipe 0 手 |
| **根因** | MediaPipe Hands 是 **palm-first 两阶段模型**：先 palm detection 再 refine 21 关节。掌根/手腕不在画面时 palm detector 直接 0 hand。已验证 4 缩放 × 2 复杂度 × 3 置信度（最低 0.05）+ 0.18 padding 全轮仍 0 手。**模型设计层面盲区，非阈值问题** |
| **尝试过的替代方案** | <br>• **肤色分割**：手指 Cr=144、木桌面 Cr=142，色度重合，纯颜色分不开。收紧阈值连手指也切掉；松阈值桌面并进巨型 blob<br>• **YOLOv8-pose**：COCO 17 点只有手腕无手指；社区 hand-pose 变体训练数据同为全手构图，同样翻车<br>• 两者均未解决此 case |
| **算法调整** | <br>• `pipeline.py`：`no_hand` 文案改为「请把手指指在书页或白纸上（不要指在桌面），让手指大部分进入画面，指尖对着那个字」——**产品引导**避开木桌面<br>• `skin_detect.py`：新建独立肤色分割模块（未接入 pipeline），留作白纸背景备用 |
| **修复后结果** | 253 仍 `no_hand`（已知 bad case，未修），但用户会听到引导文案 |
| **回归影响** | 无算法回归；文案未断言 |

---

### 第 5 轮：最长伸出指优先（intent 254）

| 项 | 内容 |
|---|---|
| **目标 case** | LAN intent **254**「看一下最新的一张照片里面手指的那个字是什么」。标准指字手势：食指伸出指字，拇指自然张开，中指/无名指/小指弯曲 |
| **asset_id** | `asset_9552eb3fc7484adb89fa420b` · [img-server/img/e09be3e2_photo_1787759393.jpg](../../img-server/img/e09be3e2_photo_1787759393.jpg) |
| **修复前症状** | `ambiguous_finger`（thumb、index）——第 3 轮的「多根即拒」把拇指也判成伸出，但这是**最正常的指字手势** |
| **根因** | `pointing_fingers` 凡 `is_extended_digit` 通过的都列出，多于 1 根就 `ambiguous_finger`，不看哪根才是「真正在指」。拇指在食指指字时自然张开是常态。254 landmark：食指 TIP 离腕 1857、拇指 TIP 离腕 1295，食指明显伸得更远 |
| **算法调整** | `geometry.py` 新增 `DOMINANT_TIP_RATIO=1.3`：<br>• `pointing_fingers` 多根伸出时按「指尖离腕距离」排序<br>• 最长的那根若 ≥ 次长的 1.3 倍 → 只取它（不判歧义）<br>• 否则仍 `ambiguous_finger`（如食指+中指都全伸的剪刀手，reach 接近） |
| **修复后结果** | 254 → `status=ok`，`digit=index`，不再 `ambiguous_finger` |
| **回归影响** | Q4 replay **30/30 无回归**；单测 12/12 ok；更新 `test_thumb_and_index_are_ambiguous` → `test_thumb_splayed_index_dominates`；新增 `test_index_and_middle_are_ambiguous` |

> **与第 3 轮的关系**：第 3 轮引入「多根即拒」修了 239（五指全伸不再猜「监」），但误伤了 254（标准指字手势）。第 5 轮加了 dominant 选择，让「拇指张开+食指指字」选食指，同时保留「剪刀手」的歧义拒绝。

---

### 第 6 轮：肤色分割自动 fallback（intent 259）

| 项 | 内容 |
|---|---|
| **目标 case** | LAN intent **259**「最新的照片上手指的字是什么字」。Android 摄像头拍儿童绘本（白纸背景），食指从画面底部伸入指着「弗洛格」，掌根不在画面 |
| **asset_id** | `asset_f3b06a7196d626c2575984fb` · [img-server/img/7c8c131f_cap_23f52099d577f3915fe2a1ec.jpg](../../img-server/img/7c8c131f_cap_23f52099d577f3915fe2a1ec.jpg) |
| **修复前症状** | `no_hand`——MediaPipe 0 手（与 253 同类的 palm-first 盲区） |
| **根因** | 与 253 同类（掌根不在画面），但 259 是**白纸背景**（非木桌面），肤色分割可用 |
| **算法调整** | <br>• `pipeline.py` `detect_finger`：MediaPipe 返回 0 手时**自动 fallback** 到 `skin_detect.detect_hands_landmarks`；timing 加 `skin_fallback` 标记<br>• `skin_detect.py` 三项关键改进：<br>  - **阈值**：Cr 135-180、Cb 85-135（松，覆盖 iPhone Cr~168 和 Android Cr~146）；HSV S 上限 150（排除印刷橘色字 S~165）<br>  - **打分**：`min(aspect,10) × orient_bonus`（竖向 ×2，横向 ×0.5），不乘 area——避免大插图条淹没小手指<br>  - **指尖定位**：`_fingertip_point` 检测 blob 触边方向，指尖 = 远离触边那端（手指从底部入镜 → 指尖在上方）；不触边时 fallback 到 farthest-from-centroid<br>  - 只返回最高分 1 个 blob |
| **修复后结果** | 259 → `status=ok`，`finger.tip=[207.4, 1165.4]`，`direction=[0.24, -0.97]`（朝上指字），`skin_fallback=True` |
| **回归影响** | 253（木桌面）仍 `no_hand`（肤色分割也失败，不误检橘色字）；254 仍 `ok`（MediaPipe 检到，无需 fallback）；单测 12/12 ok |

---

### 第 7 轮：OCR 2-pass 去重（性能优化，intent 259/261）

| 项 | 内容 |
|---|---|
| **目标 case** | LAN intent **259/261**「最新的照片上手指的字是什么字」。Android 摄像头拍儿童绘本（白纸背景），食指从画面底部伸入指着「弗洛格」 |
| **asset_id** | `asset_f3b06a7196d626c2575984fb` · [img-server/img/7c8c131f_cap_23f52099d577f3915fe2a1ec.jpg](../../img-server/img/7c8c131f_cap_23f52099d577f3915fe2a1ec.jpg) |
| **修复前症状** | 一次 `point_to_character` 打 **5 次 VLM**（HunyuanOCR via llama.cpp :8082），耗时 ~57s。`ocr_at_finger` 里每个 OCR 窗口跑 `for _pass in range(2)`，对同一张裁图调 2 遍 VLM，2 窗口 = 4 次；`rank_pointed` 确认裁图再 1 次 |
| **根因** | `for _pass in range(2)` **不是 retry**——第一遍成功后第二遍照样跑，对同一张图再调一次 VLM。VLM temperature=0.1，两遍识别出的文字相同，只有 bbox 浮动 1-2px。Q4 replay 数据验证：所有重复 block 都是同一段文字（如「找了」出现 4 份 = 2 窗口 × 2 pass），第二遍从未发现第一遍漏掉的新字 |
| **算法调整** | `pipeline.py`：`for _pass in range(2)` 循环末尾加 `if _has_cjk_blocks(part): break`——第一遍 OCR 返回的 block 里如果有 CJK 字符就跳过第二遍。新增 `_has_cjk_blocks()` 辅助函数（调 `blocks_from_ocr` + `has_cjk`）。第一遍无 CJK 时仍跑第二遍 retry |
| **修复后结果** | 259 → `status=ok`，`character=弗`，`ocr_vlm_s` 52.36→33.75（-19s），`total_s` 56.98→39.88（-30%）。VLM 调用 5→3 次（2 窗口各 1 次 + 1 确认） |
| **回归影响** | Q4 replay **30/30 无回归**；单测 12/12 ok；历史 `still_fail` case（IMG_8022/8050）不变 |

---

### 第 8 轮：skin_detect border tier 排序（intent 277）

| 项 | 内容 |
|---|---|
| **目标 case** | LAN intent **277**「最新的照片里面手指的是哪个字」。Android 拍儿童绘本，食指从画面底部伸入指着第三行「野兔」的「野」，绘本上半部有彩色插图（含肤色卡通角色） |
| **asset_id** | `asset_f9a3d5d2e71c479d5a75d65b` · [img-server/img/57bb7cd2_photo_1787795714933.jpg](../../img-server/img/57bb7cd2_photo_1787795714933.jpg) |
| **修复前症状** | 系统答「把」——第二行「把他们」的「把」。fingertip 落在页面左上角插图区域，OCR 窗只覆盖到第二行 |
| **根因** | MediaPipe 0 手（指尖-only），skin_detect fallback 误检：插图里肤色卡通角色（Blob 1，面积 2.1%，触顶边，score=4.69）被当成手指，盖过真正的手（Blob 0，面积 35.6%，触底边，score=0.99）。skin_detect 打分只看 elongation × orientation，不看 blob 在页面里的位置——插图在顶部、真手从底部进入，但打分无法区分 |
| **算法调整** | `skin_detect.py`：<br>• 新增 `_border_tier()`：触底=0、触侧=1、只触顶=2、不触边=3<br>• 排序改为 `(tier, -score)` 两层排序——先按 border tier（底 > 侧 > 顶），再按 score。真手从底边进入，插图在顶部，tier 0 必胜 tier 2<br>• 新增 `_LARGE_BLOB_FRAC=0.10`：大面积 blob（>10% 图像）score ×1.5 area_bonus<br>• 修复隐藏 bug：`sw`/`sh` 在排序循环中使用但定义在循环后，`NameError` 被 pipeline `except Exception: pass` 吞掉导致 skin_detect 静默失败 |
| **修复后结果** | 277 → `status=ok`，`character=野`，`finger.tip=[800.6, 902.4]`，`direction=[-0.10, -0.99]`（朝上指字），`skin_fallback=True` |
| **回归影响** | 259 仍 `ok`（`character=弗`，真手指触底边 tier=0 仍优先）；Q4 replay **30/30 无回归**；单测 12/12 ok |

> **与第 6 轮的关系**：第 6 轮引入 skin_detect fallback 解决了白纸背景的指尖-only case（259），但未考虑插图里肤色卡通角色的干扰。第 8 轮加 border tier 排序，让真手（从边缘进入）优先于插图角色（在页面内部）。

---

### 第 9 轮：confirm 裁图改用 PaddleOCR（性能优化，intent 278）

| 项 | 内容 |
|---|---|
| **目标 case** | LAN intent **278**「看一下最新的照片手指的是哪个字」。Android 拍儿童绘本，食指指着「雕」 |
| **asset_id** | `asset_fdd307eacd307800899b5b59` · [img-server/img/ad225ed3_photo_1787797386939.jpg](../../img-server/img/ad225ed3_photo_1787797386939.jpg) |
| **修复前症状** | 识别正确（`character=雕`），但耗时 ~83s。`rank_pointed` 的 confirm 裁图用 VLM 调用占 37-44s |
| **根因** | `rank_pointed` 对 top1 字符的 bbox 裁小窗做二次确认 OCR，用的是和主 OCR 相同的 VLM（HunyuanOCR）。VLM 对单字小裁窗也要 30-40s（llama.cpp 推理速度与图片大小无关），而 confirm 只需认单个汉字，不需要 VLM 的行级 spotting 能力 |
| **算法调整** | `pipeline.py` `rank_pointed`：confirm 调用从 `ocr_fn`（VLM）改为 `ocr_recognize`（PaddleOCR :9188），PaddleOCR 失败时 fallback 回 VLM。**标准：找字用 VLM（行级 spotting），认字用 Paddle（单字识别）** |
| **修复后结果** | 278 → `status=ok_with_alternatives`，`character=雕`。`geometry_ranking_s` 44.7→4.2s（-40s），`total_s` 83→40s（-52%）。confirm 候选分数 = top0 - 0.001，永远低于 top0，不影响 top1 |
| **回归影响** | Q4 replay **30/30 无回归**（confirm 不影响 top1，只影响 alternatives）；277/259/278 完整 pipeline top1 全对；单测 12/12 ok |

> **VLM vs Paddle 使用标准**：主 OCR（`ocr_at_finger`）用 VLM——裁窗含插图/噪声，需要 VLM 的行级 spotting 能力把文字行找出来；confirm（`rank_pointed`）用 Paddle——只是对 top1 字符的小裁窗做单字二次确认，Paddle 又快又稳。

---

### 第 10 轮：VLM 确定性（temperature=0 + OCR 缓存）

| 项 | 内容 |
|---|---|
| **目标 case** | 所有走 VLM 的 case（Q4 基线 IMG_8022/8024/8025/8026 + intent 201/259/277/278）|
| **修复前症状** | 同一张照片多次跑 pipeline，VLM OCR 返回不同文字，导致 top1 不稳定。Q4 基线在 _1600 缩图上跑全 pipeline 时 4/6 fail |
| **根因** | ① `hunyuan_ocr.py` `temperature=0.1`，采样解码有随机性——同一裁窗每次选不同 token；② 无缓存，同一张图每次都重新调 VLM（60-80s），无法复现 |
| **算法调整** | `hunyuan_ocr.py`：<br>• `temperature` 0.1→**0.0**（贪婪解码，每次选概率最高 token）<br>• 新增进程内 OCR 缓存：`SHA-256(image_bytes)+language → result`，上限 200 条，LRU 淘汰。同一张裁窗第二次调用 **0.7s**（缓存命中）vs 首次 75s |
| **修复后结果** | 同一张图连跑 2 轮结果完全一致（IMG_8024: 历/历，top3 一致）。确定性解决 |
| **回归影响** | intent 6 case 全 PASS；Q4 几何 replay 不受影响（用缓存 dump 不调 VLM）|

> **VLM 确定性边界**：temperature=0 消除采样随机性，但 llama.cpp 在不同 batch size / GPU 并行下仍可能有浮点级差异。进程内缓存保证同一 session 内完全可复现。

---

### 第 11 轮：DOMINANT_TIP_RATIO 1.3→1.1（多指歧义优化，IMG_8024/7832）

| 项 | 内容 |
|---|---|
| **目标 case** | IMG_8024（ambiguous_finger: index/middle/ring/pinky 4 指）、IMG_7832（ambiguous_finger: thumb/ring 2 指）|
| **asset_id** | 8024: `asset_f7c0fb410a2e23dc7` · `local-rt/test-imgs/IMG_8024.jpg`（4284×5712）<br>7832: `local-rt/test-imgs/IMG_7832.jpg`（3024×4032）|
| **修复前症状** | 两个 case 都 `ambiguous_finger`，pipeline 拒答。Q4 dump 时只检测到单指（旧代码用 `detect_index_landmarks` 只返回 4 个 landmark），现在用 `detect_hands_landmarks` 返回完整 21 点，多指被检出 |
| **根因** | `pointing_fingers` 中 `DOMINANT_TIP_RATIO=1.3`：多指伸出时，最长指 reach ≥ 次长 × 1.3 才取最长，否则 ambiguous。8024 的 index reach=400 / middle reach=352 = **1.14 < 1.3** → ambiguous。7832 的 thumb reach=284 / ring reach=240 = **1.18 < 1.3** → ambiguous。实际用户只用食指指字，中指/无名指/小指自然微曲但被 `is_extended_digit` 判为伸出 |
| **算法调整** | `geometry.py` `DOMINANT_TIP_RATIO` 1.3→**1.1**。peace sign（两指等长 ~1.0）仍 ambiguous，单指微优（1.1+）即可判定 |
| **修复后结果** | 8024 → 单 index 指 ✓（tip=2312,3478）；7832 → 单 thumb 指 ✓（tip=1059,2099，thumb tip 与 index tip 仅差 2px，位置等价）|
| **回归影响** | intent 6 case 全 PASS 无回归；8025/8026 原图全 pipeline PASS；Q4 几何 replay 不受影响（ratio 只影响多指判定，replay 用缓存 landmark）|
| **剩余问题** | 8024 得「相」非「霸」、7832 得「为」非「渊」——均为手指方向计算问题，**第 12 轮已修复** |

> **Q4 基线可靠性修正**：经全 pipeline 回归发现，Q4 dump 中 IMG_8022 的「pass」是 MediaPipe 误检页边为手、恰好指向「因」的**假阳性**；IMG_8024 的 Q4 dump 用旧代码 `detect_index_landmarks`（只 4 个 landmark），天然不会 ambiguous。Q4 几何 replay 30/30 仍有效（几何逻辑未变），但不能作为全 pipeline 基线。

---

### 第 12 轮：手指方向修正（_digit_ray MCP→TIP + thumb splay override，IMG_8024/7832）

| 项 | 内容 |
|---|---|
| **目标 case** | IMG_8024（得「相」非「霸」）、IMG_7832（得「为」非「渊」）|
| **asset_id** | 8024: `asset_f7c0fb410a2e23dc7` · `local-rt/test-imgs/IMG_8024.jpg`（4284×5712）<br>7832: `local-rt/test-imgs/IMG_7832.jpg`（3024×4032）|
| **修复前症状** | 8024: index 方向 (-0.37,0.93) 指向下，ranking 选了同行的「相」而非「霸」<br>7832: thumb 被选中（index 微曲未检出），方向 (1.0,-0.07) 指右，ranking 选了「为」而非「渊」|
| **根因** | ① **8024**：`_digit_ray` 优先用 DIP→TIP（最后一节），但食指最后一节微弯，DIP→TIP 方向 (-0.37,0.93) 与整体 MCP→TIP 方向 (-0.96,0.27) 差异大。Q4 用 `finger_ray`（MCP→TIP）得正确方向<br>② **7832**：`is_extended_digit` 判 index 未伸出（c2: 285 vs 285.6 差 0.2%；c4: span=54 < 0.28×232=65），thumb 通过且 reach 最长被选中。thumb 方向是横向（across palm），非指向方向 |
| **算法调整** | `geometry.py`：<br>• `_digit_ray`：优先序从 `(dip, mcp)` 改为 `(mcp, dip)`——**MCP→TIP 优先**（整体指方向，稳定），DIP→TIP fallback。与 `finger_ray` 行为一致<br>• `pointing_fingers`：**thumb splay override**——当 thumb 为 dominant 但 index tip 在 30px 内，用 index 的 MCP→TIP 方向替换 thumb 的 across-palm 方向。用户指字时 thumb 自然张开贴近 index，index 方向才是真实指向 |
| **修复后结果** | 8024 → **霸** ✓（dir -0.96,0.27 = Q4 一致，top3: 霸 是 王，12.4s）<br>7832 → **渊** ✓（thumb tip + index 方向 0.78,-0.62，top3: 渊 着 打，136.2s）|
| **回归影响** | Q4 几何 replay **0 回归**（replay 用 partial landmark 走 `finger_ray` 不受影响）；intent 5/5 PASS；8025/8026 原图 PASS |

---

### 第 13 轮：第二 OCR 窗口条件化（性能优化，intent 297）

| 项 | 内容 |
|---|---|
| **目标 case** | LAN intent **297**「这个字读什么」。Android 拍儿童绘本，食指指着字。一次 `point_to_character` 耗时 ~63s |
| **asset_id** | 同 259/261 `asset_f3b06a7196d626c2575984fb` · [img-server/img/7c8c131f_cap_23f52099d577f3915fe2a1ec.jpg](../../img-server/img/7c8c131f_cap_23f52099d577f3915fe2a1ec.jpg) |
| **修复前症状** | 第 7 轮已把每窗口的 2-pass 去重（pass 级早退），但窗口级仍无差别跑 2 个窗口（指尖居中 600px + 前移 260px）。正常态 VLM 调用 3 次（2 窗口各 1 次 + 1 确认），第二个窗口的 ~20s 在历史 case 上从未贡献新字 |
| **根因** | `ocr_at_finger` 外层 `for spec in OCR_WINDOWS` 无条件遍历两个窗口。回放全部 91 个历史 case：top1 字符 100% 落在第一个（居中）窗口内，第二个（前移 260px）窗口从未发现第一个窗口漏掉的字。第二个窗口是冗余兜底 |
| **算法调整** | `pipeline.py` `ocr_at_finger`：内层 pass 循环用 `got_cjk` 标记本窗口是否命中 CJK；pass 循环结束后 `if got_cjk: break` 跳出外层窗口循环。第一个窗口命中 CJK → 不跑第二个窗口；第一个窗口无 CJK → 仍跑第二个窗口兜底（不静默丢字） |
| **修复后结果** | 正常态（第一窗口命中）：VLM 调用 3→**2 次**（1 窗口 + 1 确认），预计省 ~20s，total ~63s→~40s。兜底态（第一窗口无 CJK）：仍跑第二窗口，行为不变 |
| **回归影响** | `_full_photo_replay` 91 case：PASS 81 / FAIL 10，失败集（q8 IMG_8022、gen45 IMG_8050、local-8022）与改动前完全一致，**0 新增回归**；单测 12/12 ok |

> **与第 7 轮的关系**：第 7 轮是 pass 级早退（同窗口第二遍跳过），第 13 轮是窗口级早退（第二个窗口跳过）。两者叠加：正常态从最多 5 次 VLM → 2 次。

---

### 第 14 轮：多指 OCR 邻近选择（intent 333，两阶段法）

| 项 | 内容 |
|---|---|
| **目标 case** | LAN intent **333**「指字认字」。照片里大拇指最突出、其余手指也伸出，指向「珍」字 |
| **asset_id** | `asset_b58aaf5f04a83fcf23ea2f0e` · [img-server/img/asset_b58aaf5f04a83fcf23ea2f0e.jpg](../../img-server/img/asset_b58aaf5f04a83fcf23ea2f0e.jpg) |
| **修复前症状** | Stage 1 几何按 reach 选了伸得最远的食指，指尖落在「【」括号上，ranking 返回 **【**（非用户所指）。用户指出：多指是常态，不能靠「正好只伸一指」 |
| **根因** | 3+ 手指伸出时「指尖离腕最远」不可靠——一根张开在边缘的手指可以伸得最远却不是指向手指（intent 333 即此）。几何 dominance 只看 reach，无法区分「伸得最远」与「指向字」 |
| **算法调整**（用户两阶段法） | `geometry.py`：新增 `extended_fingers`（收集所有伸出指，不做 dominance 过滤）；`_choose_pointing_digit` 给每个返回项打 `signal` 标签（reach/grip/cluster/thumb_lateral/ambiguous），暴露 Stage 1 用了哪种信号。<br>`pipeline.py`：`detect_finger` 改两阶段——<br>• **Stage 1（几何）**：原 `pointing_fingers` dominance 逻辑（reach + grip-pattern + palm-forward cluster + thumb-lateral + thumb splay override）保持权威，处理握书/握纸/拇指侧压等 grip 姿态<br>• **Stage 2（OCR 邻近）**：仅当 **3+ 手指伸出 且 Stage 1 信号为弱 `reach`** 时触发。新增 `select_finger_by_text`——给每个候选指尖裁 600px 窗跑 OCR + ranking，选射线最直接命中字（top1 分最高）的手指。指向空白的手指得分≈0 自然排除（用户规则「没有指字的自然就排除」）。Stage 2 的 top1 分 ≥ `STAGE2_MIN_SCORE=0.6` 才覆盖 Stage 1 |
| **修复后结果** | intent 333 → **珍** ✓（Stage 2 选拇指，top3: 珍 ...，15.1s，`multi_finger_select=true`）|
| **回归影响** | 全 pipeline 回归 16 case top1 **13/16**。intent333 由 FAIL→PASS。**0 新增回归**：intent239（小）、reading_math（no_text）、IMG_8022（。）经 `git stash` 对比**原代码即已失败**（同 finger 同字），属 Q4 基线陈旧/历史问题，非本轮引入。`multi_finger_select=false` 确认这些 case Stage 2 未触发（signal 非 reach 或 <3 指），行为与原代码完全一致 |

> **signal 门控的意义**：grip / thumb_lateral / cluster 是强几何信号（握姿、拇指侧压、掌前簇），这些姿态下字常在指甲下方而非射线前方，ray-based Stage 2 会误判。只有 Stage 1 靠弱 reach 信号选指时（多指张开、无 grip），Stage 2 OCR 邻近才允许覆盖。这保证握书/握纸等历史 PASS case 不被破坏。

---

## 当前算法架构

```
照片字节
  │
  ▼
decode_bgr (hands.py)
  │  IMREAD_IGNORE_ORIENTATION + apply_exif_orientation（只转一次）
  ▼
detect_finger (pipeline.py)
  │
  ├─ MediaPipe Hands（主检测器）
  │    4 缩放 × 2 复杂度 × 3 置信度 + padding 重试
  │    → 21 关节 landmark
  │
  ├─ 若 MediaPipe 0 手 → skin_detect（自动 fallback）
  │    HSV+YCbCr 肤色 → blob 排序：
  │    (border_tier, -score) 两层排序（第 8 轮）
  │    tier 0=触底 > 1=触侧 > 2=触顶 > 3=不触边
  │    → {INDEX_TIP, INDEX_PIP} 两点
  │
  ▼
pointing_fingers (geometry.py)
  │
  ├─ 全 21 点：is_extended_digit 判断每根手指是否伸出
  ├─ 多根伸出：按指尖离腕距离排序，最长 ≥ 次长 ×1.1 → 只取最长（第 11 轮）
  │    thumb splay override: thumb 被选中时若 index tip 邻近则借用 index 方向（第 12 轮）
  ├─ 仍多根 → ambiguous_finger
  ├─ _choose_pointing_digit 给选中项打 signal 标签（reach/grip/cluster/thumb_lateral）（第 14 轮）
  ├─ 部分 landmark（skin fallback）：finger_ray 用 TIP+PIP 算方向
  │
  ▼
detect_finger 两阶段（第 14 轮）
  │
  ├─ Stage 1（几何）：pointing_fingers dominance（reach+grip+cluster+thumb_lateral）= 默认选择
  ├─ Stage 2（OCR 邻近）：仅当 3+ 指伸出 且 Stage 1 signal=reach 时触发
  │    select_finger_by_text: 每候选指尖裁 600px 窗跑 OCR+ranking
  │    选射线最直接命中字的手指；指向空白得分≈0 自然排除
  │    top1 分 ≥ STAGE2_MIN_SCORE(0.6) 才覆盖 Stage 1
  │
  ▼
ocr_at_finger (pipeline.py)
  │
  ├─ 2 个 OCR 窗口（指尖居中 600px + 指尖前方 260px）
  ├─ 每窗口 VLM 调 1 遍，有 CJK 即跳过第二遍（第 7 轮）
  ├─ 第一窗口命中 CJK 即跳过第二窗口（第 13 轮）
  ├─ VLM temperature=0 + 进程内 SHA-256 缓存（第 10 轮）
  └─ 全失败 → 整图 fallback OCR
  │  【找字用 VLM】
  │
  ▼
rank_pointed (geometry.py)
  │
  ├─ ray 模式：指尖射线穿过字框（权威）
  ├─ cone 模式：射线附近锥形候选（fallback）
  ├─ lateral 模式：指尖同高度的侧邻字
  ├─ contact 模式：指尖接触带内后方/框内字（指甲顶字）
  └─ top1 确认裁图 → PaddleOCR 再调 1 遍（第 9 轮）
  │  【认字用 Paddle】
  │
  ▼
decide → top1 字 + top3 + 分数
```

## 已知限制

| 限制 | 说明 | 当前处理 |
|------|------|----------|
| **木桌面 + 指尖-only** | 手指 Cr~144 与木桌面 Cr~142 重合，肤色分割分不开；MediaPipe palm-first 检不到掌根 | 用户引导「指在纸上不指在桌面」 |
| **MediaPipe palm-first 盲区** | 掌根/手腕不在画面时 MediaPipe 0 手 | 肤色分割 fallback（白纸/深色背景有效） |
| **插图肤色干扰** | 绘本插图中肤色卡通角色被 skin_detect 误检为手指 | border tier 排序：真手从底边进入（tier 0）优先于插图角色（顶部 tier 2）（第 8 轮） |
| **VLM 非确定性** | temperature>0 采样解码导致同一图不同结果 | temperature=0 贪婪解码 + 进程内 SHA-256 缓存（第 10 轮） |
| **多指微曲误判** | 食指指字时中指/无名指微曲被 `is_extended_digit` 判为伸出 → ambiguous | DOMINANT_TIP_RATIO 1.3→1.1，单指微优即可判定（第 11 轮） |
| **手指方向偏差** | `_digit_ray` 用 DIP→TIP（最后一节）方向与 MCP→TIP（整体）差异大；thumb 被选中时方向为横向非指向 | `_digit_ray` 改 MCP→TIP 优先；thumb splay override 借 index 方向（第 12 轮）|
| **多指张开误选** | 3+ 手指伸出时「指尖离腕最远」不可靠，边缘张开指伸得最远却非指向指（intent 333）| 两阶段：Stage 1 几何 dominance + signal 门控，Stage 2 OCR 邻近仅在 reach 信号 + 3+ 指时覆盖（第 14 轮）|
| **Q4 全 pipeline 基线不可靠** | Q4 dump 部分为假阳性（8022 误检页边）或旧代码产物（8024 只 4 landmark） | Q4 几何 replay 仍有效；全 pipeline 回归改用 `full_pipeline_regression.py` 原图 |
| **YOLOv8-pose 不适用** | COCO 17 点无手指关节；hand-pose 变体训练数据同为全手构图 | 未采用 |
| **自训指尖 CNN** | 唯一能根本解决「指尖-only + 任意背景」的路 | 未做（需标数据） |

## 样本照片索引

| intent | asset_id | 本地路径 | img-server URL | 拍摄设备 | 场景 |
|--------|----------|----------|-----------------|----------|------|
| 200 | `asset_1cdd70e4c738d45e5550ffe3` | `img-server/img/ba0a4d81_photo_1787672612.jpg` | `http://192.168.3.73:8080/ba0a4d81_photo_1787672612.jpg` | iPhone | 医院挂号单（EXIF Orientation=6） |
| 201 | `asset_e080b636a5e20a0d4786e710` | `img-server/img/3f089bec_upload_1787701987925.jpg` | `http://192.168.3.73:8080/3f089bec_upload_1787701987925.jpg` | 扫描件 | 「崭新局面」 |
| 239 | `asset_26a331d8527deb3241ffc552` | `img-server/img/49ce8930_photo_1787751581950.jpg` | `http://192.168.3.73:8080/49ce8930_photo_1787751581950.jpg` | Android | 自来水缴费通知单 |
| 253 | `asset_dfe90d94e7ffec6e8ca45673` | `img-server/img/4f83b365_photo_1787757124.jpg` | `http://192.168.3.73:8080/4f83b365_photo_1787757124.jpg` | iPhone | 木桌面指尖-only |
| 254 | `asset_9552eb3fc7484adb89fa420b` | `img-server/img/e09be3e2_photo_1787759393.jpg` | `http://192.168.3.73:8080/e09be3e2_photo_1787759393.jpg` | iPhone | 标准指字手势 |
| 259 / 261 | `asset_f3b06a7196d626c2575984fb` | `img-server/img/7c8c131f_cap_23f52099d577f3915fe2a1ec.jpg` | `http://192.168.3.73:8080/7c8c131f_cap_23f52099d577f3915fe2a1ec.jpg` | Android | 儿童绘本「弗洛格」 |
| 277 | `asset_f9a3d5d2e71c479d5a75d65b` | `img-server/img/57bb7cd2_photo_1787795714933.jpg` | `http://192.168.3.73:8080/57bb7cd2_photo_1787795714933.jpg` | Android | 儿童绘本「野兔」（插图肤色干扰） |
| 278 | `asset_fdd307eacd307800899b5b59` | `img-server/img/ad225ed3_photo_1787797386939.jpg` | `http://192.168.3.73:8080/ad225ed3_photo_1787797386939.jpg` | Android | 儿童绘本「雕」 |

## 回归基线

| 评测集 | 性质 | top1 | top3 | 说明 |
|--------|------|------|------|------|
| **Q4** | **生产口径** | **30/30** | 30/30 | 6 张照片 × 5 replay = 30 dump，全部 top1 正确 |
| Q8 | 非生产 | 24/29 | 25/29 | IMG_8022 历史 fail（标 still_fail） |
| gen45 | 非生产 | 26/30 | 30/30 | IMG_8050 历史 fail（标 still_fail） |
| local-8022 | 历史 | 0/1 | 0/1 | 虎（标 still_fail） |
| intent201 | 个案 | 1/1 | 1/1 | 崭（contact 模式） |

**回归命令**：

```bash
# 几何 replay（91 dump，Q4 30/30 为生产基线）
python character-service/eval/_full_photo_replay.py

# 全 pipeline 回归（原图 + VLM + Paddle，含进度日志）
cd character-service && local-rt/venv/bin/python3.11 eval/full_pipeline_regression.py --rounds 1

# 单测
cd character-service && python -m unittest tests.test_geometry.PointingFingerTests tests.test_stages.StageTests
```

**历次迭代的回归结论**：第 1-9 轮 Q4 几何 replay **30/30 无回归**。第 10-12 轮新增全 pipeline 回归：intent 6/6 PASS；8024 → **霸** ✓、7832 → **渊** ✓、8025 → **剧** ✓、8026 → **碾** ✓（均原图）；8022 Q4 为假阳性（测试用例需修正）。第 13 轮窗口级早退：`_full_photo_replay` 91 case PASS 81 / FAIL 10，失败集不变，0 新增回归。Q4 几何 replay 仍 0 回归。第 14 轮多指 OCR 邻近：全 pipeline 16 case top1 **13/16**，intent333 由 FAIL→**珍** ✓，**0 新增回归**（intent239/reading_math/8022 经 `git stash` 对比原代码即已失败，属历史/Q4 基线问题，非本轮引入）。
