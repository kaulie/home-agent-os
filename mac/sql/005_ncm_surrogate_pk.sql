-- Surrogate INTEGER PRIMARY KEY id (AUTOINCREMENT) on both catalog tables.
-- original_id / song_original_id remain UNIQUE upsert keys (NetEase originalId).

CREATE TABLE ncm_songs_005 (
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

INSERT INTO ncm_songs_005 (
  original_id, encrypted_id, name, name_norm, artist, artist_norm,
  record_json, played_at, create_time, update_time
)
SELECT
  original_id, encrypted_id, name, name_norm, artist, artist_norm,
  record_json, played_at, create_time, update_time
FROM ncm_songs
ORDER BY original_id;

DROP TABLE ncm_songs;
ALTER TABLE ncm_songs_005 RENAME TO ncm_songs;

CREATE INDEX IF NOT EXISTS idx_ncm_songs_name_norm ON ncm_songs(name_norm);
CREATE INDEX IF NOT EXISTS idx_ncm_songs_artist_norm ON ncm_songs(artist_norm);

CREATE TABLE ncm_song_index_005 (
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

INSERT INTO ncm_song_index_005 (
  song_original_id, song_name, song_name_norm, song_encrypted_id,
  duration, artist, artist_norm,
  album_original_id, album_name, album_encrypted_id,
  create_time, update_time
)
SELECT
  song_original_id, song_name, song_name_norm, song_encrypted_id,
  duration, artist, artist_norm,
  album_original_id, album_name, album_encrypted_id,
  create_time, update_time
FROM ncm_song_index
ORDER BY song_original_id;

DROP TABLE ncm_song_index;
ALTER TABLE ncm_song_index_005 RENAME TO ncm_song_index;

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
