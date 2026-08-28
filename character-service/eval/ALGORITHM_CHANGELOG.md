# character-service 算法变更记录

本文件是 `reading.point_to_character` / character-service 算法改动的活文档。
每一次改几何、解码、裁窗、OCR 契约，都在这里记一笔：哪张图、哪个 case、为什么改、改了什么。
评估全量 replay 仍落在 `eval/q4`、`eval/gen45` 等目录，不要把整套评测贴进来。

## 条目模板

每条必须写清 **asset_id** 和 **图片路径**（盘上真实路径，不要占位符）。没有对应图的改动写「无」并说明原因。

```
## YYYY-MM-DD — 短标题

- **asset_id**：Brain catalog 的 asset_id（如 asset_…）
- **图片路径**：盘上真实文件路径（img-server / gopropics / Mac cache 等查到哪写哪）
- **Trigger**：intent_id / 图片说明 / case
- **Symptom**：用户可见失败
- **Root cause**：根因
- **Change**：文件 + 行为
- **How to regress**：如何复现/回归
```

---

## 2026-08-28 — crop-passing：detect 产裁剪传给 ocr/rank + VLM 运行时调优

- **asset_id**：无（性能优化，非单 case 故障修复）
- **图片路径**：`character-service/samples/IMG_8022.jpg`、`character-service/samples/IMG_8023.jpg`（回归样本）
- **Trigger**：`reading.point_to_character` 端到端耗时偏高（曾观测 ~40s），排查发现 mac-edge 复合步对**同一张整图**重复下载/读取 3 次（detect / ocr / rank 各一次），且每次都把 5MB 整图 base64 传给 char-svc。
- **Symptom**：复合步慢；不是认错字，是 I/O 与传输开销 + VLM 单次延迟方差大（同一窗口 5-30s）。
- **Root cause**
  1. **整图重复取用**：`AssetManager.materialize_file` 每次都走 HTTP 下载（或重读），无缓存；detect / ocr / rank 三个原子步各取一次整图。
  2. **整图重复传输**：每个原子步把整图 base64 编码后 POST 给 char-svc，5MB 图编码/传输/解码开销大。
  3. **VLM 抖动**：llama-server 默认 `n_slots=4`，KV cache 占用大；16GB 机器内存超commit（Cursor / Android Studio / Chrome / VLM 同跑）→ swap 抖动，连续 3 次 VLM 调用 ms/token 121→175→216 逐次退化（48→70→89s）。
- **Change**
  - **Asset 本地缓存** `mac_edge/asset/manager.py`：`materialize_file` 首次下载后按 `asset_id` 缓存本地 `Path`，后续命中不再下载；顺带修了 `Path(...).strip()` 的旧 bug（`PosixPath` 无 `.strip`）。
  - **detect 产裁剪** `character-service/pipeline.py`：`detect_finger(return_crop=True)` 在指尖处裁 `FINGER_CROP_HALF=640`（半边 640px，覆盖所有 OCR 窗最大 shift 260+半窗）的正方形，返回 `finger_crop_b64` / `crop_origin` / `full_image_shape`。
  - **裁剪传递** `mac_edge/plugins/point_to_character.py`：detect 把裁剪写本地文件 + `register_local_file` 生成新 `asset_ref`，finger 平移到裁剪坐标系（`finger - crop_origin`）下传给 ocr/rank；ocr/rank 拿到的是 450KB 裁剪而非 5MB 整图。
  - **executor 覆盖语义** `mac_edge/executor.py`：`asset_ref` 改为「前序产出则覆盖」（原先 fill-if-None 使 detect 的裁剪 asset_ref 被原始整图 asset_ref 挡住，裁剪传递是死代码）；`full_image_shape` / `crop_origin` 加入传播键并 hide 出最终输出。
  - **rank 用全图尺寸** `pipeline.rank_pointed`：`max_dist` 用 `full_image_shape`（源图对角线）校准，不因传入的是裁剪而把搜索半径缩到裁剪对角线，保持与整图口径一致。
  - **VLM 运行时** `local-rt/run_llama.sh`：`--load-mode mlock`（权重锁 RAM）+ `--parallel 1`（KV cache 从 4 slot 砍到 1 slot，内存占用 ↓75%）+ 启动后发一次预热请求（page-in 视觉编码器 + 建 compute graph，含 503 重试）。
  - **测试开关** `character-service/hunyuan_ocr.py`：新增 `HUNYUAN_OCR_CACHE` 环境变量（默认 `1` 开），测试时设 `0` 关闭 in-process OCR 缓存，让 standalone 与 composite 都跑真 VLM、公平对比。
- **验证（2026-08-28）**
  - **VLM 抖动消除**：`--parallel 1` 后连续 3 次不同图 VLM 调用 ms/token 157→83→66（首次慢=视觉编码器 page-in，之后稳定），不再 121→175→216 退化。
  - **crop-passing 一致性** `regress_crop_passing.py`（`HUNYUAN_OCR_CACHE=0`，两边纯 VLM）：IMG_8022 `'。'`/`'。'` ✓、IMG_8023 `'娘'`/`'娘'` ✓，PASS。
  - **「composite 比 standalone 慢」是假象**：加计数器实测，standalone 与 composite **都是 1 次 VLM 调用**、喂同样大小的 600×600 窗口（`ocr_at_finger` 不管入参是整图还是裁剪，都在指尖处再裁一个 600×600 小窗喂 VLM）。同一 60KB 窗口单次 VLM 延迟在 15-28s 间剧烈波动，两次跑里 composite vs standalone 的快慢方向反转，纯属 VLM CPU-prefill 噪声，非结构性差异。
  - **crop-passing 真正省的**：整图不再重复下载/读取 3 次（asset 缓存）+ ocr/rank 传 450KB 裁剪而非 5MB 整图（base64 编码/传输/解码 ↓一个量级）。VLM 推理本身（1 次 600×600 窗口）两条路相同，crop-passing 改不动它。
- **How to regress**
  - 单测：`PYTHONPATH=src .venv/bin/python -m pytest mac/tests/test_point_to_character_composite.py mac/tests/test_asset_manager.py`；`python -m unittest tests.test_stages`（cwd `character-service`）。
  - 端到端一致性：`HUNYUAN_OCR_CACHE=0` 起 char-svc，`python3 character-service/eval/regress_crop_passing.py`，应 PASS（同字）。
  - VLM 抖动：`--parallel 1` 起 llama-server，连续 3 次不同 600px 裁剪调 `/v1/chat/completions`，ms/token 应稳定/下降，不应逐次上升。
- **备注**：VLM 剩余 ~15-28s 单次延迟是 CPU-only 构建 prefill ~391 图像 token 的硬件下限，非 bug；要再降需上 GPU 或换更小视觉模型。

## 2026-08-27 — 肤色分割 fallback：MediaPipe 检不到手时自动启用（intent 259）

- **asset_id**：`asset_f3b06a7196d626c2575984fb`
- **图片路径**：`/Users/gaolei/Projects/smart_home_control/img-server/img/7c8c131f_cap_23f52099d577f3915fe2a1ec.jpg`
  - 诊断副本：`/tmp/intent_259_photo.jpg`
- **Trigger**：LAN intent **259**「最新的照片上手指的字是什么字」
- **Symptom**：`reading.point_to_character` step 2 失败，`status=no_hand`。图里是儿童绘本（白纸背景），食指从画面底部伸入指着「弗洛格」，MediaPipe 0 手（掌根不在画面）。
- **Root cause**：与 intent 253 同类——MediaPipe palm-first 模型在掌根不在画面时 0 hand。但 259 是白纸背景（非木桌面），肤色分割可用。
- **Change**
  - `character-service/pipeline.py` `detect_finger`：MediaPipe 返回 0 手且 `detect_hand is None`（即非测试注入）时，自动 fallback 到 `skin_detect.detect_hands_landmarks`。timing 加 `skin_fallback: bool` 标记。
  - `character-service/skin_detect.py`：
    - 阈值：Cr 135-180、Cb 85-135（松，覆盖 iPhone Cr~168 和 Android Cr~146 两种摄像头肤色）；HSV S 上限 150（排除高饱和印刷橘色字 S~165，保留正常皮肤 S~140）。
    - 打分：`min(aspect, 10) * orient_bonus`（竖向 blob ×2，横向 ×0.5），不乘 area——避免大插图条淹没小手指。
    - 指尖：`_fingertip_point` 检测 blob 触边方向，指尖 = 远离触边的那端（手指从底部入镜 → 指尖在上方）；不触边时 fallback 到 farthest-from-centroid。
    - 只返回最高分 1 个 blob（肤色分割检多手不可靠）。
- **验证**
  - 259：`POST /v1/detect_finger` → `status=ok`，`finger.tip=[207.4, 1165.4]`，`direction=[0.24, -0.97]`（朝上指字），`skin_fallback=True`。
  - 253（木桌面）：仍 `no_hand`（肤色分割也失败，已知 bad case，用户引导处理）。
  - 254（拇指+食指）：仍 `ok, digit=index`（MediaPipe 检到，无需 fallback）。
  - 单测 12/12 ok。
- **How to regress**
  - `python -m unittest tests.test_geometry.PointingFingerTests tests.test_stages.StageTests`
  - 对 259 照片 `POST /v1/detect_finger`：应 `status=ok`，`skin_fallback=True`。
  - 对 253 照片 `POST /v1/detect_finger`：应 `status=no_hand`（不误检橘色字）。

## 2026-08-27 — 拇指+食指同伸：最长伸出指优先（intent 254）

- **asset_id**：`asset_9552eb3fc7484adb89fa420b`
- **图片路径**：`/Users/gaolei/Projects/smart_home_control/img-server/img/e09be3e2_photo_1787759393.jpg`
  - 诊断副本：`/tmp/intent_254_photo.jpg`
- **Trigger**：LAN intent **254**「看一下最新的一张照片里面手指的那个字是什么」
- **Symptom**：`reading.point_to_character` step 2 失败，`status=ambiguous_finger`，reason「图里有多根手指，系统无法判断你指的是哪个字。（thumb、index）」。图里是**标准指字手势**：食指伸出指字，拇指自然张开，中指/无名指/小指弯曲。
- **Root cause**：`geometry.pointing_fingers` 凡 `is_extended_digit` 通过的手指都列出，多于 1 根就 `ambiguous_finger`，不看哪根才是「真正在指」。拇指在食指指字时自然张开是常态，不是歧义。254 landmark：食指 TIP 离腕 1857、拇指 TIP 离腕 1295，食指明显伸得更远。
- **Change**
  - `character-service/geometry.py`：新增 `DOMINANT_TIP_RATIO=1.3`。`pointing_fingers` 多根伸出时按「指尖离腕距离」排序，最长的那根若 ≥ 次长的 1.3 倍则只取它（不判歧义）；否则仍 `ambiguous_finger`（如食指+中指都全伸的剪刀手）。
  - `character-service/tests/test_geometry.py`：`test_thumb_and_index_are_ambiguous` → `test_thumb_splayed_index_dominates`（拇指张开+食指指字 → 只选食指）；新增 `test_index_and_middle_are_ambiguous`（食指+中指同伸 → 仍歧义）。`_synthetic_hand` 加 `middle_out` 参数。
  - `character-service/tests/test_stages.py`：`test_detect_finger_ambiguous_when_two_digits` 改用食指+中指同伸（真正歧义），不再用拇指+食指。
- **How to regress**
  - `python -m unittest tests.test_geometry.PointingFingerTests`（6/6 ok）
  - `python -m unittest tests.test_stages.StageTests`（6/6 ok）
  - Q4 几何 replay：`python character-service/eval/_full_photo_replay.py`（30/30 无回归；intent201 崭 仍 contact 通过）
  - 对 254 照片 `POST /v1/detect_finger`：`status=ok`，`digit=index`，不再 `ambiguous_finger`。
- **Live 2026-08-27**（character-service 重启 + 清 `__pycache__` 后）：`POST /v1/detect_finger` → `status=ok`，`finger.tip=[1645.9, 1600.2]`，`digit=index`。

## 2026-08-26 — 指尖在木桌上 MediaPipe 0 手（intent 253）— 已知 bad case

- **asset_id**：`asset_dfe90d94e7ffec6e8ca45673`
- **图片路径**：`/Users/gaolei/Projects/smart_home_control/img-server/img/4f83b365_photo_1787757124.jpg`
  - 诊断副本：`character-service/samples/lan_latest_asset_dfe90d94.jpg`
- **Trigger**：LAN intent **253**「看一下最新的一张照片里面手指的那个字是什么」
- **Symptom**：`reading.point_to_character` step 2 失败，`status=no_hand`，reason「图里没有检测到伸出的手指」。图里**确实有食指**指着「自来水缴费通知单」上的「用户编号：38549」。
- **Root cause**：iPhone 俯拍，**只有食指尖到中节入镜**，掌根/手腕/拇指根全在画面外。MediaPipe Hands 是 palm-first 两阶段模型，palm detector 在「掌根不在画面」时直接 0 hand，后续 21 关节 refine 不启动。这是**模型设计层面的盲区**，不是阈值问题——已验证 4 个缩放尺度 × 2 复杂度 × 3 置信度（最低 0.05）+ 0.18 黑边 padding 全轮一遍仍 0 hand。
- **尝试过的替代方案（均未解决此 case）**
  - **肤色分割** `character-service/skin_detect.py`（独立模块，未接入 pipeline）：HSV+YCbCr 肤肤色。失败原因——手指主体 `Cr=144`、木桌面 `Cr=142`，**色度几乎重合**，纯颜色无法把手指从同色桌面分出来。收紧阈值（Cr≥150）连手指自己也切掉；松阈值则桌面并进巨型 blob，凸包最远点落在图像角落而非指尖。开运算残差 47 个碎片不可用。肤色分割在**白纸/深色背景**上可用，木桌面场景失效。
  - **YOLOv8-pose**：COCO 17 关键点只有手腕无手指，不可用；社区 hand-pose 变体训练数据同为全手构图，掌根不在画面时同样翻车。自训指尖检测器是唯一能根本解决的路，但要标数据，未做。
- **当前处理**
  - **产品引导**：`pipeline.detect_finger` 的 `no_hand` 文案改为「请把手指指在书页或白纸上（不要指在桌面），让手指大部分进入画面，指尖对着那个字。」——引导用户避开木桌面同色背景，并让更多手指入镜（MediaPipe 需要掌根）。
  - `skin_detect.py` 保留在 `character-service/`，未接入 pipeline；白纸背景场景可经 `READING_HAND_BACKEND=skin` 开关启用（开关尚未接，模块已就位）。
- **Change**
  - `character-service/pipeline.py` `detect_finger`：`no_hand` reason 文案更新（引导纸上 + 更多手指入镜）。
  - `character-service/skin_detect.py`：新增独立肤色分割指尖检测器（同 `detect_hands_landmarks` 接口，返回 `[{INDEX_TIP, INDEX_PIP}]`），**未接入 pipeline**，留作白纸背景场景备用。
- **How to regress**
  - 对 intent 253 照片跑 `POST /v1/detect_finger`：仍 `status=no_hand`（已知 bad case，未修），reason 为新文案。
  - `python3 character-service/tests/test_stages.py`：`no_hand` 路径不回归（文案未断言）。
  - 白纸背景照片：`READING_HAND_BACKEND=skin`（开关未接）后 `skin_detect.detect_hands_landmarks` 应能分出指尖。
- **待办**：若频繁出现「指尖-only + 木桌面」构图，考虑边缘/阴影检测（手指 3D 物体两侧有阴影线）或自训指尖 CNN。

## 2026-08-26 — 独立指尖：多根则拒（intent 239 缴）

- **asset_id**：`asset_26a331d8527deb3241ffc552`
- **图片路径**：`/Users/gaolei/Projects/smart_home_control/img-server/img/49ce8930_photo_1787751581950.jpg`
- **Trigger**：LAN intent **239**「最新的这张照片里面手指的是哪个字」。用户指的是「自来水缴费通知单」里的 **缴**。
- **Symptom**：系统答 **监**。图上没有「监」；那是 OCR 在框 `[713,11,756,98]` 上的幻觉。旧逻辑只跟 MediaPipe **食指** 5–8，食指射线打中这块幻觉框。
- **Root cause**：`detect_index_landmarks` 默认食指。图里拇指按纸、食指伸出，是两根独立手指，系统却只跟食指并猜了一个不存在的字。
- **Change**
  - `geometry.py`：`pointing_fingers` 按腕部距离 + 伸直程度判断拇指/食指/中指/无名指/小指是否在指；**不**把多根手指拿去打分比谁更像指针。
  - `hands.py`：检出一只手上的 21 点（可多手）；`detect_index_landmarks` 仍留给 eval dump。
  - `pipeline.detect_finger`：0 根 → `no_hand`；**多于 1 根 → `ambiguous_finger`**，reason「图里有多根手指，系统无法判断你指的是哪个字。」；恰好 1 根才给出 `finger`（可以是拇指）。
  - Mac plugin：`ambiguous_finger` 或缺 `finger` 时 `PointToCharacterError`，复合步失败并带上该 reason。
- **How to regress**
  - `python3 character-service/tests/test_geometry.py PointingFingerTests`
  - `python3 character-service/tests/test_stages.py StageTests.test_detect_finger_ambiguous_when_two_digits` / `test_detect_finger_single_thumb`
  - 几何 Q4 不变：`python3 character-service/eval/_full_photo_replay.py`（仍只重打已有 dump 的 `rank_characters`）
  - 对 intent 239 照片跑 `POST /v1/detect_finger`：应 `status=ambiguous_finger`，不应再出「监」。
- **Live 2026-08-26**（character-service 重启后 `POST /v1/detect_finger`，jpeg 本路径）：`status=ambiguous_finger`，独立伸出 5 根（thumb、index、middle、ring、pinky）。reason：`图里有多根手指，系统无法判断你指的是哪个字。（thumb、index、middle、ring、pinky）`。未跑 `ocr_at_finger` / `rank_pointed`，故 **缴未检出**。MediaPipe 两只手：hand0 无伸出指；hand1 拇指尖 `(766.9, 572.2)`、食指尖仍 `(454.1, 233.4)`。
- **Bad case 文档**：[`eval/bad_cases/intent239.md`](bad_cases/intent239.md)（原图副本、为何五指全过门、改法）。

## 2026-08-26 — 全量照片几何回归（contact-pad 后）

- **asset_id**：无（离线 dump replay，不新跑图）。intent 201 dump 对应 `asset_e080b636a5e20a0d4786e710`。intent 200 / 203 **没有**保存的 OCR+landmarks dump，本次未做 live Hunyuan（本机 `9189` 进程 2026-08-25 19:33 起、早于 contact-pad；`:9188` ocr-service 未起）。
- **图片路径**：`character-service/eval/{q4,q8,gen45}/replay/*.json`（89 份）+ `eval/local-8022/IMG_8022_local_r1.json` + `eval/intent201_capability_stages/00_live_replay.json`。
- **Trigger**：用户「把之前所有的照片回归一次」；capability-only，`rank_characters` 对保存的 `replay.chars` + origin/direction 重打分，不走 Brain / intent。
- **Symptom**：无。生产口径 **Q4 30/30 top1 保持**；201 dump 由「的」→ **崭**（`mode=contact`）。
- **Root cause**：无新故障。Q8 8022 / gen45 8050 / local-8022 仍为历史失败（Q8 非生产；8050 top1「的」4/5 与基线相同；local-8022 dump 当时已是「虎」）。
- **Change**：无算法改动。合计 **91 dump**：Q4 **30/30** top1（基线 30/30）；Q8 **24/29** top1（基线 24/29）；gen45 **26/30** top1 **30/30** top3（基线相同）；intent201 **1/1 崭 contact**（相对 dump top1=的 为新通过）；local-8022 0/1（非回归）。**无 Q4 回退。**
- **How to regress**：`python3 character-service/eval/_full_photo_replay.py`（cwd 任意；脚本把 `character-service/` 加进 path）。

## 2026-08-26 — 指尖接触带（intent 201 崭）

- **asset_id**：`asset_e080b636a5e20a0d4786e710`
- **图片路径**：`/Users/gaolei/Projects/smart_home_control/img-server/img/3f089bec_upload_1787701987925.jpg`
- **Trigger**
  - intent **201**（LAN Brain，扫描件「看一下最新的照片上手指的那个字是什么字」）
  - 正确字 **崭**（「崭新局面」；指甲盖正下方 / 右侧）
  - 同字照片 intent **203** `asset_afb51c47fa60fbad177bd0c3`（`img-server/img/4eba631f_photo_1787702370071.jpg`）已走 lateral 排到崭，本改动不得回归
- **Symptom**：201 返回 **力**（「倾力支持」）。OCR 已看见「集工作的崭新局面」，崭因落在 MCP→TIP 射线后方被丢掉。
- **Root cause**：`score_character` / `lateral_score` 凡 `dot(center-TIP, direction) ≤ 0` 一律丢弃。201 食指钩着，射线几乎朝左；崭在 TIP 右上约 40×147px，被当成后方。`CONTACT_PAD_PX=8` 只覆盖指尖落在框内的情况，够不到 ~100px 的「指甲顶在字下沿」。
- **Change**
  - `character-service/geometry.py`：新增 `mode=contact` 几何类，与 ray / cone / lateral 并列。指尖邻域 pad 随 **median glyph height** 与 **max_distance** 缩放（约 0.4×600px OCR 窗，再按搜索半径封顶），不再用固定 8px。
  - 邻域内且在射线后方（或 TIP 落在框内）的字 **不因 dot≤0 丢弃**；按到 TIP 的 nearest-edge 打分。前方字仍走 ray/lateral。
  - 邻接 contact 分数封顶 0.78，避免压过 8022 因 / 8024 霸 / 8025 剧 的高分 lateral。手指仰角 >32° 时不走 contact（与 lateral 同一门槛，避免 7832 了 抢走 渊）。吞掉两个以上邻字中心的错框（如窗1 的「牵」盖住 的+崭）不进 contact。
  - 不改 `finger_ray`（仍 MCP→TIP），不全局「指向上方」。
- **How to regress**
  - 离线：`character-service/tests/test_geometry.py` `test_intent201_scan_ranks_zhan`（dump `eval/intent201_capability_stages/00_live_replay.json`）top1=崭。
  - 同文件：`test_small_char_beats_title_box`（8024 霸 vs 王）、`test_contact_does_not_steal_8025_di`（剧 vs 帝）、q4 replay 8022 因 / 8024 霸 / 8025 剧 / 7832 渊。
  - 几何 replay：对上述 dump 的 `replay.chars` 跑 `rank_characters`；崭应进 ranked 且为 top1，不得再被丢掉。

## 2026-08-26 — decode_bgr 双 EXIF 旋转

- **asset_id**：`asset_1cdd70e4c738d45e5550ffe3`
- **图片路径**：`/Users/gaolei/Projects/smart_home_control/img-server/img/ba0a4d81_photo_1787672612.jpg`
  - Brain `assets.storage`：`backend=img_server`，`key/saved_as=ba0a4d81_photo_1787672612.jpg`，`public_base=http://192.168.3.73:8080`，`size_bytes=2251964`
  - 诊断副本（同字节）：`/Users/gaolei/Projects/smart_home_control/.tmp_intent200_photo.jpg`
- **Trigger**
  - intent **200**（LAN Brain，2026-08-25 ~23:46）
  - 用户：「最新照片里手指指的那个字是什么」
  - 图：iPhone 医院挂号单 JPEG，EXIF Orientation=6，字清晰
  - 实测（2026-08-26）：文件 2251964 bytes；`IMREAD_IGNORE` 存储像素 **4032×3024**（宽×高）；正确转正 **3024×4032** 竖图；双转后变回 4032×3024 横图
  - Case：`reading.point_to_character` 指尖指字
- **Symptom**：能力返回 `no_text` / 空 character。照片本身清晰。
- **Root cause**：OpenCV 4.11 `cv2.imdecode(..., IMREAD_COLOR)` 已经按 JPEG EXIF 转正（3024×4032）；`hands.decode_bgr` 再跑一遍 `apply_exif_orientation`，图被横过来（4032×3024）。指尖落到画面上沿，600px OCR 窗切到指尖和桌布，窗内无字，Hunyuan 返回 `[]`。
- **Change**：`character-service/hands.py` `decode_bgr` 用 `IMREAD_COLOR | IMREAD_IGNORE_ORIENTATION`（无该 flag 的旧 OpenCV 仍只走 `apply_exif`）。只旋转一次，新旧 OpenCV 行为一致。不改 OCR 回退、不改几何。
- **How to regress**
  - 对上述路径跑 `decode_bgr`：应为直立竖图 **3024×4032**（宽×高，高>宽），不是双转后的 4032×3024。
  - 指尖 600px OCR 窗应切到单据文字，而不是只剩指尖/桌布。
  - 单元测试：`character-service/tests/test_exif.py` `test_decode_bgr_orientation_6_not_double_rotated`。
