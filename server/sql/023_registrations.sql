-- P0 dual-Brain: split heartbeat state out of participants into registrations.
-- Do not edit 001–022 (already applied). No secondary indexes.
--
-- Heartbeat belongs to Registration (participant_id, domain), not Runtime Identity.
-- participants keeps Identity + Declaration (services) + Exposure Policy only.
-- Existing heartbeat columns are ephemeral (30s TTL); back them up then drop.

CREATE TABLE registrations (
  participant_id TEXT NOT NULL,
  domain TEXT NOT NULL,
  registered_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  online_status TEXT,
  health TEXT,
  client_time_ms INTEGER,
  brain_time_ms INTEGER,
  clock_skew_ms INTEGER,
  schedule_eligible INTEGER,
  schedule_reject_reason TEXT,
  reported_at REAL,
  server_received_at REAL,
  connection TEXT,
  latency INTEGER,
  reachability TEXT,
  services_snapshot TEXT,
  PRIMARY KEY (participant_id, domain)
);

-- Forensic backup of pre-split heartbeat columns (one snapshot, not maintained).
CREATE TABLE participants_heartbeat_backup AS
SELECT
  participant_id,
  online_status,
  health,
  client_time_ms,
  brain_time_ms,
  clock_skew_ms,
  schedule_eligible,
  schedule_reject_reason,
  reported_at,
  server_received_at
FROM participants;

-- Drop migrated heartbeat columns from participants. Declaration (services) stays.
-- SQLite >= 3.35 supports DROP COLUMN; older versions skip (columns remain unused).
ALTER TABLE participants DROP COLUMN online_status;
ALTER TABLE participants DROP COLUMN health;
ALTER TABLE participants DROP COLUMN client_time_ms;
ALTER TABLE participants DROP COLUMN brain_time_ms;
ALTER TABLE participants DROP COLUMN clock_skew_ms;
ALTER TABLE participants DROP COLUMN schedule_eligible;
ALTER TABLE participants DROP COLUMN schedule_reject_reason;
ALTER TABLE participants DROP COLUMN reported_at;
ALTER TABLE participants DROP COLUMN server_received_at;
