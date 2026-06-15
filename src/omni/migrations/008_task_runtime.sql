-- migrations/008_task_runtime.sql
-- PRAGMAs are set in db.connect(), not here:
-- PRAGMA journal_mode=WAL;
-- PRAGMA busy_timeout=5000;
-- PRAGMA foreign_keys=ON;

CREATE TABLE tasks(
  task_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  title TEXT,
  task_type TEXT NOT NULL DEFAULT 'unknown',
  status TEXT NOT NULL DEFAULT 'open',
  outcome_status TEXT,
  tests_status TEXT,
  created_seq INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  closed_at TEXT,
  close_reason TEXT,
  evidence JSON NOT NULL DEFAULT '{}'
);

CREATE INDEX idx_tasks_status ON tasks(project_id, status, created_seq);
CREATE UNIQUE INDEX uq_tasks_one_open_per_project ON tasks(project_id) WHERE status = 'open';

ALTER TABLE runs ADD COLUMN task_id TEXT;
CREATE INDEX idx_runs_task ON runs(task_id);

UPDATE meta SET value = '8' WHERE key = 'schema_version';
