-- Intent-hit play log. Catalog rows stay insert-only; this table is append-only.
-- Only music.play (user intent) writes here — not music.next / ncm-cli autoplay.

CREATE TABLE IF NOT EXISTS ncm_plays (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  song_original_id INTEGER NOT NULL,
  participant_id TEXT NOT NULL,
  intent_id TEXT,
  played_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ncm_plays_played_at
  ON ncm_plays(played_at DESC);
CREATE INDEX IF NOT EXISTS idx_ncm_plays_participant
  ON ncm_plays(participant_id);
CREATE INDEX IF NOT EXISTS idx_ncm_plays_song
  ON ncm_plays(song_original_id);
