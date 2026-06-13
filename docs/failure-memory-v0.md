# Failure Memory v0

Failure Memory v0 starts with deterministic candidate extraction only. Phase 1
creates reviewable failure candidates from already-ingested, already-redacted
events:

```bash
omni failure extract <run_id>
omni failure ls
omni failure show <failure_cand_id>
omni failure approve <failure_cand_id> \
  --summary "Tests failed because the configured command returned a dependency resolution error." \
  --suggested-action "Inspect the existing package manager and lockfile before installing or switching package managers."
omni failure reject <failure_cand_id>
```

Failure Pattern v0 adds a human approval step for reviewed candidates. It does
not render Known Failures into `.omni/generated/memory.md`, run verification,
infer task success, or evolve memory automatically.

The extractor does not use an LLM and does not parse raw artifacts. It only reads
existing SQLite rows and the redacted event metadata already stored by ingest.
Evidence stored with a candidate is a bounded summary: run id, event id,
tool-use id, event type, tool, normalized command, exit code, failure kind, and
the error-signature hash. It does not store raw event payloads or full stderr.

Failure Candidate v0 extracts these deterministic signals:

- `PostToolUseFailure` events as `tool_failed`
- Bash or shell tool events with non-zero exit codes as `command_failed`
- visible interrupted tool results as `interrupted`

Each candidate has a deterministic `error_signature` and
`error_signature_hash`. The signature is based on the normalized command, exit
code, and first meaningful error line after ANSI stripping, whitespace
normalization, absolute-path replacement, redaction, and length capping.

Rejected candidates are not recreated in v0. Duplicate extraction for the same
run and error signature is idempotent.

Failure Candidate v0 is the next stage after Behavior Eval v0, Outcome Log v0,
Experience Candidate v0, and Experience Notes Renderer v0: eval and outcome
measure whether memory helped, experience notes can improve future behavior, and
failure candidates provide reviewable evidence for future failure-memory work.

## Failure Pattern v0

Failure Pattern v0 lets a human approve a pending failure candidate into an
active `failure_patterns` row:

```bash
omni failure approve <failure_cand_id> \
  --summary "Tests failed because the configured command returned a dependency resolution error." \
  --suggested-action "Inspect the existing package manager and lockfile before installing or switching package managers."
```

The `summary` and `suggested_action` are human-provided in v0. OmniMemory does
not use an LLM to summarize failures. Free text is redacted before it is stored,
and the approval output is passed through the same JSON output redaction path as
candidate extraction.

Approval is review-gated and stateful:

- pending candidates can become approved and get linked to an active pattern.
- rejected candidates cannot be approved in v0.
- approved candidates cannot be rejected in v0 because active pattern retire and
  supersede behavior is future work.
- if an active project pattern already exists for the same error signature, the
  newly approved candidate links to that pattern instead of creating a duplicate.

Active `failure_patterns` are storage only in this PR. They do not render into
`memory.md` yet. Known Failures Renderer v0 is future work, as are pattern
retire and supersede flows.
