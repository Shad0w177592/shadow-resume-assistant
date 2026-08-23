ALTER TABLE profile_section_entry
ADD COLUMN importance INTEGER NOT NULL DEFAULT 3
CHECK (importance BETWEEN 1 AND 5);
