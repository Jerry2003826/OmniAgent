# OmniMemory v0.2 / Experience Memory foundations

## Goal

Current phase: OmniMemory v0.2 / Experience Memory foundations.

Build ONE closed loop:

Claude Code run → redacted trace → deterministic facts → generated memory block → measurably changed behavior in the next run.

## Non-goals, hard this week

NO LLM extractors.  
NO MCP server.  
NO vector or embedding search.  
NO dashboard or TUI.  
NO multi-engine router.  
NO Computer Use.  
NO automatic evolution.  
NO answer cache.  
No new tables beyond approved migrations for the current phase. Approved now: 001_init.sql, 002_outcomes.sql, 003_experience_candidates.sql, 004_experience_notes.sql, 005_failure_candidates.sql, and 006_failure_patterns.sql.

Day-5B items are week-2 unless Day-5A acceptance passes early:
- observed_command extractor
- interactive review loop
- omni doctor

If a task seems to need any of these, STOP and leave a TODO comment instead.
`scripts/golden_demo.sh` may exist as a local sandbox harness, but Week-1
acceptance remains the manual runbook in `docs/demo.md`.

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
   - `omni render`
   - `omni outcome mark`
   - `omni outcome mark-from-verify`
   - `omni experience extract`
   - `omni experience approve`
   - `omni experience reject`
   - `omni failure extract`
   - `omni failure approve`
   - `omni failure reject`
   - `omni failure pattern retire`

   These commands are read-only:
   - `omni parse`
   - `omni run show`
   - `omni status`
   - `omni eval run`
   - `omni eval dogfood`
   - `omni outcome show`
   - `omni experience ls`
   - `omni experience show`
   - `omni failure ls`
   - `omni failure show`
   - `omni failure pattern ls`
   - `omni failure pattern show`
   - `omni verify`

   Read-only commands open SQLite in read-only mode and never run
   migrations; migrations run only inside approved write commands.
   `omni verify` is SQLite read-only but executes the selected project
   verification command; it writes no OmniMemory state.

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
   All manual testing happens in `scripts/create_sandbox.sh` repos.

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
