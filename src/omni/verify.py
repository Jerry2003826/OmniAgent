"""Read-only verification preflight for known project commands."""

from __future__ import annotations

import json
import os
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
SHELL_OPERATOR_TOKENS = ("&&", "||", ";", "|")
WINDOWS_BATCH_EXTENSIONS = (".bat", ".cmd")
WINDOWS_BATCH_META_CHARS = ("&", "<", ">", "^", "%", "!")


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
) -> dict[str, Any]:
    """Execute the active project test command without writing Omni state."""

    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    root_path = Path(root).resolve()
    selection = _select_verification_command(conn)
    result = _base_result(root_path, timeout_seconds, selection)
    if selection["status"] != "selected":
        result["status"] = "unknown"
        result["reason"] = selection["reason"]
        return result

    command = selection["_command_raw"]
    try:
        command_args = _command_args(command, root_path)
    except ValueError as exc:
        result["status"] = "unknown"
        result["reason"] = str(exc)
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
        result.update(
            {
                "status": "failed",
                "exit_code": None,
                "duration_ms": duration_ms,
                "stdout_excerpt": "",
                "stderr_excerpt": _safe_output(str(exc)),
                "reason": "verification command could not be started",
            }
        )
        return result

    duration_ms = _duration_ms(started)
    timed_out = bool(completed["timed_out"])
    exit_code = completed["exit_code"]
    if timed_out:
        result.update(
            {
                "status": "failed",
                "exit_code": None,
                "duration_ms": duration_ms,
                "timed_out": True,
                "stdout_excerpt": _safe_output(completed["stdout"]),
                "stderr_excerpt": _safe_output(completed["stderr"]),
                "reason": f"verification command timed out after {timeout_seconds}s",
            }
        )
        return result

    assert isinstance(exit_code, int)
    result.update(
        {
            "status": "passed" if exit_code == 0 else "failed",
            "exit_code": exit_code,
            "duration_ms": duration_ms,
            "stdout_excerpt": _safe_output(completed["stdout"]),
            "stderr_excerpt": _safe_output(completed["stderr"]),
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
    return {
        "status": "unknown",
        "predicate": VERIFY_PREDICATE,
        "qualifier": selection.get("qualifier"),
        "command": selection.get("command"),
        "candidate_commands": selection.get("candidate_commands", []),
        "candidate_commands_omitted": selection.get("candidate_commands_omitted", 0),
        "cwd": str(root),
        "exit_code": None,
        "duration_ms": 0,
        "timed_out": False,
        "timeout_seconds": timeout_seconds,
        "stdout_excerpt": "",
        "stderr_excerpt": "",
        "reason": selection.get("reason", "unknown"),
    }


def _select_verification_command(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = _active_test_command_rows(conn)
    candidates = _command_candidates(rows)
    if not candidates:
        return {
            "status": "missing",
            "reason": "no active uses_test_command facts",
            "candidate_commands": [],
            "candidate_commands_omitted": 0,
        }

    base_candidates = [
        candidate for candidate in candidates if ":" not in candidate["qualifier"]
    ]
    base_commands = _unique_commands(base_candidates)
    if len(base_commands) == 1:
        return _selected(base_candidates, base_commands[0], candidates)

    all_commands = _unique_commands(candidates)
    if len(all_commands) == 1:
        return _selected(candidates, all_commands[0], candidates)

    limited, omitted = _limit_candidates(candidates)
    return {
        "status": "ambiguous",
        "reason": "ambiguous active uses_test_command facts",
        "candidate_commands": limited,
        "candidate_commands_omitted": omitted,
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
        qualifier = _normalize_command(str(row["qualifier"] or "default"))
        if not command:
            continue
        key = (qualifier, command)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(
            {
                "qualifier": _safe_text(qualifier, MAX_COMMAND_CHARS),
                "command": _safe_text(command, MAX_COMMAND_CHARS),
                "_command_raw": command,
            }
        )
    return candidates


def _selected(
    candidates_to_pick_from: list[dict[str, str]],
    command: str,
    all_candidates: list[dict[str, str]],
) -> dict[str, Any]:
    selected = next(
        candidate for candidate in candidates_to_pick_from if candidate["_command_raw"] == command
    )
    limited, omitted = _limit_candidates(all_candidates)
    return {
        "status": "selected",
        "reason": "selected active uses_test_command fact",
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
    process = subprocess.Popen(
        command_args,
        cwd=root_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    threads = [
        threading.Thread(target=_read_limited, args=(process.stdout, stdout), daemon=True),
        threading.Thread(target=_read_limited, args=(process.stderr, stderr), daemon=True),
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
        process.kill()
        process.wait()

    for thread in threads:
        thread.join(timeout=1)

    return {
        "exit_code": exit_code,
        "timed_out": timed_out,
        "stdout": bytes(stdout),
        "stderr": bytes(stderr),
    }


def _read_limited(stream: Any, buffer: bytearray) -> None:
    if stream is None:
        return
    try:
        while chunk := stream.read(READ_CHUNK_BYTES):
            remaining = MAX_CAPTURE_BYTES - len(buffer)
            if remaining > 0:
                buffer.extend(chunk[:remaining])
    finally:
        stream.close()


def _command_args(command: str, root_path: Path) -> list[str]:
    if any(operator in command for operator in SHELL_OPERATOR_TOKENS):
        raise ValueError("could not parse verification command: shell operators are not supported")
    try:
        args = shlex.split(command, posix=True)
    except ValueError as exc:
        raise ValueError(f"could not parse verification command: {exc}") from exc
    if not args:
        raise ValueError("could not parse verification command: empty command")
    resolved = _resolve_executable(args[0], root_path)
    if _is_windows_batch_file(resolved) and _has_windows_batch_meta(command):
        raise ValueError(
            "could not parse verification command: Windows batch metacharacters "
            "are not supported"
        )
    args[0] = resolved
    return args


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


def _safe_output(value: str | bytes) -> str:
    return _safe_text(_to_text(value), MAX_OUTPUT_CHARS)


def _safe_text(value: str, max_chars: int) -> str:
    redacted = redact(value.encode("utf-8", errors="replace")).data.decode(
        "utf-8", errors="replace"
    )
    normalized = redacted.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 14].rstrip() + "...[truncated]"


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
