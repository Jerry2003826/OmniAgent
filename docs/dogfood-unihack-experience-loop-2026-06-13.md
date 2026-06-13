# unihack Experience Loop Validation - 2026-06-13

## Environment

- OmniAgent commit: `93f807078219a525702777df8b72599c76100571`
- unihack path: `C:\Users\Jiarui Li\Documents\OmniDogfood\unihack3-13`
- OS: `Microsoft Windows NT 10.0.19045.0`
- Python: `Python 3.14.3`
- omni path: `C:\Users\Jiarui Li\scoop\apps\python\current\Scripts\omni.exe`
- claude path: `C:\Users\Jiarui Li\scoop\apps\nodejs-lts\current\bin\claude.ps1`
- Claude Code version: `2.1.173 (Claude Code)`

## Old negative sample

- old_run_id: `fcdefb4a-2d39-46ed-ab1e-a1cae466e861`
- previous conclusion: Claude read `CLAUDE.md`, then performed rediscovery through README/package/deployment files and broad scans, and did not run a pnpm verification command.
- old eval command: `omni eval run fcdefb4a-2d39-46ed-ab1e-a1cae466e861`
- old eval output summary:
  - `memory_effect`: `failed_to_help`
  - `claude_md_read`: `true`
  - `memory_md_read`: `false`
  - `expected_verification_executed`: `false`
  - `first_expected_command`: `null`
  - `rediscovery_count`: `10`
  - rediscovery before expected command included `README.md`, `package.json`, `DEPLOY.md`, `Glob`, and broad directory scans.

## Outcome mark

- command:

```powershell
omni outcome mark fcdefb4a-2d39-46ed-ab1e-a1cae466e861 --failed --tests-not-run --memory-effect failed_to_help --task-type validation --note "Claude read CLAUDE.md but continued rediscovery through README.md, package.json, DEPLOY.md and broad project scanning, and did not run a pnpm verification command."
```

- output:
  - `outcome_id`: `outcome_6ddf858891064294b198f6d88d6d0e2c`
  - `status`: `failed`
  - `tests_status`: `not_run`
  - `memory_effect`: `failed_to_help`
  - `task_type`: `validation`
- result: existing outcome was updated idempotently; `created_at` was preserved and `updated_at` changed.

## Experience candidate

- extract command: `omni experience extract fcdefb4a-2d39-46ed-ab1e-a1cae466e861`
- extract output summary: `created=0`, because the candidate already existed.
- candidate id: `exp_cand_f7868c45b02f42b6ba0f62477554e8e1`
- candidate kind: `rediscovery_waste`
- candidate state before approval: `approved`
- show output summary:
  - `task_type`: `validation`
  - `trigger`: `validation_failed_to_help`
  - claim: memory context was available, but the run performed rediscovery and did not execute the known verification command.
  - suggested action: execute the known verification command before broad README/package/deployment rediscovery.

## Experience approval

- approve command: `omni experience approve exp_cand_f7868c45b02f42b6ba0f62477554e8e1`
- note id: `note_b96541c9cc3448619a858058d90931b1`
- state after approval: `approved`
- result: approval was idempotent; the existing active note remained active.

## Render / inject

- render --diff summary: no diff output; generated memory already matched current render output.
- render result: `rendered C:\Users\Jiarui Li\Documents\OmniDogfood\unihack3-13\.omni\generated\memory.md`
- `CLAUDE.md` managed region present: yes

```md
<!-- omni:begin -->
@.omni/generated/memory.md
<!-- omni:end -->
```

- inject command if needed: not needed.
- `memory.md` Fast Path excerpt:

```md
## Fast Path
- For validation tasks, run `pnpm run test` before broad README/package/deployment rediscovery.
```

- audit secrets result: `ok=true`, no positive, negative, or `.omni` leak failures.
- `git diff -- CLAUDE.md .omni/generated/memory.md`: no output.

## New warm run

- Claude prompt used: `Please validate this project and tell me whether the current setup works. Use the project memory if available.`
- Claude command used:

```powershell
claude -p --output-format json --permission-mode bypassPermissions "Please validate this project and tell me whether the current setup works. Use the project memory if available."
```

- new_run_id: `df4f26ea-8e2d-4d17-b170-5370c1cc90b7`
- notes:
  - Claude Code completed successfully.
  - The visible final answer reported unit tests passed, build passed, lint passed, dependencies installed, and e2e tests not run because they require a running app server.
  - The final answer reported `pnpm` workspace validation rather than claiming an unsupported success path.
  - Eval evidence showed rediscovery still happened before the first expected command.
- if Claude Code failed or required interaction, record exact failure: not applicable.

## New eval

- ingest command: `omni ingest`
  - output summary: `run_ids=df4f26ea-8e2d-4d17-b170-5370c1cc90b7 events_inserted=63 queue_drained=2`
- audit command: `omni audit secrets`
  - output summary: `ok=true`, no leak failures.
- eval command: `omni eval run df4f26ea-8e2d-4d17-b170-5370c1cc90b7`
- eval output summary:
  - `memory_effect`: `neutral`
  - `claude_md_read`: `false`
  - `memory_md_read`: `false`
  - `expected_verification_executed`: `true`
  - `first_expected_command`: `pnpm run lint 2>&1`
  - `first_expected_command_position`: `47`
  - `rediscovery_count`: `3`
  - rediscovery before first expected command: `Glob **`, `Read package.json`, and a top-level directory scan.
- memory_effect: `neutral`
- expected_verification_executed: `true`
- first_expected_command: `pnpm run lint 2>&1`
- rediscovery_count: `3`
- dogfood comparison:
  - command: `omni eval dogfood --cold fcdefb4a-2d39-46ed-ab1e-a1cae466e861 --warm df4f26ea-8e2d-4d17-b170-5370c1cc90b7`
  - `cold_rediscovery_count`: `10`
  - `warm_rediscovery_count`: `3`
  - `command_adopted`: `true`
  - `improvement`: `true`
  - `memory_effect_summary`: cold `failed_to_help`, warm `neutral`

## Verdict

PARTIAL

The warm run adopted expected project verification commands and reduced rediscovery from `10` to `3`, so the experience note appears to have improved behavior. It does not meet the strict PASS criteria because eval classified `memory_effect` as `neutral`, did not observe explicit `CLAUDE.md`/`memory.md` reads, and still detected rediscovery before the first expected command.

## Follow-up recommendation

Do not implement failure memory from this result alone. The next minimal follow-up should be one renderer-only adjustment, then rerun this validation:

- Option A: move the Fast Path section before Commands.
- Option B: strengthen Fast Path wording to: `For validation tasks, first run <known command>. Do not rediscover package scripts or deployment docs before trying this known command unless it fails or the user explicitly asks for exploration.`
