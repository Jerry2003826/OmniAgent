# Verify v0.5 Closeout Audit - 2026-06-14

This closeout covers OmniMemory Verify v0.5 / outcome-from-verify hardening.

Scope stayed narrow:

- `omni verify` remains SQLite read-only and writes no OmniMemory state.
- `omni outcome mark-from-verify` remains the explicit write bridge into
  outcomes.
- No new tables, migrations, memory types, renderer behavior, MCP, vector
  search, dashboard, adapters, Computer Use, LLM extractors, Soul runtime,
  supersede, automatic failure memory, automatic memory evolution, or automatic
  task success inference were added.

## Implementation Audit

Changed surfaces:

- `src/omni/outcome.py`
- `tests/test_outcome.py`
- `tests/test_docs.py`
- `AGENTS.md`
- `docs/experience-memory-v0.md`

The runtime code change is intentionally small: `mark-from-verify` now derives
`tests_status` from the stable verify `reason_code` instead of re-deriving it
from looser status/field shapes.

Contract:

- `reason_code=passed` maps to `tests_status=passed`.
- `reason_code=failed_exit_code` and `reason_code=timed_out` map to
  `tests_status=failed`.
- `reason_code=start_failed`, missing or ambiguous selections, qualifier
  failures, and parse errors map to `tests_status=unknown`.
- Outcome `status` is not inferred from verify. It remains `unknown` unless
  the user explicitly passes `--success`, `--failed`, or `--unknown`.
- Stored verify evidence excludes stdout and stderr excerpts.
- Re-running `mark-from-verify` for the same run updates the existing outcome
  row, preserves `created_at`, and advances `updated_at`.

## Local Verification

Commands run in the OmniMemory checkout:

```text
pytest -q
omni audit secrets
git diff --check
```

Observed:

```text
pytest -q: 457 passed, 3 skipped, 1 warning
omni audit secrets: ok=true
git diff --check: no whitespace errors
```

The three skipped tests are the existing environment-dependent skips. No test
was skipped by v0.5 logic.

## Real Dogfood Check

Target project:

```text
<DOGFOOD_PROJECT>
target git status: main...origin/main
```

Commands run:

```text
omni audit secrets
omni verify
omni outcome mark-from-verify 5bba6758-75e8-4643-bfae-8818bb84f982 --success --task-type validation --summary "Verify v0.5 closeout anchored the final dogfood PASS run through mark-from-verify." --note "Verify v0.5 selected pnpm run test, passed, and mark-from-verify recorded tests_status from reason_code=passed without changing the explicit success status."
omni outcome show 5bba6758-75e8-4643-bfae-8818bb84f982
omni audit secrets
```

Observed verify result:

```text
status: passed
reason_code: passed
command: pnpm run test
qualifier: node
selection_mode: auto
selection_reason: selected active uses_test_command fact
exit_code: 0
```

Observed outcome result:

```text
run_id: 5bba6758-75e8-4643-bfae-8818bb84f982
status: success
tests_status: passed
memory_effect: neutral
task_type: validation
final_command: pnpm run test
evidence.source: verify
evidence.verify.reason_code: passed
evidence.verify.command: pnpm run test
```

The outcome status was `success` only because the command explicitly passed
`--success`. v0.5 did not infer task success from verify.

The stored verify evidence contains bounded selection and command metadata. It
does not include stdout or stderr excerpts. The target audit passed after the
write:

```text
omni audit secrets: ok=true
```

## Findings

Blocker: none.

Major: none.

Minor: none.

Nit:

- No dedicated `docs/verify-v05-*.md` semantics page exists yet; the current
  semantics live in `docs/experience-memory-v0.md` and this closeout. This is
  adequate for v0.5 closeout and can be split later if Verify grows.

## Verdict

READY_TO_CLOSE.

Verify v0.5 is a small hardening pass over the existing verify-to-outcome
bridge. It keeps the read/write boundary intact, improves the tests-status
contract, and preserves the rule that task success is user-marked rather than
automatically inferred.
