# CLI-only Claude Code v1 Closeout

Date: 2026-06-15

## Local Verification

- `pytest -q`: 480 passed, 3 skipped, 1 warning
- `omni audit secrets`: `ok=true`
- `git diff --check`: no whitespace errors
- `pytest -q tests/test_cli_help.py`: 3 passed, 1 warning
- `pytest -q tests/test_cli_only_smoke.py`: 1 passed, 1 warning
- `pytest -q tests/test_eval.py`: 40 passed, 1 warning

## Public CLI Smoke

`scripts/cli_only_smoke.py` exercised only public commands in a temporary
project:

```powershell
omni init
omni audit secrets
omni status
omni render --diff
omni render
```

The smoke passed and confirmed `.omni/generated/memory.md` was rendered.

## Real Dogfood Target

Target project:

```text
C:\Users\Jiarui Li\Documents\OmniDogfood\unihack3-13
```

Safety gates before the Claude Code run:

- target `git status`: clean on `main...origin/main`
- `omni audit secrets`: `ok=true`
- `omni status`: `ok=true`, `claude_link=true`, `database=true`,
  `generated_memory=true`
- `CLAUDE.md` contained the managed OmniMemory link region
- `.omni/generated/memory.md` was rendered before the run

The active memory contained a Fast Path instruction requiring validation tasks
to first run `pnpm run test`, with `pnpm run build` and `pnpm run lint` only
after tests pass.

## Claude Code Run

Prompt:

```text
Please validate this project and tell me whether the current setup works. Use the project memory if available.
```

Run id:

```text
ff781e76-5063-40de-b0e3-f7496d30678a
```

Claude Code reported:

- `pnpm run test`: 21 test files passed, 97 tests passed, 1 file / 5 tests
  skipped
- `pnpm run build`: API and web apps compiled successfully
- `pnpm run lint`: no lint errors

`omni ingest` result:

```text
run_ids=ff781e76-5063-40de-b0e3-f7496d30678a events_inserted=26 queue_drained=2
```

## Eval Evidence

Cold run:

```text
fcdefb4a-2d39-46ed-ab1e-a1cae466e861
```

Warm run:

```text
ff781e76-5063-40de-b0e3-f7496d30678a
```

`omni eval run ff781e76-5063-40de-b0e3-f7496d30678a`:

- `expected_verification_executed=true`
- `first_expected_command=pnpm run test`
- `first_expected_command_position=18`
- `rediscovery_count=0`
- `rediscovery_events_before_first_expected_command=[]`
- `memory_effect=neutral`
- reason: expected command executed before rediscovery, but explicit memory read
  was not observable

Observed command order:

1. `pnpm run test`
2. `pnpm run build`
3. `pnpm run lint`

`omni eval dogfood --cold fcdefb4a-2d39-46ed-ab1e-a1cae466e861 --warm ff781e76-5063-40de-b0e3-f7496d30678a`:

- `cold_rediscovery_count=10`
- `warm_rediscovery_count=0`
- `cold_first_expected_command_position=null`
- `warm_first_expected_command_position=18`
- `command_adopted=true`
- `improvement=true`
- cold `memory_effect=failed_to_help`
- warm `memory_effect=neutral`

Single-run `memory_effect` stayed neutral because Claude Code did not emit a
detectable `Read` event for `CLAUDE.md` or `.omni/generated/memory.md`. The
cold/warm comparison is the stronger behavior metric.

## Outcome Anchor

`omni verify` selected `pnpm run test` and passed with exit code 0.

`omni outcome mark-from-verify ff781e76-5063-40de-b0e3-f7496d30678a --task-type validation` wrote:

- `tests_status=passed`
- `status=unknown`
- `memory_effect=neutral`
- `final_command=pnpm run test`
- verify evidence with no stdout/stderr excerpts

`omni audit secrets` passed after the outcome write.

## Candidate Extraction

Post-run extraction:

- `omni experience extract ff781e76-5063-40de-b0e3-f7496d30678a`: `created=0`
- `omni failure extract ff781e76-5063-40de-b0e3-f7496d30678a`: `created=0`

This run created no new experience or failure candidates. Historical pending
failure candidates still exist in the target database, but they are unrelated
to this run.

## Evaluator Hardening From Dogfood

The first eval pass exposed a real parser gap: Claude Code executed shell
commands as:

```text
cd "<project>" && pnpm run test
```

Behavior Eval originally did not strip this leading directory-change wrapper,
so it failed to recognize the expected command and incorrectly reported
`expected_verification_executed=false`. The fix normalizes leading `cd`,
`chdir`, or `pushd` segments before command matching and broad-scan detection.
Regression tests now cover:

- `cd "<path>" && pnpm run test`
- `cd /tmp/project && pnpm run test -- --watch=false`
- `cd /tmp/project && pnpm test`
- `cd /tmp/project && npm test` remains a non-match
- `cd /tmp/project && rg --files` remains broad-scan rediscovery

## Verdict

PASS.

The CLI-only Claude Code v1 path is executable end to end for the current local
workflow:

1. memory rendered into Claude context,
2. Claude Code adopted the expected verification command,
3. no pre-command rediscovery occurred,
4. verify passed,
5. the outcome was anchored through `mark-from-verify`,
6. audit remained clean,
7. dogfood comparison showed improvement from rediscovery 10 to 0.
