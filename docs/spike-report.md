# OmniMemory Spike Report - Week 1 Manual Demo

## 1. Environment

- Date: 2026-06-11
- OS: Microsoft Windows NT 10.0.19045.0
- Python version: 3.14.3
- Claude Code version: 2.1.173
- Repo: `C:\Users\Jiarui Li\Documents\OmniAgent`
- Sandbox path: `C:\Users\JIARUI~1\AppData\Local\Temp\omni-g6-coldwarm-e059c86547314019b64a95e202681731`
- Provider: DeepSeek Anthropic-compatible endpoint via ephemeral environment variables; no key recorded here.

## 2. Hook Events Observed

| Event | Count | Notes |
|---|---:|---|
| SessionStart | 4 | Observed across cold plus 3 warm runs. |
| UserPromptSubmit | 4 | Observed across cold plus 3 warm runs. |
| PostToolUse | 14 | Includes Read, Glob, Bash, PowerShell, TaskCreate, and TaskUpdate. |
| Stop | 4 | Observed across cold plus 3 warm runs. |
| SessionEnd | 4 | Observed across cold plus 3 warm runs. |
| PreToolUse | 0 | Not emitted by this Claude Code run surface. |
| PostToolUseFailure | 0 | No tool failures observed. |

## 3. Generated Memory

`omni render` produced `.omni/generated/memory.md` and `omni inject claude --mode link` linked it into the sandbox `CLAUDE.md`.

Visible generated facts:

```text
default build command: pnpm run build
default test command: pnpm run test
node package manager: pnpm
```

`omni status` after the run:

```json
{"claude_link": true, "config": true, "database": true, "generated_memory": true, "ok": true, "omni_dir": true}
```

## 4. G6 Results

Expected injected command: `pnpm run test`

| Run | First test command | Forbidden rediscovery before command | Tool output |
|---|---|---:|---|
| `36010658-558a-4583-987e-c8d11d13432a` | `pnpm run test` | 0 | `sandbox test ok` |
| `f112c057-84a7-4d57-98dc-29268bbff6ac` | `pnpm run test` | 0 | `sandbox test ok` |
| `6331b85d-d9e5-4ba3-aae7-71a1803d01d7` | `pnpm run test` | 0 | `sandbox test ok` |

G6 strict: pass, 3/3.

G6 robust: pass, 3/3. `omni run show <run_id>` showed no `package.json`, lockfile, script grep, or package-manager rediscovery before the injected command in any warm run.

## 5. Redaction And Audit

`omni audit secrets` on the sandbox after the real Claude Code session:

```json
{
  "negative_failures": [],
  "ok": true,
  "omni_leaks": [],
  "positive_failures": []
}
```

The audit scanned the `.omni/` tree and passed.

## 6. Hook Latency

- sample count: 44
- p50: 0 ms
- p95: 0 ms
- max: 0 ms
- O-6 double-fork triggered: no

## 7. Notes

- Cold run id: `962dc143-d7fc-4c83-aa12-f72f33d31026`
- Warm run ids: `36010658-558a-4583-987e-c8d11d13432a`, `f112c057-84a7-4d57-98dc-29268bbff6ac`, `6331b85d-d9e5-4ba3-aae7-71a1803d01d7`
- The cold run discovered a runnable test path itself; the warm runs used the injected memory command.
- A queued-ingest bug that mixed prior session hook events into later runs was fixed before the final G6 run. The final `omni run show` output is session-scoped.
