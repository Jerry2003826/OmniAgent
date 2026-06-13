# OmniMemory v0.2 Closeout Audit

Date: 2026-06-14 local

Branch base audited: `29e71a3bdb563b55613fb95464ecb27a6331796e`

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
- SQLite read-only commands: `parse`, `status`, `run show`, `eval run`,
  `eval dogfood`, `outcome show`, `experience ls/show`, `failure ls/show`,
  `failure pattern ls/show`, and `verify`.

Notes:

- `omni audit secrets` is not a SQLite writer, but it intentionally writes the
  existing audit marker `.omni/audit/secrets.passed` when the audit passes.
- Hidden legacy commands such as `omni doctor` and `omni review interactive`
  are outside this v0.2 closeout surface and were not expanded.

## Local Verification

Commands run in the repository:

```bash
where.exe omni
pytest -q
omni audit secrets
```

Results:

- `where.exe omni` resolved to
  `C:\Users\Jiarui Li\scoop\apps\python\current\Scripts\omni.exe`.
- `pytest -q`: `412 passed, 3 skipped, 1 warning`.
- `omni audit secrets`: `ok=true`, no positive fixture misses, no negative
  fixture failures, and no `.omni` leaks.

## Current CLI Smoke

The current refresh also ran against the real unihack dogfood project after
`omni audit secrets` passed there:

```bash
omni verify
omni eval dogfood --cold fcdefb4a-2d39-46ed-ab1e-a1cae466e861 --warm 0caab82c-8ae8-40b9-9b51-a0b10a94ae8e
```

Results:

- `omni verify` selected `pnpm run test`, exited 0, and reported
  `status=passed`.
- The underlying unihack test run reported `21 passed | 1 skipped` test files
  and `97 passed | 5 skipped` tests.
- The dogfood comparison reported `improvement=true`,
  `command_adopted=true`, cold rediscovery count `10`, warm rediscovery count
  `1`, cold first expected command position `null`, and warm first expected
  command position `64`.

The warm run is still not strict proof that the agent always runs the expected
command before all rediscovery. It remains a behavior improvement: expected
commands were adopted and rediscovery dropped, but the warm run still had one
broad scan before the first expected command.

## Read-only Guard

The following commands were run against the real unihack SQLite database while
checking the database SHA-256 before and after:

- `omni status`
- `omni run show 0caab82c-8ae8-40b9-9b51-a0b10a94ae8e`
- `omni eval run 0caab82c-8ae8-40b9-9b51-a0b10a94ae8e`
- `omni eval dogfood --cold fcdefb4a-2d39-46ed-ab1e-a1cae466e861 --warm 0caab82c-8ae8-40b9-9b51-a0b10a94ae8e`
- `omni outcome show 0caab82c-8ae8-40b9-9b51-a0b10a94ae8e`
- `omni experience ls --state all`
- `omni failure ls --state all`
- `omni failure pattern ls`
- `omni verify`

All commands exited 0. The SQLite hash stayed unchanged:

```text
496A4433E4E51889735F9406D8A58D8B02B4EFF7D7486B596F701D47B458B2BA
```

In an empty temporary directory, read-only commands did not create `.omni`.
Commands that require an existing database exited non-zero as expected.

## Fixture Coverage

The test suite and the earlier fixture smoke cover the full write-side CLI
surface:

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

## Acceptance Matrix

| Area | Status | Evidence | Boundary |
| --- | --- | --- | --- |
| Behavior Eval v0 | Pass for deterministic measurement | Real dogfood comparison reports `improvement=true`, cold `failed_to_help`, warm `neutral`, rediscovery `10 -> 1`, and command adoption. | Single-run `memory_effect` can remain `neutral` when memory import is not observable as an explicit read. |
| Outcome Log v0 | Pass | `outcome mark` and `outcome show` are covered by tests and fixture smoke. | Outcomes remain user-marked; there is no automatic success inference. |
| Verify to Outcome | Pass | Real unihack `omni verify` passed with `pnpm run test`; `outcome mark-from-verify` recorded `tests_status=passed`, `status=unknown`, and `final_command=pnpm run test`. | `omni verify` stays read-only; only `outcome mark-from-verify` writes outcome state. |
| Experience candidates, notes, renderer | Partial behavior proof | Old unihack negative run became an approved rediscovery-waste note; later warm runs adopted expected commands and reduced rediscovery. | The latest comparable warm run still had one broad scan before the first expected command. |
| Failure candidates and patterns | Pass for first reviewed pattern | Real dogfood DB has active pattern `failure_pattern_cf6523ba331547b29e2338f40936520e` for `Get-ChildItem -Name` failing under Bash. | Only reviewed active patterns render; broad automatic failure memory remains out of scope. |
| Known Failures renderer | Pass for v0 scope | Tests cover active pattern rendering and exclusion of raw ids/evidence/timestamps; real dogfood has one active pattern. | Rendering is concise guidance, not a runtime matcher or automatic remediation system. |
| Pattern lifecycle | Pass for v0 scope | `failure pattern ls/show/retire` are implemented and covered by tests and fixture smoke. | Lifecycle is active/retired only; no supersede. The real active pattern was not retired to preserve dogfood memory. |
| Read-only command safety | Pass | Real unihack DB hash guard stayed unchanged across status/run/eval/outcome/experience/failure/pattern/verify read-only commands. | `omni audit secrets` is intentionally excluded because it writes the audit marker. |
| Secret safety | Pass | `omni audit secrets` passed in both OmniAgent and unihack after the current smoke. | Redaction remains conservative and irreversible; no raw vault exists. |

## Real Dogfood Status

The real unihack loop remains the strongest evidence for v0.2 behavior impact:

- The old negative run `fcdefb4a-2d39-46ed-ab1e-a1cae466e861` evaluated as
  `failed_to_help`.
- Experience notes reduced rediscovery and were associated with expected
  command adoption in later warm runs. The latest comparable run improved from
  10 rediscovery events to 1, but it is still `PARTIAL` rather than strict pass
  because the first expected command came after one broad scan.
- Renderer tuning later pushed validation fast paths earlier and strengthened
  wording.
- Known Failures rendering was validated with a real failed command path and a
  later warm run that avoided the old failed path.
- Verify v0 selected `pnpm run test` in unihack and passed; the result was
  anchored through `outcome mark-from-verify` on run
  `0caab82c-8ae8-40b9-9b51-a0b10a94ae8e`.

This is still not universal causal proof. The defensible claim is narrower:
redacted evidence can be evaluated, reviewed into memory, rendered back to the
agent, verified with a known command, and anchored in the outcome log without
runtime services or automatic success inference.

## Remaining Stage Checklist

No merge blocker was found in this closeout audit.

Before starting a larger new module, the remaining prudent checks are:

- If the next module depends on real behavior impact, run one more controlled
  cold/warm dogfood comparison and keep the result separate from this smoke
  proof.
- Keep `Failure Pattern Lifecycle v0` limited to active/retired lifecycle unless
  a concrete review need justifies supersede.
- If deepening Verify v0, keep `omni verify` read-only and keep writes behind
  `outcome mark-from-verify` or another explicitly approved writer.

Recommended next module after a clean closeout: decide between a small
behavior-retuning pass for the remaining `PARTIAL` unihack validation result, or
small Verify v0 hardening. Do not start automatic failure memory or automatic
experience evolution from this report alone.
