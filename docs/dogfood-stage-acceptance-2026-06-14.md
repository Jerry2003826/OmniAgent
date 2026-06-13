# Stage Dogfood Acceptance - 2026-06-14

This record packages the latest real-project dogfood evidence for the current
OmniMemory stage after Failure Lifecycle UX v0.

It does not add a new Claude Code run.

It replays the acceptance commands against the existing unihack dogfood
database and records whether the current loop is still supported by real
evidence.

The claim is deliberately narrow: this target has evidence that rendered memory
changed behavior in a comparable cold/warm pair. It is not universal causal
proof for all agents, tasks, or projects.

## Scope

Included surfaces:

- Behavior Eval
- Outcome Log
- Experience Notes renderer
- Failure Patterns and Known Failures renderer
- Failure Pattern Lifecycle UX output
- Verify preflight

Excluded surfaces:

- MCP
- vector search
- dashboard UI
- adapters
- Computer Use
- LLM extractors
- Soul runtime
- automatic success inference
- automatic failure memory
- automatic memory evolution
- new database tables

## Revisions

OmniMemory checkout under test before this record:

```text
main / origin/main: de6b4ecb106da8a1961f381a8789dab00d41fc4c
```

Target project:

```text
C:\Users\Jiarui Li\Documents\OmniDogfood\unihack3-13
target git HEAD: 8ba1c9fc896ed4da9d17a1c537573d0bb9daa870
target branch: main...origin/main
```

Runs:

```text
old negative run: fcdefb4a-2d39-46ed-ab1e-a1cae466e861
latest warm run: 87722242-c373-4713-abe9-4288edc71982
prompt: Please validate this project and tell me whether the current setup works. Use the project memory if available.
```

## Gates

OmniMemory checkout:

```text
where omni: C:\Users\Jiarui Li\scoop\apps\python\current\Scripts\omni.exe
omni audit secrets: ok=true
```

Target project:

```text
omni audit secrets: ok=true
omni status: ok=true, claude_link=true, generated_memory=true, database=true
hook elapsed: p50=1ms, p95=4ms
git status: main...origin/main
```

The target audit gate passed before reading or evaluating real project memory.

## Memory State

Commands:

```bash
omni render --diff
git diff -- CLAUDE.md .omni/generated/memory.md
Select-String -Path CLAUDE.md -Pattern "omni:begin|\.omni/generated/memory\.md"
Select-String -Path .omni\generated\memory.md -Pattern "^## |pnpm run test|Known Failures|Get-ChildItem"
```

Observed:

```text
omni render --diff: no diff
git diff -- CLAUDE.md .omni/generated/memory.md: no diff
CLAUDE.md:1 <!-- omni:begin -->
CLAUDE.md:2 @.omni/generated/memory.md
memory sections: Fast Path, Commands, Known Failures, Project
```

Current memory highlights:

```text
Fast Path requires `pnpm run test` first for validation tasks.
Known Failures includes `Get-ChildItem -Name` / `Exit code 127` guidance for Bash on Windows.
```

The memory file scan did not surface run ids, candidate ids, pattern ids,
evidence JSON, timestamps, or confidence fields. The word `run` appears only as
part of commands such as `pnpm run test`.

## Behavior Eval

Old negative run:

```text
run_id: fcdefb4a-2d39-46ed-ab1e-a1cae466e861
memory_effect: failed_to_help
claude_md_read: true
memory_md_read: false
expected_verification_executed: false
first_expected_command: null
first_expected_command_position: null
rediscovery_count: 10
rediscovery kinds: broad_scan, README.md, package.json, DEPLOY.md
reason: memory context was seen; expected pnpm commands existed; no expected verification command executed; rediscovery occurred before any expected command
```

Latest warm run:

```text
run_id: 87722242-c373-4713-abe9-4288edc71982
memory_effect: neutral
claude_md_read: false
memory_md_read: false
expected_verification_executed: true
first_expected_command: pnpm run test
first_expected_command_position: 17
rediscovery_count: 0
rediscovery_before_expected_command: none
observed expected commands: pnpm run test, pnpm run build, pnpm run lint
reason: expected command executed before rediscovery, but memory context was not observed as an explicit read event
```

Dogfood comparison:

```text
command: omni eval dogfood --cold fcdefb4a-2d39-46ed-ab1e-a1cae466e861 --warm 87722242-c373-4713-abe9-4288edc71982
cold_comparable: true
cold_rediscovery_count: 10
warm_rediscovery_count: 0
cold_first_expected_command_position: null
warm_first_expected_command_position: 17
command_adopted: true
improvement: true
memory_effect_summary: cold failed_to_help, warm neutral
```

The single warm run remains `neutral` because the trace did not expose an
explicit `CLAUDE.md` or `memory.md` read. The cold/warm comparison is the
stronger behavior metric here.

## Verify and Outcome

Command:

```bash
omni verify
```

Observed:

```text
status: passed
reason_code: passed
command: pnpm run test
qualifier: node
selection_mode: auto
selection_reason: selected active uses_test_command fact
exit_code: 0
target test summary: 21 files passed, 1 skipped; 97 tests passed, 5 skipped
```

Existing outcome for the warm run:

```text
run_id: 87722242-c373-4713-abe9-4288edc71982
status: success
tests_status: passed
memory_effect: neutral
task_type: validation
final_command: pnpm run test
source: user
```

This record did not rerun `omni outcome mark-from-verify` because the historical
outcome was already marked and the goal was to package evidence without
mutating the dogfood run state.

## Failure Pattern Lifecycle

Command:

```bash
omni failure pattern ls
```

Observed active pattern summary:

```text
pattern: Get-ChildItem -Name / Exit code 127
status: active
summary: Claude Code Bash executed a PowerShell cmdlet while listing project files.
suggested_action: use POSIX shell commands such as ls, find, or test -f instead of PowerShell cmdlets.
lifecycle.renders: true
lifecycle.can_retire: true
lifecycle.can_reactivate: false
lifecycle.supersede_supported: false
lifecycle.message: active pattern renders into memory.md; retire it to stop rendering
```

This confirms the lifecycle UX change is visible in the real dogfood database.
The pattern was not retired because it remains the active Known Failure memory
used for future behavior checks.

## Verdict

Verdict: PASS

Reasons:

- The old negative run remains a clear `failed_to_help` sample.
- The latest comparable warm run adopted the expected verification command.
- The first expected command was `pnpm run test`.
- Rediscovery dropped from 10 events to 0.
- `omni verify` selected and passed the same project-level verification command.
- The warm outcome is marked `success` with `tests_status=passed`.
- The active Known Failure pattern is visible, renders into memory, and has
  clear retire-only lifecycle metadata.
- `omni audit secrets` passed in both the OmniMemory checkout and target project.

Limits:

- This record packages an existing real run; it does not create a new Claude
  Code warm run.
- Single-run `memory_effect` is conservative and remains `neutral` when memory
  import is not observable as an explicit read event.
- This is project-local dogfood evidence, not a universal proof for all future
  tasks.

Recommended next step:

```text
No immediate code change is required. For the next product stage, run a fresh
Claude Code warm run from this main commit before claiming behavior for any new
memory feature.
```
