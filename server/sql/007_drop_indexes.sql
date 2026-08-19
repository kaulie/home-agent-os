-- Drop all secondary indexes. Keep PRIMARY KEY (required for ON CONFLICT).
-- Do not edit 001–006 (already applied).

DROP INDEX IF EXISTS idx_jobs_status;
DROP INDEX IF EXISTS idx_jobs_assigned;
DROP INDEX IF EXISTS idx_participants_location;
DROP INDEX IF EXISTS idx_participants_runtime;
DROP INDEX IF EXISTS idx_participants_online;
DROP INDEX IF EXISTS idx_participants_room;
DROP INDEX IF EXISTS idx_intent_queue_position;
DROP INDEX IF EXISTS idx_intent_queue_status;
DROP INDEX IF EXISTS idx_intent_queue_assigned;
