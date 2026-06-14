# CLI-only Claude Code v1 Readiness

## Product Shape

CLI-only Claude Code v1 is the first productized OmniMemory shape:

- local Python CLI only
- Claude Code only
- project-local `.omni/` state only
- no background service
- no MCP server
- no vector search
- no dashboard or TUI
- no adapter layer beyond Claude Code hooks
- no automatic success inference or automatic memory evolution

The goal is not to add another memory type. The goal is to make the existing
closed loop installable, discoverable, and explainable for one Claude Code user:

```text
Claude Code run
-> redacted trace
-> ingest
-> behavior eval
-> user-marked outcome
-> reviewable experience/failure memory
-> render
-> next Claude Code run
-> measurable behavior comparison
```

## Existing Capabilities

The runtime already has the pieces needed for the loop:

- `omni init`
- `omni audit secrets`
- `omni init --install-claude-hooks --yes`
- `omni inject claude --mode preview`
- `omni inject claude --mode link`
- `omni ingest`
- `omni status`
- `omni eval run <run_id>`
- `omni eval dogfood --cold <run_id> --warm <run_id>`
- `omni outcome mark <run_id>`
- `omni outcome mark-from-verify <run_id>`
- `omni outcome show <run_id>`
- `omni experience extract|ls|show|approve|reject`
- `omni experience note ls|show|retire`
- `omni failure extract|ls|show|approve|reject`
- `omni failure pattern ls|show|retire`
- `omni verify`
- `omni render`

CLI-only v1 starts by making the required safety and ingestion commands
discoverable in `omni --help`: `audit` and `ingest` are public commands.
Lower-level debug or review internals such as `run` and `review` remain hidden
from top-level help until they have a deliberate user-facing shape.

## First-run Path

For the OmniMemory checkout:

```powershell
cd C:\Users\Jiarui Li\Documents\OmniAgent
pip install -e ".[dev]"
where omni
pytest -q
omni audit secrets
```

For a Claude Code target project:

```powershell
cd <target-project>
omni init
omni audit secrets
omni init --install-claude-hooks --yes
omni inject claude --mode preview
omni inject claude --mode link
```

The real-project rule remains unchanged: do not install hooks into a real
project until `omni audit secrets` passes in that checkout.

After a Claude Code session:

```powershell
omni ingest
omni audit secrets
omni status
omni eval run <run_id>
omni verify
omni outcome mark-from-verify <run_id> --task-type validation
omni experience extract <run_id>
omni failure extract <run_id>
omni render --diff
omni render
```

Human review remains explicit. v1 does not approve experience notes or failure
patterns automatically.

## Acceptance Criteria

CLI-only Claude Code v1 is ready when these are true:

1. A fresh user can discover the supported command path from `omni --help`,
   subcommand help, and one runbook.
2. The runbook includes a first-run path, post-run ingest path, review path, and
   rollback/retire path.
3. The real-project safety gate is clear: `omni audit secrets` must pass before
   hook installation.
4. Read-only commands are documented and tested to avoid migrations and SQLite
   writes.
5. Approved writers are documented and limited to the AGENTS.md command list.
6. `memory.md` rendering still excludes run ids, candidate ids, note ids,
   pattern ids, evidence payloads, timestamps, confidence, and raw stderr.
7. A temporary-project smoke proves the public CLI path can initialize, render,
   and retire memory without relying on private test helpers.
8. A real Claude Code dogfood record demonstrates at least one cold/warm
   comparison using the v1 path.

## Implementation Order

1. Make the existing v1 path discoverable in CLI help.
2. Add a concise CLI-only user runbook.
3. Add a temporary-project CLI smoke that uses only public commands.
4. Run one real Claude Code dogfood acceptance pass using the runbook.
5. Write a closeout record with the exact commands, run ids, audit result, and
   dogfood verdict.

## Non-goals

Do not implement these in CLI-only Claude Code v1:

- MCP
- vector search
- dashboard or TUI
- adapter layer for other agents
- Computer Use
- LLM extractors
- Soul runtime
- new database tables
- new memory types
- automatic success inference
- automatic failure memory
- automatic memory evolution
- supersede or reactivation lifecycle
