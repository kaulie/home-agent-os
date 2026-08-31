# Presentation 清理方案（循序渐进）

> **状态：** 方案待讨论（未开工）  
> **原则：** 小步、可回滚、每步可验收；**不**一次性抽包重写、**不**改对外 Intent API 大版本。  
> **关联：** [`presentation-io-symmetry.md`](../presentation-io-symmetry.md)、[`brain-complexity-refactor.md`](brain-complexity-refactor.md)（presentation/ 目录是远期，**本期不强制**）。

---

## 0. 一句话

Presentation **原则对、合同脏**。清理顺序是：**先钉住「对外长什么样」→ 再收 Brain 组装边角 → 再齐客户端 → 最后才考虑抽模块**。

---

## 1. 非目标（本期明确不做）

- 不重写 Planner prompt / 不改 capability 契约大面。
- 不把 Cast / `display.photo` 并进 presentation（点名上电视仍是计划步，正确）。
- 不一次拆出完整 `server/brain/presentation/`（可留到复杂度整改 P2+）。
- 不强迫 Legacy 立刻支持 `asset_ref` 图（可单独排期）。
- 不引入新的 presentation type（继续 `text | image | audio`）。

---

## 2. 目标态（冻结合约，渐进逼近）

对外（issuer Pull 看到的）`intent_detail.presentation` **规范形状**：

| 字段 | 规则 |
|------|------|
| `type` | 必填：`text` \| `image` \| `audio` |
| `from` | 必填：来源键（`answer_text` / `time_text` / `asset_ref` / `msg` / …） |
| 载荷 | `text`：**text/audio 有内容时必有**；`image`：优先 `asset_ref`，**不再新写** `image_url` |
| `endpoint` | **仅当用户点名目的地**时出现；Source Affinity 默认 **省略或稳定填 affinity id**（见开放问题） |
| `channel` | 降级为可选调试字段；客户端 **不得**依赖它做路由 |

仍允许内部短期保留废弃键，但 **assemble 出口** 不再写入 `image_url` / `photo_url` / `audio_url`（Brain 侧已大体如此，本方案是钉死 + 测）。

---

## 3. 分阶段（建议）

### P0 — 契约快照 + 回归钉（约 0.5～1 天）

**做什么**

1. 在 `server/tests/` 增加「presentation 出口形状」单测（不启全链路也行）：  
   - text：有 `type`/`from`/`text`  
   - image：有 `asset_ref.asset_id`，无 `image_url`  
   - failure：`from=msg` 且有 `text`  
   - **禁止** 出口出现「`from=answer_text` 却无 `text`」空壳（复现过的黑盒洞）
2. 黑盒清单加 2～3 条 assert（时间问句 / 简单问答 / 失败文案），只查顶层 presentation，不扩面。

**验收：** 单测绿；现有 happy path 不退化。  
**风险：** 极低。  
**谁：** `@brain` + `@quality` 补黑盒断言。

---

### P1 — Brain 组装「收口」不改路由语义（约 1～2 天）

**做什么**

1. `_apply_failure_presentation` / `assemble_presentation`：凡 `type=text|audio` 且判定「有内容」，强制写入非空 `text`（否则降级为失败文案或省略 presentation）。
2. 出口统一 strip：删除/不写 `image_url`、`photo_url`、`audio_url`（若仍有入站旧字段，只读迁移到 `asset_ref`/`text`，不写出）。
3. 日志：assemble 后若缺载荷打 `warning`（便于现场抓空壳）。
4. **暂不动** `_stamp_presentation_endpoint` 的大逻辑（避免亲和路由回归）；只加注释：`endpoint` 语义见开放问题。

**验收：** P0 测仍绿；黑盒 N 类问答无空壳 presentation。  
**风险：** 低；失败文案路径要盯一眼。  
**谁：** `@brain`。

---

### P2 — `endpoint` / `channel` 语义收紧（约 1～2 天，需拍板）

**二选一（讨论后定）：**

| 选项 | 行为 | 优点 | 缺点 |
|------|------|------|------|
| **A. 省略默认 endpoint** | Source Affinity 时不写 `endpoint`；仅点名目的地才写 | 对齐文档 | 依赖 endpoint 的旧脚本要改 |
| **B. 稳定 affinity id** | 始终写「该回谁」的 participant_id，且 **再 GET 不变空** | 调试友好 | 与「Planner 勿写 endpoint」字面不完全一致 |

建议默认 **B（稳定 id）+ 文档改一句**：*Brain 可盖亲和戳；Planner 仍勿因执行边写死 Cast 设备。*  
`channel`：停止用假默认 `iphone` 乱填；未知则省略。

**验收：** 同一 intent 连续 GET，`endpoint` 不闪空；无端上功能回归（Edge/Android 聊天本就不靠 channel）。  
**风险：** 中（要扫 Admin/脚本是否解析 endpoint）。  
**谁：** `@brain`；`@ui` 只做「若有依赖则跟着改」。

---

### P3 — 客户端对齐（小步，可拆 PR）（约 1～2 天）

**做什么**

1. **LivingRoomEdge / Android**：解析以 `asset_ref` + `text` 为准；`imageURL` 仅作只读兼容，不再作为主路径。  
2. 未识别的 `type`（`video`/`html`）：降级显示 `text` 或占位，不崩溃。  
3. **Legacy**：本阶段可只保证 `text`；图/音频明确「未支持」即可（另开任务）。  
4. Dev/Admin 若展示 presentation，跟同一形状，避免双标准。

**验收：** Edge 问答/出图与 Brain P1 出口一致；无解析崩溃。  
**谁：** `@ui`。

---

### P4 — 可选：代码搬家（延后）

仅当 P0–P3 稳了再做：把 `assemble_presentation` 等挪到 `server/brain/presentation/`（见复杂度整改）。**功能零变更**，纯搬迁 + 再导出。

**谁：** `@brain`；与复杂度整改排期合并，不单开紧急项。

---

## 4. 音频双路径（单独小项，可插在 P1 后）

现状：`type=audio` 常伴随 `_append_issuer_speak_step`（喇叭），Pull 端又可能当 text 显示。

**渐进建议（不一次拆干净）：**

1. 文档写清：客厅喇叭 = `notify.speak` 步；issuer 屏上摘要 = presentation `text`/`audio`。  
2. 若 presentation 为 audio 且无 `text`，assemble 时用同一句文案填 `text`（屏上可读）。  
3. **暂不**删除 speak 注入（避免客厅变哑）。

---

## 5. 顺序与依赖

```text
P0 契约测 ──► P1 组装收口 ──► P2 endpoint/channel（需拍板）
                │
                └─► 音频补 text（可选）
                         │
                         └─► P3 客户端
                                  │
                                  └─► P4 抽模块（可选、延后）
```

每阶段单独 commit，页脚 `agent: …`；阶段结束 `[release] stage=tested` 再进下一阶段。

---

## 6. 开放问题（拍板用）

1. P2 选 **A 省略** 还是 **B 稳定 affinity id**？（建议 B）  
2. Legacy 出图是否单独排期，还是长期只 text？  
3. P0 黑盒断言是否立刻加进 CI 门禁，还是先本地/质检手册？  
4. 是否要 `PRESENTATION_STRICT=1` 环境开关：缺载荷时直接失败 intent（默认关，避免一刀切）。

---

## 7. 建议拍板结论

- **先做 P0 + P1**（低风险、立刻减少空壳与废字段）。  
- P2 默认走 **B**。  
- P3 跟 Edge/Android；Legacy 图延后。  
- P4 并入 Brain 复杂度整改，不抢当前语音/拾音主线。

讨论定稿前 **不改代码**；定稿后按阶段派 `@brain` / `@quality` / `@ui`。
