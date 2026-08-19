-- Group review rows by conversation session. Do not edit 001–008.

ALTER TABLE intent_reviews ADD COLUMN session_id TEXT;
