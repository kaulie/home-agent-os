# Mac Edge `ncm_songs` SQLite（网易云本地歌曲库）

**范围：** Mac Edge 本机独立库，**不进** Brain `brain.sqlite3`。实现：`mac/sql/001_ncm_songs.sql`（+ `002` 若曾应用旧 001）+ `mac/sql/003_ncm_song_index.sql` + `mac/src/mac_edge/ncm_songs/store.py`。

## 路径

| 项 | 值 |
|----|-----|
| 环境变量 | `MAC_EDGE_DATA_DIR`（与 Mac Edge 其它本机数据一致） |
| 默认目录 | `mac/data/` |
| 库文件 | `{MAC_EDGE_DATA_DIR}/ncm_songs.sqlite3` |

同一 sqlite 文件里两张表：**`ncm_songs`**（完整 dump）+ **`ncm_song_index`**（精确索引）。不另开第二个库文件。

打开库：

```python
from mac_edge.ncm_songs import init_db, connect, db_path

init_db()          # 建表/迁移（幂等）
path = db_path()   # 当前文件路径
conn = connect()   # sqlite3.Connection（WAL）
```

CLI：`cd mac && python3 -m mac_edge.ncm_songs.store init`

## 表：`ncm_songs`（完整备份）

保留 search record 原文（`record_json` blob）。**不要 drop / 替换。**

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

## 表：`ncm_song_index`（精确索引）

**为何叫 `ncm_song_index`：** 这是面向「歌名 / 歌手 / 专辑 id 精确命中」的投影表，**不存** `record_json`。`ncm_songs` 继续当全量备份；`ncm_tracks` 容易被理解成第二份曲库，所以不用。一行一首，`song_original_id` 即 PK。

`003` 迁移会从已有 `ncm_songs.record_json` backfill；缺字段保持 NULL，不编造 id。

```sql
CREATE TABLE ncm_song_index (
  song_original_id INTEGER PRIMARY KEY,
  song_name TEXT NOT NULL,
  song_name_norm TEXT NOT NULL,
  song_encrypted_id TEXT,
  duration INTEGER,
  artist TEXT,
  artist_norm TEXT NOT NULL DEFAULT '',
  album_original_id INTEGER,
  album_name TEXT,
  album_encrypted_id TEXT
);

CREATE INDEX idx_ncm_song_index_song_name ON ncm_song_index(song_name);
CREATE INDEX idx_ncm_song_index_artist ON ncm_song_index(artist);
CREATE INDEX idx_ncm_song_index_album_original_id ON ncm_song_index(album_original_id);
CREATE INDEX idx_ncm_song_index_song_name_norm ON ncm_song_index(song_name_norm);
CREATE INDEX idx_ncm_song_index_name_artist ON ncm_song_index(song_name_norm, artist_norm);
```

| 列 | 类型 | 来源（ncm-cli search record） |
|----|------|------------------------------|
| `song_original_id` | INTEGER PK | `originalId` |
| `song_name` | TEXT | `name` |
| `song_name_norm` | TEXT | `normalize_text(name)`（查找用，非产品列） |
| `song_encrypted_id` | TEXT | `id` |
| `duration` | INTEGER 毫秒 | `duration`（ncm-cli 已是 ms，如十年=205423） |
| `artist` | TEXT | `artists[0].name` |
| `artist_norm` | TEXT | `normalize_text(artist)` |
| `album_original_id` | INTEGER | `album.originalId`（`album` 为 object 时） |
| `album_name` | TEXT | `album.name`；若 `album` 是字符串则整段当名称 |
| `album_encrypted_id` | TEXT | `album.id` |

缺字段 → NULL，**禁止编造**。索引表 **不复制** `record_json`。

## 读写（`@capability`）

仅通过 `mac_edge.ncm_songs`，禁止 plugin 自开 path / 自写 SQL。

| 函数 | 用途 |
|------|------|
| `upsert_record(record, played_at=None)` | play 成功后写入 **两张表**；按 `originalId` upsert；`ncm_songs.played_at` 保留已有值；index 可选列用 `COALESCE` 避免空值覆盖 |
| `get_song(original_id)` | 读备份表 |
| `get_index_song(original_id)` | 读索引表 |
| `find_by_name_artist(name=, artist=, limit=20)` | 精确歌名/歌手：先 `ncm_song_index`，再 hydrate `ncm_songs`；index 未命中则回退 `ncm_songs` |
| `find_by_norm(name_norm=, artist_norm=, limit=20)` | 已规范化键，同上 |
| `find_index_by_name_artist` / `find_index_by_norm` | 只查索引表（cache hit 优先） |
| `mark_played(original_id, at=None)` | play 成功后写 `ncm_songs.played_at` |

### 流程

1. **本地命中**：`find_index_by_name_artist(song, artist)` 有行 → 用 `song_encrypted_id` 调 `ncm-cli play`；否则回退 `find_by_name_artist` 的 `record.id`。成功则 `upsert_record` + `mark_played`（两表都写）。
2. **未命中**：`ncm-cli search --keyword "整段关键词"`（可选 `--userInput`）→ play → 成功后 `upsert_record(hit)` → `mark_played`。
3. **pause/resume/stop/next/prev**：只调 ncm-cli，不必写库。

### record 必填字段（备份表）

- `originalId`（或 `original_id`）→ `original_id` / `song_original_id`
- `id` → `encrypted_id` / `song_encrypted_id`
- `name` → `name` / `song_name`
- `artists[0].name` → `artist`（可无歌手）

缺必填 → `NcmSongsError`。`duration` / album 字段可选。

## 不在本期

- 不进 Brain
- 无 HTTP API
- 不调 ncm-cli（归 `@capability`）
- 不另开第二个 sqlite 文件
