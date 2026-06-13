-- migrations/006_failure_patterns.sql
-- PRAGMAs are set in db.connect(), not here:
-- PRAGMA journal_mode=WAL;
-- PRAGMA busy_timeout=5000;
-- PRAGMA foreign_keys=ON;

ALTER TABLE failure_candidates ADD COLUMN pattern_id TEXT;

CREATE TABLE failure_patterns(
  pattern_id TEXT PRIMARY KEY,
  source_failure_cand_id TEXT,
  scope TEXT NOT NULL,
  command_norm TEXT,
  failure_kind TEXT NOT NULL,
  error_signature TEXT NOT NULL,
  error_signature_hash TEXT NOT NULL,
  summary TEXT NOT NULL,
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

CREATE INDEX idx_failure_patterns_scope
ON failure_patterns(scope, status);

CREATE INDEX idx_failure_patterns_signature
ON failure_patterns(error_signature_hash);

CREATE UNIQUE INDEX uq_failure_patterns_active_source
ON failure_patterns(source_failure_cand_id)
WHERE status = 'active';

CREATE UNIQUE INDEX uq_failure_patterns_active_signature
ON failure_patterns(scope, error_signature_hash)
WHERE status = 'active';

UPDATE meta SET value = '6' WHERE key = 'schema_version';
