# OmniAgent Phase B (OmniMemory → OmniAgent transition)

## Goal

**Completed:** OmniMemory CLI-only Claude Code v1 (Layers 1–5). See
`docs/cli-only-claude-code-v1-l1-5-completion-2026-06-15.md`.

**Current phase:** OmniAgent Phase B — governed expansion per
`docs/omniagent-phase-b-charter-2026-06-15.md`.

Build ONE closed loop (unchanged):

Claude Code run → redacted trace → deterministic facts → generated memory block → measurably changed behavior in the next run.

Phase B adds, without breaking safety invariants:

- interactive fact review and read-only doctor diagnostics
- task/profile-aware verify selection (still read-only)
- one new review-gated memory type at a time (preference first)
- multi-project read-only status overview

## Non-goals, hard this phase

NO LLM extractors.  
NO MCP server.  
NO vector or embedding search.  
NO dashboard or TUI.  
NO multi-engine router.  
NO Computer Use.  
NO automatic evolution.  
NO answer cache.  
No new tables beyond approved migrations for the current phase. Approved now:
001_init.sql through 006_failure_patterns.sql, plus 007+ only as listed in
`docs/omniagent-phase-b-charter-2026-06-15.md`.

Phase B approved (charter section 3):

- `omni review interactive` (human-gated fact candidate review)
- `omni doctor` (read-only project diagnostics)
- `omni verify --task` / `--profile` (read-only selection mapping)
- `007_preference_memory.sql` and `omni preference *` (Sub-C)
- `omni project register|ls` and `omni status --all` (read-only multi-project)

Still deferred beyond Phase B:

- observed_command extractor
- additional memory types beyond the one approved Sub-C type
- Layer 6–9 (task runtime, multi-agent orchestration, permission tiers, UI)

If a task needs something outside the charter, STOP and leave a TODO comment.
`scripts/golden_demo.sh` may exist as a local sandbox harness; manual acceptance
remains the runbook in `docs/demo.md` and Phase B closeout notes.

## Safety rules

Violations require reverting the commit.

1. REDACTION-BEFORE-WRITE, from Day 1:
   every content byte written under `.omni/` MUST pass `redact.redact(bytes)`.
   This includes spike dumps and spool lines.
   There is NO raw-dump path anywhere, not even `/tmp`.
   There is no original vault.
   Redaction is irreversible.
   In spike-dump mode, if the redactor fails, write a stub:
   `{error, payload_sha256, byte_len}` instead of content.

2. `omni hook` ALWAYS exits 0.
   It never blocks.
   It never makes permission decisions.
   It only redacts and appends to `.omni/spool/`.
   It records its own `elapsed_ms` into the spool line meta.
   Errors go to `.omni/spool/_errors.log` on a best-effort basis.
   The process still exits 0.

3. Hooks never write the DB.
   Stop and SessionEnd hooks only write redacted ingest request files under:
   `.omni/spool/`.

   Legacy `.omni/spool/ingest_queue.jsonl` is read best-effort for migration,
   but new hooks do not append to it.

   Only these commands write SQLite:
   - `omni ingest`
   - `omni review`
   - `omni review interactive`
   - `omni render`
   - `omni outcome mark`
   - `omni outcome mark-from-verify`
   - `omni experience extract`
   - `omni experience approve`
   - `omni experience reject`
   - `omni experience note retire`
   - `omni failure extract`
   - `omni failure approve`
   - `omni failure reject`
   - `omni failure pattern retire`
   - `omni preference extract`
   - `omni preference approve`
   - `omni preference reject`
   - `omni preference note retire`
   - `omni project register`

   These commands are read-only:
   - `omni parse`
   - `omni run show`
   - `omni status`
   - `omni status --all`
   - `omni doctor`
   - `omni eval run`
   - `omni eval dogfood`
   - `omni dogfood`
   - `omni outcome show`
   - `omni outcome ls`
   - `omni experience ls`
   - `omni experience show`
   - `omni experience note ls`
   - `omni experience note show`
   - `omni failure ls`
   - `omni failure show`
   - `omni failure pattern ls`
   - `omni failure pattern show`
   - `omni preference ls`
   - `omni preference show`
   - `omni preference note ls`
   - `omni preference note show`
   - `omni project ls`
   - `omni verify`

   Read-only commands open SQLite in read-only mode and never run
   migrations; migrations run only inside approved write commands.
   `omni verify` is SQLite read-only but executes the selected project
   verification command, including when `--qualifier`, `--task`, or
   `--profile` is used; it writes no OmniMemory state.
   `omni doctor` and `omni status --all` do not open project SQLite at all
   when reporting aggregate health (doctor opens read-only for schema checks
   on the current project only).

4. Never modify user content in `CLAUDE.md` outside the managed region:

   ```md
   <!-- omni:begin -->
   @.omni/generated/memory.md
   <!-- omni:end -->
   ```

5. `omni init` creates `.omni/` only.
   Bare `omni init` may ensure exactly one gitignore entry: `.omni/`.
   Routine commands such as `omni ingest` and `omni audit secrets` must not
   modify `.gitignore` or other user files while ensuring the `.omni/` layout.
   Installing hooks into project-level `.claude/settings.json` requires:

   ```bash
   omni init --install-claude-hooks
   ```

   This command must:
   - print a redacted diff
   - ensure hook-owned gitignore entries for `.claude/*.omni-tmp` and
     `.claude/settings.json.omni-bak`
   - write `.claude/settings.json` with atomic temp-file replace
   - not create a raw settings backup by default
   - never touch global `~/.claude/settings.json`

   If `omni audit secrets` has never passed in this checkout, installing hooks additionally requires `--yes`.

6. Real projects are FORBIDDEN until `omni audit secrets` exits 0.
   Default manual testing happens in `scripts/create_sandbox.sh` repos. Real
   dogfood acceptance may run only as an explicit Dogfood Acceptance Pack task
   after `omni audit secrets` passes in both the OmniMemory checkout and the
   target project.

## Environment and commands

- Python >= 3.11
- Runtime: Python stdlib only
- Dev dependency: pytest only

Install:

```bash
pip install -e ".[dev]"
```

Test:

```bash
pytest -q
```

Run tests before every commit.

DB pragmas are set in `db.connect()`, not in migrations:

```sql
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;
PRAGMA foreign_keys=ON;
```

## Implementation order

Do not reorder.

1. Skeleton:
   - `pyproject.toml`
   - `omni` entrypoint
   - `config.py`
   - `ids.py`
   - `omni init`

2. `redact.py` MINIMAL:
   - env reverse lookup
   - regex pack
   - fail-closed / stub behavior
   - tests

3. `hook.py`:
   - stdin → `redact_minimal` → spike dump / spool
   - `omni init --install-claude-hooks`
   - `scripts/create_sandbox.sh`

4. `migrations/001_init.sql`:
   - migration runner
   - `db.py`

5. `parse.py`:
   - transcript JSONL → normalized events
   - unknown lines → redacted `transcript_archive`

6. `store.py`, `spool.py`, `ingest.py`:
   - content-addressed artifact store
   - ingest queue
   - reconcile by `tool_use_id`
   - `duration_ms`
   - watchdog
   - `omni run show`

7. `redact.py` FULL:
   - entropy detector
   - skip list
   - allowlists
   - fixtures corpus
   - `omni audit secrets`
   - scan the ENTIRE `.omni/` tree, including `spike/` and `spool/`

8. Extractors and gate:
   - `extract/pm.py`
   - `extract/scripts.py`
   - `gate.py`
   - non-interactive `omni review approve|reject <id>`

9. Renderer and injection:
   - `render.py`
   - `inject.py`
   - `omni render`
   - `omni inject claude`

10. Docs:
   - `docs/demo.md`
   - manual cold/warm procedure
   - G6 robust criterion
   - final definition-of-done checklist

## Codex working agreement

One step = one commit.

Commit message format:

```text
dayN: <step> — <what works now>
```

Commit body must include the `pytest -q` summary.

When Claude Code hook or transcript behavior is UNKNOWN:
- do not invent fields
- unknown keys go to `events.meta`
- unknown transcript lines go to redacted `transcript_archive`
- the human runs the spike and fills `docs/spike-report-template.md`
- code adapts only to recorded facts

## Week-1 Definition of Done

- `pytest -q` green
- redaction positives: 100% recall on curated fixtures
- redaction negatives: 0 false positives on curated negative corpus
- no open-world false-positive claim
- `omni audit secrets` exits 0 on the sandbox after a real session
- full `.omni/` tree scan passes
- manual cold/warm demo passes per `docs/demo.md`
- warm run satisfies G6 ROBUST criterion on 3/3 golden tasks
- `golden_demo.sh` is optional harness coverage only; manual `docs/demo.md`
  acceptance remains authoritative
