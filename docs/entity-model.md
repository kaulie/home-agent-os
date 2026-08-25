# Home Agent Entity Model（一期）

> 动机长文见 `/Users/gaolei/devspace/home-agent-docs/entity_idea.md`。本文是 **V1 实现公约**：只建 Registry，先 Device。

## 1. 目标

回答：「家里有哪些值得系统持续认知的对象？」

一期交付：**Entity Registry（`type=device`）+ 最小 HTTP API**。  
不做 Event Stream、不做 Recipe/Session、不改规划器选边、不强制 Capability 绑定 Device。

## 2. 四层正交

| 概念 | 回答 | 一期 |
|------|------|------|
| Participant | 谁在线、什么 Role | 不变；Device 可 `references.participant_id` 指向承载节点 |
| Capability | 能做什么 | 不变；`associated_entity` **不进 wire**（二期可选） |
| Asset | 资源 `asset_id` | 不变；照片不是 Device |
| Entity | 世界对象锚点 | **本表 / 本 API** |

## 3. 字段

| 字段 | 说明 |
|------|------|
| `entity_id` | 稳定主键，如 `ent_dev_livingroom_ac` |
| `type` | V1 仅 `device` |
| `name` | 用户可理解名 |
| `metadata` | 稳定 JSON（room / vendor / …） |
| `state` | 动态 JSON，V1 可为空 `{}` |
| `references` | 可选关联（`participant_id`、`capability_ids[]`） |
| `created_at_ms` / `updated_at_ms` | Unix 毫秒 |

State / metadata / references **不做列展开**。

## 4. API

| 方法 | 路径 |
|------|------|
| `GET` | `/api/v1/entities?type=device` |
| `GET` | `/api/v1/entities/{entity_id}` |
| `PUT` | `/api/v1/entities/{entity_id}`（管理 upsert / seed） |

`PUT` 给管理与 seed，**不是** capability 私自 invent 世界对象。

## 5. Seed（少而真）

迁移 `016_entities.sql` 写入现网已能作用的客厅对象：空调、大灯、GoPro、电视。禁止虚构离线设备。

## 6. 明确不做（一期）

- 不改 Participant / Asset Contract
- 不把 Entity 列表塞进规划器
- 不做 Event → state reducer
- 不做 App Capability↔Device 双视图

## 7. Schema

见 [`docs/db-schema.md`](db-schema.md) `entities` 节；迁移 `server/sql/016_entities.sql`。
