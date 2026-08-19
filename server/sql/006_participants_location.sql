-- participants.room → location. Do not edit 001–005 (already applied).

ALTER TABLE participants RENAME COLUMN room TO location;

DROP INDEX IF EXISTS idx_participants_room;
CREATE INDEX idx_participants_location ON participants(location);
