-- Exact-lookup projection of ncm-cli play hits.
-- ncm_songs stays the full backup (record_json blob). Same sqlite file.

CREATE TABLE IF NOT EXISTS ncm_song_index (
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

CREATE INDEX IF NOT EXISTS idx_ncm_song_index_song_name
  ON ncm_song_index(song_name);
CREATE INDEX IF NOT EXISTS idx_ncm_song_index_artist
  ON ncm_song_index(artist);
CREATE INDEX IF NOT EXISTS idx_ncm_song_index_album_original_id
  ON ncm_song_index(album_original_id);
CREATE INDEX IF NOT EXISTS idx_ncm_song_index_song_name_norm
  ON ncm_song_index(song_name_norm);
CREATE INDEX IF NOT EXISTS idx_ncm_song_index_name_artist
  ON ncm_song_index(song_name_norm, artist_norm);

-- Backfill from existing ncm_songs dump. Missing album/duration stay NULL.
INSERT OR IGNORE INTO ncm_song_index (
  song_original_id,
  song_name,
  song_name_norm,
  song_encrypted_id,
  duration,
  artist,
  artist_norm,
  album_original_id,
  album_name,
  album_encrypted_id
)
SELECT
  original_id,
  name,
  name_norm,
  encrypted_id,
  CAST(json_extract(record_json, '$.duration') AS INTEGER),
  artist,
  artist_norm,
  CASE
    WHEN json_type(record_json, '$.album') = 'object'
      AND json_extract(record_json, '$.album.originalId') IS NOT NULL
    THEN CAST(json_extract(record_json, '$.album.originalId') AS INTEGER)
    ELSE NULL
  END,
  CASE
    WHEN json_type(record_json, '$.album') = 'object'
    THEN json_extract(record_json, '$.album.name')
    WHEN json_type(record_json, '$.album') = 'text'
    THEN json_extract(record_json, '$.album')
    ELSE NULL
  END,
  CASE
    WHEN json_type(record_json, '$.album') = 'object'
    THEN json_extract(record_json, '$.album.id')
    ELSE NULL
  END
FROM ncm_songs;
