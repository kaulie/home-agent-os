-- Append-only review archive: intent text + LLM parse. Not logistics.
-- Do not edit 001–007 (already applied). No secondary indexes.

CREATE TABLE intent_reviews (
  review_id INTEGER PRIMARY KEY AUTOINCREMENT,
  intent_id TEXT NOT NULL,
  text TEXT,
  source TEXT,
  edge_id TEXT,
  planner TEXT,
  model TEXT,
  cost_ms INTEGER,
  raw_response TEXT,
  parsed_json TEXT,
  execution_plan TEXT,
  error TEXT,
  created_at REAL NOT NULL
);
