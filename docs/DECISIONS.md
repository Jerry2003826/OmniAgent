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

Decision: CLI commands, including `omni init`, discover the project root by
walking upward to the nearest existing `.omni/` or `.git`.

Rationale: running Omni from a package subdirectory should operate on the
repository's single local `.omni/` tree instead of silently creating nested
state. Users with `$HOME` or another parent directory managed as a git repo
should run `omni init` from the intended project root if no closer `.git` or
`.omni/` exists.

Decision: command footprints are proportional to the action requested. Bare
`omni init` may ensure `.omni/` is ignored by git, and
`omni init --install-claude-hooks` may additionally ignore hook-owned temporary
and legacy backup paths. Non-init commands such as `omni ingest` and
`omni audit secrets` never modify user files while ensuring the `.omni/`
layout.

Rationale: routine commands should not create surprise working-tree diffs in
real projects. The only commands that modify `.gitignore` are the commands
whose visible purpose is initialization or hook installation.

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

Decision: `omni ingest` runs the stale-run watchdog after ingesting queued or
manual events and before committing the SQLite transaction.

Rationale: `runs.status` should not be dead state that only changes when a
developer calls an internal helper. Ingest is the durable maintenance boundary
already allowed to write SQLite, so it is the narrowest place to close open runs
whose transcript path is missing or stale.

Decision: `omni ingest` prunes redacted hook files under
`.omni/spool/processed/` after acknowledging consumed hook records. The default
retention keeps processed hook files for up to 7 days or 128 MiB, whichever
limit is hit first.

Rationale: processed hook files are already-redacted recovery evidence, not the
primary database. Real dogfood volume showed this tree can grow by tens of MiB
per day under heavy use, so retaining about a week by age and volume keeps
status/debug evidence useful without unbounded local growth. Live spool files,
bad files, and error logs are not pruned by this maintenance path.

Decision: manual `omni ingest --transcript` is transcript-only unless the user
also supplies `--run-id`.

Rationale: unscoped hook reconciliation can attach unrelated live-session hook
spool to a manually ingested transcript. When `--run-id` is provided, Week-1
treats it as the Claude session id and only reconciles hook records carrying
that same `session_id`.

Decision: empty-queue `omni ingest` without a run id does not consume live
`hook-*.jsonl` files into a synthetic run.

Rationale: live hook records are only authoritative after a Stop/SessionEnd
ingest request scopes them to a session. A manual fallback can still be run with
an explicit run id, but it only consumes hook records whose payload
`session_id` equals that run id; records without that `session_id` remain in
spool for the real scoped request or a correctly scoped recovery. The default
path should not steal hooks before the real session request arrives.

Decision: `omni init --install-claude-hooks` installs into
`.claude/settings.local.json` by default. Project-level installation into
`.claude/settings.json` remains available only with
`--claude-hooks-scope project`.

Rationale: dogfood hooks are personal capture configuration. Committing them to
a shared project can either break other users who do not have `omni` installed
or silently enable capture for users who do. The local settings target keeps
dogfood opt-in per checkout while preserving an explicit project-scope escape
hatch for disposable sandboxes or intentionally single-user repos.

Decision: installed Claude hooks use the portable command `omni hook` by
default. `OMNI_HOOK_COMMAND` remains the explicit escape hatch for local
environments that need a fully qualified command.

Rationale: project `.claude/settings.json` may be shared or inspected. A local
absolute Python path leaks workstation details and breaks on other machines.

Decision: `.omni/redaction-allow.txt` is an audit-only exact-value allowlist.

Rationale: it exists only to suppress known audit false positives during local
validation. It does not change runtime hook, parse, ingest, or render redaction.
It must not be used to approve real secrets.

Decision: `omni status` hook elapsed percentiles are in-process capture metrics,
not end-to-end process startup latency.

Rationale: the value is written by the hook while handling a payload. Week-1
demo notes that process-level latency should be sampled separately when judging
Claude Code UX.
