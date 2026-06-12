# Week-2 Spike Report

Fill this report only with evidence from human-run Claude Code sandbox
sessions. Do not invent transcript fields. For transcript examples, preserve
keys only and replace every value.

## 1. Environment

| Field | Evidence |
| --- | --- |
| OS | PENDING HUMAN EVIDENCE |
| Python version | PENDING HUMAN EVIDENCE |
| Claude Code version | PENDING HUMAN EVIDENCE |
| OmniMemory commit (`git rev-parse HEAD`) | PENDING HUMAN EVIDENCE |
| Sandbox path | PENDING HUMAN EVIDENCE |
| `omni` on PATH in the claude-launching shell: yes/no | PENDING HUMAN EVIDENCE |
| CLAUDE_PROJECT_DIR observed for hooks: yes/no/value | PENDING HUMAN EVIDENCE |
| `claude doctor` or session-start warnings | PENDING HUMAN EVIDENCE |
| Unknown hook event name warnings in `.claude/settings.json` | PENDING HUMAN EVIDENCE |

## 2. Hook capture matrix

| Event name | Observed yes/no | Required fields present | Notes |
| --- | --- | --- | --- |
| SessionStart | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE |
| UserPromptSubmit | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE |
| PreToolUse | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE |
| PostToolUse | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE |
| PostToolUseFailure | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE |
| PermissionRequest | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE |
| Notification | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE |
| PreCompact | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE |
| SubagentStart | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE |
| SubagentStop | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE |
| Stop | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE |
| SessionEnd | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE |

## 3. Transcript parser matrix

This section closes Week-1 spike sections 3 and 4. Use one example line shape
per row type with KEYS ONLY; all values must be replaced/redacted.

| Observed row type | Example line shape, KEYS ONLY | Parsed yes/no | Archived yes/no | unknown line ratio | tool_use id reconciliation or mismatches |
| --- | --- | --- | --- | --- | --- |
| PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE |

## 4. Bash evidence

| Scenario | Command | exit_code | stdout | stderr | Source: hook, transcript, reconciled |
| --- | --- | --- | --- | --- | --- |
| S1 Bash success | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE |
| S2 Bash failure | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE |
| S10 interrupt Bash | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE |

## 5. File operation evidence

| Operation | Paths visible | Content redacted | Skiplisted read shows withheld stub with envelope intact | Notes |
| --- | --- | --- | --- | --- |
| Read | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE |
| Write | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE |
| Edit | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE |

## 6. Permission / denial behavior

| Scenario | Event names | Denial represented yes/no | Parsed or archived | Notes |
| --- | --- | --- | --- | --- |
| S4 permission deny | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE |
| S5 PreToolUse deny if feasible | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE |

## 7. Subagent behavior

| Field | Evidence |
| --- | --- |
| Subagent support feasible yes/no | PENDING HUMAN EVIDENCE |
| Subagent event names observed | PENDING HUMAN EVIDENCE |
| Sidechain/session identifiers | PENDING HUMAN EVIDENCE |
| tool_use_id collisions across sidechains | PENDING HUMAN EVIDENCE |
| Parser or ingest behavior | PENDING HUMAN EVIDENCE |

## 8. Compact behavior

| Compact type | Occurred yes/no | Event names | Session identity before/after | Notes |
| --- | --- | --- | --- | --- |
| Manual /compact | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE |
| Auto compact if feasible | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE | PENDING HUMAN EVIDENCE |

## 9. Resume behavior

| Field | Evidence |
| --- | --- |
| Same session_id resumed yes/no | PENDING HUMAN EVIDENCE |
| Canonical update, not duplicates | PENDING HUMAN EVIDENCE |
| Re-ingest events_inserted=0 | PENDING HUMAN EVIDENCE |
| Notes | PENDING HUMAN EVIDENCE |

## 10. Crash / missing SessionEnd behavior

| Field | Evidence |
| --- | --- |
| Ingest request file absent yes/no | PENDING HUMAN EVIDENCE |
| Plain `omni ingest` no-op output | PENDING HUMAN EVIDENCE |
| How session id was found | PENDING HUMAN EVIDENCE |
| `omni ingest <session_id>` recovery output | PENDING HUMAN EVIDENCE |
| Scoped recovery consumed only matching session yes/no | PENDING HUMAN EVIDENCE |

## 11. S12 planted secret result

| Check | Result |
| --- | --- |
| raw FAKE_AWS value absent from `.omni/**` | PENDING HUMAN EVIDENCE |
| raw OMNI_FAKE_SECRET absent from `.omni/**` | PENDING HUMAN EVIDENCE |
| raw fake GitHub token absent from `.omni/**` | PENDING HUMAN EVIDENCE |
| withheld stub envelope present for the `.env` read event | PENDING HUMAN EVIDENCE |
| `omni audit secrets` result | PENDING HUMAN EVIDENCE |

## 12. Hook latency

| Metric | Evidence |
| --- | --- |
| in-process capture p50 / p95 / sample count from `omni status` | PENDING HUMAN EVIDENCE |
| process-level latency sampled separately at least once | PENDING HUMAN EVIDENCE |
| G7 in-process p95 under 250 ms yes/no | PENDING HUMAN EVIDENCE |

## 13. Cold / warm demo

| Field | Evidence |
| --- | --- |
| Cold run observations | PENDING HUMAN EVIDENCE |
| Generated `memory.md` summary | PENDING HUMAN EVIDENCE |
| Warm run first matching test command | PENDING HUMAN EVIDENCE |
| Rediscovery events before first correct command | PENDING HUMAN EVIDENCE |
| G6 strict pass/fail | PENDING HUMAN EVIDENCE |
| G6 robust pass/fail | PENDING HUMAN EVIDENCE |

## 14. Go / No-Go decision

| Field | Evidence |
| --- | --- |
| Sandbox pass/fail | PENDING HUMAN EVIDENCE |
| Dogfood pass/fail | PENDING HUMAN EVIDENCE |
| Blockers | PENDING HUMAN EVIDENCE |
| Targeted fixes required | PENDING HUMAN EVIDENCE |
| Decision | PENDING HUMAN EVIDENCE |
