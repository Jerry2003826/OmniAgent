-- migrations/007_preference_memory.sql
-- PRAGMAs are set in db.connect(), not here:
-- PRAGMA journal_mode=WAL;
-- PRAGMA busy_timeout=5000;
-- PRAGMA foreign_keys=ON;

CREATE TABLE preference_candidates(
  pref_cand_id TEXT PRIMARY KEY,
  source_cand_id TEXT,
  scope TEXT NOT NULL,
  kind TEXT NOT NULL,
  predicate TEXT NOT NULL,
  qualifier TEXT NOT NULL DEFAULT 'default',
  body TEXT NOT NULL,
  suggested_action TEXT NOT NULL,
  evidence JSON NOT NULL,
  state TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL,
  reviewed_at TEXT,
  review_note TEXT
);

CREATE INDEX idx_preference_candidates_state
ON preference_candidates(state, created_at);

CREATE TABLE preference_notes(
  note_id TEXT PRIMARY KEY,
  source_cand_id TEXT,
  scope TEXT NOT NULL,
  kind TEXT NOT NULL,
  body TEXT NOT NULL,
  suggested_action TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  evidence JSON NOT NULL,
  created_seq INTEGER NOT NULL,
  retired_seq INTEGER,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX idx_preference_notes_scope
ON preference_notes(scope, status);

CREATE UNIQUE INDEX uq_preference_notes_active_source
ON preference_notes(source_cand_id)
WHERE status = 'active';

UPDATE meta SET value = '7' WHERE key = 'schema_version';
