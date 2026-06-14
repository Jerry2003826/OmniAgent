# Acceptance Pack v0 Closeout

Date: 2026-06-15 local

## Scope decision

This stage chose **Scope A (docs-only)**. It adds no runtime code.

All acceptance evidence for an already-ingested run is already obtainable from
existing read-only commands (`omni status`, `omni eval run`,
`omni eval dogfood`, `omni verify`, `omni outcome show`) and the two
already-approved write steps (`omni outcome mark-from-verify`,
`omni experience extract`, `omni failure extract`). A new
`omni acceptance` CLI (Scope B) was not added because it would introduce runtime
code without exposing any state the existing read-only commands do not already
provide. Docs-only is the smaller, lower-risk change and is the preferred option.

## What was added

- `docs/acceptance-pack-v0.md`: a deterministic runbook for packaging the
  existing evidence of an already-ingested run. It documents the exact commands
  and expected fields for `omni audit secrets`, `omni status`,
  `omni eval run <run_id>`,
  `omni eval dogfood --cold <cold_run_id> --warm <warm_run_id>`, `omni verify`,
  `omni outcome mark-from-verify <run_id> --task-type validation`,
  `omni outcome show <run_id>`, `omni experience extract <run_id>`, and
  `omni failure extract <run_id>`.
- `tests/test_docs.py`: a guard test asserting the runbook covers the read-only
  vs writer classification, dogfood comparison fields, the verify/outcome bridge,
  the explicit experience/failure extract write status, the neutral
  `memory_effect` caveat, the no-causal-overclaim statement, and the no-new-tables
  / no-new-features boundary.

This complements the existing real-project loop runbook
`docs/dogfood-acceptance-pack-v0.md`, which covers running a fresh warm run.

## Read-only vs writer confirmation

The runbook's classification matches AGENTS.md and the CLI:

- Read-only: `omni status`, `omni eval run`, `omni eval dogfood`,
  `omni outcome show`, and `omni verify` (read-only for OmniMemory state, but it
  executes the selected verification command).
- Approved writers, run explicitly by a human: `omni outcome mark-from-verify`,
  `omni experience extract`, `omni failure extract`.
- `omni audit secrets` is not a SQLite writer; it only writes the existing audit
  marker `.omni/audit/secrets.passed`.

The pack never runs the writers for the human. Experience and failure extract are
explicit human steps, not automatic.

## Required semantics confirmation

1. Acceptance Pack v0 is evidence packaging, not causal proof.
2. A single-run `memory_effect` can remain `neutral` when memory import is not
   observable as an explicit read event.
3. The dogfood cold/warm comparison is the stronger behavior metric.
4. Outcome `status` is user-marked or explicitly `mark-from-verify` anchored;
   there is no automatic task success inference.
5. `omni verify` is read-only for OmniMemory state but executes the selected
   verification command.
6. `omni experience extract` and `omni failure extract` are approved writers and
   must be run explicitly by the human.
7. The acceptance report contains no raw stdout/stderr or artifact payloads.
8. Redaction boundaries are preserved.

## Boundaries held

- No new database tables and no new migrations (still 001-006).
- No new memory types.
- No renderer behavior change.
- No Behavior Eval classification change.
- No MCP, vector search, dashboard, adapters, Computer Use, LLM extractors, Soul
  runtime, supersede, automatic failure memory, or automatic memory evolution.

## Local validation

```bash
pytest -q
omni audit secrets
git diff --check
```

Results:

- `pytest -q`: `459 passed, 3 skipped, 1 warning`.
- `omni audit secrets`: `ok=true`, with empty `positive_failures`,
  `negative_failures`, and `omni_leaks`.
- `git diff --check`: pass.

## Closeout verdict

Acceptance Pack v0 is ready to close. The defensible claim is narrow: the project
now has a deterministic, docs-only runbook for packaging the existing redacted
evidence of an already-ingested run, with an explicit read-only vs writer
boundary, and without adding runtime code, new tables, or any automatic success
inference.
