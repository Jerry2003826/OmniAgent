# OmniMemory Manual Demo

This runbook verifies the week-1 vertical slice:

```text
Claude Code run -> redacted trace -> deterministic facts -> generated memory block -> measurably changed behavior in the next run
```

Run this only in a sandbox repository created by `scripts/create_sandbox.sh`. Do not test on a real project until `omni audit secrets` exits 0.

## Preconditions

From the OmniMemory checkout:

```bash
python -m pytest -q
omni audit secrets
```

Create or refresh a sandbox on macOS/Linux or another environment with Bash:

```bash
bash scripts/create_sandbox.sh /tmp/omni-demo-sandbox
cd /tmp/omni-demo-sandbox
```

On Windows PowerShell, use the equivalent script:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/create_sandbox.ps1 $env:TEMP\omni-demo-sandbox
Set-Location $env:TEMP\omni-demo-sandbox
```

Confirm the sandbox contains `package.json`, `pnpm-lock.yaml`, and `CLAUDE.md`.

## Cold Run

Start a new Claude Code session in the sandbox before any generated memory is injected.

Ask it to run the project tests. Record the run id or transcript path in `docs/spike-report-template.md`.

After the run ends, execute:

```bash
omni ingest
omni render --diff
omni render
omni inject claude --mode preview
omni inject claude --mode link
```

Expected results:

- `.omni/generated/memory.md` exists.
- `CLAUDE.md` contains only this managed region added by OmniMemory:

```md
<!-- omni:begin -->
@.omni/generated/memory.md
<!-- omni:end -->
```

- User-authored `CLAUDE.md` content outside that region is unchanged.
- The generated memory includes the detected package manager and test command.

## Warm Run

Start a fresh Claude Code session in the same sandbox after `omni inject claude --mode link`.

Ask the same task: run the project tests.

After the run ends:

```bash
omni ingest
omni run show <run_id>
```

Inspect the run with `omni run show <run_id>` and, if needed, expand relevant events with:

```bash
omni run show <run_id> --seq <seq>
```

Record the first matching test command and any rediscovery events in `docs/spike-report-template.md`.

## G6 Robust Criterion

Strict acceptance passes if the first command that tries to run tests equals the injected command from `.omni/generated/memory.md`.

Robust acceptance passes when:

```text
first matching test command equals injected command
AND no forbidden rediscovery event occurred before it
```

Allowed before first correct test command:

```text
pwd
git status
ls current directory
read CLAUDE.md
read .omni/generated/memory.md
```

Forbidden before first correct test command:

```text
cat package.json
cat pnpm-lock.yaml
cat package-lock.json
cat pyproject.toml
grep scripts in package.json
npm run
pnpm run without injected command
yarn run without injected command
```

If strict acceptance passes, robust acceptance also passes.

## Final Definition Of Done

- [ ] G1 hook capture writes only redacted data and `omni hook` exits 0.
- [ ] G2 transcript parsing preserves known events and archives unknown lines redacted.
- [ ] G3 ingest persists runs, events, artifacts, and drains the spool idempotently.
- [ ] G4 `omni audit secrets` scans the full `.omni/` tree and exits 0.
- [ ] G5 static extraction passes at least 11 of 12 assertions; A12 path-limited subject deferral is recorded.
- [ ] G6 warm run satisfies the robust criterion above on 3 of 3 golden tasks.
- [ ] G7 hook latency p95 is under 250 ms for week 1, with the hard target under 100 ms.
- [ ] `memory.md` is byte-stable and contains no timestamp, confidence, or `fact_id` in the visible body.
- [ ] `CLAUDE.md` managed region is created safely and user content outside it is unchanged.
- [ ] Day-5B items remain out of scope: observed-command extractor, interactive review loop, full `golden_demo.sh` automation, and `omni doctor`.
