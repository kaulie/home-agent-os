-- Snapshot of the planner catalog at plan time (schedulable capabilities).
-- JSON array: the exact Available Capabilities list passed into the planner.
-- Unavailable ads (available=false) are already filtered out of that catalog.
-- Historical rows stay NULL. Do not edit 001–023. No secondary indexes.

ALTER TABLE jobs ADD COLUMN available_capabilities TEXT;
