# Brain schema

正式合同：[`docs/db-schema.md`](../docs/db-schema.md)。

实现：`sql/*.sql` + `db.py`。空库：`python3 db.py init` → `server/data/brain.sqlite3`（或 `BRAIN_DB_PATH`）。

现行表：`meta`、`jobs`、`participants`、`intent_reviews`、`assets`、`asset_grants`、`schema_migrations`。只有 PRIMARY KEY，无二级索引。wire 仍用 `edge_id`。Asset 身份是 `asset_id`；步间只传 `asset_ref`，禁止 `photo_url`。
