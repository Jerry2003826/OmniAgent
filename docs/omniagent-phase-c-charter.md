# OmniAgent Phase C Charter (DRAFT — pending approval)

Date: 2026-06-15
Status: **DRAFT.** Records the boundary change implied by the 2026-06-15 vision
update (OmniAgent reframed as an *agent-agnostic* governed brain layer). No Phase C
sub-project may land before this charter and a matching `AGENTS.md` update are
approved and merged — the same rule Phase B used.

## Purpose

The 2026-06-15 vision reframes OmniAgent as an **agent-agnostic** governed brain
layer for AI Coding Agents (Claude Code, Codex, OpenCode, QwenCode, Cursor) — not
a Claude-only memory loop. Phase A/B built the **Kernel** (Layers 1–5) with its
I/O bound to Claude Code. **Phase C opens the boundary toward OmniBridge**
(multi-engine adapters + a read-only access surface) **without relaxing any safety
invariant.**

This charter supersedes the "MCP server / multi-engine router / multi-agent" rows
of the Phase B non-goals **only as approved future direction** — implementation
still proceeds one governed sub-project at a time.

## 1. Invariants (unchanged from Phase B — must not relax)

- **Redaction-before-write** — every byte under `.omni/` passes `redact.redact`.
- **`omni hook` always exits 0** — hooks never write the DB; only append redacted spool lines.
- **Read-only commands** open SQLite `mode=ro`, never run migrations, never write OmniMemory state.
- **Human review gate** — candidates become active memory only after explicit approve. No automatic success inference, no automatic memory evolution.
- **Render safety** — generated memory must not leak internal ids, evidence, timestamps, or confidence scores.
- **Real-project gate** — no hooks / real dogfood until `omni audit secrets` exits 0 in both checkouts.

### New invariants introduced by multi-agent scope

- **External agents are read-only consumers.** Any adapter or MCP surface may
  *read* rendered memory, known failures, verify plans, and audit summaries. It
  **must not** write OmniMemory state. Every write still goes through the
  human-gated CLI write commands listed in `AGENTS.md`.
- **Capture stays append-only and redacted.** A new capture adapter (OpenCode,
  Codex, …) obeys the same contract as the Claude hook: redact → append spool,
  never touch the DB, never block the host agent.

Violations require reverting the commit.

## 2. Vision → repository mapping

| Vision stage | Status in this repo |
|---|---|
| ① OmniMemory Kernel | **done** (Phase A/B); I/O currently bound to Claude Code |
| ② OmniBridge | **done** (OmniBridge Stage ② — capture/inject seams + machine read) |
| ③ OmniRuntime (task lifecycle, multi-agent handoff) | **Phase C target (C-5)** — task lifecycle only; handoff deferred |
| ④ Product (orchestration, permission tiers, UI) | deferred |

## 3. Relaxations (Phase C only)

| Area | Pre-C boundary | Phase C allowance |
|---|---|---|
| Agent binding | Claude-only hook / transcript / `CLAUDE.md` | extract a `capture` + `inject-target` seam; Claude becomes one implementation; add **one** second engine |
| MCP | forbidden | a **read-only** MCP server exposing memory / known-failures / verify-plan / audit-summary — **no write tools** |
| Machine read | human-facing CLI text only | a stable machine-facing JSON read surface (unified memory read, known failures read, verify plan, audit summary) |
| Inject target | `CLAUDE.md` only | parametrized managed-region injection (`AGENTS.md`, `.cursor/rules`, …) reusing the existing `<!-- omni:begin/end -->` mechanism |

**Still forbidden in Phase C** (defer to Runtime/Product): multi-agent orchestration /
handoff, permission tiers, dashboard / TUI, vector / embedding search, LLM extractors,
automatic memory evolution, **any external write path**, Computer Use.

**Approved in Phase C (Stage ③ — task lifecycle, C-5):** `omni task *` lifecycle
commands and migration **`008_task_runtime.sql`** (`tasks` table + nullable
`runs.task_id`). Tasks are **operational state, not memory** — closing a task does
not auto-create experience/failure/preference rows or infer success without the
existing human-gated commands.

**v0 decisions (locked for C-5 implementation):**
- Representative run for `task close`: the most recent run attached to the task; if
  none, close records task-level `outcome_status` / `tests_status` only.
- Second `task start` while one is open: hard error (no auto-close / supersede).
- `eval` / memory `extract` stay run-keyed in this stage.

## 4. Proposed sub-projects (PROPOSED — each needs explicit approval + DoD before code)

| Sub-project | Scope | New surface | Migration |
|---|---|---|---|
| **C-1: capture/inject seam** | refactor `hook`/`ingest` capture and `inject` into adapter interfaces; Claude becomes one impl behind them (pure refactor, behavior unchanged) | internal interfaces; no new command | none |
| **C-2: second engine** | one of OpenCode **or** Codex: capture adapter + inject target; prove one cold/warm loop end to end | `omni inject <target>`, capture wiring | none |
| **C-3: machine read** | stable read-only JSON for memory / known-failures / verify-plan / audit-summary | e.g. `omni memory read --json` (R) | none |
| **C-4: read-only MCP** | wrap C-3 as MCP tools, read-only | e.g. `omni mcp serve` (R) | none |
| **C-5: task lifecycle** | `tasks` table + `runs.task_id`; start/status/ls/show/close/abandon/read; ingest attaches runs to open task | `omni task *` | **`008_task_runtime.sql`** |

Recommended order: **C-1 → C-3 → C-2 → C-4 → C-5.** C-1 unlocks everything; C-3 defines
the contract external engines consume; C-2 proves the agent-agnostic claim with a
real second engine; C-4 packages C-3 for tool-calling agents. C-5 adds task lifecycle
without multi-agent handoff. Migrations beyond 008 follow the approval process in §5.

## 5. Definition of Done, migrations, execution protocol

### Approved migrations (Phase C)

| Migration | Table(s) / change | Sub-project |
|---|---|---|
| `008_task_runtime.sql` | `tasks`; nullable `runs.task_id`; `meta.current_task_id` pointer | C-5 |

Reuse Phase B charter §4 (sub-project DoD template), §5 (migration approval
006 → 007+ → 008+), and §6 (execution protocol: brainstorm → spec → plan → TDD,
one step = one commit). Each Phase C sub-project additionally asserts:

- the read-only external-consumer invariant holds (no adapter/MCP write path)
- a second-engine adapter does not regress the Claude path
- machine-read output passes the same metadata-leak tests as `render`

## 6. Open decisions for the human (before C-1 lands)

1. Which second engine first — OpenCode or Codex? (vision lists both; pick one to prove the seam)
2. Is the read surface delivered as `omni <noun> read --json` first, with MCP (C-4) as a thin wrapper later? (recommended) or MCP-first?
3. ~~Does `task` runtime (Stage ③) stay deferred until OmniBridge has a proven second engine?~~ **Resolved:** C-5 (task lifecycle) approved after OmniBridge; multi-agent handoff stays deferred.
