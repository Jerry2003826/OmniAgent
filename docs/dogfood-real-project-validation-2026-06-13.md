# OmniMemory Real-Project Dogfood Validation - 2026-06-13

## Objective

Prove OmniMemory is safe and stable in a real small project, and collect evidence
that a later agent run spends less effort rediscovering project basics.

Target project:

- `C:\Users\Jiarui Li\Documents\OmniDogfood\unihack3-13`
- Repository: `Jerry2003826/unihack3-13`
- Validation mode: real local project, personal Claude hooks only

## Gates

Safety gates:

- No tracked `.claude/settings.json`.
- No tracked `CLAUDE.md` memory link.
- Claude hooks installed only in ignored `.claude/settings.local.json`.
- `omni audit secrets` exits 0 before and after agent work.
- `.omni/spool/bad/` and `_errors.log` stay empty after ingest.

Stability gates:

- `omni ingest` can be run twice; second run inserts 0 events.
- `omni render --diff`, `omni render`, and `omni inject claude --mode link`
  complete without unmanaged `CLAUDE.md` changes.
- The project remains clean except intentional local dogfood files ignored by
  Git.

Reduced rediscovery signal:

- Compare agent behavior against prior/cold runs and this warm run.
- Record whether the warm agent still reads `package.json`, lockfiles, or broad
  project structure before choosing verification commands.
- Record the first verification command the agent chooses.

## Run Ledger

### V0 - Start State

Status: pass.

Commands and evidence:

```text
git switch main && git pull --ff-only
  Fast-forwarded to merge commit 8ba1c9f.

git status --short --branch
  ## main...origin/main

git ls-files .claude/settings.json .claude/settings.local.json CLAUDE.md .gitignore
  .gitignore

Test-Path .claude/settings.json
  False
Test-Path .claude/settings.local.json
  True
Test-Path CLAUDE.md
  False before injection

omni audit secrets
  ok: true
  positive_failures: []
  negative_failures: []
  omni_leaks: []

omni init --install-claude-hooks --yes
  Initialized OmniMemory at ...\unihack3-13\.omni

local hook inspection
  settings_json_exists=False
  settings_local_exists=True
  hook_events=12
  omni_hook_handlers=12

omni render --diff
  no diff output

omni render
  rendered ...\unihack3-13\.omni\generated\memory.md

omni inject claude --mode link
  created local CLAUDE.md managed region linking @.omni/generated/memory.md

git status --short --branch --ignored=matching .claude CLAUDE.md .omni .gitignore
  ## main...origin/main
  !! .claude/settings.local.json
  !! .omni/
  !! CLAUDE.md

git status --short --branch
  ## main...origin/main

omni status
  ok: true
  claude_link: true
  generated_memory: true
  hook_elapsed_ms_p50: 1
  hook_elapsed_ms_p95: 6
```

### V1 - Warm Agent Validation

Status: safety/stability pass; reduced-rediscovery signal fail.

Prompt:

```text
你在真实项目 unihack3-13 中做一次只读验证：确认当前中文本地化仍然可用，并运行你认为必要的最小验证命令。不要修改任何文件。最后用中文简短报告：你运行了哪些命令、结果如何、有没有发现需要后续处理的问题。
```

Commands and evidence:

```text
claude --print --input-format text --output-format text --permission-mode bypassPermissions --allowedTools "Bash,Read,Grep,Glob,LS" --max-budget-usd 1
  exit: 0
  elapsed: about 149s
  result: Claude did not run validation commands. It returned a Chinese project
  overview based on README and project files.

omni ingest
  run_ids=fcdefb4a-2d39-46ed-ab1e-a1cae466e861 events_inserted=65 queue_drained=2

omni ingest
  run_ids=fcdefb4a-2d39-46ed-ab1e-a1cae466e861 events_inserted=0 queue_drained=2
  Note: this second ingest was started in parallel with the first and saw the
  same request files. It inserted 0 events but its queue_drained count is not a
  clean sequential idempotency signal.

omni ingest
  run_ids= events_inserted=0 queue_drained=0
  Sequential confirmation after the first two ingests.

omni audit secrets
  ok: true
  positive_failures: []
  negative_failures: []
  omni_leaks: []

omni status
  ok: true
  claude_link: true
  generated_memory: true
  hook_elapsed_ms_p50: 1
  hook_elapsed_ms_p95: 6

spool checks
  .omni/spool/bad: absent
  .omni/spool/_errors.log: absent
  live hook-*.jsonl: none
  live ingest-*.json: none

omni render --diff
  no diff output

omni render
  rendered ...\unihack3-13\.omni\generated\memory.md

omni inject claude --mode link
  no diff output

git status --short --branch
  ## main...origin/main
```

Run ids:

```text
fcdefb4a-2d39-46ed-ab1e-a1cae466e861
```

Rediscovery observations:

```text
Event count: 65
Event types:
  PostToolUse: 9
  PostToolUseFailure: 2
  SessionEnd: 1
  SessionStart: 1
  Stop: 1
  UserPromptSubmit: 1
  assistant/user/attachment/last-prompt/queue-operation: remaining transcript rows

Tool calls:
  Glob: 3
  Read: 4
  PowerShell: 3
  Bash: 1 failed PowerShell command passed through Bash

Tool sequence:
  46 PostToolUse Glob pattern=*.{json,md,ts,js,yaml,yml}
  47 PostToolUse Read path=CLAUDE.md
  48 PostToolUse PowerShell command=Get-ChildItem -Path "." -Directory -Depth 0
  49 PostToolUse Read path=README.md
  50 PostToolUse Read path=package.json
  51 PostToolUse PowerShell command=Get-ChildItem -Path "." -File -Depth 0
  52 PostToolUse Glob pattern=**/*.{json,md,ts,js,yaml,yml}
  53 PostToolUse Glob pattern=.omni/**/*
  54 PostToolUse Read path=DEPLOY.md
  55 PostToolUseFailure PowerShell recursive file listing
  56 PostToolUseFailure Bash with PowerShell command text

First verification command:
  none

Package/lock rediscovery:
  package.json was read despite memory containing package manager and test/build commands.
  pnpm-lock.yaml appeared in top-level file listing output.

Interpretation:
  This warm run is negative evidence for the "less exploration" claim. The agent
  read CLAUDE.md but did not use the memory to jump directly to validation. It
  still performed broad project rediscovery and failed to run the requested
  verification.
```

## Current Assessment

Safety and stability passed for this run: hooks were local-only, audit stayed
green, ingest was durable/idempotent after the clean sequential retry, status was
ok, and the target repository stayed clean.

The reduced-rediscovery goal did not pass on V1. The real warm agent read the
memory link, then still re-read README/package.json/project structure and did
not run any validation command. Current conclusion: OmniMemory is leaving usable
trace and is safe enough to keep dogfooding, but it has not yet proven real
agent exploration reduction in this project.
