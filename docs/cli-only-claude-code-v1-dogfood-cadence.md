# CLI-only Claude Code v1 — Dogfood Cadence (Phase B)

This is the repeatable Phase B practice for turning real Claude Code runs into
governance evidence. It does not add product features; it institutionalizes the
existing operator ritual so memory quality stays measurable over time.

`docs/cli-only-claude-code-v1-runbook.md` remains the canonical step reference.
`docs/demo.md` remains the authoritative manual acceptance. This document is the
*when* and *how often*; the runbook is the *how*.

## When to run

- After each real Claude Code validation session on a hooked project.
- At least once on the current dogfood target when memory or the renderer
  changes, so a cold/warm comparison stays available.

Real-project rule (AGENTS.md): never run on a real project until
`omni audit secrets` exits 0 in both the OmniMemory checkout and the target.

## One-command helper

From the target project root, after a Claude Code session:

```powershell
omni ingest            # note the warm run id from run_ids=...
python <omni_checkout>\scripts\dogfood_ritual.py --warm <warm_run_id> --cold <cold_run_id>
```

`scripts/dogfood_ritual.py` runs the ritual through the public CLI and prints a
consolidated JSON report:

```text
ingest -> audit secrets -> eval run -> verify -> outcome mark-from-verify -> eval dogfood
```

It never passes `--success` (task success stays user-marked), writes only through
the approved `ingest` and `outcome mark-from-verify` commands, and adds no new
state. Use `--skip-ingest` if the run is already ingested. Omit `--cold` to skip
the dogfood comparison.

The helper exits non-zero if `audit secrets` is not ok or the run cannot be
evaluated; a failing verification (tests failed) is reported in the summary, not
treated as a helper error.

## What to check each run

- `audit_ok` is `true` (before and after ingest).
- The target working tree was not modified by the Claude run.
- `first_expected_command` is the known verification command and
  `rediscovery_count` is low or zero.
- `dogfood_improvement` is `true` against a comparable cold run.
- `outcome_status` stays `unknown` unless you explicitly confirm task success
  with `omni outcome mark <run_id> --success` (a deliberate, separate step).

## Recording evidence

- For a notable run (new target, renderer change, regression, or a failure
  sample), add a dated evidence note under `docs/`, following the existing
  `cli-only-claude-code-v1-*-2026-06-15.md` records.
- Routine green runs do not each need a doc; record the run id and the headline
  (improvement, rediscovery trend) in your own log.

## On a failing run

1. Inspect the verify summary and the failing command.
2. `omni failure extract <run_id>` to create reviewable candidates.
3. Review and, if valid, `omni failure approve <id> --summary ... --suggested-action ...`.
4. `omni render` to surface a Known Failures line; `omni failure pattern retire`
   to withdraw it later.

## Boundaries

- No automatic execution of Claude Code, no automatic success inference, no LLM
  extractors, no new tables or memory types.
- The cadence is a human practice plus a thin orchestration helper over the
  existing CLI. It stays inside the CLI-only Claude Code v1 boundary.
