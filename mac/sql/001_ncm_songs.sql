-- Mac Edge local NetEase Cloud Music song catalog (not Brain brain.sqlite3).
-- Path: {MAC_EDGE_DATA_DIR}/ncm_songs.sqlite3

CREATE TABLE IF NOT EXISTS schema_migrations (
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
