-- migrations/005_failure_candidates.sql
-- PRAGMAs are set in db.connect(), not here:
-- PRAGMA journal_mode=WAL;
-- PRAGMA busy_timeout=5000;
-- PRAGMA foreign_keys=ON;

CREATE TABLE failure_candidates(
  failure_cand_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES runs(run_id),
  event_id TEXT,
  tool_use_id TEXT,
  tool TEXT,
  command_norm TEXT,
  exit_code INTEGER,
  failure_kind TEXT NOT NULL,
  error_signature TEXT NOT NULL,
  error_signature_hash TEXT NOT NULL,
  -- Legacy column name: stores a redacted normalized signature, not raw stderr.
  stderr_excerpt TEXT,
  artifact_ref TEXT,
  evidence JSON NOT NULL,
  state TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL,
  reviewed_at TEXT,
  review_note TEXT
);

CREATE INDEX idx_failure_candidates_state
ON failure_candidates(state);

CREATE INDEX idx_failure_candidates_run
ON failure_candidates(run_id);

CREATE INDEX idx_failure_candidates_signature
ON failure_candidates(error_signature_hash);

CREATE UNIQUE INDEX uq_failure_candidate_run_signature
ON failure_candidates(run_id, error_signature_hash);

UPDATE meta SET value = '5' WHERE key = 'schema_version';
