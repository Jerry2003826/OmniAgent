# OmniMemory v0.2 Closeout Audit

Date: 2026-06-14 local

Branch base audited: `355ff468c6603243f7f83c4c49fb226981a4daa9`

## Scope

This closeout audit covers the current OmniMemory v0.2 / Experience Memory
foundations loop:

- Behavior Eval v0
- Outcome Log v0
- Experience Candidates, Experience Notes, and renderer behavior
- Failure Candidates, Failure Patterns, and Known Failures renderer behavior
- Failure pattern `ls`, `show`, and `retire`
- Verify v0 and `outcome mark-from-verify`

It does not add product features. It does not cover MCP, vector search,
dashboard, adapters, Computer Use, LLM extractors, Soul runtime, automatic
evolution, or new tables beyond migrations 001-006.

## Main Alignment

The current `main` branch contains the approved migration set:

- `001_init.sql`
- `002_outcomes.sql`
- `003_experience_candidates.sql`
- `004_experience_notes.sql`
- `005_failure_candidates.sql`
- `006_failure_patterns.sql`

`src/omni/db.py` reports schema version `6`, matching AGENTS.md and the current
docs.

AGENTS.md, `docs/experience-memory-v0.md`, and the CLI routing agree on the
current v0.2 command surface:

- SQLite writers: `ingest`, `review`, `render`, `outcome mark`,
  `outcome mark-from-verify`, `experience extract/approve/reject`,
  `failure extract/approve/reject`, and `failure pattern retire`.
- SQLite read-only commands: `run show`, `eval run`, `eval dogfood`,
  `outcome show`, `experience ls/show`, `failure ls/show`,
  `failure pattern ls/show`, and `verify`.

Notes:

- `omni audit secrets` is not a SQLite writer, but it intentionally writes the
  existing audit marker `.omni/audit/secrets.passed` when the audit passes.
- Hidden legacy commands such as `omni doctor` and `omni review interactive`
  are outside this v0.2 closeout surface and were not expanded.

## Local Verification

Commands run in the repository:

```bash
where omni
pytest -q
omni audit secrets
```

Results:

- `where omni` resolved to
  `C:\Users\Jiarui Li\scoop\apps\python\current\Scripts\omni.exe`.
- `pytest -q`: `392 passed, 3 skipped, 1 warning`.
- `omni audit secrets`: `ok=true`, no positive fixture misses, no negative
  fixture failures, and no `.omni` leaks.

## CLI Smoke

A temporary project with a fresh `.omni/omni.sqlite3` fixture was created for
end-to-end CLI smoke validation. The smoke covered:

- `omni eval run`: classified the warm fixture as `helped`.
- `omni eval dogfood`: reported `improvement=true`.
- `omni outcome mark` and `omni outcome show`: recorded
  `status=success`, `tests_status=passed`.
- `omni experience extract`, `ls`, `show`, and `approve`: created and approved
  a `fast_path` candidate.
- `omni failure extract`, `ls`, `show`, `approve`, and
  `failure pattern ls/show`: created an active failure pattern.
- `omni render`: rendered both `Fast Path` and `Known Failures` sections.
- `omni failure pattern retire`: moved the pattern to `retired`.
- `omni verify`: selected the active `uses_test_command` fact and returned
  `status=passed`.
- `omni outcome mark-from-verify`: wrote an outcome with
  `tests_status=passed`.

Read-only safety checks:

- 12 read-only commands were run after the smoke writes; the SQLite file
  SHA-256 hash was unchanged before and after those commands.
- 7 read-only commands were run in a directory with no `.omni` state; none
  created `.omni`.

## Real Dogfood Status

The real unihack loop remains the strongest evidence for v0.2 behavior impact:

- The old negative run `fcdefb4a-2d39-46ed-ab1e-a1cae466e861` evaluated as
  `failed_to_help`.
- Experience notes reduced rediscovery and caused expected command adoption in
  later warm runs, but at least one rerun was only `PARTIAL`.
- Renderer tuning later pushed validation fast paths earlier and strengthened
  wording.
- Known Failures rendering was validated with a real failed command path and a
  later warm run that avoided the old failed path.
- Verify v0 selected `pnpm run test` in unihack and passed; the result was
  anchored through `outcome mark-from-verify`.

This is still not universal causal proof. The defensible claim is narrower:
redacted evidence can be evaluated, reviewed into memory, rendered back to the
agent, verified with a known command, and anchored in the outcome log without
runtime services or automatic success inference.

## Remaining Stage Checklist

No merge blocker was found in this closeout audit.

Before starting a larger new module, the remaining prudent checks are:

- After this report merges, run one final `pytest -q` on `main`.
- If the next module depends on real behavior impact, run one more controlled
  cold/warm dogfood comparison and keep the result separate from this smoke
  proof.
- Keep `Failure Pattern Lifecycle v0` limited to active/retired lifecycle unless
  a concrete review need justifies supersede.
- If deepening Verify v0, keep `omni verify` read-only and keep writes behind
  `outcome mark-from-verify` or another explicitly approved writer.

Recommended next module after a clean closeout: small Verify v0 hardening, not
automatic failure memory or automatic experience evolution.
