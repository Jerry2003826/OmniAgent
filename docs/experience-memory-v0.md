# Experience Memory v0

Experience Memory v0 keeps the next iteration focused on measurement before
adding new memory types or runtime surfaces.

## Behavior Eval v0

Behavior Eval v0 adds read-only commands for classifying whether an ingested run
appears to use existing memory effectively. It is a heuristic evaluator, not causal proof
by itself; treat a single-run result as evidence about observed
behavior, and use cold/warm comparison when making a memory-impact claim.

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

Hard classification signals come from tool input fields such as `tool_input`,
`input`, `parameters`, or `args` with command, path, or glob-pattern values.
Tool output, response, and message-context fields are ignored for hard command
and rediscovery detection so stdout or historical content does not look like an
agent action.

JSON output is bounded. The report includes the first 100 observed commands and
the first 100 rediscovery events, plus `observed_commands_omitted` and
`rediscovery_events_omitted` counts when longer runs exceed those limits. String
values are redacted and truncated before the final JSON redaction pass so large
runs keep the same eval-report shape instead of becoming a redaction wrapper.

Current scope limitation: expected commands are project-level facts. The
evaluator does not yet model task-specific expectations, package-specific
workspaces, or per-subdirectory command scopes.

The `memory_effect` values are:

- `helped`: an expected verification command ran before forbidden rediscovery
  and memory context was observed.
- `neutral`: an expected verification command ran, but only after rediscovery or
  the task signal is otherwise unclear. This also covers aligned behavior where
  no `CLAUDE.md` or generated-memory read was detected.
- `failed_to_help`: `CLAUDE.md` or generated memory appears to have been read,
  but no expected verification command ran and rediscovery occurred.
- `unknown`: there is not enough stored evidence to classify the run.

When memory context is observed but no expected command runs and no rediscovery
is detected, v0 stays conservative: `memory_effect` remains `unknown`, and the
report sets `memory_context_seen_but_no_expected_command` because task intent is
not yet modeled.

Rediscovery events include reads or listings involving `README.md`,
`package.json`, `pnpm-lock.yaml`, `package-lock.json`, `yarn.lock`, `DEPLOY.md`,
and broad glob or directory scan behavior.

`omni eval dogfood --cold <run_id> --warm <run_id>` compares cold and warm runs
by rediscovery count, first expected command position, command adoption, and an
improvement flag. Improvement requires the warm run to execute an expected
command.

The unihack negative sample should be represented as `failed_to_help`: Claude
read `CLAUDE.md`, then rediscovered `README.md`, `package.json`, `DEPLOY.md`,
and broad project structure, and did not run any pnpm verification command.

## Outcome Log v0

Outcome Log v0 adds a small user-marked record for an ingested run:

```bash
omni outcome mark <run_id>
omni outcome show <run_id>
```

`omni outcome mark <run_id>` records the human-visible outcome for an existing
run. In v0 this is explicitly user-marked. OmniMemory does not infer task
success, task failure, or test status automatically.

The logged fields are:

- task type: `validation`, `bugfix`, `docs`, `refactor`, `exploration`, or
  `unknown`
- status: `success`, `failed`, or `unknown`
- tests status: `passed`, `failed`, `not_run`, or `unknown`
- memory effect: `helped`, `neutral`, `failed_to_help`, or `unknown`
- optional redacted free text: summary, final command, and note

If the caller does not provide `memory_effect`, the outcome command may reuse
Behavior Eval v0 when the local evidence is available, but it falls back to
`unknown` and never blocks the mark operation on eval uncertainty.

Outcome records are an anchor for future experience and failure memory work:
they connect a run id, the observed memory effect, and a user-marked outcome.
Outcome Log v0 does not create failure memory, automatic verify logic, or any
runtime memory behavior.

## Experience Candidate v0

Experience Candidate v0 turns Behavior Eval and Outcome Log evidence into
reviewable candidate records only:

```bash
omni experience extract <run_id>
omni experience ls
omni experience show <exp_cand_id>
omni experience approve <exp_cand_id>
omni experience reject <exp_cand_id>
```

`omni experience extract <run_id>` reads the run's Behavior Eval result and its
user-marked outcome. It can create `fast_path` candidates when validation
succeeded after using the known verification command early, or
`rediscovery_waste` candidates when validation had memory available but
rediscovered project structure and missed the known verification command.

Candidates are reviewable only as candidate rows. In v0.2, `extract` proposes
candidates and human review decides whether the candidate should become active
experience memory.

This is the bridge from eval/outcome evidence to future memory rendering:
candidate rows preserve the run id, outcome id, eval summary, outcome summary,
claim, and suggested action without raw event payloads.

## Experience Notes + Renderer v0

Experience Notes + Renderer v0 turns approved candidates into active experience
notes and renders active notes into `.omni/generated/memory.md`:

```bash
omni experience approve <exp_cand_id>
omni render
```

All notes are review-gated. A pending candidate does not render. A rejected
candidate does not render. In this v0, approving a pending candidate creates one
active note with project scope, the candidate task type and kind, the candidate
claim as note body, and the candidate suggested action as behavior guidance.
Approving an already-approved candidate is idempotent when its active note
already exists, and rejected candidates cannot be approved in v0.

In practice, active notes can affect future agent behavior only through the
generated memory file that existing Claude/agent context reads. The renderer
keeps note evidence, run ids, candidate ids, note ids, timestamps, and
confidence values out of `memory.md`; it renders concise guidance such as
validation fast paths instead.
When an active `uses_test_command` fact exists, validation fast-path notes may
render the concrete command, for example `pnpm run test`; otherwise they use the
generic known-verification-command wording.

This is still not Soul runtime, failure memory, verify automation, automatic
memory evolution, LLM extraction, MCP, vector search, dashboard work, or an
adapter layer. Experience notes are a small reviewed bridge from eval/outcome
evidence into deterministic rendered behavior guidance.
