# Failure Memory v0

Failure Memory v0 starts with deterministic candidate extraction only. Phase 1
creates reviewable failure candidates from already-ingested, already-redacted
events:

```bash
omni failure extract <run_id>
omni failure ls
omni failure show <failure_cand_id>
omni failure reject <failure_cand_id>
```

There is no approval flow in this phase. Failure Candidate v0 does not create approved failure patterns, render Known Failures into `.omni/generated/memory.md`, run verification, infer task success, or evolve memory automatically.

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
