# OmniMemory

OmniMemory is a local, CLI-only memory loop for Claude Code.

The v1 shape is intentionally narrow:

```text
Claude Code run
-> redacted trace
-> ingest
-> behavior eval
-> user-marked outcome
-> reviewed experience/failure memory
-> render
-> next Claude Code run
-> measurable behavior comparison
```

There is no service, MCP server, vector search, dashboard, adapter layer, or
automatic memory evolution in this version. State is project-local under
`.omni/`, and content written there is redacted before write.

## Install

From this checkout:

```powershell
pip install -e ".[dev]"
where omni
omni --help
pytest -q
omni audit secrets
```

Do not install Claude Code hooks into a real project until `omni audit secrets`
passes in both this checkout and the target project.

## Target Project Setup

From a Claude Code target project:

```powershell
omni init
omni audit secrets
omni init --install-claude-hooks --yes
omni inject claude --mode preview
omni inject claude --mode link
```

`omni inject claude --mode link` only manages this region in `CLAUDE.md`:

```md
<!-- omni:begin -->
@.omni/generated/memory.md
<!-- omni:end -->
```

## After a Claude Code Run

```powershell
omni ingest
omni audit secrets
omni status
omni eval run <run_id>
omni verify
omni outcome mark-from-verify <run_id> --success --task-type validation
```

Record the new `run_id` from the `omni ingest` `run_ids=...` output, not from
`omni status`. `omni verify` is read-only with respect to OmniMemory state; the
Outcome Log write happens only through `omni outcome mark-from-verify`. Use
`--success` only after a passing verification command and once you have confirmed
the task succeeded; otherwise use `--failed` or `--unknown`.

Review and render memory explicitly:

```powershell
omni experience extract <run_id>
omni experience ls
omni failure extract <run_id>
omni failure ls
omni render --diff
omni render
```

Compare behavior across runs:

```powershell
omni eval dogfood --cold <old_run_id> --warm <new_run_id>
```

## Current Evidence

CLI-only Claude Code v1 has a real dogfood PASS recorded in
`docs/cli-only-claude-code-v1-closeout-2026-06-15.md`: rediscovery dropped from
10 to 0, the warm run adopted `pnpm run test` before rediscovery, and the verify
to outcome bridge recorded passing tests.

See:

- `docs/cli-only-claude-code-v1-runbook.md`
- `docs/cli-only-claude-code-v1-readiness.md`
- `docs/cli-only-claude-code-v1-closeout-2026-06-15.md`
- `AGENTS.md`
