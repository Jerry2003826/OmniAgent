"""Read-only verification preflight for known project commands."""

from __future__ import annotations

import json
import os
import signal
import shlex
import shutil
import sqlite3
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from omni import db
from omni.redact import redact

VERIFY_PREDICATE = "uses_test_command"
DEFAULT_TIMEOUT_SECONDS = 120
MAX_COMMAND_CHARS = 300
MAX_OUTPUT_CHARS = 4000
MAX_CAPTURE_BYTES = 64 * 1024
READ_CHUNK_BYTES = 4096
MAX_CANDIDATE_COMMANDS = 10
SELECTION_REASON_SELECTED = "selected active uses_test_command fact"
REASON_CODE_PASSED = "passed"
REASON_CODE_FAILED_EXIT_CODE = "failed_exit_code"
REASON_CODE_TIMED_OUT = "timed_out"
REASON_CODE_START_FAILED = "start_failed"
REASON_CODE_NO_ACTIVE_TEST_COMMAND = "no_active_test_command"
REASON_CODE_AMBIGUOUS_ACTIVE_TEST_COMMAND = "ambiguous_active_test_command"
REASON_CODE_QUALIFIER_NOT_FOUND = "qualifier_not_found"
REASON_CODE_AMBIGUOUS_QUALIFIER = "ambiguous_qualifier"
REASON_CODE_PARSE_ERROR_EMPTY_COMMAND = "parse_error_empty_command"
REASON_CODE_PARSE_ERROR_SHELL_OPERATOR = "parse_error_shell_operator"
REASON_CODE_PARSE_ERROR_SHELL_WRAPPER = "parse_error_shell_wrapper"
REASON_CODE_PARSE_ERROR_BATCH_METACHARACTER = "parse_error_batch_metacharacter"
REASON_CODE_PARSE_ERROR_INVALID_COMMAND = "parse_error_invalid_command"
REASON_CODE_SELECTED = "selected"
REASON_CODE_UNKNOWN = "unknown"
DISAMBIGUATION_HINT = (
    "Pass --qualifier <name> to select one active uses_test_command fact."
)
WINDOWS_BATCH_EXTENSIONS = (".bat", ".cmd")
WINDOWS_BATCH_META_CHARS = ("&", "<", ">", "^", "%", "!")
ENV_WRAPPER_EXECUTABLES = {"env", "env.exe"}
POSIX_SHELL_WRAPPER_EXECUTABLES = {
    "bash",
    "bash.exe",
    "dash",
    "dash.exe",
    "ksh",
    "ksh.exe",
    "sh",
    "sh.exe",
    "zsh",
    "zsh.exe",
}
CMD_WRAPPER_EXECUTABLES = {"cmd", "cmd.exe"}
POWERSHELL_WRAPPER_EXECUTABLES = {
    "powershell",
    "powershell.exe",
    "pwsh",
    "pwsh.exe",
}
SHELL_WRAPPER_EXECUTABLES = (
    POSIX_SHELL_WRAPPER_EXECUTABLES
    | CMD_WRAPPER_EXECUTABLES
    | POWERSHELL_WRAPPER_EXECUTABLES
)
POWERSHELL_COMMAND_FLAGS = {
    "-c",
    "-command",
    "-commandwithargs",
    "-cwa",
    "-e",
    "-ec",
    "-encodedcommand",
    "-enc",
}
POSIX_SHELL_CLUSTER_FLAGS = set("abefhilmnptuvxc")
ENV_OPTIONS_WITH_VALUE = {"-u", "--unset", "-C", "--chdir", "-S", "--split-string"}


class VerifyCommandError(ValueError):
    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(message)


def connect_project_readonly(root: Path | str | None = None) -> sqlite3.Connection:
    base = Path(root or Path.cwd()).resolve()
    db_path = base / ".omni" / "omni.sqlite3"
    if not db_path.exists():
        raise FileNotFoundError(f"OmniMemory database not found: {db_path}")
    conn = db.connect_readonly(db_path)
    version = db.schema_version(conn)
    if version != db.LATEST_SCHEMA_VERSION:
        conn.close()
        raise ValueError(
            f"OmniMemory schema is outdated (found {version or 'none'}, "
            f"need {db.LATEST_SCHEMA_VERSION})"
        )
    return conn


def run_preflight(
    conn: sqlite3.Connection,
    root: Path | str,
    *,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    qualifier: str | None = None,
) -> dict[str, Any]:
    """Execute the active project test command without writing Omni state."""

    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    root_path = Path(root).resolve()
    selection = _select_verification_command(conn, qualifier=qualifier)
    result = _base_result(root_path, timeout_seconds, selection)
    if selection["status"] != "selected":
        result["status"] = "unknown"
        result["reason"] = selection["reason"]
        result["reason_code"] = selection["reason_code"]
        return result

    command = selection["_command_raw"]
    try:
        command_args = _command_args(command, root_path)
    except VerifyCommandError as exc:
        result["status"] = "unknown"
        result["reason"] = str(exc)
        result["reason_code"] = exc.reason_code
        return result

    started = time.perf_counter()
    try:
        completed = _run_process(
            command_args,
            root_path,
            timeout_seconds=timeout_seconds,
        )
    except OSError as exc:
        duration_ms = _duration_ms(started)
        stderr_excerpt, stderr_truncated = _safe_output_with_flag(str(exc))
        result.update(
            {
                "status": "failed",
                "reason_code": REASON_CODE_START_FAILED,
                "exit_code": None,
                "duration_ms": duration_ms,
                "stdout_excerpt": "",
                "stderr_excerpt": stderr_excerpt,
                "stdout_truncated": False,
                "stderr_truncated": stderr_truncated,
                "reason": "verification command could not be started",
            }
        )
        return result

    duration_ms = _duration_ms(started)
    timed_out = bool(completed["timed_out"])
    exit_code = completed["exit_code"]
    stdout_excerpt, stdout_text_truncated = _safe_output_with_flag(completed["stdout"])
    stderr_excerpt, stderr_text_truncated = _safe_output_with_flag(completed["stderr"])
    stdout_truncated = stdout_text_truncated or bool(completed["stdout_capture_truncated"])
    stderr_truncated = stderr_text_truncated or bool(completed["stderr_capture_truncated"])
    if timed_out:
        result.update(
            {
                "status": "failed",
                "reason_code": REASON_CODE_TIMED_OUT,
                "exit_code": None,
                "duration_ms": duration_ms,
                "timed_out": True,
                "stdout_excerpt": stdout_excerpt,
                "stderr_excerpt": stderr_excerpt,
                "stdout_truncated": stdout_truncated,
                "stderr_truncated": stderr_truncated,
                "reason": f"verification command timed out after {timeout_seconds}s",
            }
        )
        return result

    assert isinstance(exit_code, int)
    result.update(
        {
            "status": "passed" if exit_code == 0 else "failed",
            "reason_code": (
                REASON_CODE_PASSED if exit_code == 0 else REASON_CODE_FAILED_EXIT_CODE
            ),
            "exit_code": exit_code,
            "duration_ms": duration_ms,
            "stdout_excerpt": stdout_excerpt,
            "stderr_excerpt": stderr_excerpt,
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
            "reason": (
                "verification command passed"
                if exit_code == 0
                else f"verification command failed with exit code {exit_code}"
            ),
        }
    )
    return result


def as_json(value: dict[str, Any]) -> str:
    sanitized = _sanitize_for_json(value)
    encoded = json.dumps(sanitized, indent=2, sort_keys=True).encode("utf-8")
    defended = redact(encoded).data.decode("utf-8", errors="replace")
    if _is_redaction_wrapper(defended):
        return encoded.decode("utf-8", errors="replace") + "\n"
    return defended + "\n"


def _base_result(
    root: Path,
    timeout_seconds: int,
    selection: dict[str, Any],
) -> dict[str, Any]:
    result = {
        "status": "unknown",
        "reason_code": selection.get("reason_code", REASON_CODE_UNKNOWN),
        "predicate": VERIFY_PREDICATE,
        "qualifier": selection.get("qualifier"),
        "command": selection.get("command"),
        "selection_mode": selection.get("selection_mode", "auto"),
        "selection_reason": selection.get("selection_reason", selection.get("reason", "unknown")),
        "candidate_commands": selection.get("candidate_commands", []),
        "candidate_commands_omitted": selection.get("candidate_commands_omitted", 0),
        "cwd": str(root),
        "exit_code": None,
        "duration_ms": 0,
        "timed_out": False,
        "timeout_seconds": timeout_seconds,
        "stdout_excerpt": "",
        "stderr_excerpt": "",
        "stdout_truncated": False,
        "stderr_truncated": False,
        "reason": selection.get("reason", "unknown"),
    }
    for key in ("available_qualifiers", "disambiguation_hint"):
        if key in selection:
            result[key] = selection[key]
    return result


def _select_verification_command(
    conn: sqlite3.Connection,
    *,
    qualifier: str | None = None,
) -> dict[str, Any]:
    rows = _active_test_command_rows(conn)
    candidates = _command_candidates(rows)
    limited, omitted = _limit_candidates(candidates)
    if not candidates:
        return {
            "status": "missing",
            "reason_code": REASON_CODE_NO_ACTIVE_TEST_COMMAND,
            "reason": "no active uses_test_command facts",
            "selection_mode": "qualifier" if qualifier is not None else "auto",
            "selection_reason": "no active uses_test_command facts",
            "candidate_commands": [],
            "candidate_commands_omitted": 0,
        }

    if qualifier is not None:
        normalized_qualifier = _normalize_qualifier(qualifier)
        display_qualifier = _safe_text(normalized_qualifier, MAX_COMMAND_CHARS)
        qualified_candidates = [
            candidate
            for candidate in candidates
            if candidate["_qualifier_raw"] == normalized_qualifier
        ]
        if not qualified_candidates:
            return {
                "status": "missing",
                "reason_code": REASON_CODE_QUALIFIER_NOT_FOUND,
                "reason": (
                    "no active uses_test_command fact for qualifier "
                    f"{display_qualifier}"
                ),
                "selection_mode": "qualifier",
                "selection_reason": (
                    "no active uses_test_command fact for qualifier "
                    f"{display_qualifier}"
                ),
                "candidate_commands": limited,
                "candidate_commands_omitted": omitted,
                "available_qualifiers": _available_qualifiers(candidates),
            }
        qualified_commands = _unique_commands(qualified_candidates)
        if len(qualified_commands) == 1:
            selection_reason = (
                "selected active uses_test_command fact for qualifier "
                f"{display_qualifier}"
            )
            return _selected(
                qualified_candidates,
                qualified_commands[0],
                candidates,
                selection_mode="qualifier",
                selection_reason=selection_reason,
            )
        qualified_limited, qualified_omitted = _limit_candidates(qualified_candidates)
        return {
            "status": "ambiguous",
            "reason_code": REASON_CODE_AMBIGUOUS_QUALIFIER,
            "reason": (
                "ambiguous active uses_test_command facts for qualifier "
                f"{display_qualifier}"
            ),
            "selection_mode": "qualifier",
            "selection_reason": (
                "ambiguous active uses_test_command facts for qualifier "
                f"{display_qualifier}"
            ),
            "candidate_commands": qualified_limited,
            "candidate_commands_omitted": qualified_omitted,
            "disambiguation_hint": DISAMBIGUATION_HINT,
        }

    base_candidates = [
        candidate for candidate in candidates if ":" not in candidate["_qualifier_raw"]
    ]
    base_commands = _unique_commands(base_candidates)
    if len(base_commands) == 1:
        return _selected(
            base_candidates,
            base_commands[0],
            candidates,
            selection_mode="auto",
            selection_reason=SELECTION_REASON_SELECTED,
        )

    all_commands = _unique_commands(candidates)
    if len(all_commands) == 1:
        return _selected(
            candidates,
            all_commands[0],
            candidates,
            selection_mode="auto",
            selection_reason=SELECTION_REASON_SELECTED,
        )

    return {
        "status": "ambiguous",
        "reason_code": REASON_CODE_AMBIGUOUS_ACTIVE_TEST_COMMAND,
        "reason": "ambiguous active uses_test_command facts",
        "selection_mode": "auto",
        "selection_reason": "ambiguous active uses_test_command facts",
        "candidate_commands": limited,
        "candidate_commands_omitted": omitted,
        "disambiguation_hint": DISAMBIGUATION_HINT,
    }


def _active_test_command_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT qualifier, object_norm
        FROM facts
        WHERE retired_seq IS NULL
          AND scope = 'project'
          AND subject = '.'
          AND predicate = ?
        ORDER BY qualifier, created_seq, object_norm
        """,
        (VERIFY_PREDICATE,),
    ).fetchall()


def _command_candidates(rows: list[sqlite3.Row]) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        command = _normalize_command(str(row["object_norm"]))
        qualifier = _normalize_qualifier(str(row["qualifier"] or "default"))
        key = (qualifier, command)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(
            {
                "qualifier": _safe_text(qualifier, MAX_COMMAND_CHARS),
                "_qualifier_raw": qualifier,
                "command": _safe_text(command, MAX_COMMAND_CHARS),
                "_command_raw": command,
            }
        )
    return candidates


def _selected(
    candidates_to_pick_from: list[dict[str, str]],
    command: str,
    all_candidates: list[dict[str, str]],
    *,
    selection_mode: str,
    selection_reason: str,
) -> dict[str, Any]:
    selected = next(
        candidate for candidate in candidates_to_pick_from if candidate["_command_raw"] == command
    )
    limited, omitted = _limit_candidates(all_candidates)
    return {
        "status": "selected",
        "reason_code": REASON_CODE_SELECTED,
        "reason": SELECTION_REASON_SELECTED,
        "selection_mode": selection_mode,
        "selection_reason": selection_reason,
        "qualifier": selected["qualifier"],
        "command": selected["command"],
        "_command_raw": selected["_command_raw"],
        "candidate_commands": limited,
        "candidate_commands_omitted": omitted,
    }


def _unique_commands(candidates: list[dict[str, str]]) -> list[str]:
    commands: list[str] = []
    for candidate in candidates:
        command = candidate["_command_raw"]
        if command not in commands:
            commands.append(command)
    return commands


def _available_qualifiers(candidates: list[dict[str, str]]) -> list[str]:
    qualifiers: list[str] = []
    for candidate in candidates:
        qualifier = candidate["_qualifier_raw"]
        if qualifier not in qualifiers:
            qualifiers.append(qualifier)
    return sorted(qualifiers)


def _limit_candidates(candidates: list[dict[str, str]]) -> tuple[list[dict[str, str]], int]:
    limited = [
        {
            "qualifier": candidate["qualifier"],
            "command": candidate["command"],
        }
        for candidate in candidates[:MAX_CANDIDATE_COMMANDS]
    ]
    return limited, max(0, len(candidates) - MAX_CANDIDATE_COMMANDS)


def _duration_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))


def _run_process(
    command_args: list[str],
    root_path: Path,
    *,
    timeout_seconds: int,
) -> dict[str, Any]:
    stdout = bytearray()
    stderr = bytearray()
    stdout_capture_truncated = [False]
    stderr_capture_truncated = [False]
    process = subprocess.Popen(
        command_args,
        cwd=root_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=os.name != "nt",
    )
    threads = [
        threading.Thread(
            target=_read_limited,
            args=(process.stdout, stdout, stdout_capture_truncated),
            daemon=True,
        ),
        threading.Thread(
            target=_read_limited,
            args=(process.stderr, stderr, stderr_capture_truncated),
            daemon=True,
        ),
    ]
    for thread in threads:
        thread.start()

    timed_out = False
    exit_code: int | None
    try:
        exit_code = process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        exit_code = None
        _terminate_process_tree(process)
        process.wait()
    except BaseException:
        _terminate_process_tree(process)
        try:
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass
        raise

    for thread in threads:
        thread.join(timeout=1)

    return {
        "exit_code": exit_code,
        "timed_out": timed_out,
        "stdout": bytes(stdout),
        "stderr": bytes(stderr),
        "stdout_capture_truncated": stdout_capture_truncated[0],
        "stderr_capture_truncated": stderr_capture_truncated[0],
    }


def _read_limited(stream: Any, buffer: bytearray, truncated: list[bool]) -> None:
    if stream is None:
        return
    try:
        while chunk := stream.read(READ_CHUNK_BYTES):
            remaining = MAX_CAPTURE_BYTES - len(buffer)
            if remaining > 0:
                buffer.extend(chunk[:remaining])
            if len(chunk) > max(remaining, 0):
                truncated[0] = True
    finally:
        stream.close()


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )
            if process.poll() is not None:
                return
        except (OSError, subprocess.TimeoutExpired):
            pass
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass
        if process.poll() is not None:
            return
    try:
        process.kill()
    except OSError:
        pass


def _command_args(command: str, root_path: Path) -> list[str]:
    _reject_embedded_null(command)
    try:
        args = _split_command(command)
    except VerifyCommandError as exc:
        raise VerifyCommandError(
            exc.reason_code,
            f"could not parse verification command: {exc}",
        ) from exc
    if not args:
        raise VerifyCommandError(
            REASON_CODE_PARSE_ERROR_EMPTY_COMMAND,
            "could not parse verification command: empty command",
        )
    for arg in args:
        _reject_embedded_null(arg)
    try:
        resolved = _resolve_executable(args[0], root_path)
    except (OSError, ValueError) as exc:
        raise VerifyCommandError(
            REASON_CODE_PARSE_ERROR_INVALID_COMMAND,
            f"could not parse verification command: invalid executable path: {exc}",
        ) from exc
    _reject_embedded_null(resolved)
    if _is_windows_batch_file(resolved) and _has_windows_batch_meta(command):
        raise VerifyCommandError(
            REASON_CODE_PARSE_ERROR_BATCH_METACHARACTER,
            "could not parse verification command: Windows batch metacharacters "
            "are not supported",
        )
    args[0] = resolved
    return args


def _reject_embedded_null(value: str) -> None:
    if "\x00" in value:
        raise VerifyCommandError(
            REASON_CODE_PARSE_ERROR_INVALID_COMMAND,
            "could not parse verification command: embedded null byte",
        )


def _split_command(command: str) -> list[str]:
    if _has_unquoted_shell_operator(command):
        raise VerifyCommandError(
            REASON_CODE_PARSE_ERROR_SHELL_OPERATOR,
            "shell operators are not supported",
        )
    try:
        args = shlex.split(command, posix=True, comments=False)
    except ValueError as exc:
        raise VerifyCommandError(REASON_CODE_PARSE_ERROR_INVALID_COMMAND, str(exc)) from exc
    if _uses_shell_command_wrapper(args):
        raise VerifyCommandError(
            REASON_CODE_PARSE_ERROR_SHELL_WRAPPER,
            "shell interpreter wrappers are not supported",
        )
    return args


def _has_unquoted_shell_operator(command: str) -> bool:
    quote: str | None = None
    escaped = False
    index = 0
    while index < len(command):
        char = command[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if char == "\\" and quote != "'":
            escaped = True
            index += 1
            continue
        if quote:
            if char == quote:
                quote = None
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
        elif char in {";", "|"}:
            return True
        elif char == "&" and index + 1 < len(command) and command[index + 1] == "&":
            return True
        index += 1
    return False


def _uses_shell_command_wrapper(args: list[str]) -> bool:
    if not args:
        return False
    executable = _executable_name(args[0])
    if executable in ENV_WRAPPER_EXECUTABLES:
        return _uses_shell_command_wrapper(_env_delegated_args(args[1:]))
    if executable not in SHELL_WRAPPER_EXECUTABLES:
        return False
    return any(_is_shell_command_flag(executable, arg) for arg in args[1:])


def _env_delegated_args(args: list[str]) -> list[str]:
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            return args[index + 1 :]
        if arg == "-":
            index += 1
            continue
        if _is_env_split_string_option(arg):
            return ["sh", "-c"]
        if _is_env_assignment(arg):
            index += 1
            continue
        if _is_env_option_with_joined_value(arg):
            index += 1
            continue
        if arg in ENV_OPTIONS_WITH_VALUE:
            index += 2
            continue
        if arg.startswith("-"):
            index += 1
            continue
        return args[index:]
    return []


def _is_env_split_string_option(value: str) -> bool:
    return (
        value in {"-S", "--split-string"}
        or value.startswith("--split-string=")
        or (value.startswith("-S") and value != "-S")
    )


def _is_env_assignment(value: str) -> bool:
    name, separator, _ = value.partition("=")
    return bool(separator and name) and not name.startswith("-")


def _is_env_option_with_joined_value(value: str) -> bool:
    if any(value.startswith(option + "=") for option in ENV_OPTIONS_WITH_VALUE):
        return True
    return any(
        value.startswith(option) and value != option
        for option in ("-u", "-C", "-S")
    )


def _executable_name(value: str) -> str:
    return value.replace("\\", "/").rsplit("/", 1)[-1].lower()


def _is_shell_command_flag(executable: str, value: str) -> bool:
    normalized = value.lower()
    if executable in CMD_WRAPPER_EXECUTABLES:
        return normalized == "/c"
    if executable in POWERSHELL_WRAPPER_EXECUTABLES:
        return normalized in POWERSHELL_COMMAND_FLAGS
    if executable not in POSIX_SHELL_WRAPPER_EXECUTABLES:
        return False
    if normalized == "-c":
        return True
    if not normalized.startswith("-") or normalized.startswith("--"):
        return False
    flags = normalized[1:]
    # POSIX shells accept clustered short flags such as -cl and -lc.
    return "c" in flags and set(flags) <= POSIX_SHELL_CLUSTER_FLAGS


def _resolve_executable(executable: str, root_path: Path) -> str:
    if _has_path_separator(executable):
        executable_path = Path(executable)
        if not executable_path.is_absolute():
            executable_path = root_path / executable_path
        return shutil.which(str(executable_path)) or str(executable_path)
    return shutil.which(executable, path=_path_for_cwd(root_path)) or executable


def _path_for_cwd(root_path: Path) -> str:
    entries: list[str] = []
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not entry:
            entries.append(str(root_path))
            continue
        path = Path(entry)
        entries.append(str(path if path.is_absolute() else root_path / path))
    return os.pathsep.join(entries)


def _has_path_separator(value: str) -> bool:
    return "/" in value or "\\" in value


def _is_windows_batch_file(value: str) -> bool:
    return value.lower().endswith(WINDOWS_BATCH_EXTENSIONS)


def _has_windows_batch_meta(command: str) -> bool:
    return any(char in command for char in WINDOWS_BATCH_META_CHARS)


def _normalize_command(command: str) -> str:
    return " ".join(command.strip().split())


def _normalize_qualifier(qualifier: str) -> str:
    return qualifier.strip()


def _safe_output_with_flag(value: str | bytes) -> tuple[str, bool]:
    return _safe_text_with_flag(_to_text(value), MAX_OUTPUT_CHARS)


def _safe_text(value: str, max_chars: int) -> str:
    return _safe_text_with_flag(value, max_chars)[0]


def _safe_text_with_flag(value: str, max_chars: int) -> tuple[str, bool]:
    redacted = redact(value.encode("utf-8", errors="replace")).data.decode(
        "utf-8", errors="replace"
    )
    normalized = redacted.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(normalized) <= max_chars:
        return normalized, False
    return normalized[: max_chars - 14].rstrip() + "...[truncated]", True


def _to_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _sanitize_for_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _sanitize_for_json(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_sanitize_for_json(child) for child in value]
    if isinstance(value, str):
        return _safe_text(value, MAX_OUTPUT_CHARS)
    return value


def _is_redaction_wrapper(value: str) -> bool:
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return True
    return isinstance(decoded, dict) and decoded.get("error") in {
        "payload_truncated",
        "redaction_failed",
    }
