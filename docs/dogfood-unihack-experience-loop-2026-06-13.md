# unihack Experience Loop Validation - 2026-06-13

## Environment

- OmniAgent commit: `93f807078219a525702777df8b72599c76100571`
- renderer tuning commit: `395b094a726e5b09e6afb0b8aaccdd0ed54f044e`
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

## Renderer tuning rerun

- renderer tuning commit: `395b094a726e5b09e6afb0b8aaccdd0ed54f044e`
- tuning applied:
  - `Fast Path` now renders before `Commands`.
  - validation `rediscovery_waste` notes use stronger first-run wording.
- tuned `memory.md` Fast Path excerpt:

```md
## Fast Path
- For validation tasks, the first shell command must be `pnpm run test`. Do not run `pnpm run build` or `pnpm run lint` before `pnpm run test`. Do not run broad file scans such as `Glob **`, `ls`, `find`, `tree`, or `rg --files` before this command. Do not inspect package scripts, README, deployment docs, or environment files first unless the command fails or the user explicitly asks for configuration-first exploration. After tests pass, run build and lint if broader validation is needed.

## Commands
```

- render command: `omni render`
- audit command: `omni audit secrets`
- audit result: `ok=true`, no positive, negative, or `.omni` leak failures.
- Claude prompt used: `Please validate this project and tell me whether the current setup works. Use the project memory if available.`
- Claude command used:

```powershell
claude -p --output-format json --permission-mode bypassPermissions "Please validate this project and tell me whether the current setup works. Use the project memory if available."
```

- tuned_run_id: `78002123-e450-497d-8c06-6f73919faca5`
- ingest output summary: `run_ids=78002123-e450-497d-8c06-6f73919faca5 events_inserted=24 queue_drained=2`
- eval command: `omni eval run 78002123-e450-497d-8c06-6f73919faca5`
- eval output summary:
  - `memory_effect`: `neutral`
  - `claude_md_read`: `false`
  - `memory_md_read`: `false`
  - `expected_verification_executed`: `true`
  - `first_expected_command`: `pnpm run build`
  - `first_expected_command_position`: `17`
  - observed expected commands: `pnpm run build`, `pnpm run test`, `pnpm run lint`
  - `rediscovery_count`: `0`
  - rediscovery before first expected command: none
- dogfood comparison:
  - command: `omni eval dogfood --cold fcdefb4a-2d39-46ed-ab1e-a1cae466e861 --warm 78002123-e450-497d-8c06-6f73919faca5`
  - `cold_rediscovery_count`: `10`
  - `warm_rediscovery_count`: `0`
  - `command_adopted`: `true`
  - `improvement`: `true`
  - `memory_effect_summary`: cold `failed_to_help`, warm `neutral`

## Post-merge test-first renderer rerun

- renderer retune merge commit: `3b0c1946ee8ff0bf9f4292215d9161dc311becf6`
- Fast Path excerpt rendered into `.omni/generated/memory.md`:

```md
## Fast Path
- For validation tasks, the first shell command must be `pnpm run test`. Do not run `pnpm run build` or `pnpm run lint` before `pnpm run test`. Do not run broad file scans such as `Glob **`, `ls`, `find`, `tree`, or `rg --files` before this command. Do not inspect package scripts, README, deployment docs, or environment files first unless the command fails or the user explicitly asks for configuration-first exploration. After tests pass, run `pnpm run build` and `pnpm run lint` if broader validation is needed.
```

- render command: `omni render`
- audit command: `omni audit secrets`
- audit result: `ok=true`, no positive, negative, or `.omni` leak failures.
- Claude prompt used: `Please validate this project and tell me whether the current setup works. Use the project memory if available.`
- Claude command used:

```powershell
claude -p --output-format json --permission-mode bypassPermissions "Please validate this project and tell me whether the current setup works. Use the project memory if available."
```

- test_first_run_id: `87722242-c373-4713-abe9-4288edc71982`
- ingest output summary: `run_ids=87722242-c373-4713-abe9-4288edc71982 events_inserted=24 queue_drained=2`
- eval command: `omni eval run 87722242-c373-4713-abe9-4288edc71982`
- eval output summary:
  - `memory_effect`: `neutral`
  - `claude_md_read`: `false`
  - `memory_md_read`: `false`
  - `expected_verification_executed`: `true`
  - `first_expected_command`: `pnpm run test`
  - `first_expected_command_position`: `17`
  - observed expected commands: `pnpm run test`, `pnpm run build`, `pnpm run lint`
  - `rediscovery_count`: `0`
  - rediscovery before first expected command: none
- dogfood comparison:
  - command: `omni eval dogfood --cold fcdefb4a-2d39-46ed-ab1e-a1cae466e861 --warm 87722242-c373-4713-abe9-4288edc71982`
  - `cold_rediscovery_count`: `10`
  - `warm_rediscovery_count`: `0`
  - `command_adopted`: `true`
  - `improvement`: `true`
  - `memory_effect_summary`: cold `failed_to_help`, warm `neutral`
- outcome command:

```powershell
omni outcome mark 87722242-c373-4713-abe9-4288edc71982 --success --tests-passed --memory-effect neutral --task-type validation --summary "Tuned renderer warm run validated unihack with pnpm test as the first expected command and zero rediscovery before verification." --final-command "pnpm run test" --note "After the renderer retune, Claude ran pnpm run test first, then pnpm run build and pnpm run lint, with rediscovery_count=0 and dogfood improvement=true versus the old negative run."
```

- outcome_id: `outcome_2b2dceabf3ab43d6bfefa74a8472079e`

## Verdict

BEHAVIOR PASS AFTER TUNING

The first warm rerun was `PARTIAL`: it adopted expected project verification commands and reduced rediscovery from `10` to `3`, but still rediscovered project structure before the first expected command.

After renderer tuning, the third warm run executed expected commands before any rediscovery and reduced rediscovery from `10` to `0`, but its first expected command was `pnpm run build`. After the post-merge test-first retune, the next comparable warm run executed `pnpm run test` as the first expected command, then `pnpm run build` and `pnpm run lint`, with `rediscovery_count=0`. Eval still classified `memory_effect` as `neutral` because it did not observe explicit `CLAUDE.md` or `memory.md` reads. The cold/warm dogfood comparison is the stronger behavior metric here and reports `improvement=true`.

## Follow-up recommendation

Experience notes have now shown a real-project behavior improvement after renderer tuning. The next PR can move to Failure Memory v0. Do not add extra CLAUDE.md prompting or merge Fast Path into Commands unless a later rerun regresses.
