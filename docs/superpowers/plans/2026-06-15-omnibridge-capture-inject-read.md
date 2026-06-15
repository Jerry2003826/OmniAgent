# Plan — OmniBridge Stage ②: capture adapter, inject target, machine-facing read

Date: 2026-06-15
Governs: Phase C sub-projects **C-1 (capture/inject seam)** and **C-3 (machine read)**
of [`docs/omniagent-phase-c-charter.md`](../../omniagent-phase-c-charter.md).
Status: completed implementation plan. WP-1 through WP-3 have landed. A
second-engine adapter (C-2) and MCP wrapper (C-4) build on this but remain out
of scope here.

> **Read this whole file before writing any code.** Sections 2 (invariants) and 3
> (anti-patterns) are not advice — a violation is grounds for reverting the commit.
> Every work package is **behavior-preserving for the Claude path**: the full
> `pytest -q` suite must stay green and the Claude hook/transcript/`CLAUDE.md`
> behavior must be byte-identical unless a step explicitly says otherwise.

---

## 0. TL;DR of the work

Three seams, each small and independently shippable:

| WP | What | Kind | New command | Status |
|----|------|------|-------------|---|
| **WP-1** | Extract a `capture`/engine seam so Claude hook specifics live behind one interface | refactor (no behavior change) | none | done |
| **WP-2** | Make `inject` target-parametrized (file path + region + import syntax) | refactor (no behavior change) | `omni inject <target>` keeps `claude` working identically | done |
| **WP-3** | Add a **read-only**, machine-facing JSON read surface (memory / known-failures / verify-plan) | additive | `omni memory read`, `omni failure read`, `omni verify plan` (all `R`) | done |

Completed order: **WP-1 → WP-2 → WP-3**. The remaining OmniBridge proof points
are C-2 (a real second engine) and C-4 (a thin read-only MCP wrapper).

---

## 1. Current architecture (read before changing anything)

Capture → store → brain → render → inject. Only the two ends touch Claude.

```
Claude Code hook ──stdin──> `omni hook`
  └ hook.capture_hook(payload: bytes)
       ├ redact_minimal(payload)              # redaction-before-write
       ├ write .omni/spool/hook-<ns>-<uuid>.jsonl   record = {meta, payload}
       └ if hook_event_name in {Stop, SessionEnd}:
            write .omni/spool/ingest-<ns>.json  {event, session_id, transcript_path}

`omni ingest`
  ├ spool.iter_hook_records(root) -> [HookRecord]      # engine-neutral
  ├ spool.drain_ingest_queue(root)                     # engine-neutral
  └ ingest._ingest_one(...)  reconcile transcript+hook by tool_use_id

parse.parse_transcript(path) -> [NormalizedEvent]      # ALREADY engine-neutral
  └ _event_type accepts type | event_type | hook_event_name
  └ fields accept tool|tool_name|name, timestamp|ts|created_at, tool_use_id|id

brain: eval / outcome / experience / failure / verify / gate / review  # engine-neutral, operate on DB rows
render.render_project(...) -> .omni/generated/memory.md # engine-neutral
inject.inject_claude(root, mode) -> CLAUDE.md managed region  # CLAUDE-BOUND
```

**Engine-bound code, exhaustively (this is the entire surface to abstract):**

- `src/omni/hook.py`
  - `CLAUDE_HOOK_EVENTS` (12 event names), `MATCHER_EVENTS` — used only to install hooks
  - `INGEST_EVENTS = {"Stop", "SessionEnd"}` — which events flush an ingest request
  - `install_claude_hooks(...)` + `_settings_with_omni_hooks` + `_hook_group` — writes `.claude/settings.json`
  - `_event_for_enqueue` keys on `hook_event_name`
  - `capture_hook` itself is **engine-neutral** except for the `INGEST_EVENTS` check
- `src/omni/ingest.py`
  - `_preferred_hook_record` order `("PostToolUse","PostToolUseFailure","PreToolUse")`
  - `_hook_duration_ms` keys on `PreToolUse` / `PostToolUse*`
  - reconcile by `tool_use_id`
- `src/omni/config.py`
  - `CLAUDE_HOOK_GITIGNORE_ENTRIES`
- `src/omni/inject.py`
  - hard-coded `CLAUDE.md`, `@.omni/generated/memory.md`, `<!-- omni:begin/end -->`
- `src/omni/cli.py`
  - `_add_inject_parser` exposes only `claude`; `install-claude-hooks` flag on `init`

**Engine-neutral already (do NOT touch to "make it generic" — it already is):**
`parse.py`, `spool.py`, `store.py`, `db.py`, `outcome.py`, `experience.py`,
`failure/*`, `verify/*`, `eval/*`, `render.py`, `gate.py`, `review.py`, `redact.py`.

---

## 2. Hard invariants (violation ⇒ revert)

These come from [`AGENTS.md`](../../../AGENTS.md) and the Phase C charter. They are
**not negotiable** and several already have tests guarding them.

1. **Redaction-before-write.** Every byte written under `.omni/` passes
   `redact.redact` / `redact_minimal`. No raw-dump path, ever. New capture
   adapters redact in exactly the same place `capture_hook` does.
2. **`omni hook` (and any capture entrypoint) ALWAYS exits 0.** Never blocks the
   host agent, never makes permission decisions, never writes the DB.
3. **Capture never writes the DB.** Hooks/adapters only append redacted spool
   files. Only the approved write commands in `AGENTS.md` write SQLite.
4. **Read-only commands open SQLite `mode=ro`, run no migrations.** WP-3's new
   read commands are read-only: use `dbaccess.connect_project_readonly(...)`,
   never `connect_project_migrate`.
5. **No metadata leak.** Machine-read output (WP-3) must not expose internal ids
   (`run_id`, `*_cand_id`, `note_id`, `pattern_id`), evidence blobs, timestamps,
   or confidence/trust scores — the same rule `render` follows. Reuse the render
   redaction path and add the same leak tests.
6. **External consumers are read-only.** Nothing in WP-1/2/3 creates a write path
   for an external engine. Memory still only changes through the human-gated CLI.
7. **No new tables.** None of these WPs need a migration. If you think you need
   one, STOP and leave a `TODO` — do not add migration `008` here.
8. **Adapt only to recorded facts.** Do NOT invent a second engine's hook/event
   schema. Unknown keys go to `events.meta`; unknown transcript lines go to the
   redacted `transcript_archive`. Where a real OpenCode/Codex fact is unknown,
   leave a `TODO` and a spike note — do not guess field names.

---

## 3. Anti-patterns to avoid (these are the exact mistakes made in this codebase before — do NOT repeat them)

Each item is a real defect class found in review of this repo. Read the "why".

1. **No "twin" functions.** (Defect seen: `connect_project_readonly` vs
   `connect_project_readonly_verify` — two near-identical bodies differing only in
   wording.) When the second engine arrives, **do not copy the Claude adapter and
   tweak strings.** Share the mechanism; put per-engine differences in a small
   declarative config/table. One mechanism, N configs — never N copies.

2. **No shallow forwarding wrappers.** (Defect seen: `EventCandidate` wrapping a
   `NormalizedEvent` behind 10 pure-passthrough `@property`s.) An adapter
   interface must *hide* real differences, not just forward calls. If your
   abstraction is 90% `return self.inner.x`, you have added boilerplate, not a
   seam. Prefer composition (`adapter.engine.foo`) over a forwarding façade unless
   the façade genuinely stabilizes a shaky interface.

3. **No parallel `if` chains.** (Defect seen: `list_outcomes` had two separate
   per-filter `if x is not None` ladders.) Drive validation + mapping + output
   from **one** declarative spec (a tuple/list of records), iterated once. Adding
   an engine or a field must touch exactly one place.

4. **Behavior-preserving means byte-identical for Claude.** (Defect risk seen:
   error-message wording is asserted verbatim by tests, e.g. `"OmniMemory database
   is missing"` vs `"...not found"`.) Refactors in WP-1/WP-2 must not change the
   Claude spool record shape, the `CLAUDE.md` region text, any error string, or
   any exit code. Run the suite before and after; diffs in test expectations are a
   red flag, not a fix.

5. **YAGNI on the interface shape.** Do NOT design a grand multi-engine plugin
   system up front with one implementation. Extract the seam with **Claude as the
   sole implementation first** (suite stays green), and let the *second real
   engine* (C-2, later) reshape the interface. Speculative generality is how you
   get the forwarding-wrapper and twin problems above.

6. **Name for the domain, not the mechanism.** No `manager`, `helper`, `handler`,
   `data`, `info`, `process` names. Use `CaptureEngine`, `InjectTarget`,
   `ingest_events`, `event_aliases` — names that say what, in domain terms.

7. **Tests assert behavior, not implementation.** (Defect seen: a smoke test was
   converted to in-process global-state juggling, losing entry-point fidelity.)
   New tests cover failure/edge paths (unknown engine, missing target file,
   read-only DB, leak attempts), keep at least one real-subprocess smoke test for
   any new CLI entrypoint, and do not bind to private helpers.

8. **Respect module line budgets.** `tests/test_module_budget.py` caps module
   sizes. `hook.py` is already ~646 lines. If WP-1 grows it, **split** the
   engine-config part into a new submodule and add its budget row — do not grow a
   file past its cap.

---

## 4. WP-1 — Capture / engine seam

**Goal:** isolate the four Claude-specific capture concerns behind one tiny
interface, with Claude as the only implementation. No behavior change.

### 4.1 Introduce `src/omni/capture/` (new package)

```
src/omni/capture/__init__.py     # CaptureEngine protocol + registry
src/omni/capture/claude.py       # the Claude implementation (moved, not rewritten)
```

`CaptureEngine` is a *data-first* description, not a class hierarchy:

```python
# capture/__init__.py
from __future__ import annotations
from dataclasses import dataclass, field
from collections.abc import Mapping

@dataclass(frozen=True)
class CaptureEngine:
    name: str                              # "claude"
    ingest_events: frozenset[str]          # {"Stop", "SessionEnd"}
    install: "Callable[[InstallSpec], InstallResult] | None" = None
    # event-name aliases consumed by ingest reconcile, e.g.
    #   {"post": ("PostToolUse", "PostToolUseFailure"), "pre": ("PreToolUse",)}
    event_roles: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

_REGISTRY: dict[str, CaptureEngine] = {}
def register(engine: CaptureEngine) -> None: ...
def get(name: str) -> CaptureEngine: ...      # raises ValueError on unknown engine
def default() -> CaptureEngine:               # "claude" for now
```

### 4.2 Steps (each is one commit)

1. Create the package and `CaptureEngine`; register a single `claude` engine whose
   `ingest_events` and `event_roles` reproduce today's constants
   (`INGEST_EVENTS`, the `_preferred_hook_record` / `_hook_duration_ms` orders).
2. In `hook.py`, replace the literal `INGEST_EVENTS` check in `capture_hook` with
   `engine.ingest_events` (default engine). **No format change** to the spool
   record or the ingest-request file.
3. In `ingest.py`, replace the hard-coded `("PostToolUse", ...)` orders with
   lookups into `engine.event_roles`. Keep reconcile-by-`tool_use_id` as-is.
4. Move `install_claude_hooks` + helpers into `capture/claude.py` as the engine's
   `install`. `hook.py` keeps a thin re-export so `omni init --install-claude-hooks`
   and existing imports/tests are unchanged. (Update `cli.py` import only.)
5. Add `tests/test_capture.py`: registry get/unknown, default engine identity,
   and an assertion that `claude` engine constants equal the old literals.

### 4.3 Done when

- `pytest -q` green; Claude spool record + ingest request byte-identical
  (add a golden-bytes test if one does not exist).
- `hook.py` and `ingest.py` contain **no** literal Claude event names; they read
  them from the engine.
- New `capture/claude.py` budget row added to `tests/test_module_budget.py`.

---

## 5. WP-2 — Inject target abstraction

**Goal:** `inject` works for any prompt file with a managed region. Claude stays a
named target with identical output.

### 5.1 Shape

```python
# inject.py
@dataclass(frozen=True)
class InjectTarget:
    name: str           # "claude"
    filename: str       # "CLAUDE.md"
    begin: str          # "<!-- omni:begin -->"
    end: str            # "<!-- omni:end -->"
    import_line: str    # "@.omni/generated/memory.md"

TARGETS = {
    "claude": InjectTarget("claude", "CLAUDE.md",
                           "<!-- omni:begin -->", "<!-- omni:end -->",
                           "@.omni/generated/memory.md"),
    # opencode/cursor added by C-2 with RECORDED region syntax, not guesses
}

def inject(root, *, target: str, mode: str) -> InjectResult: ...
```

### 5.2 Steps

1. Extract `InjectTarget` and rewrite the body of today's `inject_claude` to take a
   target. The managed-region find/replace logic is already generic — parametrize
   `BEGIN`/`END`/`MANAGED_REGION` and the `CLAUDE.md` filename from the target.
2. Keep `inject_claude(root, mode)` as a one-line wrapper
   `return inject(root, target="claude", mode=mode)` so existing callers/tests are
   untouched. `ManagedRegionEditedError` message must stay `"CLAUDE.md managed
   region was edited; refusing overwrite"` for the claude target (assert it).
3. CLI: `omni inject claude ...` keeps working; add `omni inject <target>` only for
   targets that actually exist in `TARGETS`. Unknown target ⇒ `parser.error` /
   exit 2, no traceback.
4. Tests: parametrize the existing inject tests over the `claude` target;
   byte-identical output; unknown-target path returns exit 2.

### 5.3 Done when

- Diff of `CLAUDE.md` for the `claude` target is identical to pre-change.
- Adding a new target is **data only** (one `TARGETS` row), no new code path.
- No second target is added here with invented syntax (that is C-2, fact-driven).

---

## 6. WP-3 — Machine-facing read surface

**Goal:** stable, read-only, **leak-free** JSON that an external engine can consume
without parsing human text. This is the core new value of OmniBridge.

### 6.1 Commands (all read-only `R`)

| Command | Returns (JSON) | Source |
|---------|----------------|--------|
| `omni memory read` | the rendered memory the next run would see, structured: `{schema_version, sections:[{kind, items:[...]}]}` | `render` model, **post-redaction** |
| `omni failure read` | active known-failure patterns: `[{summary, suggested_action, command_norm?}]` | `failure.list_patterns(status="active")`, stripped |
| `omni verify plan` | what `verify` *would* run without running it: `{predicate, qualifier, profile, candidate_commands, selection_mode}` | verify selection layer, **no execution** |

Notes:
- These are **machine** views. Output is JSON via the existing `jsonio.as_json`
  / `dump_json` (already redacts), `schema_version` is an integer literal you bump
  on breaking changes.
- `verify plan` must **not** execute anything (today's `omni verify` does run the
  command — `plan` is the dry-run sibling and stays read-only with no process
  spawn).

### 6.2 Steps

1. Add a `read_view(...)` function next to each producer (`render.py`,
   `failure/repo.py`, `verify/selection`), returning **plain dicts/lists already
   stripped of internal ids/evidence/timestamps**. Do not re-derive stripping in
   the CLI — strip at the source so MCP (C-4) reuses it.
2. Wire three read-only CLI commands through the existing `_run_db_command(...)`
   dispatch (it already opens read-only and prints via a renderer). For
   `verify plan`, reuse the read-only verify connection path
   (`connect_project_readonly_verify`) and the selection layer **only**.
3. Drive any per-field stripping from one declarative allowlist of public fields
   (anti-pattern #3): never a hand-maintained parallel `del`-list.
4. Tests `tests/test_machine_read.py`:
   - JSON shape + `schema_version` present
   - **leak tests**: assert no `run_id`/`*_cand_id`/`note_id`/`pattern_id`/
     `evidence`/timestamp keys appear anywhere in the output (reuse the render
     leak-test helper if present)
   - read-only: command runs against a `mode=ro` DB and never migrates
   - `verify plan` spawns **no** subprocess (assert via a patched runner / no
     process side effects)
   - one real-subprocess smoke test per command (entry-point fidelity)

### 6.3 Done when

- All three commands listed `R` in `AGENTS.md`'s read-only section (update that list).
- Leak tests pass with the same strictness as `render`.
- Output is consumable without reading any human-formatted line.

---

## 7. Definition of Done (whole plan)

- `pytest -q` green (state the pass/skip counts in each commit body).
- `git diff --check` clean (no whitespace errors).
- `omni audit secrets` exits 0 when any runtime/`.omni` path changed.
- Claude path is byte-identical for capture spool, ingest request, and `CLAUDE.md`.
- New read commands are read-only and pass metadata-leak tests.
- `AGENTS.md` read/write command lists updated; new modules added to
  `tests/test_module_budget.py`.
- No new DB table; no external write path; no invented second-engine schema.
- Commit format: `dayN: <step> — <what works now>`, one step per commit, body
  includes the `pytest -q` summary.

## 8. Explicitly OUT of scope (do not build here)

- A second engine implementation (OpenCode/Codex) — that is C-2, and it is what
  will *validate* WP-1/WP-2's seams. Build the seams so C-2 is "add data + one
  small module", but do not add the engine now with guessed schemas.
- MCP server — that is C-4, a thin read-only wrapper over WP-3.
- `task` runtime / lifecycle, multi-agent handoff, permission tiers, any UI —
  Stage ③/④, still deferred.
- Any automatic memory write/evolution, LLM extractor, or vector search — banned.
