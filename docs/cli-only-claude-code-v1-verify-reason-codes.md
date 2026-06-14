# CLI-only Claude Code v1 — Verify Reason Codes

`omni verify` runs the known project verification command and prints a redacted
JSON result. It is read-only with respect to OmniMemory state (it opens SQLite
read-only and runs no migrations); the only writer in the post-verify flow is
`omni outcome mark-from-verify`. This document is the reference for the `status`,
`reason_code`, and process exit codes it can emit.

`docs/cli-only-claude-code-v1-runbook.md` remains the operator path; this file is
the field guide for reading a `verify` result.

## Status and exit codes

| `status` | meaning | CLI exit code |
|---|---|:--:|
| `passed` | command ran and exited 0 | 0 |
| `failed` | command ran and failed, timed out, or could not start | 1 |
| `unknown` | no command was executed (selection or parse problem) | 2 |

`status` is the headline; `reason_code` is the precise cause.

## Reason codes that executed a command

| `reason_code` | `status` | when |
|---|---|---|
| `passed` | `passed` | the command exited 0 |
| `failed_exit_code` | `failed` | the command exited non-zero (`exit_code` is set) |
| `timed_out` | `failed` | the command exceeded `timeout_seconds` (`timed_out: true`) |
| `start_failed` | `failed` | the command could not be started (e.g. executable not found) |

## Reason codes from command selection (nothing executed)

These resolve the active `uses_test_command` facts and stop before running
anything.

| `reason_code` | `status` | when |
|---|---|---|
| `no_active_test_command` | `unknown` | no active `uses_test_command` fact exists |
| `ambiguous_active_test_command` | `unknown` | several distinct commands are active and no `--qualifier` disambiguates them |
| `qualifier_not_found` | `unknown` | `--qualifier <q>` matched no active fact |
| `ambiguous_qualifier` | `unknown` | `--qualifier <q>` matched several distinct commands |

When selection is ambiguous, the result lists the choices under
`candidate_commands` (capped at 10, with `candidate_commands_omitted` counting
the remainder). Pass a more specific `--qualifier`, or retire the extra
`uses_test_command` facts, to make the selection unambiguous.

## Reason codes from command parsing (nothing executed)

The selected command is parsed without a shell. These reject anything that would
need shell semantics.

| `reason_code` | `status` | when |
|---|---|---|
| `parse_error_empty_command` | `unknown` | the command is empty after normalization |
| `parse_error_shell_operator` | `unknown` | the command contains an unquoted `;`, `\|`, or `&&` |
| `parse_error_shell_wrapper` | `unknown` | the command delegates to a shell interpreter (`bash -c`, `cmd /c`, PowerShell `-Command`, `env -S …`) |
| `parse_error_batch_metacharacter` | `unknown` | a Windows batch target (`.bat`/`.cmd`) is combined with batch metacharacters |
| `parse_error_invalid_command` | `unknown` | the command cannot be tokenized (unbalanced quotes, embedded null byte, unresolvable executable) |

## Other values

- `selected` is an internal selection state. A successful selection always runs
  the command, so a completed result reports an execution reason code
  (`passed` / `failed_exit_code` / `timed_out` / `start_failed`), never
  `selected`.
- `unknown` is the default reason code before selection resolves; it should not
  appear in a completed result.

## Notes

- Output excerpts are redacted and bounded. `stdout_truncated` /
  `stderr_truncated` flag when an excerpt was shortened, whether by the text
  budget or the in-flight capture limit.
- `omni verify` never writes OmniMemory state, but it does execute the selected
  project command (for example `pnpm run test`). Bridge a result into the Outcome
  Log with `omni outcome mark-from-verify <run_id>`; task success stays
  user-marked via `--success`.
