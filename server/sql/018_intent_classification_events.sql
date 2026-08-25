-- Append-only intent complexity classification events. Not logistics, not LLM reviews.
-- Do not edit 001–017 (already applied). No secondary indexes. No FK.

CREATE TABLE intent_classification_events (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  intent_id TEXT,
  text TEXT,
  classifier_version TEXT,
  score REAL,
  classification TEXT,
  features TEXT,
  candidates TEXT,
  created_at REAL NOT NULL
);
