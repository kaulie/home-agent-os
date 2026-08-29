-- Mac Edge local NetEase Cloud Music song catalog (not Brain brain.sqlite3).
-- Path: {MAC_EDGE_DATA_DIR}/ncm_songs.sqlite3

CREATE TABLE IF NOT EXISTS schema_migrations (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL
);

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

CREATE INDEX IF NOT EXISTS idx_ncm_songs_name_norm ON ncm_songs(name_norm);
CREATE INDEX IF NOT EXISTS idx_ncm_songs_artist_norm ON ncm_songs(artist_norm);
