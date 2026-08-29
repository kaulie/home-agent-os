# Mac Edge `ncm_songs` SQLite（网易云本地歌曲库）

**范围：** Mac Edge 本机独立库，**不进** Brain `brain.sqlite3`。实现：`mac/sql/001_ncm_songs.sql` + `mac/src/mac_edge/ncm_songs/store.py`。

## 路径

| 项 | 值 |
|----|-----|
| 环境变量 | `MAC_EDGE_DATA_DIR`（与 Mac Edge 其它本机数据一致） |
| 默认目录 | `mac/data/` |
| 库文件 | `{MAC_EDGE_DATA_DIR}/ncm_songs.sqlite3` |

初始化（空库建表）：

```bash
cd mac && python3 -m mac_edge.ncm_songs.store init
# 或代码：from mac_edge.ncm_songs import init_db; init_db()
```

## DDL

```sql
CREATE TABLE schema_migrations (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL
);

CREATE TABLE ncm_songs (
  original_id TEXT PRIMARY KEY,
  encrypted_id TEXT,
  name_norm TEXT NOT NULL DEFAULT '',
  artist_norm TEXT NOT NULL DEFAULT '',
  record_json TEXT NOT NULL,
  played_at REAL,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
```

- `original_id`：网易云歌曲稳定 id（upsert 主键）。从 search record 的 `original_id` / `originalId` / `id` / `songId` 提取。
- `encrypted_id`：播放用加密 id（`encrypted_id` / `encryptedId` / `enc_id`）。
- `name_norm` / `artist_norm`：经 `normalize_text()`（trim、空白折叠、`casefold`）后的检索键。
- `record_json`：**完整** ncm-cli search record（单行 JSON object，禁止双重编码）。
- `played_at`：最近一次成功播放，Unix **秒** 浮点；未播过为 NULL。
- `created_at` / `updated_at`：Unix **秒** 浮点。

引擎：`journal_mode=WAL`，`foreign_keys=ON`，`busy_timeout=5000`。

## 读写约定（`@capability`）

仅通过 `mac_edge.ncm_songs` 模块访问，**禁止** plugin 直连 path / 自写 SQL。

| 函数 | 用途 |
|------|------|
| `init_db()` | 建库/迁移（幂等） |
| `db_path()` | 当前库路径 |
| `normalize_text(s)` | 歌名/歌手规范化（写入与查询共用） |
| `upsert_record(record, played_at=None)` | search 后写入；按 `original_id` upsert；`played_at` 可选，默认保留旧值 |
| `get_song(original_id)` | 按主键读一行（含解析后的 `record` dict） |
| `find_by_norm(name_norm=, artist_norm=, limit=20)` | 本地库按规范化歌名/歌手查（可只传其一） |
| `mark_played(original_id, at=None)` | 播放成功后更新 `played_at`（行必须已存在） |
| `list_library(limit=100, offset=0)` | 按 `updated_at` 倒序 |
| `list_recent_played(limit=20)` | 按 `played_at` 倒序 |

### 推荐流程

1. **search**：`ncm-cli search --keyword "…"`（整段关键词加引号）→ 对每条 hit 调 `upsert_record(hit)`。
2. **play**：`get_song` / `find_by_norm` 取 `encrypted_id`（或 `record` 内字段）→ `ncm-cli play` → 成功则 `mark_played(original_id)`。
3. **pause/resume/stop/next/prev**：只调 ncm-cli，**不必**写库（除非业务要记状态）。

### record 字段提取（实现已内置）

| 列 | search record 候选键 |
|----|----------------------|
| `original_id` | `original_id`, `originalId`, `id`, `songId`, `song_id` |
| `encrypted_id` | `encrypted_id`, `encryptedId`, `enc_id`, `encId` |
| 歌名 | `name`, `songName`, `song_name`, `title` |
| 歌手 | `artist`, `artistName`, `artists[]`, `ar[]` |

缺 `original_id` → `NcmSongsError`。

## 不在本期

- 不进 Brain `assets` / `jobs`
- 无 HTTP API；仅 Mac Edge 进程内读写
- 无二级索引（一期 PRIMARY KEY only）
