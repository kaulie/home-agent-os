-- Drop Observer event-list contract. Keep role_observer.
-- Do not edit 001–009 (already applied). No secondary indexes.

ALTER TABLE participants DROP COLUMN observer_events;
