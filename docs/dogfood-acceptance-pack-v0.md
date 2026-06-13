# Dogfood Acceptance Pack v0

Dogfood Acceptance Pack v0 is a repeatable evidence package for proving the
current OmniMemory loop on a real project. It adds no runtime features and no
new storage. It turns existing commands into a controlled acceptance procedure:

```text
rendered memory -> Claude Code warm run -> ingest -> eval -> verify -> outcome -> reviewed evidence
```

Single runs are not causal proof. The strongest claim comes from a comparable
cold/warm pair where the warm run executes the expected command earlier and does
less rediscovery.

## Scope

This pack covers real-project validation for the already implemented v0.2-v0.4
surface:

- Behavior Eval
- Outcome Log and `mark-from-verify`
- Experience Notes renderer
- Failure Patterns and Known Failures renderer
- Verify preflight

It does not implement MCP, vector search, dashboard UI, adapters, Computer Use,
LLM extractors, Soul runtime, automatic success inference, automatic failure
memory, automatic memory evolution, or new database tables.

## Preconditions

Run from the OmniMemory checkout first:

```bash
git rev-parse HEAD
pytest -q
omni audit secrets
where omni
```

Then move to the target project root and gate real-project work:

```bash
omni audit secrets
omni status
git status --short
```

Do not continue if `omni audit secrets` fails. Do not install or modify hooks
unless that is part of the explicit test. Do not edit target project source as
part of this acceptance pack except for OmniMemory managed outputs such as
`.omni/generated/memory.md` and the managed `CLAUDE.md` region.

## Prepare Memory

In the target project:

```bash
omni render --diff
omni render
grep -n "omni:begin" CLAUDE.md
grep -n ".omni/generated/memory.md" CLAUDE.md
```

If the managed region is missing:

```bash
omni inject claude --mode preview
omni inject claude --mode link
```

Re-check:

```bash
omni audit secrets
git diff -- CLAUDE.md .omni/generated/memory.md
```

Expected:

- `CLAUDE.md` changes only inside the managed region.
- `.omni/generated/memory.md` contains no run ids, candidate ids, note ids,
  pattern ids, evidence JSON, timestamps, raw stderr, or secrets.
- `omni audit secrets` exits 0.

## Warm Run

Open a fresh Claude Code session in the target project root. Use a neutral task
prompt. Do not tell the agent the exact verification command.

Recommended prompt:

```text
Please validate this project and tell me whether the current setup works. Use the project memory if available.
```

After the Claude Code run ends:

```bash
omni ingest
omni audit secrets
omni status
```

Record the new `run_id`, then evaluate it:

```bash
omni eval run <warm_run_id>
omni verify
omni outcome mark-from-verify <warm_run_id> --task-type validation
```

If the target has a known qualifier-specific command, use the same qualifier for
both verify and outcome:

```bash
omni verify --qualifier <qualifier>
omni outcome mark-from-verify <warm_run_id> --qualifier <qualifier> --task-type validation
```

## Cold/Warm Comparison

Compare the new warm run against a known cold or old negative run:

```bash
omni eval dogfood --cold <cold_run_id> --warm <warm_run_id>
```

Record:

- cold and warm run ids
- `memory_effect`
- `first_expected_command`
- `first_expected_command_position`
- `expected_verification_executed`
- `rediscovery_count`
- rediscovery kinds before the first expected command
- `dogfood improvement`
- verify `reason_code`
- outcome `tests_status`

## Acceptance Verdict

Use these verdicts:

- `PASS`: warm run executes the expected verification command before forbidden
  rediscovery, rediscovery count is lower than cold, `omni verify` passes, and
  `omni audit secrets` passes.
- `PARTIAL`: warm run adopts the expected command or reduces rediscovery, but
  still does broad rediscovery before the first expected command, or verify is
  inconclusive.
- `FAIL`: memory is available but the warm run still misses the expected
  verification command and repeats broad rediscovery.
- `INCONCLUSIVE`: cold/warm runs are not comparable, the run is missing, ingest
  failed, or the target lacks enough facts to select a verification command.

Do not claim universal causal proof from one pass. A pass is evidence that the
current memory package influenced this target under this task prompt.

## Failure/Experience Follow-up

If the warm run exposes a new failure:

```bash
omni failure extract <warm_run_id>
omni failure ls
omni failure show <failure_cand_id>
```

Approve only after human review:

```bash
omni failure approve <failure_cand_id> --summary "<summary>" --suggested-action "<action>"
omni render --diff
```

If the warm run proves a useful validation fast path:

```bash
omni experience extract <warm_run_id>
omni experience ls
omni experience show <exp_cand_id>
```

Approve only when the candidate is supported by eval and outcome evidence.

## Evidence Record

Copy `docs/dogfood-acceptance-record-template.md` for each real-project run.
Keep evidence concise and redacted. Do not paste raw artifacts, raw stderr,
secrets, or large transcript content.

Recorded stage acceptance:

- `docs/dogfood-stage-acceptance-2026-06-14.md` packages the latest real
  unihack evidence after Failure Lifecycle UX v0. It replays the acceptance
  commands against existing runs and records the current PASS verdict without
  creating a new Claude Code session.
