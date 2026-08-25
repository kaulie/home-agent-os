-- Admin overlay for which registered roles/capabilities may be scheduled.
-- Does not touch participants heartbeat or registration columns.
-- Do not edit 001–013. No secondary indexes. No FK.

CREATE TABLE edge_control_policy (
  participant_id TEXT NOT NULL,
  target_kind TEXT NOT NULL,
  target_id TEXT NOT NULL,
  enabled INTEGER NOT NULL,
  updated_at REAL NOT NULL,
  PRIMARY KEY (participant_id, target_kind, target_id)
);
