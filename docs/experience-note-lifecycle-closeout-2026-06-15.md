# Experience Note Lifecycle v1 Closeout

Date: 2026-06-15

## Scope

Experience Note Lifecycle v1 added explicit controls for approved experience
notes:

```bash
omni experience note ls
omni experience note show <note_id>
omni experience note retire <note_id>
```

The phase did not add new tables, migrations, supersede, reactivation,
automatic evolution, or renderer expansion. `note ls` and `note show` are
read-only; `note retire` is the only approved writer in this lifecycle slice.

## Validation

Local validation on `main` after PR #39 merged:

- `pytest -q`: 476 passed, 3 skipped, 1 warning
- `omni audit secrets`: `ok=true`

Temporary-project CLI smoke:

- Created a synthetic active `fast_path` experience note in a temporary
  OmniMemory database.
- `omni experience note ls` returned the active note with
  `lifecycle.renders=true`.
- `omni experience note show <note_id>` returned the note and redacted a
  synthetic GitHub token in evidence.
- `omni render` rendered the active note into `.omni/generated/memory.md`.
- `omni experience note retire <note_id>` changed the note to `retired` with
  `lifecycle.renders=false`.
- `omni experience note ls --status retired` returned the retired note.
- A second `omni render` removed the retired note from `memory.md`.
- The rendered memory file did not contain the note id, source candidate id,
  evidence field, or raw token.

## Result

Verdict: PASS.

Approved experience notes can now be withdrawn from future agent behavior
without deleting evidence or changing the source candidate state. The lifecycle
remains intentionally narrow: retired notes cannot be reactivated in v1, and
supersede remains out of scope.

## Next Recommended Stage

Move to CLI-only Claude Code v1 readiness:

- define the install and first-run path for a Claude Code-only user,
- keep `omni audit secrets` as the real-project gate,
- package the minimum commands for ingest, eval, outcome, experience, failure,
  verify, render, and note/pattern lifecycle,
- avoid adding new memory types until the CLI-only loop is installable and
  explainable end to end.
