PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migration (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_profile (
  id TEXT PRIMARY KEY,
  display_name TEXT,
  payload_json TEXT NOT NULL DEFAULT '{}',
  schema_version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS profile_section_entry (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL REFERENCES user_profile(id) ON DELETE CASCADE,
  section_key TEXT NOT NULL,
  title TEXT,
  payload_json TEXT NOT NULL DEFAULT '{}',
  schema_version INTEGER NOT NULL DEFAULT 1,
  deleted_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_document (
  id TEXT PRIMARY KEY,
  managed_file_id TEXT,
  original_name TEXT NOT NULL,
  status TEXT NOT NULL,
  parsed_json TEXT,
  schema_version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_target (
  id TEXT PRIMARY KEY,
  company TEXT,
  title TEXT,
  jd_text TEXT NOT NULL,
  notes TEXT,
  status TEXT NOT NULL DEFAULT 'draft',
  deleted_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_requirement (
  id TEXT PRIMARY KEY,
  job_target_id TEXT NOT NULL REFERENCES job_target(id) ON DELETE CASCADE,
  requirement_type TEXT NOT NULL,
  summary TEXT NOT NULL,
  source_text TEXT NOT NULL,
  source_start INTEGER NOT NULL,
  source_end INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence_link (
  id TEXT PRIMARY KEY,
  job_requirement_id TEXT NOT NULL REFERENCES job_requirement(id) ON DELETE CASCADE,
  profile_entry_id TEXT REFERENCES profile_section_entry(id) ON DELETE CASCADE,
  status TEXT NOT NULL,
  reason TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS resume_config (
  id TEXT PRIMARY KEY,
  job_target_id TEXT NOT NULL REFERENCES job_target(id) ON DELETE CASCADE,
  config_json TEXT NOT NULL,
  schema_version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS resume_draft (
  id TEXT PRIMARY KEY,
  job_target_id TEXT NOT NULL REFERENCES job_target(id) ON DELETE CASCADE,
  document_json TEXT NOT NULL,
  schema_version INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'draft',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS resume_version (
  id TEXT PRIMARY KEY,
  draft_id TEXT NOT NULL REFERENCES resume_draft(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  notes TEXT,
  document_json TEXT NOT NULL,
  schema_version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS edit_proposal (
  id TEXT PRIMARY KEY,
  draft_id TEXT NOT NULL REFERENCES resume_draft(id) ON DELETE CASCADE,
  target_block_id TEXT NOT NULL,
  before_text TEXT NOT NULL,
  after_text TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  payload_json TEXT NOT NULL DEFAULT '{}',
  schema_version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_setting (
  setting_key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL,
  schema_version INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_run (
  id TEXT PRIMARY KEY,
  task_type TEXT NOT NULL,
  status TEXT NOT NULL,
  progress INTEGER NOT NULL DEFAULT 0,
  payload_json TEXT NOT NULL DEFAULT '{}',
  schema_version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS backup_record (
  id TEXT PRIMARY KEY,
  file_name TEXT NOT NULL,
  status TEXT NOT NULL,
  manifest_json TEXT,
  schema_version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_profile_entry_profile ON profile_section_entry(profile_id, section_key);
CREATE INDEX IF NOT EXISTS idx_job_requirement_job ON job_requirement(job_target_id);
CREATE INDEX IF NOT EXISTS idx_resume_draft_job ON resume_draft(job_target_id, updated_at);

