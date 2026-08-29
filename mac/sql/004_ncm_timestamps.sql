-- Conventional create_time / update_time on both catalog tables.
-- Unix seconds (REAL), same unit as played_at. Existing rows backfilled to now.

ALTER TABLE ncm_songs ADD COLUMN create_time REAL;
ALTER TABLE ncm_songs ADD COLUMN update_time REAL;
ALTER TABLE ncm_song_index ADD COLUMN create_time REAL;
ALTER TABLE ncm_song_index ADD COLUMN update_time REAL;

UPDATE ncm_songs
SET
  create_time = COALESCE(create_time, CAST(strftime('%s', 'now') AS REAL)),
  update_time = COALESCE(update_time, CAST(strftime('%s', 'now') AS REAL))
WHERE create_time IS NULL OR update_time IS NULL;

UPDATE ncm_song_index
SET
  create_time = COALESCE(create_time, CAST(strftime('%s', 'now') AS REAL)),
  update_time = COALESCE(update_time, CAST(strftime('%s', 'now') AS REAL))
WHERE create_time IS NULL OR update_time IS NULL;
