# Failure Memory v0

Failure Memory v0 starts with deterministic candidate extraction, human approval
into active patterns, and a small Known Failures renderer. Phase 1 creates
reviewable failure candidates from already-ingested, already-redacted events:

```bash
omni failure extract <run_id>
omni failure ls
omni failure show <failure_cand_id>
omni failure approve <failure_cand_id> \
  --summary "Tests failed because the configured command returned a dependency resolution error." \
  --suggested-action "Inspect the existing package manager and lockfile before installing or switching package managers."
omni failure reject <failure_cand_id>
omni failure pattern ls
omni failure pattern show <pattern_id>
omni failure pattern retire <pattern_id>
```

Failure Pattern v0 adds a human approval step for reviewed candidates. Known
Failures Renderer v0 renders approved active patterns into
`.omni/generated/memory.md`. Failure Memory v0 still does not run verification,
does not infer task success, and does not evolve memory automatically.

The extractor does not use an LLM and does not parse raw artifacts. It only reads
existing SQLite rows and the redacted event metadata already stored by ingest.
Evidence stored with a candidate is a bounded summary: run id, event id,
tool-use id, event type, tool, normalized command, exit code, failure kind, and
the error-signature hash. It does not store raw event payloads or full stderr.

Failure Candidate v0 extracts these deterministic signals:

- `PostToolUseFailure` events as `tool_failed`
- Bash or shell tool events with non-zero exit codes as `command_failed`
- visible interrupted tool results as `interrupted`

Command-not-found failures (exit code 127) are skipped. On hosts without a given
shell (for example Windows without `bash`), an agent's failed shell or command
probe reports exit 127, which is environment noise rather than a project failure.

Each candidate has a deterministic `error_signature` and
`error_signature_hash`. The signature is based on the normalized command, exit
code, and first meaningful error line after ANSI stripping, whitespace
normalization, absolute-path replacement, redaction, and length capping.

Rejected candidates are not recreated in v0. Duplicate extraction for the same
run and error signature is idempotent.

Failure Candidate v0 is the next stage after Behavior Eval v0, Outcome Log v0,
Experience Candidate v0, and Experience Notes Renderer v0: eval and outcome
measure whether memory helped, experience notes can improve future behavior, and
failure candidates provide reviewable evidence for reviewed failure-memory
patterns.

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

## Pattern Lifecycle v0

Pattern Lifecycle v0 adds the minimum controls needed after Known Failures can
affect future behavior:

```bash
omni failure pattern ls
omni failure pattern show <pattern_id>
omni failure pattern retire <pattern_id>
```

`ls` and `show` are read-only and open SQLite in read-only mode. `retire` is the
only pattern lifecycle writer in v0. It changes an active pattern's `status` to
`retired`, sets `retired_seq` and `updated_at`, and leaves the source failure
candidate approved with its original `pattern_id`.

`ls`, `show`, and `retire` include a `lifecycle` summary so the JSON output is
auditable without reading renderer internals. Active patterns report
`renders=true`, `can_retire=true`, `can_reactivate=false`, and
`supersede_supported=false`. Retired patterns report `renders=false`,
`can_retire=false`, `can_reactivate=false`, and `supersede_supported=false`.

Retiring an already-retired pattern is idempotent. Unknown pattern ids return a
clear error and a non-zero CLI exit. Retired patterns do not render into
`.omni/generated/memory.md`.

Pattern Lifecycle v0 does not implement supersede, reactivation, automatic
trust changes, verification, or note/pattern evolution. Approving a candidate
whose linked pattern was retired returns a clear error; v0 does not silently
reactivate retired patterns.

## Known Failures Renderer v0

Known Failures Renderer v0 reads active `failure_patterns` rows and renders a
`## Known Failures` section in `.omni/generated/memory.md`. It does not read or
render pending or rejected `failure_candidates`.

Rendered lines are deterministic and intentionally narrow:

```md
## Known Failures

- If `pnpm run build` fails with `exit 1: dependency resolution failed`: Inspect the existing package manager and lockfile before changing dependencies.
```

If a pattern has no normalized command, the line uses generic recurrence
wording:

```md
- If this failure recurs with `exit 1: dependency resolution failed`: Inspect the existing package manager and lockfile before changing dependencies.
```

Renderer output excludes pattern ids, source candidate ids, run ids, event ids,
tool-use ids, evidence, error-signature hashes, timestamps, trust, confidence,
raw stderr, and artifact references. The final generated memory block still
passes through output redaction before it is written.

The manual loop is:

```bash
omni failure approve <failure_cand_id> \
  --summary "Tests failed because dependency resolution failed." \
  --suggested-action "Inspect the existing package manager and lockfile before changing dependencies."
omni render --diff
omni render
```

This completes the v0 deterministic path from a redacted failure event to a
candidate, then a human-approved active pattern, then a Known Failures memory
line. Supersede flows, verification, and automatic pattern evolution remain
future work.
