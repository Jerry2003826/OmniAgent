# Week-2 Spike Report

Fill this report only with evidence from human-run Claude Code sandbox
sessions. Do not invent transcript fields. For transcript examples, preserve
keys only and replace every value.

This automated run filled the former `PENDING HUMAN EVIDENCE` slots with
observed CLI sandbox evidence where available; unsupported interactive surfaces
are recorded as not feasible rather than invented.

## 1. Environment

| Field | Evidence |
| --- | --- |
| OS | Microsoft Windows NT 10.0.19045.0 |
| Python version | Python 3.14.3 |
| Claude Code version | 2.1.173 (Claude Code) |
| OmniMemory commit (`git rev-parse HEAD`) | 3693cf1a1862b15d3308509c92589bcbda77230f |
| Sandbox path | C:\Users\Jiarui Li\AppData\Local\Temp\omni-week2-sandbox |
| `omni` on PATH in the claude-launching shell: yes/no | yes: C:\Users\Jiarui Li\scoop\apps\python\current\Scripts\omni.exe |
| CLAUDE_PROJECT_DIR observed for hooks: yes/no/value | no explicit CLAUDE_PROJECT_DIR field in captured hook payloads; S1 hook metadata cwd stayed at sandbox root after Bash `cd .claude` |
| `claude doctor` or session-start warnings | `claude doctor` timed out after 124s; no doctor result captured |
| Unknown hook event name warnings in `.claude/settings.json` | none observed during S1; installed project hooks use portable `omni hook` |

## 2. Hook capture matrix

| Event name | Observed yes/no | Required fields present | Notes |
| --- | --- | --- | --- |
| SessionStart | yes | session_id, transcript_path, cwd observed in ingested metadata | S1 |
| UserPromptSubmit | yes | session_id and prompt artifact observed | S1 |
| PreToolUse | yes | session_id, tool_name, tool_input, tool_use_id, transcript_path observed in processed hook files | 89 processed hook records; current `omni run show` does not surface PreToolUse |
| PostToolUse | yes | session_id, tool_name, tool_input, tool_response, tool_use_id, transcript_path observed | S1 Bash/Read/Glob |
| PostToolUseFailure | yes | session_id, tool_name, tool_input, error, tool_use_id, transcript_path observed | S1 Bash failure from `Get-ChildItem -Directory` in Bash |
| PermissionRequest | no | n/a | S4 non-interactive print mode did not present a denial surface |
| Notification | no | n/a | not observed in S1-S12 |
| PreCompact | no | n/a | `/compact` and auto compact were not feasible in bounded non-interactive runs |
| SubagentStart | yes | session_id, agent_id, agent_type, transcript_path observed | S6 |
| SubagentStop | yes | session_id, agent_id, agent_transcript_path, agent_type observed | S6 |
| Stop | yes | session_id and transcript_path observed | S1 |
| SessionEnd | yes | session_id and transcript_path observed | S1; queued ingest requests were written and drained |

## 3. Transcript parser matrix

This section closes Week-1 spike sections 3 and 4. Use one example line shape
per row type with KEYS ONLY; all values must be replaced/redacted.

| Observed row type | Example line shape, KEYS ONLY | Parsed yes/no | Archived yes/no | unknown line ratio | tool_use id reconciliation or mismatches |
| --- | --- | --- | --- | --- | --- |
| assistant | top keys: cwd, entrypoint, gitBranch, isSidechain, message, parentUuid, sessionId, timestamp, type, userType, uuid, version; message keys: content, id, model, role, stop_details, stop_reason, stop_sequence, type, usage | yes | no | 0/211 bad JSONL lines; 0 archive events | tool results reconciled from matching hook records when hook data existed |
| attachment | top keys: attachment, cwd, entrypoint, gitBranch, isSidechain, parentUuid, sessionId, timestamp, type, userType, uuid, version; attachment keys: content, isInitial, itemCount, names, skillCount, type | yes | no | 0/211 bad JSONL lines; 0 archive events | n/a |
| last-prompt | top keys: lastPrompt, leafUuid, sessionId, type | yes | no | 0/211 bad JSONL lines; 0 archive events | n/a |
| mode | top keys: mode, sessionId, type | yes | no | 0/211 bad JSONL lines; 0 archive events | S9 resume emitted one mode row |
| queue-operation | top keys: content, operation, sessionId, timestamp, type | yes | no | 0/211 bad JSONL lines; 0 archive events | n/a |
| user | top keys: cwd, entrypoint, gitBranch, isSidechain, message, parentUuid, permissionMode, promptId, promptSource, sessionId, sourceToolAssistantUUID, timestamp, toolUseResult, type, userType, uuid, version; toolUseResult keys include command, stdout, stderr, interrupted, filePath, structuredPatch, agentId, agentType | yes | no | 0/211 bad JSONL lines; 0 archive events | Bash/Edit/Read/Agent results reconcile by tool_use_id when present |

## 4. Bash evidence

| Scenario | Command | exit_code | stdout | stderr | Source: hook, transcript, reconciled |
| --- | --- | --- | --- | --- | --- |
| S1 Bash success | `cd .claude && pwd && ls && cd .. && node test.js` | unavailable in current parser output | `/tmp/omni-week2-sandbox/.claude`; `settings.json`; `sandbox test ok` | shell cwd reset warning in stderr | hook |
| S2 Bash failure | `bash -c 'echo "error message" >&2; exit 7'` | unavailable in current parser output; hook error contains `Exit code 7` | none | `error message` | hook |
| S10 interrupt Bash | long `sleep` Bash commands plus `TaskStop` | unavailable in current parser output | partial start lines captured in hook artifacts | timeout/task-stop behavior captured via PostToolUseFailure and TaskStop | hook |

## 5. File operation evidence

| Operation | Paths visible | Content redacted | Skiplisted read shows withheld stub with envelope intact | Notes |
| --- | --- | --- | --- | --- |
| Read | yes: `s3-note.txt`, `.env` | normal non-secret S3 content preserved; S12 `.env` content withheld | yes for `.env`: session_id, tool_use_id, tool_name retained with `skiplisted_path_withheld` stubs | S12 audit passed and planted literal scan under `.omni/**` was empty |
| Write | yes: `s3-note.txt` | non-secret S3 content preserved | n/a | Write tool envelope preserved file_path/content/tool_response |
| Edit | yes: `s3-note.txt` | non-secret S3 diff preserved | n/a | Edit tool envelope preserved old_string/new_string/structuredPatch |

## 6. Permission / denial behavior

| Scenario | Event names | Denial represented yes/no | Parsed or archived | Notes |
| --- | --- | --- | --- | --- |
| S4 permission deny | SessionStart, UserPromptSubmit, PostToolUse Bash, Stop, SessionEnd | no | parsed | non-interactive `claude -p` did not present a denial prompt; PASS as not feasible |
| S5 PreToolUse deny if feasible | SessionStart, UserPromptSubmit, Stop, SessionEnd; transcript showed Bash unavailable | yes, as tool unavailable before execution | parsed; no hook tool event | `--disallowedTools Bash` blocked execution; no PreToolUse hook row surfaced for this denial |

## 7. Subagent behavior

| Field | Evidence |
| --- | --- |
| Subagent support feasible yes/no | yes |
| Subagent event names observed | Agent tool PostToolUse plus SubagentStart/SubagentStop |
| Sidechain/session identifiers | agent_id `a482835b075250310`; agent_transcript_path under session `3cc7cab7-4c4c-4e8b-beb3-c7dcc6ba2c5c/subagents/agent-a482835b075250310.jsonl` |
| tool_use_id collisions across sidechains | none observed in run show; canonical run remained attributed to parent session |
| Parser or ingest behavior | first ingest inserted 33 events, second inserted 0, audit passed |

## 8. Compact behavior

| Compact type | Occurred yes/no | Event names | Session identity before/after | Notes |
| --- | --- | --- | --- | --- |
| Manual /compact | no | none | unchanged session id `95aa96a9-6bc9-47f0-991f-178a5fc152cb` | non-interactive print mode reported `/compact` not feasible; audit/ingest idempotency passed |
| Auto compact if feasible | no | none | unchanged session id `f3774526-df2f-47cf-891d-c0e093b47c3b` | bounded automation did not force long context; recorded not feasible |

## 9. Resume behavior

| Field | Evidence |
| --- | --- |
| Same session_id resumed yes/no | yes. Original failing run requested/returned `d04acbc6-3ea6-429c-b274-cc6046279b23`; post-fix rerun requested/returned `52ae0fe5-0a72-4153-8d48-efbab35eef30` |
| Canonical update, not duplicates | yes after fix. S9-only rerun event count moved from 29 to 44 with 23 transcript uuids and 23 unique transcript uuids; duplicate uuid counts were `{}` |
| Re-ingest events_inserted=0 | yes. Post-fix baseline second ingest inserted 0; resume first ingest inserted 15 new events; immediate second ingest inserted 0 |
| Notes | Fixed by using stable top-level transcript `uuid` as transcript event identity when present, while leaving no-uuid rows on the existing fallback. Original pre-fix failure is retained in the scenario ledger for traceability. |

## 10. Crash / missing SessionEnd behavior

| Field | Evidence |
| --- | --- |
| Ingest request file absent yes/no | yes: S11 had 4 live hook files and 0 ingest json files after forced kill |
| Plain `omni ingest` no-op output | two runs: `run_ids= events_inserted=0 queue_drained=0` |
| How session id was found | provided explicit session id `0b05e349-b46a-42a2-a520-62a13d4b25fe`; confirmed via live hook payload for `echo s11-crash-check` |
| `omni ingest <session_id>` recovery output | first scoped ingest: `run_ids=0b05e349-b46a-42a2-a520-62a13d4b25fe events_inserted=3 queue_drained=0`; repeat inserted 0 |
| Scoped recovery consumed only matching session yes/no | yes; spool hook/ingest/bad were empty after recovery and audit passed |

## 11. S12 planted secret result

| Check | Result |
| --- | --- |
| raw FAKE_AWS value absent from `.omni/**` | yes; direct byte scan returned no hits |
| raw OMNI_FAKE_SECRET absent from `.omni/**` | yes; direct byte scan returned no hits |
| raw fake GitHub token absent from `.omni/**` | yes; direct byte scan returned no hits |
| withheld stub envelope present for the `.env` read event | yes: S12 Read retained session_id, tool_use_id, tool_name, file_path and replaced file content with `skiplisted_path_withheld` |
| `omni audit secrets` result | ok true |

## 12. Hook latency

| Metric | Evidence |
| --- | --- |
| in-process capture p50 / p95 / sample count from `omni status` | final status: p50=0 ms, p95=1 ms; processed hook sample count=240 including one synthetic valid latency hook |
| process-level latency sampled separately at least once | yes: Python-launched `omni hook` subprocess elapsed 127.9 ms and exited 0; scoped ingest cleanup passed |
| G7 in-process p95 under 250 ms yes/no | yes |

## 13. Cold / warm demo

| Field | Evidence |
| --- | --- |
| Cold run observations | S1 before injection produced redacted trace and generated memory; `CLAUDE.md` initially had no managed region |
| Generated `memory.md` summary | package manager `pnpm`; commands `pnpm run test` and `pnpm run build`; render byte-stable |
| Warm run first matching test command | warm1 `pnpm run test`; warm2 `pnpm run test`; warm3 `pnpm run test` |
| Rediscovery events before first correct command | none in all 3 warm runs |
| G6 strict pass/fail | pass 3/3 |
| G6 robust pass/fail | pass 3/3 |

## 14. Go / No-Go decision

| Field | Evidence |
| --- | --- |
| Sandbox pass/fail | PASS after S9-only rerun. S1-S8 and S10-S12 passed or were not-feasible per runbook fallbacks; S9 originally failed, then passed after the transcript uuid identity fix. Every scenario's immediate second ingest was 0, audit passed, render was byte-stable, and final spool hook/ingest/bad/errors were empty. |
| Dogfood pass/fail | Demo pass for G6: cold render/inject succeeded and warm robust passed 3/3 |
| Blockers | none remaining for Week-2 sandbox entry criteria |
| Targeted fixes required | Completed: redaction placeholder re-scan false positive fixed; transcript `uuid` identity prevents resume duplicate old rows; redaction fixture corpus idempotency test added. |
| Decision | Go for dogfood entry on a small real project. |

## 15. Scenario ledger

All rows below also had `omni audit secrets` ok, `omni status` ok, final
`.omni/spool/bad/` empty, `_errors.log` absent, and no leftover
`hook-*.jsonl` or `ingest-*.json` after the recorded recovery path.

| Scenario | run_id | Ingest evidence | Result |
| --- | --- | --- | --- |
| S1 Bash success | `d04acbc6-3ea6-429c-b274-cc6046279b23` | first `events_inserted=38 queue_drained=2`; second `events_inserted=0 queue_drained=0` | PASS; hook file appeared during live session and spool stayed rooted at sandbox `.omni/spool/` after Bash `cd .claude` |
| S2 Bash failure | `339d9b3f-9e13-464c-82c4-198127332fd6` | first `events_inserted=15 queue_drained=2`; second `events_inserted=0 queue_drained=0` | PASS; `PostToolUseFailure` captured `Exit code 7` and stderr line |
| S3 Edit / Write / Read | `a6f4cb78-4d52-4676-b42b-622be8c43fb6` | first `events_inserted=23 queue_drained=2`; second `events_inserted=0 queue_drained=0` | PASS; Write, Read, and Edit envelopes preserved paths and structured patch |
| S4 permission deny | `9c303211-b937-488e-8fc6-2c7422384f06` | first `events_inserted=15 queue_drained=2`; second `events_inserted=0 queue_drained=0` | PASS with fallback; non-interactive `claude -p` had no denial surface |
| S5 PreToolUse deny | `695c1a93-d423-4578-a939-6078c2174d1d` | first `events_inserted=14 queue_drained=2`; second `events_inserted=0 queue_drained=0` | PASS with fallback; `--disallowedTools Bash` blocked execution before tool run, no hook tool event |
| S6 subagent | `3cc7cab7-4c4c-4e8b-beb3-c7dcc6ba2c5c` | first `events_inserted=33 queue_drained=2`; second `events_inserted=0 queue_drained=0` | PASS; Agent tool plus SubagentStart/SubagentStop observed |
| S7 manual compact | `95aa96a9-6bc9-47f0-991f-178a5fc152cb` | first `events_inserted=33 queue_drained=2`; second `events_inserted=0 queue_drained=0` | PASS with fallback; `/compact` not available in print mode |
| S8 auto compact | `f3774526-df2f-47cf-891d-c0e093b47c3b` | first `events_inserted=10 queue_drained=2`; second `events_inserted=0 queue_drained=0` | PASS with fallback; bounded automation did not trigger auto compact |
| S8 invalid timeout attempt | `c06fe359-de20-4f1f-8731-843b72092785` | plain ingest twice no-op; scoped ingest inserted 37 then 0 | Diagnostic only; revealed redaction placeholder re-scan audit false positive, fixed in this branch |
| S9 resume pre-fix | `d04acbc6-3ea6-429c-b274-cc6046279b23` | first `events_inserted=20 queue_drained=2`; second `events_inserted=0 queue_drained=0` | FAIL; same session id resumed, but original S1 transcript-backed rows were duplicated in canonical run show |
| S9 resume post-fix rerun | `52ae0fe5-0a72-4153-8d48-efbab35eef30` | baseline first `events_inserted=29 queue_drained=2`; baseline second `events_inserted=0`; resume first `events_inserted=15 queue_drained=2`; resume second `events_inserted=0` | PASS; same session id resumed, run show had no old transcript uuid duplicates, duplicate uuid counts `{}`, audit/status/checklist passed |
| S10 interrupt Bash | `d7b75e44-56b1-4d15-8b2b-aabb35fac2fa` | first `events_inserted=37 queue_drained=1`; second `events_inserted=0 queue_drained=0` | PASS; timeout/TaskStop behavior captured without leftover partial hook files |
| S11 crash / missing SessionEnd | `0b05e349-b46a-42a2-a520-62a13d4b25fe` | plain ingest twice no-op; scoped ingest inserted 3 then 0 | PASS; no ingest request existed after forced kill, scoped recovery consumed matching session hooks |
| S12 read `.env` | `f917c86f-3169-4567-a2fa-e3ac82e8a260` | first `events_inserted=15 queue_drained=2`; second `events_inserted=0 queue_drained=0` | PASS; withheld stub envelope present and planted literal scan under `.omni/**` was empty |

Demo warm runs:

| Warm run | run_id | First matching test command | G6 strict | G6 robust |
| --- | --- | --- | --- | --- |
| warm1 | `3f604fc1-8316-42f9-ac2b-a6bc3c4430bc` | `pnpm run test` | PASS | PASS |
| warm2 | `03dc18ee-a2d2-4d2f-af90-6293d49667ae` | `pnpm run test` | PASS | PASS |
| warm3 | `2e5b885a-597b-4c82-8802-880b01e5f861` | `pnpm run test` | PASS | PASS |
