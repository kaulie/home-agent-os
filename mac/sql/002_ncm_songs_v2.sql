-- Realign ncm_songs after 001 draft (TEXT pk, no name/artist/indexes).
-- Safe for empty dev catalogs; capability contract is 002 shape.

DROP TABLE IF EXISTS ncm_songs;

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
