# OmniMemory v0.4 Verify Polish Plan

Date: 2026-06-14 local

## Summary

v0.4 is a small polish stage for Verify. It should reduce ambiguity in the
verify contract without expanding OmniMemory into new runtime features.

This stage should not add tables, migrations, adapters, MCP, vector search,
dashboard UI, LLM extraction, Computer Use, Soul runtime, automatic evolution,
automatic failure memory, or automatic success inference.

## Planned Work

1. Decide `start_failed` exit semantics.
   - Current behavior: verify result has `status="failed"` and
     `reason_code="start_failed"`, so CLI exits `1`.
   - v0.4 decision: either keep exit `1` as a failed verification command, or
     map only `start_failed` to exit `2` as an environment/selection problem.
   - Update tests and docs to match the chosen contract.

2. Centralize verify reason codes.
   - Replace scattered string literals with one local source of truth in
     `verify.py`.
   - Keep public JSON values unchanged unless the exit-code decision explicitly
     requires documentation changes.

3. Add narrow missing regression coverage.
   - Add a literal empty configured command case.
   - Keep the test focused on stable JSON and reason code behavior.

4. Refresh manual docs if verify becomes part of acceptance.
   - Update `docs/demo.md` only if the manual runbook should now include
     `omni verify`.
   - Keep v0.2/v0.3 dogfood claims narrow and evidence-based.

5. Re-run read-only safety smoke.
   - Confirm `omni verify` still opens SQLite read-only, runs no migrations,
     and writes no OmniMemory state.
   - Confirm `outcome mark-from-verify` remains the separate approved writer.

## Acceptance Criteria

- `pytest -q` passes.
- `omni audit secrets` passes.
- `git diff --check` passes.
- No new migrations or tables are added.
- `AGENTS.md`, docs, CLI behavior, and tests agree on verify exit semantics.
- Any PR for v0.4 remains tightly scoped to Verify Polish.

## Recommended PR Order

1. `verify: settle start_failed exit semantics`
2. `verify: centralize reason codes`
3. `docs: refresh verify manual acceptance`

Each PR should be independently reviewable and should not mix runtime behavior
changes with broad documentation cleanup.
