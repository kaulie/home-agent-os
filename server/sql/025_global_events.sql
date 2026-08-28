-- Append-only household global events (mode switches, future scene/preference kinds).
-- Do not edit 001–024 (already applied). No secondary indexes. No FK.

CREATE TABLE global_events (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  action TEXT NOT NULL,
  subject TEXT,
  payload TEXT,
  edge_id TEXT,
  intent_id TEXT,
  created_at REAL NOT NULL
);
