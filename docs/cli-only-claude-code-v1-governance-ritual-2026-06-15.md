# CLI-only Claude Code v1 — Real Governance Ritual (unihack3-13)

Date: 2026-06-15

## What this records

Phase B (real-usage quality governance) evidence: one full governance ritual on a
REAL project, exercising the operator path end to end:

```text
warm Claude Code run -> ingest -> eval -> verify -> outcome -> dogfood
```

Unlike the sandbox G6 and failure-loop records, this is a real Claude Code warm
run on the designated dogfood target, not a disposable sandbox. `docs/demo.md`
remains the authoritative manual acceptance path.

## Target and safety gate

- target: `C:\Users\Jiarui Li\Documents\OmniDogfood\unihack3-13`
- `omni audit secrets`: `ok=true` before the run and after ingest (required by
  AGENTS.md before any real-project run).
- `omni status`: ok (`claude_link`, `database`, `generated_memory` all true).
- target `git status --short`: clean BEFORE and AFTER the Claude run — Claude
  modified, staged, or cleaned no source files.
- Only the target `.omni/` was written, through the approved write commands
  (`ingest`, `outcome mark-from-verify`).

## Warm run

- run_id: `d93f997d-0be8-4890-8de1-eba9d2d10511`
- `omni ingest`: `events_inserted=7`, `queue_drained=2`
- Claude exit code: 0

## eval run

| field | value |
|-------|-------|
| `expected_verification_executed` | true |
| `first_expected_command` | `pnpm run test` |
| `first_expected_command_position` | 1 |
| `rediscovery_count` | 0 |
| `rediscovery_events_before_first_expected_command` | [] |
| `claude_md_read` / `memory_md_read` | false / false |
| `memory_effect` | neutral |

reason: expected command executed before rediscovery, but memory context not
observed.

## verify

- `status=passed`, `reason_code=passed`, `command=pnpm run test`, `exit_code=0`.

## outcome (mark-from-verify, no --success)

- `status=unknown` (task success is user-confirmed, never auto-inferred)
- `tests_status=passed` (derived from the verify result)
- `memory_effect=neutral`, `final_command=pnpm run test`

## dogfood (cold `fcdefb4a-2d39-46ed-ab1e-a1cae466e861` vs warm)

| field | value |
|-------|-------|
| `improvement` | true |
| `command_adopted` | true |
| `cold_rediscovery_count` | 10 |
| `warm_rediscovery_count` | 0 |
| `cold_first_expected_command_position` | null |
| `warm_first_expected_command_position` | 1 |
| `cold_comparable` | true |
| `memory_effect` | cold=failed_to_help, warm=neutral |

## Notes

- Outcome `status` stayed `unknown` by design: `mark-from-verify` was run without
  `--success`, so task success was not inferred from a passing verification.
- Single-run `memory_effect` is `neutral` because no explicit `CLAUDE.md` or
  `.omni/generated/memory.md` `Read` event was observed; the cold/warm comparison
  (`improvement=true`, rediscovery 10 -> 0) is the stronger behavior metric.
- This run added no product code, tables, or memory types; it exercised the
  existing CLI on the real target and wrote only redacted `.omni/` state.
