# CLI-only Claude Code v1 Release Notes

Date: 2026-06-15

## What This Release Is

CLI-only Claude Code v1 is the first productized OmniMemory path for one local
Claude Code user. It packages the existing redacted-evidence loop into a
discoverable command-line workflow:

```text
Claude Code run
-> redacted trace
-> ingest
-> behavior eval
-> user-marked outcome
-> reviewed experience/failure memory
-> render
-> next Claude Code run
-> dogfood comparison
```

## Supported

- Project-local `.omni/` state.
- Claude Code hook capture through `omni hook`.
- Safety gate through `omni audit secrets`.
- Ingestion through `omni ingest`.
- Behavior evaluation through `omni eval run` and `omni eval dogfood`.
- Read-only consolidated dogfood review through `omni dogfood`.
- User-marked outcomes through `omni outcome mark` and
  `omni outcome mark-from-verify`.
- Reviewable experience candidates and active experience notes.
- Reviewable failure candidates and active known failure patterns.
- Retiring active experience notes and failure patterns.
- Verification preflight through `omni verify`.
- Deterministic memory rendering through `omni render`.
- Claude memory injection through `omni inject claude`.
- Public CLI help for the v1 path, including `audit` and `ingest`.

## Not Supported

- MCP server.
- Vector or embedding search.
- Dashboard or TUI.
- Multi-agent or multi-engine adapter layer.
- Computer Use.
- LLM extractors.
- Soul runtime.
- Background service.
- Automatic success inference.
- Automatic failure memory.
- Automatic memory evolution.
- Supersede or reactivation lifecycle.
- New database tables beyond migrations 001-006.

## Evidence

The v1 closeout dogfood record is in
`docs/cli-only-claude-code-v1-closeout-2026-06-15.md`.

Summary:

- Cold run: `fcdefb4a-2d39-46ed-ab1e-a1cae466e861`
- Warm run: `ff781e76-5063-40de-b0e3-f7496d30678a`
- First expected command: `pnpm run test`
- Rediscovery count: `10 -> 0`
- Dogfood improvement: `true`
- Verify-to-outcome bridge recorded `tests_status=passed`
- `omni audit secrets` passed after the outcome write

The warm single-run `memory_effect` remained `neutral` because Claude Code did
not emit an explicit `Read` event for `CLAUDE.md` or generated memory. The
cold/warm dogfood comparison is the stronger behavior metric for this result.

## Upgrade Notes

No migration is introduced by this release-polish step. Existing databases that
have migrations 001-006 remain current.

The only runtime change in the v1 readiness work was CLI discoverability and
Behavior Eval command normalization for leading directory-change wrappers such
as:

```text
cd "<project>" && pnpm run test
```

## First Commands

From this checkout:

```powershell
pip install -e ".[dev]"
where omni
omni --help
pytest -q
omni audit secrets
```

From a target Claude Code project:

```powershell
omni init
omni audit secrets
omni init --install-claude-hooks --yes
omni inject claude --mode preview
omni inject claude --mode link
```

See `docs/cli-only-claude-code-v1-runbook.md` for the full operator path.
