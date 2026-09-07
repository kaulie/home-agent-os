-- Local BlackHole→mp3 capture catalog (one row per song).
-- complete = full duration; incomplete / recording = may overwrite on next play.

CREATE TABLE IF NOT EXISTS ncm_recordings (
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

CREATE INDEX IF NOT EXISTS idx_ncm_recordings_status
  ON ncm_recordings(status);
CREATE INDEX IF NOT EXISTS idx_ncm_recordings_name_norm
  ON ncm_recordings(song_name_norm);
CREATE INDEX IF NOT EXISTS idx_ncm_recordings_artist_norm
  ON ncm_recordings(artist_norm);
