# 指尖认字算法改进备忘录 + SOP

> 本文是 `reading.point_to_character` 算法改进的**总览备忘录**与**标准作业流程（SOP）**。
> 每轮详细记录（症状/根因/调整/回归）见 [`ALGORITHM_ITERATION.md`](ALGORITHM_ITERATION.md)；
> 代码变更明细见 [`ALGORITHM_CHANGELOG.md`](ALGORITHM_CHANGELOG.md)；失败样本见 [`bad_cases/`](bad_cases/)。

---

## 第一部分：改进备忘录（14 轮浓缩）

### 核心原则（贯穿所有迭代）

1. **不预设用户用哪根手指，也不指望图里只有一根手指**——我们只是在按逻辑找「图片上概率最大的那个字」。
2. **找字用 VLM（行级 spotting），认字用 Paddle（单字识别）**。
3. **几何信号有强弱**：grip / thumb_lateral / cluster 是强信号（握姿、拇指侧压、掌前簇），reach 是弱信号（多指张开时不可靠）。弱信号才允许被 OCR 邻近覆盖。
4. **方向只当软门，不当硬射线**：指尖位置是主信号，方向用来排除「指尖后方」的字，不应让解剖方向（如拇指横向）压过「指尖正上方的字」。
5. **失败必须有可读 msg；空 plan 不得停在 intent_parsed**（见 qc-design-charter）。
6. **每次改动必须过回归**：Q4 几何 replay（30/30 生产基线）+ 全 pipeline 回归 + 单测，0 新增回归才合并。

### 14 轮改进一览

| 轮 | 目标 case | 解决的问题 | 关键改动 | 文件 |
|---|---|---|---|---|
| 1 | intent 200 | EXIF 双旋转，图被横过来 | `decode_bgr` 用 `IMREAD_IGNORE_ORIENTATION`，EXIF 只转一次 | hands.py |
| 2 | intent 201 | 指甲顶字，字在射线后方被丢 | 新增 `contact` 几何模式，pad 随字高缩放，后方字不丢 | geometry.py |
| 3 | intent 239 | 只跟食指，OCR 幻觉出「监」 | `pointing_fingers` 判所有伸出指，多指→`ambiguous_finger` | geometry.py / pipeline.py |
| 4 | intent 253 | 木桌面指尖-only，MediaPipe 0 手 | 已知限制：用户引导「指在纸上」；建 skin_detect 备用 | pipeline.py / skin_detect.py |
| 5 | intent 254 | 标准指字手势被误判歧义 | `DOMINANT_TIP_RATIO=1.3`，最长指 ≥ 次长×1.3 取最长 | geometry.py |
| 6 | intent 259 | 白纸背景指尖-only，MediaPipe 0 手 | MediaPipe 0 手自动 fallback skin_detect | pipeline.py / skin_detect.py |
| 7 | intent 259/261 | VLM 调 5 次，耗时 57s | OCR 2-pass 去重，第一遍有 CJK 即跳第二遍 | pipeline.py |
| 8 | intent 277 | 插图肤色卡通角色被误检为手指 | skin_detect 加 `border_tier` 排序（底>侧>顶） | skin_detect.py |
| 9 | intent 278 | confirm 用 VLM 占 40s | confirm 改 PaddleOCR，VLM 失败再 fallback | pipeline.py |
| 10 | 全部 VLM case | VLM 非确定性，同图不同结果 | `temperature=0` + 进程内 SHA-256 缓存 | hunyuan_ocr.py |
| 11 | IMG_8024/7832 | 多指微曲被判伸出→ambiguous | `DOMINANT_TIP_RATIO` 1.3→1.1 | geometry.py |
| 12 | IMG_8024/7832 | 手指方向算偏（DIP→TIP / 拇指横向） | `_digit_ray` 改 MCP→TIP 优先；thumb splay override 借 index 方向 | geometry.py |
| 13 | intent 297 | 第二 OCR 窗冗余，多 20s | 第一窗命中 CJK 即跳第二窗 | pipeline.py |
| 14 | intent 333 | 3+ 指张开，reach 选错食指→【 | 两阶段：Stage1 几何+signal 门控，Stage2 OCR 邻近仅在 reach+3 指时覆盖 | geometry.py / pipeline.py |

### 关键常量速查

| 常量 | 值 | 作用 | 引入轮 |
|---|---|---|---|
| `DOMINANT_TIP_RATIO` | 1.1 | 多指时最长指 ≥ 次长×此值才取最长 | 5→11 |
| `STAGE2_MIN_SCORE` | 0.6 | Stage2 OCR 覆盖 Stage1 的置信门槛 | 14 |
| `CONTACT_PAD` | 随字高×max_dist | 指甲顶字的接触带 | 2 |
| `OCR_WINDOWS` | 600px 居中 + 260px 前移 | 指尖 OCR 裁窗 | 7/13 |
| VLM `temperature` | 0.0 | 贪婪解码，确定性 | 10 |
| OCR 缓存 | SHA-256, 200 条 LRU | 同图复现 | 10 |

### 当前管线架构（三阶段）

```
照片 → decode_bgr（EXIF 一次）
  → detect_finger（Stage1 几何 dominance + signal；Stage2 OCR 邻近，仅 reach+3指触发）
  → ocr_at_finger（VLM 找字，第一窗命中即停）
  → rank_pointed（ray/cone/lateral/contact 四模式 + Paddle 确认）
  → top1 字 + top3 + 分数
```

### 已知限制（未解决）

- **木桌面 + 指尖-only**：肤色与木桌 Cr 重合，分割不开 → 用户引导避开。
- **MediaPipe palm-first 盲区**：掌根不在画面 → skin_detect fallback（白纸有效）。
- **Q4 全 pipeline 基线不可靠**：部分假阳性 / 旧代码产物 → 几何 replay 仍有效，全 pipeline 用原图回归。
- **自训指尖 CNN**：唯一能根治「指尖-only + 任意背景」的路，未做（需标数据）。

### 待修问题（最新）

- **intent 333 方向带偏**：Stage2 选对了拇指，但拇指解剖方向（向右上）让射线打中「珍」，而拇指正上方是「和」。根因：rank_pointed 用 ray-hit 主导，方向硬射线压过指尖邻近。**修复方向**：把 rank_pointed 打分从「ray-hit 主导」改为「proximity × 前方软门」，方向只排除指尖后方的字，不再奖励射线正中。回归期望值需从「珍」改为「和」（待确认）。

---

## 第二部分：算法改进 SOP

> 每次改 `reading.point_to_character` 算法时，按本流程执行。目标：**可复现、可验证、0 意外回归**。

### 步骤 0：建立基线（改之前必做）

1. 确认 `character-service` 服务在跑：`curl -s http://127.0.0.1:9189/health`。
2. 跑一次当前代码的全 pipeline 回归，记录改动前基线：
   ```bash
   cd character-service && local-rt/venv/bin/python3.11 eval/full_pipeline_regression.py --rounds 1
   ```
   保存输出（top1/top3/fails/timing）作为「改前基线」。
3. 跑 Q4 几何 replay（生产基线 30/30）：
   ```bash
   python character-service/eval/_full_photo_replay.py
   ```

### 步骤 1：定位根因（不要急着改）

1. **复现**：用 HTTP 三阶段诊断脚本对目标 case 跑 `detect_finger` → `ocr_at_finger` → `rank_pointed`，打印每步输出（finger tip/direction、chars bbox、ranking top3）。
   - 优先用已运行的 character-service HTTP API，**不要**另起进程跑 MediaPipe（GPU 上下文冲突会 SIGFPE）。
2. **看图**：用 Read 工具看原图，人工判断用户指的是哪个字（作为期望值）。
3. **定位是哪一阶段错**：
   - finger 选错 → detect_finger（Stage1 几何 / Stage2 OCR 邻近）
   - finger 对但方向错 → `_digit_ray` / thumb splay override
   - finger 对、字也 OCR 到了，但排序错 → rank_pointed 打分模型
   - OCR 没看到字 → ocr_at_finger 裁窗 / VLM
4. **写根因一句话**：例如「Stage2 选对拇指，但拇指解剖方向向右上，ray-hit 打中珍，正上方是和」。

### 步骤 2：最小改动

1. 只改与根因直接相关的函数 / 常量，**不顺手重构**。
2. 改动遵循核心原则：不预设手指、方向当软门、几何信号分强弱。
3. 若引入新常量，在本备忘录「关键常量速查」补一行。

### 步骤 3：验证目标 case

1. 重启服务：`kill <pid>; cd character-service && nohup ./run.sh > /tmp/cs.log 2>&1 &`
2. 对目标 case 跑三阶段诊断，确认 top1 = 期望值。
3. 若不对，回到步骤 1 重新定位（不要堆叠补丁）。

### 步骤 4：回归（0 新增回归才合并）

1. 全 pipeline 回归（同步骤 0 命令），对比「改前基线」：
   - 目标 case：FAIL→PASS ✓
   - 其他 case：**不得新增 FAIL**。若某 case 由 PASS 变 FAIL，是回归，必须处理。
2. Q4 几何 replay：仍需 30/30（生产基线）。
3. 单测：
   ```bash
   cd character-service && python -m unittest tests.test_geometry tests.test_stages
   ```
   - 预存的 `test_side_char_out_of_cone` 失败是历史问题，不计入。
   - 若改了 detect_finger 的函数签名 / mock 目标，同步改 `tests/test_stages.py`。
4. **区分「真回归」与「历史问题」**：若某 case 改前就 FAIL（用 `git stash` 对比原代码确认），属历史/Q4 基线陈旧，不是本轮引入，在记录里注明。

### 步骤 5：留痕

1. 在 `ALGORITHM_ITERATION.md` 加一轮（第 N 轮），按统一表格：目标 case / asset_id / 修复前症状 / 根因 / 算法调整 / 修复后结果 / 回归影响。
2. 更新本文「14 轮改进一览」表与「关键常量速查」。
3. 更新 `ALGORITHM_ITERATION.md` 的「当前算法架构」图与「已知限制」表。
4. 更新「历次迭代的回归结论」一句话。
5. （产品代码改动）按 release-pipeline：commit → test → deploy，Chatbox 留 `[release]` 痕。

### 步骤 6：清理

- 删除一次性诊断脚本（`eval/_diag_*.py`），不留在仓库。
- 临时 `git stash` 用完即 `drop`。

---

## 附：诊断脚本模板

对单个 case 跑三阶段、只打印关键信息（不 dump base64）：

```python
#!/usr/bin/env python3
import base64, json, urllib.request
from pathlib import Path
BASE = "http://127.0.0.1:9189"
IMG = Path("img-server/img/<文件名>.jpg")
def post(stage, payload):
    req = urllib.request.Request(f"{BASE}/v1/{stage}", data=json.dumps(payload).encode(),
                                 headers={"Content-Type":"application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=300).read().decode())
img = base64.b64encode(IMG.read_bytes()).decode()
det = post("detect_finger", {"image_base64": img, "return_crop": True})
f, co = det["finger"], det.get("crop_origin",[0,0])
rel = dict(f); rel["tip"] = [round(f["tip"][0]-co[0],1), round(f["tip"][1]-co[1],1)]
cb = base64.b64encode(base64.b64decode(det["finger_crop_b64"])).decode()
ocr = post("ocr_at_finger", {"image_base64": cb, "finger": rel})
for c in ocr.get("chars",[]):
    print(c["text"], [c["bbox"][0]+co[0], c["bbox"][1]+co[1], c["bbox"][2]+co[0], c["bbox"][3]+co[1]])
rank = post("rank_pointed", {"image_base64": cb, "finger": rel,
            "chars": ocr.get("chars"), "full_image_shape": det.get("full_image_shape")})
print("digit", f.get("digit"), "tip", f.get("tip"), "dir", f.get("direction"))
print("top1", rank.get("character"), rank.get("score"))
for r in rank.get("top3",[]): print(" ", r.get("text"), round(r.get("score",0),3), r.get("bbox"))
```

---

## 附：回归命令速查

```bash
# 0. 健康检查
curl -s http://127.0.0.1:9189/health

# 1. 全 pipeline 回归（原图 + VLM + Paddle）
cd character-service && local-rt/venv/bin/python3.11 eval/full_pipeline_regression.py --rounds 1

# 2. Q4 几何 replay（91 dump，生产基线 30/30）
python character-service/eval/_full_photo_replay.py

# 3. 单测
cd character-service && python -m unittest tests.test_geometry tests.test_stages

# 4. 重启服务
kill <pid>; cd character-service && nohup ./run.sh > /tmp/cs.log 2>&1 &
```
