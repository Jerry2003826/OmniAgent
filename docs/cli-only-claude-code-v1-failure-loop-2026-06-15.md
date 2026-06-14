# CLI-only Claude Code v1 — Failure-Memory Loop Sandbox Evidence

Date: 2026-06-15

## What this records

Phase B (real-usage quality governance) evidence that the failure-memory half of
the closed loop works end to end with a real failing Claude Code run. The v1
closeout and the G6 robust record exercised the experience / fast-path side; this
record exercises the previously-unverified failure side:

```text
failing run -> ingest -> failure extract -> failure approve -> render Known Failures -> failure pattern retire -> render
```

This is corroborating harness evidence in a disposable sandbox. `docs/demo.md`
remains the authoritative manual acceptance path.

## Method (Windows adaptation)

- disposable sandbox via `scripts/create_sandbox.ps1`, with `test.js` overwritten
  to fail (`process.exit(1)`)
- Claude Code driven headlessly to run the tests (which then fail)
- `omni ingest`, then the existing failure-memory commands
- `bash` is unavailable on the host, so the loop was reproduced with PowerShell +
  OmniMemory's own CLI rather than `scripts/golden_demo.sh`

Environment: `claude` 2.1.173, `node` v22.22.0, `pnpm` 10.33.0. No product code,
tables, or memory types were added.

## Sandbox and run

- sandbox: `%TEMP%\omni-fail-e41ed309` (disposable; removed after the run)
- failing run_id: `52eb5970-ad1c-4606-baad-0f7fbb5222c1` (ingest reported
  `events_inserted=13`)

## failure extract

`omni failure extract <run_id>` created 2 candidates:

| candidate | kind | command_norm | exit_code | tool | disposition |
|-----------|------|--------------|-----------|------|-------------|
| `failure_cand_563f12a1...` | tool_failed | `node test.js` | 1 | PowerShell | approved |
| `failure_cand_db8dc956...` | tool_failed | `node test.js 2>&1` | 127 | Bash | left pending |

The exit-1 candidate is the planted real failure. The exit-127 candidate is noise
from Claude attempting Bash on a host without `bash`.

## approve and render

Approved the real candidate into pattern `failure_pattern_9264baa4...`:

- summary: "The configured Node test command failed with a non-zero exit."
- suggested_action: "Inspect the failing test and its dependencies before
  switching package managers or test commands."

Rendered Known Failures section:

```md
## Known Failures
- If `node test.js` fails with `Exit code 1`: Inspect the failing test and its dependencies before switching package managers or test commands.
```

`omni audit secrets`: `ok=true` (the sandbox planted secrets did not leak).

## retire and re-render

`omni failure pattern retire failure_pattern_9264baa4...` set the pattern to
`retired`. Re-rendering removed the `## Known Failures` section entirely; retired
patterns do not render.

## Findings

- The full failure-memory loop (extract -> approve -> render -> retire) works end
  to end. The review gate correctly contained the noise candidate: only the real
  exit-1 failure was approved and rendered.
- Windows quality signal: Claude's failed Bash attempts on a host without `bash`
  produce extra exit-127 "command not found" failure candidates. These are
  contained by review gating today (do not approve them). A future, optional,
  test-driven extractor de-noise for exit-127 / command-not-found could reduce the
  noise. It is not urgent and is not an LLM extractor, so it stays within the v1
  boundary.
- The candidate `kind` was `tool_failed` because Claude Code surfaced the failure
  as a `PostToolUseFailure` event. The extractor maps `PostToolUseFailure` to
  `tool_failed` and only classifies a shell-tool event with a non-zero exit as
  `command_failed`, so the kind reflects the event path, not whether the command
  ran through the package manager. This is a classification detail, not a defect.

## Status

With this record, both halves of the CLI-only Claude Code v1 closed loop now have
real end-to-end dogfood evidence: experience / fast-path (G6 robust 3/3) and
failure memory (this record). Remaining Phase B value is driven by real Claude
Code usage on real projects.
