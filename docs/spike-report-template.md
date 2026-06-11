# OmniMemory Spike Report

## 1. Environment

- Date:
- OS:
- Python version:
- Claude Code version:
- Repo:
- Sandbox path:

## 2. Hook events observed

| Event | Observed | Required fields present | Notes |
|---|---:|---:|---|
| SessionStart |  |  |  |
| UserPromptSubmit |  |  |  |
| PreToolUse |  |  |  |
| PostToolUse |  |  |  |
| PostToolUseFailure |  |  |  |
| PermissionRequest |  |  |  |
| Notification |  |  |  |
| PreCompact |  |  |  |
| SubagentStart |  |  |  |
| SubagentStop |  |  |  |
| Stop |  |  |  |
| SessionEnd |  |  |  |

## 3. Transcript row types

Observed row types:

```text

```

Unknown row percentage:

```text

```

## 4. Tool-use reconciliation

- hook tool_use_id matches transcript tool_use.id:
- mismatches:
- missing hook events:
- missing transcript events:

## 5. Bash evidence chain

- command available:
- exit code available:
- stdout available:
- stderr available:
- chosen authority source:

## 6. Edit / Write / Read evidence

- file_path available:
- content or diff available:
- sensitive file skip behavior observed:

## 7. Transcript truncation behavior

- long stdout truncated:
- truncation marker:
- hook response more complete:
- chosen strategy:

## 8. Resume behavior

- resume reuses session_id:
- transcript continues or new file:
- parent_run_id decision:

## 9. Subagent behavior

- SubagentStart observed:
- SubagentStop observed:
- agent_transcript_path observed:
- v0 strategy: fold or expand:

## 10. Compaction behavior

- manual /compact observed:
- auto compact observed:
- session_id continuity:
- project CLAUDE.md re-injected after compact:

## 10b. Hook latency

- p50:
- p95:
- sample count:
- O-6 double-fork triggered:

## 10c. Redaction FP observations

- false positives observed:
- detector:
- handling:
- allowlist required:

## 11. G5 / G6 results

- G5 assertions passed:
- A12 deferred:
- G6 strict:
- G6 robust:
- forbidden rediscovery events observed:

## 12. Go / No-Go decision

| Gate | Result | Notes |
|---|---|---|
| G1 |  |  |
| G2 |  |  |
| G3 |  |  |
| G4 |  |  |
| G5 |  |  |
| G6 |  |  |
| G7 |  |  |

## 13. Architecture decisions

- run identity model:
- tool_result authority:
- subagent strategy:
- injection strategy:
- fallback selected:
