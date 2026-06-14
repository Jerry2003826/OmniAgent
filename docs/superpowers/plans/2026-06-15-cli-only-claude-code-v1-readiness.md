# CLI-only Claude Code v1 Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make OmniMemory usable as a first CLI-only Claude Code product path without adding new memory types or runtime services.

**Architecture:** Keep the current local SQLite and `.omni/` architecture. Improve discoverability, runbooks, and public-command smoke coverage around the existing loop instead of adding MCP, adapters, services, dashboards, or new tables.

**Tech Stack:** Python 3.11+, stdlib CLI via `argparse`, SQLite, pytest, Markdown docs, existing OmniMemory commands.

---

## File Structure

- Modify: `src/omni/cli.py`
  - Make the v1-supported commands discoverable in help while keeping abandoned or unsafe internals hidden.
- Create: `tests/test_cli_help.py`
  - Assert public help includes the CLI-only v1 path and still hides unsupported commands.
- Create: `docs/cli-only-claude-code-v1-runbook.md`
  - User-facing first-run and post-run workflow.
- Create: `scripts/cli_only_smoke.py`
  - Temporary-project smoke that exercises public commands only.
- Create: `tests/test_cli_only_smoke.py`
  - Runs the smoke script in a temp project.
- Modify: `AGENTS.md`
  - Keep the phase, writer list, read-only list, and non-goals aligned with the implemented surface.
- Create: `docs/cli-only-claude-code-v1-closeout-2026-06-15.md`
  - Final evidence record after local smoke and real dogfood.

## Task 1: Public CLI Help Surface

**Files:**
- Modify: `src/omni/cli.py`
- Create: `tests/test_cli_help.py`

- [x] **Step 1: Write tests for discoverable commands**

Create `tests/test_cli_help.py` with:

```python
from omni import cli


def _help_for(*args: str) -> str:
    parser = cli.build_parser()
    try:
        parser.parse_args([*args, "--help"])
    except SystemExit:
        pass
    return parser.format_help()


def test_top_level_help_includes_cli_only_v1_commands(capsys):
    code = cli.main(["--help"])
    captured = capsys.readouterr()

    assert code == 0
    for command in (
        "init",
        "audit",
        "ingest",
        "status",
        "eval",
        "outcome",
        "experience",
        "failure",
        "verify",
        "render",
        "inject",
    ):
        assert command in captured.out


def test_top_level_help_keeps_internal_commands_hidden(capsys):
    code = cli.main(["--help"])
    captured = capsys.readouterr()

    assert code == 0
    assert "doctor" not in captured.out
    assert "hook" not in captured.out
```

- [x] **Step 2: Run the tests and verify they fail**

Run:

```bash
pytest -q tests/test_cli_help.py
```

Expected result: failure because `audit` and `ingest` are still hidden from
top-level help.

- [x] **Step 3: Update CLI help visibility**

In `src/omni/cli.py`, remove `audit` and `ingest` from the `_hide_subcommands`
set. Keep `doctor`, `hook`, `parse`, `run`, and `review` hidden unless a later
task deliberately promotes them.

The line should become:

```python
_hide_subcommands(
    subcommands,
    {"doctor", "hook", "parse", "run", "review"},
)
```

- [x] **Step 4: Verify help tests pass**

Run:

```bash
pytest -q tests/test_cli_help.py
```

Expected result: all tests pass.

- [x] **Step 5: Commit**

Run:

```bash
git add src/omni/cli.py tests/test_cli_help.py
git commit -m "cli-v1: expose supported help surface"
```

## Task 2: CLI-only User Runbook

**Files:**
- Create: `docs/cli-only-claude-code-v1-runbook.md`
- Modify: `docs/cli-only-claude-code-v1-readiness.md`

- [x] **Step 1: Create the runbook**

Create `docs/cli-only-claude-code-v1-runbook.md` with these sections:

````markdown
# CLI-only Claude Code v1 Runbook

## Preconditions

- Python 3.11 or newer
- Claude Code installed
- OmniMemory installed from the local checkout with `pip install -e ".[dev]"`
- `where omni` resolves to the intended executable on Windows

## Install and Local Safety Check

```powershell
cd C:\Users\Jiarui Li\Documents\OmniAgent
pip install -e ".[dev]"
where omni
pytest -q
omni audit secrets
```

## Target Project Setup

```powershell
cd <target-project>
omni init
omni audit secrets
omni init --install-claude-hooks --yes
omni inject claude --mode preview
omni inject claude --mode link
```

## After a Claude Code Run

```powershell
omni ingest
omni audit secrets
omni status
omni eval run <run_id>
omni verify
omni outcome mark-from-verify <run_id> --task-type validation
```

## Review and Render Memory

```powershell
omni experience extract <run_id>
omni experience ls
omni failure extract <run_id>
omni failure ls
omni render --diff
omni render
```

Approve or reject experience and failure candidates only after inspecting their
JSON output. Do not approve candidates automatically.

## Withdraw Rendered Guidance

```powershell
omni experience note ls
omni experience note retire <note_id>
omni failure pattern ls
omni failure pattern retire <pattern_id>
omni render --diff
omni render
```

## Dogfood Comparison

```powershell
omni eval dogfood --cold <old_run_id> --warm <new_run_id>
```
````

- [x] **Step 2: Link the runbook from readiness docs**

Append this line to `docs/cli-only-claude-code-v1-readiness.md`:

```markdown
The operator-facing command sequence is maintained in
`docs/cli-only-claude-code-v1-runbook.md`.
```

- [x] **Step 3: Verify docs are clean**

Run:

```bash
git diff --check
```

Expected result: no whitespace errors.

- [x] **Step 4: Commit**

Run:

```bash
git add docs/cli-only-claude-code-v1-readiness.md docs/cli-only-claude-code-v1-runbook.md
git commit -m "docs: add cli-only Claude Code v1 runbook"
```

## Task 3: Public-command Smoke

**Files:**
- Create: `scripts/cli_only_smoke.py`
- Create: `tests/test_cli_only_smoke.py`

- [x] **Step 1: Create a public-command smoke script**

Create `scripts/cli_only_smoke.py` that:

```python
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="omni-cli-v1-smoke-"))
    env = os.environ.copy()
    commands = [
        ["omni", "init"],
        ["omni", "audit", "secrets"],
        ["omni", "status"],
        ["omni", "render", "--diff"],
        ["omni", "render"],
    ]
    results = []
    for command in commands:
        proc = subprocess.run(
            command,
            cwd=root,
            env=env,
            text=True,
            capture_output=True,
            timeout=60,
        )
        results.append({"command": command, "returncode": proc.returncode})
        if proc.returncode != 0:
            print(json.dumps({"ok": False, "root": str(root), "results": results}, indent=2))
            return proc.returncode
    print(json.dumps({"ok": True, "root": str(root), "results": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [x] **Step 2: Add a pytest wrapper**

Create `tests/test_cli_only_smoke.py` with:

```python
import json
import subprocess
import sys


def test_cli_only_smoke_script_passes():
    proc = subprocess.run(
        [sys.executable, "scripts/cli_only_smoke.py"],
        text=True,
        capture_output=True,
        timeout=90,
    )

    assert proc.returncode == 0, proc.stderr + proc.stdout
    result = json.loads(proc.stdout)
    assert result["ok"] is True
    assert [item["returncode"] for item in result["results"]] == [0, 0, 0, 0, 0]
```

- [x] **Step 3: Run smoke tests**

Run:

```bash
pytest -q tests/test_cli_only_smoke.py
```

Expected result: pass.

- [x] **Step 4: Commit**

Run:

```bash
git add scripts/cli_only_smoke.py tests/test_cli_only_smoke.py
git commit -m "cli-v1: add public command smoke"
```

## Task 4: Full Verification and Dogfood Record

**Files:**
- Create: `docs/cli-only-claude-code-v1-closeout-2026-06-15.md`

- [x] **Step 1: Run local verification**

Run:

```bash
pytest -q
omni audit secrets
git diff --check
```

Expected result:

- pytest passes
- audit JSON contains `"ok": true`
- diff check has no whitespace errors

- [x] **Step 2: Run one real Claude Code dogfood pass**

In the target project, follow `docs/cli-only-claude-code-v1-runbook.md` and
record:

```text
cold_run_id=<id>
warm_run_id=<id>
omni eval run <warm_run_id>
omni eval dogfood --cold <cold_run_id> --warm <warm_run_id>
omni audit secrets
```

- [x] **Step 3: Write closeout evidence**

Create `docs/cli-only-claude-code-v1-closeout-2026-06-15.md` with:

```markdown
# CLI-only Claude Code v1 Closeout

## Local Verification

- `pytest -q`: <summary>
- `omni audit secrets`: ok=true
- `git diff --check`: no whitespace errors

## Dogfood Evidence

- cold run: `<cold_run_id>`
- warm run: `<warm_run_id>`
- warm `memory_effect`: `<helped|neutral|failed_to_help|unknown>`
- dogfood `improvement`: `<true|false>`
- rediscovery count delta: `<cold_count> -> <warm_count>`

## Verdict

PASS if the runbook was executable end to end and dogfood comparison improved.
PARTIAL if the runbook was executable but behavior improvement was weak.
FAIL if the runbook could not be completed safely.
```

- [x] **Step 4: Commit**

Run:

```bash
git add docs/cli-only-claude-code-v1-closeout-2026-06-15.md
git commit -m "docs: close out cli-only Claude Code v1"
```

## Task 5: Final PR

**Files:**
- All files changed by Tasks 1-4.

- [ ] **Step 1: Run final validation**

Run:

```bash
pytest -q
omni audit secrets
git diff --check
```

- [ ] **Step 2: Push and open PR**

Run:

```bash
git push -u origin Jiarui/cli-only-claude-code-v1-readiness
gh pr create --base main --head Jiarui/cli-only-claude-code-v1-readiness --title "CLI-only Claude Code v1 readiness" --body "## Summary
- Make the CLI-only Claude Code v1 command path discoverable.
- Add the operator runbook and public-command smoke coverage.
- Record final dogfood evidence and closeout status.

## Test Plan
- pytest -q
- omni audit secrets
- git diff --check
- python scripts/cli_only_smoke.py"
```

- [ ] **Step 3: Merge only after checks and review pass**

Expected result: CI passes on Python 3.11 and 3.12, review has no blocker or
major finding, and the PR does not include unrelated Qwen workflow files.
