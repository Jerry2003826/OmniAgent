# OmniAgent Phase B Charter

Date: 2026-06-15

## Purpose

OmniMemory CLI-only Claude Code v1 (Layers 1–5) is complete. Phase B is the
governed transition toward OmniAgent: expand the CLI boundary without breaking
local-first safety, human review gates, or read-only invariants.

This charter is the approval record for that boundary change. Sub-projects must
not land before this document and an AGENTS.md update are merged.

## 1. Invariants (must not relax)

- **Redaction-before-write:** every content byte written under `.omni/` passes
  `redact.redact(bytes)`. No raw-dump path, no original vault.
- **`omni hook` always exits 0.** Hooks never write the DB; they only append
  redacted spool lines.
- **Read-only commands** open SQLite with `mode=ro`, never run migrations, and
  never write OmniMemory state. `omni verify` may execute the selected project
  verification command but writes no OmniMemory state.
- **Human review gate:** candidates become active memory only after explicit
  approve. No automatic success inference, no automatic memory evolution.
- **Render safety:** generated `memory.md` must not leak internal ids, evidence,
  timestamps, or confidence scores.
- **Real-project gate:** do not install hooks or run real dogfood until
  `omni audit secrets` exits 0 in both the OmniMemory checkout and the target.

Violations require reverting the commit.

## 2. Relaxations (Phase B only)

| Area | v1 boundary | Phase B allowance |
|------|-------------|-------------------|
| Migrations | 001–006 only | 007+ per sub-project rows below |
| Memory types | experience + failure only | one new review-gated type per approved sub-project (preference first) |
| Interactive review | week-2 / disabled | `omni review interactive` enabled (human-gated writes only) |
| Doctor | week-2 / disabled | `omni doctor` enabled (read-only diagnostics) |
| Verify selection | `--qualifier` only | `--task` and `--profile` mapping layers (still read-only) |
| Multi-project | single `project_root()` only | user registry + read-only `omni status --all` |

Still forbidden in Phase B: MCP server, multi-engine router, Computer Use,
vector/embedding search, dashboard/TUI, automatic evolution, automatic failure
memory, LLM extractors, answer cache.

## 3. Approved sub-projects and migrations

| Sub-project | Migration | New tables / commands | DoD |
|-------------|-----------|----------------------|-----|
| Sub-A: review + doctor | none | `omni review interactive`, `omni doctor` | CLI wired; read-only doctor; interactive approve/reject/skip/quit |
| Sub-B: task-profile verify | none | `omni verify --task`, `--profile` | verify still read-only; reason codes tested |
| Sub-C: preference memory | `007_preference_memory.sql` | `preference_candidates`, `preference_notes`, `omni preference *` | candidate→approve→render→retire; render section; no metadata leak |
| Sub-D: multi-project overview | none | `~/.omni/projects.json`, `omni project register/ls`, `omni status --all` | read-only aggregate; single-project status unchanged |

## 4. Sub-project Definition of Done (template)

Each sub-project PR must satisfy:

- `pytest -q` green
- `omni audit secrets` ok when touching runtime paths
- `git diff --check` clean
- read-only invariants preserved for read-only commands
- render/metadata-leak tests pass when touching render
- human review gate preserved for memory writes
- AGENTS.md read/write command lists updated
- charter row marked done in the sub-project closeout note (if any)

## 5. Migration approval process (006 → 007+)

1. Sub-project spec names the migration file(s) and tables.
2. Charter row (section 3) lists the migration before implementation starts.
3. `src/omni/db.py` `MIGRATIONS` tuple registers the new file with the next
   integer version string.
4. Migration SQL ends with `UPDATE meta SET value = 'N' WHERE key = 'schema_version'`.
5. Write commands that call `db.migrate()` apply the migration; read-only
   commands require `LATEST_SCHEMA_VERSION` match.
6. No migration may be added without a matching charter row.

## 6. Execution protocol

Every sub-project follows:

1. `superpowers:using-superpowers`
2. `superpowers:brainstorming` → spec under `docs/superpowers/specs/` (optional
   for wiring-only sub-projects)
3. `superpowers:writing-plans` → plan under `docs/superpowers/plans/`
4. Implementation with TDD and `superpowers:verification-before-completion`

One step = one commit. Commit message format:

```text
dayN: <step> — <what works now>
```

Commit body must include the `pytest -q` summary.

## 7. Ongoing practice (not code gates)

Layer 3 real dogfood samples accrue through human Claude Code sessions per
`docs/cli-only-claude-code-v1-dogfood-cadence.md`. Routine green runs do not
each need a doc; G6 robust 3/3 evidence already exists.
