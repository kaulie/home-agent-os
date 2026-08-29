# Mac Edge `ncm_songs` SQLite（网易云本地歌曲库）

**范围：** Mac Edge 本机独立库，**不进** Brain `brain.sqlite3`。实现：`mac/sql/001_ncm_songs.sql`（+ `002` 若曾应用旧 001）+ `mac/src/mac_edge/ncm_songs/store.py`。

## 路径

| 项 | 值 |
|----|-----|
| 环境变量 | `MAC_EDGE_DATA_DIR`（与 Mac Edge 其它本机数据一致） |
| 默认目录 | `mac/data/` |
| 库文件 | `{MAC_EDGE_DATA_DIR}/ncm_songs.sqlite3` |

打开库：

```python
from mac_edge.ncm_songs import init_db, connect, db_path

init_db()          # 建表/迁移（幂等）
path = db_path()   # 当前文件路径
conn = connect()   # sqlite3.Connection（WAL）
```

CLI：`cd mac && python3 -m mac_edge.ncm_songs.store init`

## DDL

```sql
CREATE TABLE ncm_songs (
  original_id INTEGER PRIMARY KEY,
  encrypted_id TEXT NOT NULL,
  name TEXT NOT NULL,
  name_norm TEXT NOT NULL,
  artist TEXT,
  artist_norm TEXT NOT NULL DEFAULT '',
  record_json TEXT NOT NULL,
  played_at REAL
);

CREATE INDEX idx_ncm_songs_name_norm ON ncm_songs(name_norm);
CREATE INDEX idx_ncm_songs_artist_norm ON ncm_songs(artist_norm);
```

| 列 | 含义 |
|----|------|
| `original_id` | 网易云 `originalId`（INTEGER PK，upsert 键） |
| `encrypted_id` | search record 的 **`id`**（ncm-cli play 用） |
| `name` | 歌名原文 |
| `name_norm` | `normalize_text(name)` |
| `artist` | `artists[0].name` |
| `artist_norm` | `normalize_text(artist)` |
| `record_json` | 完整 search record（单行 JSON object） |
| `played_at` | 最近一次 play 成功，Unix **秒**；未播过 NULL |

`normalize_text`：trim → 空白折叠 → `casefold()`。

## 读写（`@capability`）

仅通过 `mac_edge.ncm_songs`，禁止 plugin 自开 path / 自写 SQL。

| 函数 | 用途 |
|------|------|
| `upsert_record(record, played_at=None)` | search 后写入；按 `originalId` upsert；保留已有 `played_at` |
| `get_song(original_id)` | 按 PK 读 |
| `find_by_name_artist(name=, artist=, limit=20)` | 按歌名/歌手查（内部 normalize） |
| `find_by_norm(name_norm=, artist_norm=, limit=20)` | 已规范化键查询 |
| `mark_played(original_id, at=None)` | play 成功后写 `played_at` |

### 流程

1. **本地命中**：`find_by_name_artist(song, artist)` 有行 → 用 `encrypted_id` 调 `ncm-cli play`，成功则 `mark_played`。
2. **未命中**：`ncm-cli search --keyword "整段关键词"` → 对选中 hit `upsert_record(hit)` → play → `mark_played`。
3. **pause/resume/stop/next/prev**：只调 ncm-cli，不必写库。

### record 必填字段

- `originalId`（或 `original_id`）→ `original_id`
- `id` → `encrypted_id`
- `name` → `name` / `name_norm`
- `artists[0].name` → `artist` / `artist_norm`（可无歌手）

缺字段 → `NcmSongsError`。

## 不在本期

- 不进 Brain
- 无 HTTP API
- 不调 ncm-cli（归 `@capability`）
