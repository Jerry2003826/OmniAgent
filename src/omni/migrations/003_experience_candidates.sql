-- migrations/003_experience_candidates.sql
-- PRAGMAs are set in db.connect(), not here:
-- PRAGMA journal_mode=WAL;
-- PRAGMA busy_timeout=5000;
-- PRAGMA foreign_keys=ON;

CREATE TABLE experience_candidates(
  exp_cand_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES runs(run_id),
  outcome_id TEXT,
  task_type TEXT NOT NULL,
  kind TEXT NOT NULL,
  trigger TEXT,
  claim TEXT NOT NULL,
  suggested_action TEXT NOT NULL,
  evidence JSON NOT NULL,
  state TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL,
  reviewed_at TEXT,
  review_note TEXT
);

CREATE INDEX idx_experience_candidates_state ON experience_candidates(state);
CREATE INDEX idx_experience_candidates_run_id ON experience_candidates(run_id);
CREATE INDEX idx_experience_candidates_kind ON experience_candidates(kind);

UPDATE meta SET value = '3' WHERE key = 'schema_version';
