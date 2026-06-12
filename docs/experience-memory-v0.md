# Experience Memory v0

Experience Memory v0 keeps the next iteration focused on measurement before
adding new memory types or runtime surfaces.

## Behavior Eval v0

Behavior Eval v0 adds read-only commands for classifying whether an ingested run
appears to use existing memory effectively:

```bash
omni eval run <run_id>
omni eval dogfood --cold <run_id> --warm <run_id>
```

The evaluator has these boundaries:

- read-only
- no DB writes
- no new tables
- no LLM extractors
- no MCP, vector search, dashboard, adapter, Computer Use, or Soul runtime work

`omni eval run <run_id>` reads the existing `runs`, `events`, and `facts` data.
It reports whether `CLAUDE.md` or `.omni/generated/memory.md` was read when that
is detectable, the active expected commands from `uses_test_command`,
`uses_build_command`, `uses_lint_command`, and `uses_typecheck_command` facts,
the observed shell commands, the first expected command position, rediscovery
events before that position, and a `memory_effect` classification.

The `memory_effect` values are:

- `helped`: an expected verification command ran before forbidden rediscovery.
- `neutral`: an expected verification command ran, but only after rediscovery or
  the task signal is otherwise unclear.
- `failed_to_help`: `CLAUDE.md` or generated memory appears to have been read,
  but no expected verification command ran and rediscovery occurred.
- `unknown`: there is not enough stored evidence to classify the run.

Rediscovery events include reads or listings involving `README.md`,
`package.json`, `pnpm-lock.yaml`, `package-lock.json`, `yarn.lock`, `DEPLOY.md`,
and broad glob or directory scan behavior.

`omni eval dogfood --cold <run_id> --warm <run_id>` compares cold and warm runs
by rediscovery count, first expected command position, and an improvement flag.

The unihack negative sample should be represented as `failed_to_help`: Claude
read `CLAUDE.md`, then rediscovered `README.md`, `package.json`, `DEPLOY.md`,
and broad project structure, and did not run any pnpm verification command.
