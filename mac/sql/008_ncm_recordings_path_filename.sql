-- Split full file path into directory (path) + basename (filename)
-- so recordings can move without losing the stable file name.

ALTER TABLE ncm_recordings ADD COLUMN filename TEXT;

-- Backfill from legacy full paths written by 007.
UPDATE ncm_recordings
SET
  filename = replace(path, rtrim(path, replace(path, '/', '')), ''),
  path = rtrim(rtrim(path, replace(path, '/', '')), '/')
WHERE filename IS NULL OR filename = '';
