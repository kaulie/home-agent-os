-- P0 dual-Brain: Runtime Identity / domain / Capability Exposure Policy.
-- Do not edit 001–021 (already applied). No secondary indexes.
--
-- participant_id is now Runtime Identity (client-supplied, stable across Brains).
-- `domain` records which Brain control plane this row belongs to (lan|cloud);
--   backfilled by the app on next register/heartbeat (NULL until then).
-- `exposure_policy` is JSON {lan:[cap...], cloud:[cap...]}; NULL = open by default.
-- `runtime_id` is a redundant alias of participant_id for future cross-Brain federation.

ALTER TABLE participants ADD COLUMN domain TEXT;
ALTER TABLE participants ADD COLUMN exposure_policy TEXT;
ALTER TABLE participants ADD COLUMN runtime_id TEXT;
