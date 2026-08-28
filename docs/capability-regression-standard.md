# 能力回归测试标准流程（总览）

> **读者**：`@boss`、实现方、`@quality`、`@capability`  
> **分工**：本文 **L0–L2**（契约 + 插件单测 + 算法/composite）；**L3 黑盒按能力细则** 见 [`tests/blackbox/capability-regression.md`](tests/blackbox/capability-regression.md)（标准句、期望 plan、观察窗、通过标准 §2.1–2.25）。  
> **黑盒执行**：[`tests/blackbox/agent-brief.md`](tests/blackbox/agent-brief.md) · 用例编号 [`cases.md`](tests/blackbox/cases.md)

---

## 1. 四层模型

| 层 | 负责 | 测什么 | 不测什么 |
|----|------|--------|----------|
| **L0 契约** | `@capability` | `capability_ads` + `edge_services` / `services.py` 的 schema、kind、触发词 | Brain 规划 |
| **L1 插件单测** | `@capability` | plugin：resolved params → outputs / 失败 msg | 真机 I/O、Planner |
| **L2 组合 / 算法** | `@capability` | composite 展开；character-service 几何/OCR | 整单 intent 物流 |
| **L3 黑盒** | `@quality` | `POST /api/v1/intent` → `intent_detail` | 不改代码 |

**结案**：L0–L2 实现方自证；**对外验收必须 L3 交卷**（`log.md` + `report.md`）。不得只跑单测就报结案。

---

## 2. 改动后通用流程

```text
1. 改契约 → capability_ads + edge_services（+ mac/services.py）
2. 改 plugin → L1 单测（mac/tests/ 或 server/tests/）
3. composite / 识字算法 → L2
4. 本地 unittest 全绿
5. Chatbox @quality：用例 id + 环境 + 期望 plan
6. @quality 按 capability-regression.md §2 跑 L3
7. @coordinator 评审
```

**Asset**：identity 用 `asset_ref` / `capture_ref`，禁止 `photo_url` 作契约（[`asset-contract.md`](asset-contract.md)）。跑 `mac/tests/test_capability_asset_refs.py`。

**需 Edge 的黑盒**：runner POST URL 与 Edge `intentServerURL` 同一棵 Brain（见 agent-brief §双 Brain）。

---

## 3. L0–L2 标准命令

```bash
# L0
cd mac && python3 -m unittest tests.test_capability_descriptions tests.test_capability_asset_refs -q

# L1（按能力选文件，见 capability-regression.md §2 单测列）
cd mac && python3 -m unittest discover -s tests -p 'test_*.py' -q

# L2 识字
cd mac && python3 -m unittest tests.test_point_to_character_composite -q
cd character-service && python3 -m pytest tests/test_geometry.py tests/test_stages.py -q
cd character-service && python3 eval/_full_photo_replay.py
cd character-service && python3 eval/full_pipeline_regression.py --rounds 1
```

**L0 通过**：广告含 `planner_recognize` / `typical_triggers` / `do_not_dispatch`；schema 与 plugin 一致。

**L1 通过**：缺必填 → 可读失败；happy path 产出声明字段。

**L2 通过**：composite 最终 outputs 符合契约；识字 **Q4 几何 replay 0 回归**（改算法时记 [`ALGORITHM_CHANGELOG.md`](character-service/eval/ALGORITHM_CHANGELOG.md)）。

---

## 4. L3 黑盒（@quality 摘要）

细则与 **每种能力的标准句** 在 [`capability-regression.md`](tests/blackbox/capability-regression.md)：

- §1 通用 POST/detail 流程、四层验收口径、P0–P3 批次  
- §2.1–2.25 按能力：标准句、期望 plan、前置、观察窗、通过/负例  
- §3 冒烟 / 标准 / 全量套餐  

每条 case 材料清单见 agent-brief §4。交卷：`log.md`、`report.md`、`run_results_*.json`。

---

## 5. 新能力上线检查表

**@capability**

- [ ] ads + edge_services schema 与 plugin 一致  
- [ ] 无 path/URL 作 identity  
- [ ] L1（+ L2）单测通过  
- [ ] capability-regression.md §2 补一行标准句与通过标准  
- [ ] Chatbox `@quality` 派单  

**@quality**

- [ ] cases.md 或专项 md 有 case id  
- [ ] 按 capability-regression.md 跑 L3 并写 log  
- [ ] `@coordinator` 评审  

---

## 6. 当前缺口

| 能力 | case id（[`cases.md` §7](tests/blackbox/cases.md)） | 状态 |
|------|------------------------------------------------------|------|
| `document.scan` | **DS1** | 取消路径已跑；成功 `asset_ref` **待执行** |
| `image.ocr` | **OCR1** | case 已写；**待执行** |
| `capabilities.summary` | **CAP1** | case 已写；**待执行** |
| `climate.set` | **CL1** | case 已写；**待执行**（阻塞海信绑定） |
| `pronunciation.assess` | **P1–P3** | case 已有；**待执行** |
| IoT | **LT1 / AQ1 / LK1** | case 已写；P2 **待执行** |

`@quality` 交卷：[`tests/blackbox/report.md`](tests/blackbox/report.md) 2026-08-28 §7 case 补全。

---

## 7. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-08-28 | 初版：L0–L3 总览；按能力细则见 tests/blackbox/capability-regression.md |
| 2026-08-28 | `@quality`：§7 case id 补全（cases.md §7）；与 capability #72 对齐 |
