-- migrations/002_outcomes.sql
-- PRAGMAs are set in db.connect(), not here:
-- PRAGMA journal_mode=WAL;
-- PRAGMA busy_timeout=5000;
-- PRAGMA foreign_keys=ON;

CREATE TABLE outcomes(
  outcome_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES runs(run_id),
  task_type TEXT NOT NULL DEFAULT 'unknown',
  status TEXT NOT NULL,
  tests_status TEXT NOT NULL DEFAULT 'unknown',
  memory_effect TEXT NOT NULL DEFAULT 'unknown',
  task_summary TEXT,
  final_command TEXT,
  note TEXT,
  evidence JSON NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX uq_outcomes_run_id ON outcomes(run_id);

UPDATE meta SET value = '2' WHERE key = 'schema_version';
