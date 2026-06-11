# Decisions

## `.omni/` is local-only

Decision: the entire `.omni/` directory is local-only, ignored by git, and
should not be committed. There are no exceptions for `.omni/project_id`.

Rationale: OmniMemory uses this file as the durable local project identity after
`omni init`. On first creation, `omni init` bootstraps the value from the git
remote origin hash when a `git remote origin` URL is available; otherwise it
creates a random `proj_` id. After the file exists, the file wins over git
remote origin so moving the repo path or changing the remote later does not
silently change `project_id`.

## Week-1 spool and status limits

Decision: Week-1 writes one ingest request file per hook stop event instead of
appending to a shared queue file. This avoids concurrent append corruption while
keeping hook capture stdlib-only and redaction-before-write.

Rationale: the hook must remain an observer and exit 0. Per-request files are
good enough for Week-1, but a later version should make drain processing more
durable if crash recovery during ingest becomes a requirement.

Decision: legacy `ingest_queue.jsonl` support is best-effort in Week-1. A
malformed legacy queue line quarantines the whole legacy queue file rather than
salvaging valid neighboring lines.

Rationale: current hooks no longer append to the legacy shared queue file. The
legacy reader exists only to drain pre-existing local files during migration,
and the quarantine preserves the original bytes for manual inspection.

Decision: hook capture `_errors.log` remains a best-effort append-only diagnostic
log in Week-1.

Rationale: hook failures must not block Claude Code. Error diagnostics are
redacted before write, but a future version can move to file-per-error records
if partial diagnostic writes become a practical problem.

Decision: skiplisted hook capture keeps read commands visible but withholds Bash
commands that write inline content to skiplisted paths with `>`, `>>`, or `tee`.

Rationale: command lines are useful evidence for reads such as `cat .env`, where
the response content is withheld. For writes into skiplisted files, the command
itself may contain inline secrets, so Week-1 replaces that command with the same
skiplist stub used for content fields. This does not claim general secret
detection for arbitrary command text.

Decision: `events_as_jsonl()` performs output-safety redaction even though
`NormalizedEvent` values are already redacted.

Rationale: parse output is a terminal/log boundary, so a second redaction pass is
intentional. The final JSONL may be redacted beyond the event.detectors metadata,
which describes redaction found while normalizing the event.

Decision: no raw Claude settings backup is created during hook installation in
Week-1. `.claude/settings.json` is written with an atomic temp-file replace
instead.

Rationale: copying `.claude/settings.json` into `.omni/` would violate
redaction-before-write and create an original vault. Atomic replace covers the
main corruption risk without storing raw user-local configuration.

Decision: `omni status` computes hook latency p50/p95 by scanning hook spool
files in Week-1.

Rationale: this is acceptable for short sandbox runs. Future versions should
summarize on ingest or archive processed spool files so status does not scan an
ever-growing spool tree.

Decision: manual `omni ingest --transcript` is transcript-only unless the user
also supplies `--run-id`.

Rationale: unscoped hook reconciliation can attach unrelated live-session hook
spool to a manually ingested transcript. When `--run-id` is provided, Week-1
treats it as the Claude session id and only reconciles hook records carrying
that same `session_id`.
