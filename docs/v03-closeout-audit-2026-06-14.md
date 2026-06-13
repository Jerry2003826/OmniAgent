# OmniMemory v0.3 Closeout Audit

Date: 2026-06-14 local

Branch base audited: `cd0c4b8559bbf7b5abfd4a2c1a56dedc6e3eb623`

Merged PR: `#25` (`Jiarui/verify-hardening-v03`)

## Scope

This closeout audit covers OmniMemory v0.3 / Verify hardening only.

v0.3 keeps the v0.2 Experience/Failure Memory loop intact and hardens the
read-only verification bridge:

- `omni verify`
- `omni verify --qualifier <qualifier>`
- `omni outcome mark-from-verify <run_id>`
- `omni outcome mark-from-verify <run_id> --qualifier <qualifier>`

It does not add product features. It does not cover MCP, vector search,
dashboard, adapters, Computer Use, LLM extractors, Soul runtime, automatic
evolution, automatic failure memory, or new database tables.

## Main Alignment

The current `main` branch still contains the approved migration set only:

- `001_init.sql`
- `002_outcomes.sql`
- `003_experience_candidates.sql`
- `004_experience_notes.sql`
- `005_failure_candidates.sql`
- `006_failure_patterns.sql`

No v0.3 migration was added.

AGENTS.md, `docs/experience-memory-v0.md`, the CLI route, and the implementation
agree on the v0.3 boundary:

- `omni verify` is SQLite read-only, opens the database through the read-only
  connection path, and never writes OmniMemory state.
- `omni verify` may execute the selected project-level verification command.
- `omni outcome mark-from-verify` is the approved write bridge that records the
  verify result into Outcome Log evidence.
- `--qualifier` selects among active project-level `uses_test_command` facts by
  exact qualifier after trimming surrounding whitespace only. It does not accept
  arbitrary commands.

## Verify Contract

Verify v0.3 returns stable machine-readable JSON fields for humans and scripts:

- `status`
- `reason`
- `reason_code`
- `selection_mode`
- `selection_reason`
- `command`
- `qualifier`
- `exit_code`
- `timed_out`
- `stdout_truncated`
- `stderr_truncated`
- `candidate_commands`
- `candidate_commands_omitted`

Selection failures return `status=unknown` and do not execute a verification
command. Passing commands return `status=passed`. Executed commands that fail,
time out, or cannot start return `status=failed` with a specific reason code.

The reason-code surface includes:

- `passed`
- `failed_exit_code`
- `timed_out`
- `start_failed`
- `no_active_test_command`
- `ambiguous_active_test_command`
- `qualifier_not_found`
- `ambiguous_qualifier`
- `parse_error_empty_command`
- `parse_error_shell_operator`
- `parse_error_shell_wrapper`
- `parse_error_batch_metacharacter`
- `parse_error_invalid_command`

## Safety Confirmations

v0.3 keeps the safety model conservative:

- Verify executes commands without a shell.
- Unquoted shell operators are rejected before execution.
- Shell interpreter wrappers such as `bash -c`, `sh -c`, `cmd /c`, PowerShell
  execution wrappers, and shell delegation through `env` are rejected.
- `env -S`, `env --split-string`, `env --split-string=...`, and `env -S...`
  are rejected as shell-wrapper risk instead of being split and executed.
- Embedded NUL bytes in configured commands are rejected before subprocess
  launch.
- Malformed configured commands return stable parse reason codes and keep the
  JSON output contract.
- Stdout and stderr excerpts are bounded and redacted.
- `outcome mark-from-verify` excludes stdout and stderr excerpts from stored
  evidence.
- Timeout and interruption cleanup attempts to terminate the full process tree
  and falls back to direct process kill where needed.

## Local Verification

Commands run in the repository after the PR was merged into `main`:

```bash
git rev-parse HEAD
git ls-remote origin refs/heads/main
pytest -q
omni audit secrets
```

Results:

- `git rev-parse HEAD`:
  `cd0c4b8559bbf7b5abfd4a2c1a56dedc6e3eb623`.
- `git ls-remote origin refs/heads/main` reported the same commit.
- `pytest -q`: `440 passed, 3 skipped, 1 warning`.
- `omni audit secrets`: `ok=true`, no positive fixture misses, no negative
  fixture failures, and no `.omni` leaks.

## Acceptance Matrix

| Area | Status | Evidence | Boundary |
| --- | --- | --- | --- |
| Qualifier selection | Pass | Tests cover exact qualifier selection, missing qualifier, ambiguous qualifier, whitespace handling, and long qualifier raw matching. | Qualifier is not a scope selector and does not accept arbitrary commands. |
| Stable verify JSON | Pass | Tests cover reason codes, selection fields, truncation booleans, malformed commands, start failures, timeouts, and redaction-safe output. | Existing fields remain for compatibility; new scripts should prefer `reason_code`. |
| Shell-wrapper rejection | Pass | Tests cover direct wrappers and `env` delegation, including `env -S` and `--split-string` forms. | This is preflight hardening over reviewed facts, not a general command sandbox. |
| Outcome bridge | Pass | Tests cover `outcome mark-from-verify` with qualifier and safe evidence storage. | It records verify evidence but still does not infer task success. |
| Read-only boundary | Pass | `omni verify` remains on the read-only SQLite path and writes no OmniMemory state. | It may execute the selected project verification command. |
| Migration governance | Pass | Migration set remains 001-006; no v0.3 tables were added. | Future schema changes require an approved phase and migration. |

## Remaining Non-blocking Items

No blocker or major issue remains for v0.3 closeout.

Possible v0.4 follow-ups:

- `start_failed` keeps CLI exit code `1`; scripts should use
  `reason_code="start_failed"` to distinguish process-start failures.
- Centralize verify reason-code literals into constants or an enum.
- Add a narrow test for a literal empty configured command if future reviewers
  want direct coverage beyond the current parse-error matrix.
- Update `docs/demo.md` if manual acceptance starts using Verify v0.3 as a
  standard step.

## Closeout Verdict

OmniMemory v0.3 / Verify hardening is ready to close.

The defensible claim is narrow: the project now has a read-only verification
preflight with deterministic qualifier selection, stable machine-readable
failure reasons, stronger command preflight rejection, bounded redacted output,
and a separate approved outcome-write bridge. It does not add runtime services,
automatic success inference, automatic memory evolution, or any new storage
schema.
