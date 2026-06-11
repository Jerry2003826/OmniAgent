# OmniMemory Spike Scenarios

Run these only inside a sandbox created by `scripts/create_sandbox.sh`.

## Day 1: S1-S6

S1. Run `omni init`.

S2. Run `omni init --install-claude-hooks --yes` and record the printed diff.

S3. Start Claude Code in the sandbox and submit a simple prompt that runs `pwd`.

S4. Ask Claude Code to run the project test command.

S5. Ask Claude Code to read `package.json`.

S6. End the session and inspect `.omni/spool/` for redacted hook records and ingest queue lines.

## Day 2: S7-S12

S7. Locate the Claude transcript JSONL path for the sandbox session.

S8. Run `omni parse <transcript.jsonl>` once parser support exists.

S9. Run `omni ingest --transcript <transcript.jsonl>` once ingest support exists.

S10. Run `omni run show <run_id>` and inspect event ordering.

S11. Compare hook `tool_use_id` values with transcript tool IDs where available.

S12. Fill `docs/spike-report-template.md` sections 1-10 with observed facts.
