# Mac Edge `ncm_songs` SQLite（网易云本地歌曲库）

**范围：** Mac Edge 本机独立库，**不进** Brain `brain.sqlite3`。实现：`mac/sql/001_ncm_songs.sql`（+ `002` 若曾应用旧 001）+ `mac/sql/003_ncm_song_index.sql` + `mac/sql/004_ncm_timestamps.sql` + `mac/sql/005_ncm_surrogate_pk.sql` + `mac/sql/006_ncm_plays.sql` + `mac/sql/007_ncm_recordings.sql` + `mac/src/mac_edge/ncm_songs/store.py`。

## 路径

| 项 | 值 |
|----|-----|
| 环境变量 | `MAC_EDGE_DATA_DIR`（与 Mac Edge 其它本机数据一致） |
| 默认目录 | `mac/data/` |
| 库文件 | `{MAC_EDGE_DATA_DIR}/ncm_songs.sqlite3` |

同一 sqlite 文件里四张表：**`ncm_songs`**（完整 dump）+ **`ncm_song_index`**（精确索引）+ **`ncm_plays`**（意图播放日志）+ **`ncm_recordings`**（BlackHole 录音目录）。不另开第二个库文件。

打开库：

```python
from mac_edge.ncm_songs import init_db, connect, db_path

init_db()          # 建表/迁移（幂等）
path = db_path()   # 当前文件路径
conn = connect()   # sqlite3.Connection（WAL）
```

CLI：`cd mac && python3 -m mac_edge.ncm_songs.store init`

## 表：`ncm_songs`（完整备份，insert-only）

保留 search record 原文（`record_json` blob）。**不要 drop / 替换。** 网易云 metadata 不随时间改；**首次 INSERT 胜出**，后续 `ON CONFLICT(original_id) DO NOTHING`。

`005` 起本机自增 `id` 为主键；`original_id` 仍是 UNIQUE upsert 键。

```sql
CREATE TABLE ncm_songs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  original_id INTEGER NOT NULL UNIQUE,
  encrypted_id TEXT NOT NULL,
  name TEXT NOT NULL,
  name_norm TEXT NOT NULL,
  artist TEXT,
  artist_norm TEXT NOT NULL DEFAULT '',
  record_json TEXT NOT NULL,
  played_at REAL,
  create_time REAL,
  update_time REAL
);
```

| 列 | 含义 |
|----|------|
| `id` | 本机自增主键 |
| `original_id` | 网易云 `originalId`（UNIQUE，upsert 键） |
| `encrypted_id` | search record 的 **`id`**（ncm-cli play 用） |
| `name` | 歌名原文 |
| `name_norm` | `normalize_text(name)` |
| `artist` | `artists[0].name` |
| `artist_norm` | `normalize_text(artist)` |
| `record_json` | 完整 search record（单行 JSON object） |
| `played_at` | 遗留列；新写入恒为 NULL。播放历史在 `ncm_plays` |
| `create_time` | 首次写入，Unix **秒**；冲突忽略后不改 |
| `update_time` | 首次写入；冲突忽略后不改 |

`normalize_text`：trim → 空白折叠 → `casefold()`。

## 表：`ncm_song_index`（精确索引，insert-only）

**为何叫 `ncm_song_index`：** 这是面向「歌名 / 歌手 / 专辑 id 精确命中」的投影表，**不存** `record_json`。`ncm_songs` 继续当全量备份；`ncm_tracks` 容易被理解成第二份曲库，所以不用。一行一首；本机 `id` 自增主键，`song_original_id` 唯一。同样 **首次 INSERT 胜出**。

`003` 迁移会从已有 `ncm_songs.record_json` backfill；缺字段保持 NULL，不编造 id。

```sql
CREATE TABLE ncm_song_index (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  song_original_id INTEGER NOT NULL UNIQUE,
  song_name TEXT NOT NULL,
  song_name_norm TEXT NOT NULL,
  song_encrypted_id TEXT,
  duration INTEGER,
  artist TEXT,
  artist_norm TEXT NOT NULL DEFAULT '',
  album_original_id INTEGER,
  album_name TEXT,
  album_encrypted_id TEXT,
  create_time REAL,
  update_time REAL
);
```

| 列 | 类型 | 来源（ncm-cli search record） |
|----|------|------------------------------|
| `id` | INTEGER PK 自增 | 本机主键 |
| `song_original_id` | INTEGER UNIQUE | `originalId` |
| `song_name` | TEXT | `name` |
| `song_name_norm` | TEXT | `normalize_text(name)`（查找用，非产品列） |
| `song_encrypted_id` | TEXT | `id` |
| `duration` | INTEGER 毫秒 | `duration`（ncm-cli 已是 ms，如十年=205423） |
| `artist` | TEXT | `artists[0].name` |
| `artist_norm` | TEXT | `normalize_text(artist)` |
| `album_original_id` | INTEGER | `album.originalId`（`album` 为 object 时） |
| `album_name` | TEXT | `album.name`；若 `album` 是字符串则整段当名称 |
| `album_encrypted_id` | TEXT | `album.id` |
| `create_time` | REAL Unix 秒 | 首次写入；冲突忽略后不改 |
| `update_time` | REAL Unix 秒 | 首次写入；冲突忽略后不改 |

缺字段 → NULL，**禁止编造**。索引表 **不复制** `record_json`。

## 表：`ncm_plays`（意图播放日志，append-only）

谁在什么意图下点了哪首歌。只记 **`music.play` 命中用户意图的那一首**；不记 `music.next` / prev，也不记 ncm-cli 播完自动下一首。

`participant_id` 是 Intent Source（发出端），不是 Mac 执行边。Brain 在 `do_execution_plan` 把 issuer 填进 `music.play` 的 `input_constrict`（`source_context.input_participant_id` / `device_id`，否则 `edge_id`）。Plugin 只读本步 params，缺 `participant_id` 则跳过本行并打 warning。

```sql
CREATE TABLE ncm_plays (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  song_original_id INTEGER NOT NULL,
  participant_id TEXT NOT NULL,
  intent_id TEXT,
  played_at REAL NOT NULL
);
```

| 列 | 含义 |
|----|------|
| `id` | 本机自增主键 |
| `song_original_id` | 命中的网易云 `originalId` |
| `participant_id` | 发出这条意图的 participant |
| `intent_id` | Brain intent id（可选） |
| `played_at` | 本条 play 成功时刻，Unix **秒** |

## 表：`ncm_recordings`（BlackHole 录音目录）

`music.play` 旁路录音（`ncm_play_record`）的索引。按 `song_original_id` 唯一；**录完整不再重录**，未完整可覆盖同路径 mp3。

```sql
CREATE TABLE ncm_recordings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  song_original_id INTEGER NOT NULL UNIQUE,
  song_encrypted_id TEXT,
  song_name TEXT NOT NULL,
  song_name_norm TEXT NOT NULL,
  artist TEXT,
  artist_norm TEXT NOT NULL DEFAULT '',
  duration_ms INTEGER,
  path TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('recording', 'complete', 'incomplete')),
  create_time REAL,
  update_time REAL
);
```

| status | 含义 | 再播 |
|--------|------|------|
| `complete` | 按时长定时器正常结束 | 跳过（文件仍在） |
| `incomplete` | stop / next / prev 提前停 | 可覆盖重录 |
| `recording` | 进行中或崩溃残留 | 可覆盖；启动时 `abandon_stale_recordings` 标成 incomplete |

## 读写（`@capability`）

仅通过 `mac_edge.ncm_songs`，禁止 plugin 自开 path / 自写 SQL。

| 函数 | 用途 |
|------|------|
| `upsert_record(record)` | 写入 **两张目录表**；按 `originalId` **INSERT OR IGNORE**。搜索命中的 10 首都会写；已有行不改 |
| `get_song(original_id)` | 读备份表 |
| `get_index_song(original_id)` | 读索引表 |
| `find_by_name_artist(name=, artist=, limit=20)` | 精确歌名/歌手：先 `ncm_song_index`，再 hydrate `ncm_songs`；index 未命中则回退 `ncm_songs` |
| `find_by_norm(name_norm=, artist_norm=, limit=20)` | 已规范化键，同上 |
| `find_index_by_name_artist` / `find_index_by_norm` | 只查索引表（cache hit 优先） |
| `record_play(original_id, participant_id, intent_id=, at=)` | `music.play` 成功后追加 `ncm_plays`；目录行不变 |
| `list_recent_played(limit=20)` | 最近意图播放（`ncm_plays`，新→旧） |
| `get_recording` / `recording_is_complete` / `upsert_recording_started` / `mark_recording_*` | 录音表读写与状态 |
| `abandon_stale_recordings()` | 把残留 `recording` 标成 `incomplete` |

### 流程

1. **本地命中**：`find_index_by_name_artist(song, artist)` 有行 → 用 `song_encrypted_id` 调 `ncm-cli play`；否则回退 `find_by_name_artist` 的 `record.id`。成功则 `upsert_record`（已有则忽略）+ `record_play`。
2. **未命中**：`ncm-cli search song --keyword … --limit 10`（可选 `--userInput`）→ **10 首全部 upsert** 进两表 → 歌名与关键字完全相同则播该首，否则按相同字数（字符多重集交集）选最高分 → play 成功再 `record_play`（只记播出的那首）。
3. **pause/resume/stop/next/prev**：只调 ncm-cli，不写 `ncm_plays`。
4. **music.cache**：只 upsert 索引，不 play、不写 `ncm_plays`。

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
