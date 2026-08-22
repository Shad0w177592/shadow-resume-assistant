CREATE TABLE IF NOT EXISTS import_candidate (
  id TEXT PRIMARY KEY,
  source_document_id TEXT NOT NULL REFERENCES source_document(id) ON DELETE CASCADE,
  section_key TEXT NOT NULL,
  title TEXT,
  payload_json TEXT NOT NULL DEFAULT '{}',
  source_locator_json TEXT NOT NULL DEFAULT '{}',
  confidence TEXT NOT NULL,
  duplicate_of TEXT REFERENCES profile_section_entry(id) ON DELETE SET NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_import_candidate_document
ON import_candidate(source_document_id, status);
