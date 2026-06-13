# OmniMemory v0.3 Stage Report

Date: 2026-06-14 local

Current main at report time: `e9dcd798dfe374f48366d72e825930a62beebeb2`

## Summary

OmniMemory v0.3 closed the Verify hardening stage. It did not add product
features, tables, migrations, runtime services, automatic success inference, or
automatic memory evolution.

The stage kept the v0.2 Experience/Failure Memory loop intact and hardened the
manual verification bridge:

- `omni verify`
- `omni verify --qualifier <qualifier>`
- `omni outcome mark-from-verify <run_id>`
- `omni outcome mark-from-verify <run_id> --qualifier <qualifier>`

## What Shipped

PR `#25` added deterministic verify selection and output semantics:

- exact qualifier selection for active project-level `uses_test_command` facts
- stable `reason_code`, `selection_mode`, and `selection_reason`
- bounded stdout/stderr excerpts and truncation booleans
- parse reason codes for malformed configured commands
- conservative shell-wrapper rejection
- explicit rejection for delegated `env -S` / `--split-string` wrapper forms
- embedded NUL rejection before subprocess launch
- timeout and interruption process cleanup hardening
- safe verify evidence in `outcome mark-from-verify`, excluding stdout/stderr
  excerpts

## Final Audit Result

External closeout review found:

- Blocker: none
- Major: none
- Minor: none
- Nit: `start_failed` currently maps to CLI exit code `1`; v0.4 may decide
  whether to keep that behavior or map it to exit code `2`.

The earlier `env -S` / `--split-string` bypass finding was fixed in commit
`9a8186d` and confirmed closed by review.

## Validation Evidence

After PR `#25` was merged, the closeout docs commit recorded:

```bash
pytest -q
omni audit secrets
git diff --check
```

Results:

- `pytest -q`: `440 passed, 3 skipped, 1 warning`
- `omni audit secrets`: `ok=true`
- `git diff --check`: pass
- `origin/main` was confirmed at
  `e9dcd798dfe374f48366d72e825930a62beebeb2`

## Boundaries Preserved

- Approved migrations remain exactly `001` through `006`.
- `omni verify` remains SQLite read-only and does not run migrations.
- `omni verify` may execute the selected project verification command but writes
  no OmniMemory state.
- `omni outcome mark-from-verify` remains the approved write bridge into the
  Outcome Log.
- No MCP, vector search, dashboard, adapters, Computer Use, LLM extractors, Soul
  runtime, automatic evolution, automatic failure memory, or automatic success
  detection were added.

## Verdict

OmniMemory v0.3 is closed.

The defensible claim is narrow: OmniMemory now has a deterministic, read-only
verification preflight with exact qualifier selection, stable machine-readable
reason codes, conservative command preflight rejection, and a separate
reviewable outcome-write bridge.
