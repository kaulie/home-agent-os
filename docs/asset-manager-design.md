# Asset Manager 设计（Mac Edge Runtime + Brain 资产表）

> **状态：** Design v2（2026-08-19，用户定稿）  
> **Owner：** `@runtime`（Edge Asset Manager + Brain 注册 API 消费方）  
> **Schema：** `@dba`（`assets` 表 + 迁移）  
> **规划 / presentation：** `@brain`（`AssetRef` 步间传递、`presentation.from=asset_ref`）  
> **Plugin 契约：** `@capability`（入参/产出改为 `asset_ref`，禁止 `photo_url`）  
> **上位公约：** [`asset-contract.md`](asset-contract.md)

## 0. 用户定稿（2026-08-19）

1. **Asset 需要新加表** — Brain SQLite  Canonical 注册表（不是 Edge 本地 JSON 为主）。
2. **不要写兼容逻辑** — 禁止 `photo_url` 双写、deprecated 字段、legacy hydrate、`$photo_url` 透明转换。
3. **按新协议设计** — 步间只传 **`AssetRef`**；跨 intent 引用也用 **`AssetRef`**（后续阶段再做，不在 MVP 挡路）。

此前 v1 中「P1 双写 `photo_url` + `photo_asset`」**作废**。

---

## 1. 问题与目标

现网用 `photo_url` 当 identity，违反 Asset Contract。目标：

| 层 | 改什么 |
|----|--------|
| **Identity** | `asset_id` + `type`（`AssetRef`） |
| **Storage** | Runtime 后端持有 blob；Brain 表只存 **locator + metadata**，不存 URL 当 id |
| **步间** | `output_constrict` / `input_constrict` / `ctx_param` 用 **`asset_ref`** |
| **Capability** | 契约声明 `asset_ref`；Runtime 在 execute 前 **resolve → representation**（本地 path / 临时 URL），**不**把 URL 写回 step_outputs |
| **Presentation** | Brain `presentation.from=asset_ref`；Endpoint 侧再 resolve（归 `@brain` / `@intent`） |

**MVP 范围：** 单 intent 内 producer → consumer；**跨 intent 的 AssetRef 引用**列为 Phase 2（表与 grant 模型预留，不实现）。

---

## 2. 架构

```text
Producer Capability（持有 CapAsset SDK）
       │  upload blob → asset.register_*() → AssetRef
       ▼
Brain SQLite  assets 表  ← canonical identity
       │
       │  AssetRef in step_outputs / ctx_param
       ▼
Consumer Capability（持有 CapAsset SDK）
       │  ref = asset.require_ref(params)
       │  url = asset.http_url(ref)   ← representation 仅本步内部
       ▼
Capability 业务逻辑（Cast / Vision API …）
```

**分工：**

| 组件 | 职责 |
|------|------|
| **`assets` 表（Brain）** | `asset_id`、type、status、producer、storage locator JSON、lifecycle |
| **`CapAsset`（Runtime SDK）** | 面向 Capability 的 Asset Manager 会话：register / resolve / grant 校验 |
| **Capability Plugin** | **知道** Asset Manager；自己 resolve/register；params 不含 `photo_url` identity |
| **Executor** | 构造 `CapAsset` 传入 `_execute_capability(cap, asset, …)`；**不**偷偷改写 AssetRef |
| **Brain `assemble_presentation`** | `from=asset_ref` 时查表或 intent context，填 `presentation.asset_ref`（非 `image_url`） |

---

## 3. 核心类型

### 3.1 AssetRef（唯一对外引用）

```json
{
  "asset_id": "asset_01JABC...",
  "type": "image",
  "mime_type": "image/jpeg"
}
```

- 出现在：`step_outputs`、`ctx_param`、planner `input_constrict` 的 `$var` 目标字段。
- **禁止** `url`、`path`、`photo_url`。

### 3.2 StorageLocator（仅 Brain `assets.storage` JSON + Edge 内存）

```json
{
  "backend": "img_server",
  "key": "f69d2920_20260818_230023_GOPR1171.JPG",
  "edge_id": "edge-node-x0OjfixA"
}
```

不暴露给 Capability；Consumer 通过 `AssetManager.resolve()` 获取 representation。

### 3.3 Representation（Runtime 内部，不进 step_outputs）

- `LocalFileRepresentation` — OCR / 本地 ML
- `HttpUrlRepresentation` — Cast、外部 vision API（**临时**，有 TTL）

---

## 4. Brain：`assets` 表（ `@dba` 落地）

遵循 [`db-schema.md`](db-schema.md) 原则：标量列 + JSON 列；**不加二级索引**；迁移在 `server/sql/`。

### 4.1 表 `assets`

| 列 | 类型 | 说明 |
|----|------|------|
| `asset_id` | TEXT PK | `asset_` + ULID |
| `type` | TEXT | image / video / audio / text / document / other |
| `mime_type` | TEXT | 可空 |
| `status` | TEXT | available / pending / expired / deleted |
| `producer_capability` | TEXT | 如 camera.capture |
| `producer_edge_id` | TEXT | participant_id |
| `origin_intent_id` | TEXT | 创建时所属 intent（可空） |
| `origin_step` | INTEGER | 可空 |
| `size_bytes` | INTEGER | 可空 |
| `metadata` | TEXT | JSON，公开描述（宽高等） |
| `storage` | TEXT | JSON StorageLocator（内部） |
| `created_at` | REAL | Unix 秒 |
| `updated_at` | REAL | Unix 秒 |
| `expires_at` | REAL | 可空 |

### 4.2 表 `asset_grants`（intent 内访问，MVP）

| 列 | 类型 | 说明 |
|----|------|------|
| `asset_id` | TEXT | PK 之一 |
| `intent_id` | TEXT | PK 之一 |
| `granted_at` | REAL | |

- Producer 注册时自动 grant `(asset_id, origin_intent_id)`。
- Consumer 步 resolve 前校验存在 grant。
- **跨 intent：** Phase 2 扩展 grant 或显式 `asset_ref` 引用策略（用户说可后做）；MVP 不实现。

### 4.3 API（Brain，`@brain` + `@dba` 评审）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/assets` | Edge 注册；body 含 type、storage、producer、origin_intent_id/step |
| GET | `/api/v1/assets/{asset_id}` | 元数据 + storage（**仅 Runtime 凭证**，不对 Intent Source 开放） |
| POST | `/api/v1/assets/{asset_id}/grant` | 预留；Phase 2 跨 intent |

`intent_detail` / GET intent 对外快照 **只暴露 `AssetRef` 形状**，不暴露 `storage` JSON。

---

## 5. Edge AssetManager

模块：`mac/src/mac_edge/asset/`

```python
class AssetManager:
    def register_local_file(...) -> AssetRef:
        """写 backend → POST Brain assets → grant origin intent."""

    def register_storage_locator(...) -> AssetRef:
        """blob 已在 img_server 等；只登记 Brain。"""

    def resolve_for_capability(
        self,
        ref: AssetRef,
        *,
        intent_id: str,
        need: Literal["local_path", "http_url"],
    ) -> LocalFileRepresentation | HttpUrlRepresentation:
        """校验 grant；失败 → AssetAccessDenied / Pending。"""

    def sweep_expired(self) -> int: ...
```

- **无** `photo_url` 字段处理。
- **无** `MAC_EDGE_ASSET_COMPAT_*` 配置。
- Edge 可保留 `{data_dir}/assets/` 作 blob 缓存，**不以 JSON ledger 为 canonical**（Brain 表为准）。

---

## 6. Executor / Capability SDK（新协议）

### 6.1 原则

**Asset Manager 是 Runtime 提供给 Capability 的 SDK 能力**，不是 executor 偷偷改 params 的黑盒。

```text
_execute_capability(cap, asset, *, params, config)
```

- ``asset``：本步 `CapAsset`（绑定 `AssetManager` + `intent_id` + `step_num`）
- ``params``：非资产字段 + **AssetRef 身份**（`image_ref` / `capture_ref` / `image_refs`）
- **禁止** executor 把 AssetRef 预解成 `photo_url` 再塞进 params
- Capability **自己**调用 `asset.http_url(ref)` / `asset.register_*`

### 6.2 产出

- Producer（如 `camera.capture`）上传 blob 后 `asset.register_from_upload_url(...)` → 只写 `capture_ref`
- `post_step_status.outputs` 示例：

```json
{
  "capture_ref": {
    "asset_id": "asset_01J...",
    "type": "image",
    "mime_type": "image/jpeg"
  }
}
```

### 6.3 消费

- Planner：`input_constrict`: `{ "image_ref": "$capture_ref" }`
- Hydrate：`$capture_ref` → context 中 AssetRef JSON（身份）
- Capability：`ref = asset.require_ref(params)` → `url = asset.http_url(ref)`（representation 仅本步内部）

### 6.4 前序门

- `should_wait_for_unresolved(plan, step, "capture_ref")`：producer 步 RUNNING → wait
- 缺 ref 且无 producer → **fail**

---

## 7. Capability / Brain 契约变更（协调清单）

| 能力 | 旧 | 新 |
|------|----|----|
| camera.capture | output `photo_url` | output `capture_ref` : AssetRef |
| vision.perceive / vision.ask | input `photo_url` | input `image_ref` : AssetRef（Runtime resolve 后调 API） |
| display.photo / slideshow | input `photo_url(s)` | input `image_ref` / `image_refs` : AssetRef |
| query.content（生图） | output `photo_url` | output `image_ref` : AssetRef |
| Brain presentation | `from=photo_url`, `image_url` | `from=asset_ref`, `presentation.asset_ref` |
| Planner hydrate | `$photo_url` | `$capture_ref` 等 |

**一次性切换**，不保留旧字段。黑盒用例由 `@quality` 更新。

---

## 8. 分期

| 阶段 | 内容 | Owner |
|------|------|-------|
| **D1** | 本文档 + `@dba` 建表迁移 + Brain POST/GET assets | @dba @brain |
| **D2** | Edge AssetManager + register/resolve；executor 接线 | @runtime |
| **D3** | Plugin + manifest 改 `asset_ref`；Brain planner/presentation | @capability @brain |
| **D4** | 跨 intent AssetRef + grant 扩展 | @runtime @brain |
| **D5** | Endpoint 从 `asset_ref` render | @intent @brain |

MVP = **D1 + D2 + D3（单 intent）**。

---

## 9. 权限

- **MVP：** `asset_grants(asset_id, intent_id)` — 仅同 intent。
- **Phase 2（跨 intent）：** 显式 AssetRef 出现在 planner/context；grant 扩展或引用即授权（设计待定，用户允后续再做）。

---

## 10. 目录结构

```text
mac/src/mac_edge/asset/
  types.py          # 已有 AssetRef
  manager.py
  brain_client.py   # POST/GET /api/v1/assets
  runtime.py        # resolve_inputs / register_outputs
  backends/
    local_dir.py
    img_server.py

server/sql/00N_assets.sql   # @dba
server/home_brain.py        # assets routes + assemble from asset_ref  # @brain
```

---

## 11. 测试

- `@dba`：迁移、register/get round-trip
- `@runtime`：register → grant → resolve；无 grant 拒绝
- `@quality`：拍照 → perceive → presentation 全链路 **仅 AssetRef**，无 `photo_url`

---

## 12. 开放项（信箱对齐）

1. **`@dba`**：`assets` / `asset_grants` DDL 与迁移编号。
2. **`@brain`**：planner prompt、`assemble_presentation` 改 `asset_ref`；是否 intent_detail 顶层 `presentation.asset_ref`。
3. **`@capability`**：各 plugin manifest 字段 rename 与 executor 注册点（upload 收进 Runtime）。
4. **`@intent`**：Endpoint 何时 resolve `asset_ref` → 像素（D5）。

---

## 13. 一句话

**Canonical 身份在 Brain `assets` 表；步间只传 `AssetRef`；Runtime 负责 blob 与 representation；不写任何 `photo_url` 兼容层；跨 intent 引用 Phase 2 再做。**
