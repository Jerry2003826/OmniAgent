# Dogfood Acceptance Record

Date:

Operator:

Target project:

OmniMemory commit:

Target project commit:

## Gate

```bash
pytest -q
omni audit secrets
where omni
```

OmniMemory result:

```text
<paste concise result>
```

Target project gate:

```bash
omni audit secrets
omni status
git status --short
```

Target result:

```text
<paste concise result>
```

## Memory State

```bash
omni render --diff
omni render
grep -n "omni:begin" CLAUDE.md
grep -n ".omni/generated/memory.md" CLAUDE.md
git diff -- CLAUDE.md .omni/generated/memory.md
```

Memory notes:

```text
<managed region present, memory sections present, no raw ids/evidence/secrets>
```

## Runs

Cold or old negative run id:

Warm run id:

Prompt used:

```text
Please validate this project and tell me whether the current setup works. Use the project memory if available.
```

Post-run ingest:

```bash
omni ingest
omni audit secrets
omni status
```

Result:

```text
<paste concise result>
```

## Eval

```bash
omni eval run <warm_run_id>
omni eval dogfood --cold <cold_run_id> --warm <warm_run_id>
```

Key fields:

```text
memory_effect:
expected_verification_executed:
first_expected_command:
first_expected_command_position:
rediscovery_count:
rediscovery_before_expected_command:
dogfood improvement:
```

## Verify and Outcome

```bash
omni verify
omni outcome mark-from-verify <warm_run_id> --task-type validation
omni outcome show <warm_run_id>
```

If using a qualifier:

```bash
omni verify --qualifier <qualifier>
omni outcome mark-from-verify <warm_run_id> --qualifier <qualifier> --task-type validation
```

Key fields:

```text
verify status:
verify reason_code:
verify command:
outcome tests_status:
outcome status:
outcome memory_effect:
```

## Experience / Failure Follow-up

Commands run:

```bash
omni experience extract <warm_run_id>
omni experience ls
omni failure extract <warm_run_id>
omni failure ls
```

Candidates:

```text
<candidate ids and reviewed decision, or created=0 with reason>
```

## Verdict

Verdict: PASS | PARTIAL | FAIL | INCONCLUSIVE

Reason:

```text
<short evidence-based explanation>
```

Follow-up:

```text
<renderer wording, lifecycle, verify, or no follow-up>
```
