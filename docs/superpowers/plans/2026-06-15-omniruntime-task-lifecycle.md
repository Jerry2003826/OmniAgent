# Plan — OmniRuntime Stage ③: task lifecycle (run → task model shift)

Date: 2026-06-15
Targets: OmniAgent Stage ③ (OmniRuntime) of
[`docs/omniagent-phase-c-charter.md`](../../omniagent-phase-c-charter.md).
Status: completed implementation plan for C-5. WP-0 through WP-4 have landed.

> **Read this whole file before writing any code.** This plan changes the data
> *model*, not just the I/O: it introduces `task` as a first-class entity with a
> lifecycle, and makes `run` an execution record *under* a task. That touches the
> schema (a new migration) and the command model. Sections 2 (invariants) and 3
> (anti-patterns) are hard rules — a violation is grounds for reverting the commit.

> **Status note.** WP-0 landed before any schema/code work: `AGENTS.md` and the
> Phase C charter now approve migration `008_task_runtime.sql` and `omni task *`.
> Future task-runtime expansions still need their own charter row before code.

---

## 0. TL;DR

| WP | What | Kind | Status |
|----|------|------|---|
| **WP-0** | Governance amendment: unfreeze task runtime + register migration 008 | docs / charter | done |
| **WP-1** | Migration `008_task_runtime.sql`: `tasks` table + `runs.task_id` (nullable) | schema (write) | done |
| **WP-2** | Task lifecycle core: `start` / `status` / `ls` / `show` / `close` / `abandon` | new module + commands | done |
| **WP-3** | Bridge existing verify + outcome into a task (no logic forks) | reuse | done |
| **WP-4** | Read-only task evidence view (leak-free JSON, machine-facing) | reuse WP-3-of-OmniBridge pattern | done |

Completed order: **WP-0 → WP-1 → WP-2 → WP-3 → WP-4.** Multi-agent handoff is
explicitly **out of scope** (Section 9); this plan shipped the single-task
closed loop first.

---

## 1. Starting model and shipped gap

**Before this plan (passive, after-the-fact):**

```
Claude hook ─> spool ─> `omni ingest` ─> runs row (status open/closed) + events
                                          └ `omni outcome mark[-from-verify] <run_id>`
                                          └ `omni eval run <run_id>`
```

A `run` is discovered *after* an agent session, reconstructed from a redacted
trace. There is no object that represents "the unit of work the agent was asked to
do." `outcome` and `eval` are keyed on a single `run_id`.

**Vision (active, in-the-loop) — OmniRuntime:**

```
`omni task start "intent"` ─> task row (open)
   ⟳ agent works; one or more runs are ingested and attached to the open task
`omni task close --from-verify` ─> runs the known verify command, records evidence on the task
`omni task close`               ─> records the task outcome, status=closed
```

`task` becomes the first-class entity; `run` is an execution record under it.

**What already exists in the schema (do not re-invent):**
- `runs.engine` (default `'claude_code'`) and `runs.parent_run_id` already exist
  (`001_init.sql`). The multi-engine / parent columns are *already there* — a task
  with runs from different engines is representable without new run columns.
- `runs.status`, `started_at`, `ended_at`, `end_reason` already model run state.
- `outcomes` (per-run), `verify` (read-only preflight), `eval` already exist and
  are engine-neutral.

**What this plan added:**
- a `tasks` table,
- `runs.task_id` (nullable FK) to attach a run to a task,
- a "current open task" pointer so newly ingested runs attach automatically,
- task lifecycle commands.

---

## 2. Hard invariants (violation ⇒ revert)

All Phase B/C invariants still apply. Re-stated, plus task-specific ones:

1. **Redaction-before-write.** A task `title`/intent is user text → it passes
   `redact_text` before it is stored. No raw intent string in the DB.
2. **`omni hook` still always exits 0 and never writes the DB.** Task attachment
   happens inside `omni ingest` (an approved write command), **not** in the hook.
   Do not add a DB write to the capture path to "know the current task."
3. **Read-only stays read-only.** `task status` / `task ls` / `task show` open
   SQLite `mode=ro` via `dbaccess.connect_project_readonly`, run no migration.
   `task start` / `close` / `abandon` / `verify`(record) are the only new writers.
4. **Human review gate is untouched.** Tasks are operational state, **not memory**.
   A task closing does NOT auto-create experience/failure/preference memory and does
   NOT auto-infer success — memory still only changes through the existing gated
   commands. (A closed task may be *evidence* a later `extract` reads, nothing more.)
5. **No metadata leak.** The WP-4 read view strips internal ids/evidence/timestamps
   exactly like `render.read_view` / `failure.read_view`. Reuse that pattern + its
   leak tests.
6. **Migration discipline.** `008` is all-or-nothing (the `executescript`
   BEGIN/COMMIT runner already guarantees this); it ends with
   `UPDATE meta SET value = '8' WHERE key = 'schema_version';`; `db.MIGRATIONS`
   registers it; read-only commands then require `LATEST_SCHEMA_VERSION == '8'`.
   **No migration without a charter row (WP-0).**
7. **Backward compatibility.** Existing rows must survive. `runs.task_id` is
   **nullable**; every pre-existing run keeps `task_id = NULL` and every current
   command (`ingest`, `outcome`, `eval`, `run show`) must behave identically when a
   run has no task. Adding tasks must not change any existing test's expectations.

---

## 3. Anti-patterns to avoid (the exact mistakes made in this repo before — do NOT repeat)

The first eight are the same defect classes as the OmniBridge plan; 9–12 are
specific to introducing the task entity.

1. **No twin functions.** (Seen: `connect_project_readonly` vs `…_verify`.) Do not
   copy `outcome.mark_outcome` to make a `task_mark`. Bridge by *calling* the
   existing function (WP-3), not by forking its body.
2. **No shallow forwarding wrappers.** (Seen: `EventCandidate`'s 10 passthrough
   `@property`s.) The task module should not wrap a run/outcome row behind a façade
   of `return self.row["x"]`. Pass dicts/rows; add a property only when it computes
   something.
3. **No parallel `if` chains.** (Seen: `list_outcomes`' double filter ladder.)
   Lifecycle state validation and the status-transition table are **one**
   declarative structure, iterated once — not a fresh `if status == …` ladder per
   command.
4. **Behavior-preserving for everything that exists.** Running `008` and adding the
   task module must leave `ingest`/`outcome`/`eval`/`render`/`verify` byte-identical
   for tasks-absent flows. Run the full suite before and after; changed expectations
   in *existing* tests are a red flag.
5. **YAGNI on the lifecycle.** Implement the minimum state machine
   (`open → closed | abandoned`). Do NOT add `verifying`/`blocked`/`paused`
   sub-states, priorities, assignees, or handoff records speculatively. The second
   real need reshapes the model, not imagination.
6. **Name for the domain.** No `manager`/`handler`/`data`/`info`. The entity is
   `task`; the module is `src/omni/task.py`; ids are `task_id`.
7. **Tests assert behavior, not implementation.** Cover the failure/edge paths:
   double-start, close-already-closed, close-with-no-runs, attach-to-closed-task,
   read-only DB, leak attempts, and a backward-compat test that a task-less run is
   unchanged. Keep a real-subprocess smoke test per new CLI command.
8. **Respect module line budgets.** Add `task.py` to `tests/test_module_budget.py`.
   If lifecycle + bridge + read-view outgrow one file, split (e.g. `task/repo.py`,
   `task/lifecycle.py`) and budget each — do not grow past a cap.

9. **`task` (entity) vs `task_type` (attribute) — never conflate them.** A
   `task_type` already exists across `outcome`/`experience` (the enum
   `validation|bugfix|docs|refactor|exploration|unknown` in `_common.TASK_TYPE_VALUES`).
   The new `tasks` table **reuses that enum as a column** (`tasks.task_type`). Do NOT
   invent a second enum, and do NOT name anything `task` that actually means
   `task_type`. In code: `task.task_type`, validated with the existing
   `validate_choice(..., TASK_TYPE_VALUES)`.

10. **Concurrency: match the *strong* pattern, not the weak one.** (Seen:
    `experience`/`failure` guard state transitions with optimistic
    `UPDATE … WHERE status = <expected>` + `rowcount` checks and rollback recovery;
    `preference` has none.) Every task state transition uses the **strong** pattern:
    `UPDATE tasks SET status=? WHERE task_id=? AND status=<expected>`, check
    `rowcount`, recover on race. No bare "read-then-write" without the guarded write.

11. **`ALTER TABLE` must stay within SQLite's rules.** `runs.task_id` is added as a
    **nullable column with no default expression** (`ALTER TABLE runs ADD COLUMN
    task_id TEXT;`) — that is the one safe ALTER form. Do not try to add a NOT NULL
    column, a foreign-key constraint via ALTER, or a computed default; create the
    index separately (`CREATE INDEX idx_runs_task ON runs(task_id);`).

12. **Do not put task attachment in the hook or in a read command.** The "current
    task" pointer is written by `task start`/`close` (writers) and read by `ingest`
    (writer) to stamp `runs.task_id`. A read-only command must never write the
    pointer; the hook must never touch it.

---

## 4. Core design

### 4.1 The `tasks` table (migration 008)

```sql
-- migrations/008_task_runtime.sql
CREATE TABLE tasks(
  task_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  title TEXT,                                   -- redacted intent, nullable
  task_type TEXT NOT NULL DEFAULT 'unknown',    -- reuse TASK_TYPE_VALUES
  status TEXT NOT NULL DEFAULT 'open',          -- open | closed | abandoned
  outcome_status TEXT,                          -- success | failed | unknown (set at close)
  tests_status TEXT,                            -- passed | failed | not_run | unknown (from verify at close)
  created_seq INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  closed_at TEXT,
  close_reason TEXT,
  evidence JSON NOT NULL DEFAULT '{}'           -- redacted; verify reason_code, run count, etc.
);

CREATE INDEX idx_tasks_status ON tasks(project_id, status, created_seq);

ALTER TABLE runs ADD COLUMN task_id TEXT;       -- nullable, backward-compatible
CREATE INDEX idx_runs_task ON runs(task_id);

UPDATE meta SET value = '8' WHERE key = 'schema_version';
```

The "current open task" pointer reuses the existing `meta` table — no extra table:

```
meta('current_task_id', '<task_id>')   -- set by `task start`, cleared by close/abandon
```

### 4.2 Lifecycle state machine (one declarative table — anti-pattern #3)

```
open ──close──>   closed      (records outcome_status, tests_status)
open ──abandon──> abandoned    (no outcome; intentional give-up)
closed/abandoned: terminal. The internal transition helper is idempotent when
the requested terminal status is already present; public `task close` still
requires a current open task. Re-open is NOT supported in v0.
```

```python
# task.py — single source of truth, not an if-ladder per command
TASK_STATUS_VALUES = frozenset({"open", "closed", "abandoned"})
_TERMINAL = frozenset({"closed", "abandoned"})
# transition(target) is allowed iff current == "open"; transition(target) returns
# cleanly if the task already has that exact terminal status.
```

### 4.3 run ↔ task ↔ outcome relationship

- **Attachment:** `task start` writes `meta.current_task_id`. `omni ingest`, when a
  current task exists, stamps `runs.task_id = current_task_id` on runs it
  creates/updates (one new line in the existing `_ensure_run`/ingest path, guarded
  so tasks-absent ingest is unchanged). Runs ingested with no current task keep
  `task_id = NULL` (backward compatible).
- **Outcome:** a task does **not** get its own row in `outcomes`. `outcomes` stays
  per-run. `task close` (WP-3) *calls* the existing `outcome.mark_outcome[_from_verify]`
  for the task's representative run, then snapshots `outcome_status` / `tests_status`
  onto the `tasks` row for fast machine reads. (Open decision §8.1 picks the
  "representative run".)
- **Evidence:** `tasks.evidence` holds only redacted, non-id summary (verify
  `reason_code`, run count, last verify command) — never raw stderr, never ids.

### 4.4 Commands and read/write classification

| Command | R/W | Notes |
|---------|-----|-------|
| `omni task start "<intent>"` `[--task-type T]` | **W** | redact title; create open task; set `current_task_id`; error if one already open |
| `omni task status` | **R** | the current open task (or "none") + attached run count |
| `omni task ls [--status open\|closed\|abandoned\|all]` | **R** | list tasks |
| `omni task show <task_id>` | **R** | one task + attached run ids count (ids gated in read-view) |
| `omni task close [--success\|--failed\|--unknown] [--from-verify ...]` | **W** | record outcome via WP-3, status=closed, clear pointer |
| `omni task abandon [--reason ...]` | **W** | status=abandoned, clear pointer |
| `omni task read` | **R** | machine-facing leak-free JSON (WP-4) |

Wire writers through `connect_project_migrate`; readers through `_run_db_command(readonly=True, …)`.

---

## 5. Work packages

### WP-0 — Governance amendment (BLOCKING, docs only)

Task runtime is forbidden in the current charter. Before any code:

1. Add a charter section (amend `docs/omniagent-phase-c-charter.md`, or open
   `docs/omniagent-phase-d-charter.md`) that:
   - **unfreezes** "task runtime & lifecycle" as approved direction,
   - registers **migration 008** in a charter row (the migration-approval process
     in Phase B charter §5 requires the row to exist *before* implementation),
   - restates that tasks are operational state, not memory (invariant §2.4),
   - keeps multi-agent handoff / permission tiers deferred.
2. Update `AGENTS.md`: move "task runtime" out of the hard non-goal list into the
   approved-for-this-phase list; add the new `task` commands to the read/write
   command lists; bump the "approved migrations" line to include `008`.
3. DoD: charter row exists naming `008_task_runtime.sql` and the `tasks` table; the
   AGENTS read/write lists name every `omni task *` command. No code yet.

### WP-1 — Migration 008 (schema)

1. Write `migrations/008_task_runtime.sql` exactly as §4.1 (table + nullable
   `runs.task_id` + indexes + `schema_version='8'`).
2. Register `("8", "008_task_runtime.sql")` in `db.MIGRATIONS`.
3. Tests: a fresh DB migrates to `'8'`; an existing `'7'` DB upgrades and **keeps
   all rows** (seed a run at v7, migrate, assert the run still exists with
   `task_id IS NULL`); `connect_project_readonly` against a v7 DB raises the
   existing "schema is outdated" error (now expecting 8).
4. DoD: full suite green after re-pointing the schema-version assertions
   (`"found 7, need 8"`) — those are the *only* legitimate test-expectation changes.

### WP-2 — Task lifecycle core

1. New `src/omni/task.py` (or `task/` package if it would exceed budget):
   `start_task`, `current_task`, `list_tasks`, `show_task`, `close_task`,
   `abandon_task`, plus `cli_command_readonly` + `handle_cli_action` mirroring the
   existing memory modules' shape (so it slots into `_run_db_command`).
2. State transitions use the strong concurrency pattern (anti-pattern #10):
   guarded `UPDATE … WHERE status='open'`, `rowcount` check, rollback recovery.
3. `start_task` redacts the title, validates `task_type` via `TASK_TYPE_VALUES`,
   refuses a second open task, and sets `current_task_id`.
4. Stamp attachment in `ingest`: one guarded line setting `runs.task_id` from
   `current_task_id` when present. Tasks-absent ingest path unchanged.
5. CLI: `_add_task_parser`, `_cmd_task`, register in `_HANDLERS`.
6. Tests: lifecycle happy path; double-start refused; internal terminal
   transition idempotence; attach stamps `task_id`; tasks-absent ingest
   byte-identical; readers read-only.

### WP-3 — Verify + outcome bridge (reuse, do not fork)

1. `close_task --from-verify` *calls* `verify.run_preflight` + `outcome.mark_outcome_from_verify`
   for the representative run, then snapshots `outcome_status`/`tests_status` onto
   the task. `close_task --success/--failed/--unknown` calls plain `outcome.mark_outcome`.
2. Absolutely no copy of verify/outcome logic into `task.py` (anti-pattern #1).
3. Tests: close-from-verify writes a per-run outcome AND the task snapshot, with
   identical verify reason-code behavior as the standalone `outcome mark-from-verify`.

### WP-4 — Read-only task read view (machine-facing)

1. `task.read_view(conn)` → `{schema_version, tasks:[{title, task_type, status,
   outcome_status, tests_status, run_count}]}`, stripped of `task_id`/run ids/
   evidence/timestamps via the existing redaction path.
2. Declarative field allowlist (like `PATTERN_READ_VIEW_FIELDS`), not a del-list.
3. `omni task read` wired read-only; leak test reusing the OmniBridge
   `assert_no_metadata_leak` helper, including an adversarial seed (ids in evidence).

---

## 6. Definition of Done (whole plan)

- WP-0 merged before any code; charter row names `008` and the `tasks` table.
- `pytest -q` green; the only changed existing-test expectations are the
  schema-version strings (`7`→`8`).
- Tasks-absent flows (`ingest`/`outcome`/`eval`/`render`/`verify`/`run show`) are
  byte-identical; a backward-compat test proves a `task_id IS NULL` run is unchanged.
- All new writers go through migrate-connections; all readers are read-only and
  pass metadata-leak tests.
- `AGENTS.md` read/write lists + approved-migrations line updated; `task.py`
  budget row added.
- No forked verify/outcome logic; no memory auto-created on close; strong
  concurrency guard on every transition.
- Commit format `dayN: <step> — <what works now>`, one step per commit, body has
  the `pytest -q` summary.

## 7. Test matrix (minimum)

| Area | Must-have tests |
|------|-----------------|
| Migration | fresh→8; 7→8 preserves rows; readonly rejects v7 |
| Lifecycle | start; double-start refused; close; abandon; internal terminal transition idempotence; abandon-when-open |
| Attachment | run ingested under open task gets `task_id`; run with no task gets NULL; **tasks-absent ingest byte-identical** |
| Concurrency | racing close vs abandon resolves via rowcount guard (no lost update) |
| Bridge | close-from-verify == standalone outcome mark-from-verify reason codes |
| Read view | shape + schema_version; adversarial leak seed; read-only no-migrate |
| Backward compat | every pre-existing run/outcome test still passes unchanged |

## 8. Resolved v0 decisions

1. **Representative run for `close`:** use the most recent attached run; if none,
   `close` records a task-level outcome with `status` only and no verify bridge.
2. **Second `task start` while one is open:** hard error; no auto-close and no
   `--force` supersede in v0.
3. **`eval`/memory `extract`:** stay run-keyed in this stage; task-aware eval is a
   later step.

## 9. Explicitly OUT of scope (do not build here)

- **Multi-agent handoff.** The `runs.engine` column already lets different engines'
  runs sit under one task, but cross-agent handoff *protocol*, ownership transfer,
  and "who holds the task now" are a later step. Build the single-task loop first;
  let a real second-engine handoff need reshape it (same YAGNI discipline that kept
  OmniBridge clean).
- **Permission tiers, scheduling, assignees, priorities, blocked/paused states.**
- **Any dashboard/TUI/console** (Stage ④).
- **Auto-creating memory or auto-inferring success on close** — banned by §2.4.
- **A second `task_type` enum** — reuse the existing one (anti-pattern #9).
