-- Per-intent user ratings from Intent Source (understanding + response speed).
-- One row per (intent_id, participant_id); upsert on resubmit.

CREATE TABLE intent_user_feedback (
  feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,
  intent_id INTEGER NOT NULL,
  participant_id TEXT NOT NULL,
  understanding TEXT NOT NULL CHECK(understanding IN ('accurate', 'inaccurate')),
  response_speed TEXT NOT NULL CHECK(response_speed IN ('fast', 'normal', 'slow')),
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  UNIQUE(intent_id, participant_id)
);
