-- Silence marks from post-record ffmpeg silencedetect (App pause gaps, etc.).

ALTER TABLE ncm_recordings ADD COLUMN silence_spans_json TEXT;
ALTER TABLE ncm_recordings ADD COLUMN silence_total_sec REAL;
ALTER TABLE ncm_recordings ADD COLUMN has_long_silence INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_ncm_recordings_has_long_silence
  ON ncm_recordings(has_long_silence);
