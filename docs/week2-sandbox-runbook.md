# Week-2 Sandbox Runbook

This runbook validates Week-1 OmniMemory in a real Claude Code CLI sandbox. It
does not replace `docs/demo.md`; use `docs/demo.md` for the authoritative
cold/warm G6 procedure.

Do not automate Claude Code. A human runs Claude Code manually and records
evidence in `docs/week2-spike-report.md`.

## Baseline

From the OmniMemory checkout:

```bash
pytest -q
omni audit secrets
git rev-parse HEAD
claude --version
```

Record the OmniMemory commit and Claude Code version in the spike report.

## Sandbox Setup

Create the sandbox:

```bash
bash scripts/create_sandbox.sh /tmp/omni-demo-sandbox
cd /tmp/omni-demo-sandbox
omni init
omni audit secrets
omni init --install-claude-hooks --yes
omni status
```

Verify `omni` resolves on PATH in the same shell that will launch `claude`.
The installed hook command is the portable `omni hook`.

```bash
command -v omni
```

On Windows shells:

```cmd
where omni
```

If hooks do not fire in S1, stop and fix PATH or hook installation before
blaming capture code.

## After Every Scenario

Run these commands after the Claude Code scenario ends. For `omni ingest`,
run it TWICE; the second run MUST report `events_inserted=0`.

```bash
omni ingest
omni ingest
omni run show <run_id>
omni audit secrets
omni status
omni render
copy .omni/generated/memory.md /tmp/omni-memory-first.md
omni render
cmp .omni/generated/memory.md /tmp/omni-memory-first.md
```

If `copy` or `cmp` is unavailable, use the shell equivalent. The requirement is
that `.omni/generated/memory.md` is byte-identical across two renders when facts
did not change.

Standing inspection list:

- hook events actually captured: spool files appeared during the session
- no leftover hook-*.jsonl for the ingested session in .omni/spool/
- .omni/spool/bad/ is empty
- .omni/spool/_errors.log is empty
- ingest-*.json appeared on Stop/SessionEnd and is gone after ingest
- `.omni/generated/memory.md` is byte-identical across two renders when facts did not change

Record for every scenario:

- the prompt typed into Claude Code
- both `omni ingest` outputs, including `events_inserted=0` on the second run
- the `session_id` used as `<run_id>`
- `omni run show <run_id>` output summary
- `omni audit secrets` result
- `omni status` hook p50/p95 and sample count
- pass/fail criteria result
- fallback used when data was missing

## S1 Bash success

Prompt to type into Claude Code:

```text
Run the project test command. Before running it, cd into a subdirectory of this sandbox, then run one harmless command from there.
```

After scenario commands:

```bash
omni ingest
omni ingest
omni run show <run_id>
omni audit secrets
omni status
```

What to record:

- whether hook events actually captured
- whether `.omni/spool` stayed in the project root after the subdirectory `cd`
- whether `CLAUDE_PROJECT_DIR` is set for hooks: yes/no/value
- command, exit_code, stdout, stderr for the successful Bash event

Pass/fail criteria:

- PASS if the Bash command is visible, the exit code is 0, spool remains rooted at the sandbox project, audit passes, and the second ingest reports `events_inserted=0`
- FAIL if hooks do not fire, spool is created in the subdirectory, raw secrets appear, or second ingest inserts events

Fallback if missing data:

- If hook events are absent, stop and check `command -v omni` / `where omni`, `.claude/settings.json`, and hook install before continuing.

## S2 Bash failure

Prompt to type into Claude Code:

```text
Run a Bash command that fails with exit code 7 and prints one line to stderr.
```

After scenario commands:

```bash
omni ingest
omni ingest
omni run show <run_id>
omni audit secrets
omni status
```

What to record:

- command text
- exit_code
- stdout and stderr evidence source: hook, transcript, or reconciled

Pass/fail criteria:

- PASS if the failed Bash event is captured with command, nonzero exit_code, stderr, audit passes, and the second ingest reports `events_inserted=0`
- FAIL if the failure is dropped, marked successful, or unredacted content appears under `.omni/`

Fallback if missing data:

- If transcript data is missing but hook data exists, record hook-only evidence and continue.

## S3 Edit / Write / Read

Prompt to type into Claude Code:

```text
Create a small text file, read it back, edit one line, and show the final content.
```

After scenario commands:

```bash
omni ingest
omni ingest
omni run show <run_id>
omni audit secrets
omni status
```

What to record:

- Read, Write, and Edit event shapes
- paths visible in events
- whether file content is redacted or archived safely

Pass/fail criteria:

- PASS if file operation envelopes are preserved, paths are visible, sensitive content is not raw under `.omni/`, and second ingest reports `events_inserted=0`
- FAIL if file operation events are corrupted, missing without archive, or leak raw sensitive bytes

Fallback if missing data:

- Record the transcript row keys only in the spike report and mark parser support as pending targeted fix.

## S4 permission deny

Prompt to type into Claude Code:

```text
Attempt an operation that requires permission, then deny it when Claude Code asks.
```

After scenario commands:

```bash
omni ingest
omni ingest
omni run show <run_id>
omni audit secrets
omni status
```

What to record:

- permission/denial event names
- required fields present
- whether denied operations create hook or transcript rows

Pass/fail criteria:

- PASS if denial behavior is captured or safely archived with redaction, audit passes, and second ingest reports `events_inserted=0`
- FAIL if denial rows crash ingest or leak raw content

Fallback if missing data:

- If Claude Code cannot produce a denial surface, record "not feasible" with version and continue.

## S5 PreToolUse deny if feasible

Prompt to type into Claude Code:

```text
Try an action that should be blocked before tool execution if the current Claude Code surface supports PreToolUse deny.
```

After scenario commands:

```bash
omni ingest
omni ingest
omni run show <run_id>
omni audit secrets
omni status
```

What to record:

- whether PreToolUse fires at all
- observed event name and keys only
- denial representation if any

Pass/fail criteria:

- PASS if supported PreToolUse denial is captured or archived redacted
- PASS with "not feasible" if the surface does not emit PreToolUse denial
- FAIL if emitted rows break ingest or leak raw content

Fallback if missing data:

- The Week-1 spike observed PreToolUse count = 0 on this surface. Record whether it fires at all; "not feasible" is acceptable.

## S6 subagent if feasible

Prompt to type into Claude Code:

```text
Use a subagent, if this Claude Code build supports it, to inspect the sandbox test command and report it back.
```

After scenario commands:

```bash
omni ingest
omni ingest
omni run show <run_id>
omni audit secrets
omni status
```

What to record:

- SubagentStart/SubagentStop or equivalent event names
- sidechain/session identifiers
- tool_use_id collisions across sidechains, if any

Pass/fail criteria:

- PASS if subagent behavior is captured or archived safely and no tool_use_id collision corrupts the canonical run
- PASS with "not feasible" if this Claude Code build cannot start subagents
- FAIL if sidechain rows are misattributed or leak raw content

Fallback if missing data:

- Record "not feasible" with Claude Code version and continue.

## S7 manual /compact

Prompt to type into Claude Code:

```text
Summarize the current work briefly, then run /compact manually.
```

After scenario commands:

```bash
omni ingest
omni ingest
omni run show <run_id>
omni audit secrets
omni status
```

What to record:

- compact-related hook event names
- transcript row types around compaction
- whether session identity remains stable

Pass/fail criteria:

- PASS if compact rows are captured or archived redacted, audit passes, and re-ingest is idempotent
- FAIL if compact rows break parse/ingest or create duplicate canonical events

Fallback if missing data:

- If compact is unavailable, record "not feasible" with the exact Claude Code version.

## S8 auto compact if feasible

Prompt to type into Claude Code:

```text
Continue a long enough sandbox conversation to trigger auto compact if practical in this environment.
```

After scenario commands:

```bash
omni ingest
omni ingest
omni run show <run_id>
omni audit secrets
omni status
```

What to record:

- whether auto compact occurred
- event names and keys only
- session_id before and after compact

Pass/fail criteria:

- PASS if auto compact is captured or archived safely
- PASS with "not feasible" if triggering auto compact is impractical
- FAIL if auto compact corrupts run identity or leaks raw content

Fallback if missing data:

- Do not spend unbounded time forcing auto compact; record "not feasible" and continue.

## S9 resume

Prompt to type into Claude Code:

```text
Resume the previous sandbox session and run the same test command again.
```

After scenario commands:

```bash
omni ingest
omni ingest
omni run show <run_id>
omni audit secrets
omni status
```

What to record:

- whether the same session_id resumed
- whether canonical events update instead of duplicating
- second ingest output

Pass/fail criteria:

- PASS if re-ingest reports `events_inserted=0` for already-ingested rows and resume does not duplicate canonical events
- FAIL if resume creates duplicate semantic events for the same tool_use_id

Fallback if missing data:

- If the session id is unclear, inspect redacted spool record payloads and Claude Code session list to identify it.

## S10 interrupt Bash

Prompt to type into Claude Code:

```text
Start a long-running Bash command, then interrupt or kill it from Claude Code.
```

After scenario commands:

```bash
omni ingest
omni ingest
omni run show <run_id>
omni audit secrets
omni status
```

What to record:

- interrupt event representation
- whether any spool temporary files remain
- partial stdout/stderr if present

Pass/fail criteria:

- PASS if only *.tmp orphan files are acceptable in spool after the kill and ingest/audit still succeed
- FAIL if a half-written `hook-*.jsonl` remains, ingest crashes, or raw content leaks

Fallback if missing data:

- If no run id is emitted, inspect redacted spool payloads to find `session_id`; use `omni ingest <session_id>` only for recovery.

## S11 crash / missing SessionEnd

Prompt to type into Claude Code:

```text
Start a sandbox session, run one simple command, then crash or kill Claude Code before SessionEnd.
```

After scenario commands:

```bash
omni ingest
omni ingest
omni run show <run_id>
omni audit secrets
omni status
```

What to record:

- absence of ingest request file
- plain `omni ingest` output
- explicit recovery output from `omni ingest <session_id>`
- how the session id was found

Pass/fail criteria:

- PASS if no ingest request file exists, plain `omni ingest` is a no-op by design, and `omni ingest <session_id>` recovers only matching session hook records
- FAIL if unscoped ingest consumes unrelated live hook spool

Fallback if missing data:

- Find `session_id` from redacted spool record payloads or the Claude Code session list, then run `omni ingest <session_id>`.

## S12 read .env

Prompt to type into Claude Code:

```text
Read .env and report whether it contains the planted fake values.
```

After scenario commands:

```bash
omni ingest
omni ingest
omni run show <run_id>
omni audit secrets
omni status
```

What to record:

- whether the `.env` read event appears as a withheld stub
- preserved envelope fields: session_id, tool_use_id, tool_name
- absence of raw planted values under `.omni/**`
- `omni audit secrets` result

Pass/fail criteria:

- PASS if no raw planted FAKE_AWS value, OMNI_FAKE_SECRET value, or fake GitHub token appears under `.omni/**`, audit exits 0, and the withheld stub envelope is present
- FAIL if raw planted values appear anywhere under `.omni/**` or the stub drops the envelope fields

Fallback if missing data:

- Do not expect file content in `omni run show`. A read command like `cat .env` stays visible, but a write command like `echo X > .env` is stubbed.
