-- migrations/004_experience_notes.sql
-- PRAGMAs are set in db.connect(), not here:
-- PRAGMA journal_mode=WAL;
-- PRAGMA busy_timeout=5000;
-- PRAGMA foreign_keys=ON;

CREATE TABLE experience_notes(
  note_id TEXT PRIMARY KEY,
  source_cand_id TEXT,
  scope TEXT NOT NULL,
  task_type TEXT NOT NULL,
  kind TEXT NOT NULL,
  trigger TEXT,
  body TEXT NOT NULL,
  suggested_action TEXT NOT NULL,
  trust INTEGER NOT NULL DEFAULT 2,
  status TEXT NOT NULL DEFAULT 'active',
  evidence JSON NOT NULL,
  created_seq INTEGER NOT NULL,
  retired_seq INTEGER,
  superseded_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX idx_experience_notes_scope
ON experience_notes(scope, task_type, status);

CREATE UNIQUE INDEX uq_experience_notes_active_source
ON experience_notes(source_cand_id)
WHERE status = 'active';

UPDATE meta SET value = '4' WHERE key = 'schema_version';
