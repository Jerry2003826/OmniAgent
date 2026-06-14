# CLI-only Claude Code v1 Runbook

This runbook is the operator path for the first CLI-only OmniMemory product
shape. It assumes one local Claude Code user, project-local `.omni/` state, and
no service, MCP server, dashboard, vector search, or adapter layer.

## Preconditions

- Python 3.11 or newer
- Claude Code installed
- OmniMemory installed from the local checkout with `pip install -e ".[dev]"`
- On Windows, `where omni` resolves to the intended executable

## Install and Local Safety Check

Run this in the OmniMemory checkout:

```powershell
cd C:\Users\Jiarui Li\Documents\OmniAgent
pip install -e ".[dev]"
where omni
pytest -q
omni audit secrets
```

Do not install hooks into a real target project until this checkout passes
`omni audit secrets`.

## Target Project Setup

Run this from the target project root:

```powershell
cd <target-project>
omni init
omni audit secrets
omni init --install-claude-hooks --yes
omni inject claude --mode preview
omni inject claude --mode link
```

`omni inject claude --mode preview` should show only the managed region. The
link mode must not modify user-authored `CLAUDE.md` content outside:

```md
<!-- omni:begin -->
@.omni/generated/memory.md
<!-- omni:end -->
```

## Run Claude Code

Start a fresh Claude Code session in the target project. Use a normal task
prompt. Do not over-prompt the expected command if you are trying to measure
whether memory changes behavior.

For a validation dogfood run, a suitable prompt is:

```text
Please validate this project and tell me whether the current setup works. Use the project memory if available.
```

## After a Claude Code Run

Run:

```powershell
omni ingest
omni audit secrets
omni status
```

Record the new `run_id` from the `omni ingest` `run_ids=...` output, then
inspect behavior:

```powershell
omni eval run <run_id>
omni verify
omni outcome mark-from-verify <run_id> --success --task-type validation
omni outcome show <run_id>
omni outcome ls
```

`omni verify` is read-only with respect to OmniMemory state. In the post-verify
flow, the write into the Outcome Log happens through
`omni outcome mark-from-verify`. Use
`--success` only after a passing verification command; use `--failed` or
`--unknown` when the user has not confirmed task success.

For the full `reason_code` enumeration and the `reason_code` → `tests_status`
mapping used by `omni outcome mark-from-verify`, see
[Verify reason codes](experience-memory-v0.md#verify-reason-codes-v05-reference)
in `docs/experience-memory-v0.md`.

`omni outcome show <run_id>` shows one run; `omni outcome ls` lists every
recorded outcome with a per-field tally (status, tests_status, memory_effect,
task_type). Both are read-only with respect to OmniMemory state.

## Review and Render Memory

Extract reviewable candidates:

```powershell
omni experience extract <run_id>
omni experience ls
omni failure extract <run_id>
omni failure ls
```

Inspect candidates before approving:

```powershell
omni experience show <exp_cand_id>
omni failure show <failure_cand_id>
```

Approve or reject explicitly:

```powershell
omni experience approve <exp_cand_id>
omni experience reject <exp_cand_id>
omni failure approve <failure_cand_id> --summary "<summary>" --suggested-action "<action>"
omni failure reject <failure_cand_id>
```

Render only after review:

```powershell
omni render --diff
omni render
omni audit secrets
```

## Withdraw Rendered Guidance

Experience notes and failure patterns are withdrawable without deleting their
evidence:

```powershell
omni experience note ls
omni experience note show <note_id>
omni experience note retire <note_id>
omni failure pattern ls
omni failure pattern show <pattern_id>
omni failure pattern retire <pattern_id>
omni render --diff
omni render
```

Retired notes and retired patterns do not render into
`.omni/generated/memory.md`. v1 does not support reactivation or supersede.

## Dogfood Comparison

Compare a cold or older run against a warm run:

```powershell
omni eval dogfood --cold <old_run_id> --warm <new_run_id>
```

For a read-only consolidated review of one warm run (behavior eval, recorded
outcome when present, and optional cold/warm pairwise compare), use the
top-level command instead of chaining the low-level eval/outcome commands:

```powershell
omni dogfood --warm <new_run_id>
omni dogfood --warm <new_run_id> --cold <old_run_id>
```

`omni dogfood` does not ingest, verify, or mark outcomes. Use
`scripts/dogfood_ritual.py` when you need the full write-path governance ritual.

Treat cold/warm comparison as stronger evidence than a single-run
`memory_effect`, especially when Claude Code imports memory without emitting an
explicit `Read` event for `CLAUDE.md` or `.omni/generated/memory.md`.

## Pass Criteria

For a validation task, a strong pass is:

- `omni audit secrets` passes after ingest and after render.
- The warm run executes the known verification command.
- The first expected verification command appears before README/package/deploy
  rediscovery and before broad scans.
- `omni eval dogfood` reports `improvement=true`.

A partial pass is still useful evidence if rediscovery decreases and the
expected command is adopted, but pre-command rediscovery remains.
