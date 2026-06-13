"""Reviewable failure candidates derived from redacted event evidence."""

from __future__ import annotations

import hashlib
import json
import re
import shlex
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from omni import db
from omni import eval as behavior_eval
from omni.ids import new_id
from omni.redact import redact

STATE_VALUES = {"pending", "approved", "rejected"}
LIST_STATE_VALUES = STATE_VALUES | {"all"}
MAX_ERROR_CHARS = 300
MAX_EXCERPT_CHARS = 300
MAX_COMMAND_CHARS = 200
INPUT_CONTAINER_KEYS = ("tool_input", "input", "parameters", "args")
OUTPUT_CONTAINER_KEYS = ("tool_response", "toolUseResult")
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
WINDOWS_ABS_PATH_RE = re.compile(r"(?i)\b[A-Z]:[\\/][^\s\"']+")


def connect_project(root: Path | str | None = None) -> sqlite3.Connection:
    base = Path(root or Path.cwd()).resolve()
    db_path = base / ".omni" / "omni.sqlite3"
    if not db_path.exists():
        raise FileNotFoundError(f"OmniMemory database is missing: {db_path}")
    conn = db.connect(db_path)
    db.migrate(conn)
    return conn


def connect_project_readonly(root: Path | str | None = None) -> sqlite3.Connection:
    base = Path(root or Path.cwd()).resolve()
    db_path = base / ".omni" / "omni.sqlite3"
    if not db_path.exists():
        raise FileNotFoundError(f"OmniMemory database is missing: {db_path}")
    conn = db.connect_readonly(db_path)
    version = db.schema_version(conn)
    if version != db.LATEST_SCHEMA_VERSION:
        conn.close()
        raise ValueError(
            f"OmniMemory schema is outdated (found {version or 'none'}, need "
            f"{db.LATEST_SCHEMA_VERSION}); run an approved write command such as "
            "'omni failure extract' to migrate"
        )
    return conn


def extract_candidates(conn: sqlite3.Connection, run_id: str) -> list[dict[str, Any]]:
    _ensure_run_exists(conn, run_id)
    created: list[dict[str, Any]] = []
    for event in _events_for_run(conn, run_id):
        spec = _candidate_spec(event)
        if spec is None:
            continue
        inserted = _insert_candidate(conn, spec)
        if inserted is not None:
            created.append(inserted)
    conn.commit()
    return created


def list_candidates(conn: sqlite3.Connection, state: str = "pending") -> list[dict[str, Any]]:
    _validate_choice("state", state, LIST_STATE_VALUES)
    if state == "all":
        rows = conn.execute(
            """
            SELECT *
            FROM failure_candidates
            ORDER BY created_at, failure_cand_id
            """
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT *
            FROM failure_candidates
            WHERE state = ?
            ORDER BY created_at, failure_cand_id
            """,
            (state,),
        ).fetchall()
    return [_candidate_from_row(row) for row in rows]


def show_candidate(conn: sqlite3.Connection, failure_cand_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM failure_candidates WHERE failure_cand_id = ?",
        (failure_cand_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown failure candidate: {failure_cand_id}")
    return _candidate_from_row(row)


def approve_candidate(
    conn: sqlite3.Connection,
    failure_cand_id: str,
    *,
    summary: str,
    suggested_action: str,
) -> dict[str, Any]:
    summary = _required_redacted_text("summary", summary)
    suggested_action = _required_redacted_text("suggested_action", suggested_action)
    try:
        conn.execute("BEGIN")
        candidate = _candidate_row(conn, failure_cand_id)
        state = candidate["state"]
        _validate_choice("state", state, STATE_VALUES)
        if state == "rejected":
            raise ValueError(
                f"rejected failure candidate cannot be approved in v0: {failure_cand_id}"
            )
        if state == "approved":
            pattern_id = candidate["pattern_id"]
            if pattern_id and _active_pattern_exists(conn, pattern_id):
                conn.commit()
                return show_candidate(conn, failure_cand_id)
            raise ValueError(
                f"approved failure candidate has no active pattern in v0: {failure_cand_id}"
            )

        pattern_id = _active_pattern_id_for_signature(
            conn,
            scope="project",
            error_signature_hash=candidate["error_signature_hash"],
        )
        if pattern_id is None:
            pattern_id = _create_failure_pattern(
                conn,
                candidate,
                summary=summary,
                suggested_action=suggested_action,
            )
        updated = conn.execute(
            """
            UPDATE failure_candidates
            SET state = 'approved', reviewed_at = ?, review_note = NULL,
                pattern_id = ?
            WHERE failure_cand_id = ? AND state = 'pending'
            """,
            (_now(), pattern_id, failure_cand_id),
        )
        if updated.rowcount != 1:
            raise ValueError(f"failure candidate could not be approved: {failure_cand_id}")
        conn.commit()
        return show_candidate(conn, failure_cand_id)
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def reject_candidate(conn: sqlite3.Connection, failure_cand_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT state FROM failure_candidates WHERE failure_cand_id = ?",
        (failure_cand_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown failure candidate: {failure_cand_id}")
    if row["state"] == "rejected":
        return show_candidate(conn, failure_cand_id)
    if row["state"] == "approved":
        raise ValueError(
            f"approved failure candidate cannot be rejected in v0: {failure_cand_id}"
        )
    _validate_choice("state", row["state"], STATE_VALUES)
    conn.execute(
        """
        UPDATE failure_candidates
        SET state = 'rejected', reviewed_at = ?
        WHERE failure_cand_id = ? AND state = 'pending'
        """,
        (_now(), failure_cand_id),
    )
    conn.commit()
    return show_candidate(conn, failure_cand_id)


def as_json(value: dict[str, Any]) -> str:
    return behavior_eval.as_json(value)


def normalize_command(command: str | None) -> str | None:
    collapsed = _normalizable_command(command)
    if collapsed is None:
        return None
    tokens = _shell_tokens(collapsed)
    if not tokens:
        return None
    lowered = [token.lower() for token in tokens]
    known = _known_command_norm(lowered)
    if known is not None:
        return known
    return _safe_text(collapsed, MAX_COMMAND_CHARS)


def _normalizable_command(command: str | None) -> str | None:
    if command is None:
        return None
    collapsed = _primary_command_segment(_collapse_whitespace(command))
    return collapsed or None


def _known_command_norm(lowered: list[str]) -> str | None:
    first = lowered[0]
    if first in {"pnpm", "npm", "yarn"}:
        return _package_command_norm(first, lowered)
    if first == "bun":
        return _single_arg_command_norm("bun", lowered)
    if first == "uv":
        return _uv_command_norm(lowered)
    if first in {"python", "python3", "py"}:
        return _python_module_norm(first, lowered)
    if first == "pytest":
        return "pytest"
    if first in {"bash", "sh", "pwsh", "powershell", "cmd"}:
        return first
    return None


def _package_command_norm(first: str, lowered: list[str]) -> str:
    if len(lowered) >= 3 and lowered[1] == "run":
        return f"{first} run {lowered[2]}"
    if len(lowered) >= 2:
        return f"{first} run {lowered[1]}"
    return first


def _single_arg_command_norm(first: str, lowered: list[str]) -> str:
    if len(lowered) >= 2:
        return f"{first} {lowered[1]}"
    return first


def _uv_command_norm(lowered: list[str]) -> str | None:
    if len(lowered) >= 3 and lowered[1] == "run":
        return f"uv run {lowered[2]}"
    return None


def _python_module_norm(first: str, lowered: list[str]) -> str | None:
    if len(lowered) >= 3 and lowered[1] == "-m":
        return f"{first} -m {lowered[2]}"
    return None


def _primary_command_segment(command: str) -> str:
    segments = _split_shell_segments(command)
    for segment in segments:
        tokens = _shell_tokens(segment)
        if not tokens:
            continue
        command_name = tokens[0].lower()
        if command_name in {"cd", "pushd", "popd"}:
            continue
        if command_name in {"if", "then"}:
            continue
        return segment
    return command


def _split_shell_segments(command: str) -> list[str]:
    segments: list[str] = []
    current: list[str] = []
    quote: str | None = None
    index = 0
    while index < len(command):
        char = command[index]
        if quote is not None:
            current.append(char)
            if char == quote:
                quote = None
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            current.append(char)
            index += 1
            continue
        if char == ";":
            _append_segment(segments, current)
            current = []
            index += 1
            continue
        if command.startswith("&&", index) or command.startswith("||", index):
            _append_segment(segments, current)
            current = []
            index += 2
            continue
        current.append(char)
        index += 1
    _append_segment(segments, current)
    return segments or [command]


def _append_segment(segments: list[str], current: list[str]) -> None:
    segment = _collapse_whitespace("".join(current))
    if segment:
        segments.append(segment)


def _shell_tokens(command: str) -> list[str]:
    try:
        return shlex.split(command, posix=True)
    except ValueError:
        return command.split()


def _insert_candidate(
    conn: sqlite3.Connection, spec: dict[str, Any]
) -> dict[str, Any] | None:
    failure_cand_id = new_id("failure_cand")
    now = _now()
    inserted = conn.execute(
        """
        INSERT OR IGNORE INTO failure_candidates(
          failure_cand_id, run_id, event_id, tool_use_id, tool, command_norm,
          exit_code, failure_kind, error_signature, error_signature_hash,
          stderr_excerpt, artifact_ref, evidence, state, created_at,
          reviewed_at, review_note
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            failure_cand_id,
            spec["run_id"],
            spec["event_id"],
            spec["tool_use_id"],
            spec["tool"],
            spec["command_norm"],
            spec["exit_code"],
            spec["failure_kind"],
            _redact_text(spec["error_signature"]),
            spec["error_signature_hash"],
            _redact_text(spec["stderr_excerpt"]),
            spec["artifact_ref"],
            _redact_json(spec["evidence"]),
            "pending",
            now,
            None,
            None,
        ),
    )
    if inserted.rowcount == 0:
        return None
    return show_candidate(conn, failure_cand_id)


def _candidate_row(conn: sqlite3.Connection, failure_cand_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM failure_candidates WHERE failure_cand_id = ?",
        (failure_cand_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown failure candidate: {failure_cand_id}")
    return row


def _active_pattern_exists(conn: sqlite3.Connection, pattern_id: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM failure_patterns
        WHERE pattern_id = ? AND status = 'active'
        """,
        (pattern_id,),
    ).fetchone()
    return row is not None


def _active_pattern_id_for_signature(
    conn: sqlite3.Connection, *, scope: str, error_signature_hash: str
) -> str | None:
    row = conn.execute(
        """
        SELECT pattern_id
        FROM failure_patterns
        WHERE scope = ? AND error_signature_hash = ? AND status = 'active'
        ORDER BY created_seq, pattern_id
        LIMIT 1
        """,
        (scope, error_signature_hash),
    ).fetchone()
    return None if row is None else row["pattern_id"]


def _create_failure_pattern(
    conn: sqlite3.Connection,
    candidate: sqlite3.Row,
    *,
    summary: str,
    suggested_action: str,
) -> str:
    pattern_id = new_id("failure_pattern")
    now = _now()
    conn.execute(
        """
        INSERT INTO failure_patterns(
          pattern_id, source_failure_cand_id, scope, command_norm, failure_kind,
          error_signature, error_signature_hash, summary, suggested_action, trust,
          status, evidence, created_seq, retired_seq, superseded_by, created_at,
          updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            pattern_id,
            candidate["failure_cand_id"],
            "project",
            candidate["command_norm"],
            candidate["failure_kind"],
            candidate["error_signature"],
            candidate["error_signature_hash"],
            summary,
            suggested_action,
            2,
            "active",
            _redact_json(_pattern_evidence(candidate)),
            _next_commit_seq(conn),
            None,
            None,
            now,
            now,
        ),
    )
    return pattern_id


def _pattern_evidence(candidate: sqlite3.Row) -> dict[str, Any]:
    return {
        "source_failure_cand_id": candidate["failure_cand_id"],
        "run_id": candidate["run_id"],
        "event_id": candidate["event_id"],
        "tool_use_id": candidate["tool_use_id"],
        "command_norm": candidate["command_norm"],
        "exit_code": candidate["exit_code"],
        "failure_kind": candidate["failure_kind"],
        "error_signature_hash": candidate["error_signature_hash"],
        "candidate_evidence": _decode_json_object(candidate["evidence"]),
    }


def _candidate_spec(event: sqlite3.Row) -> dict[str, Any] | None:
    meta = _decode_meta(event["meta"])
    command_norm = normalize_command(_nested_command(_input_metadata(meta)))
    exit_code = _event_exit_code(event, meta)
    failure_kind = _failure_kind(event, meta, exit_code)
    if failure_kind is None:
        return None
    error_line = _first_error_line(meta)
    if error_line is None:
        error_line = "unknown failure"
        failure_kind = "unknown_failure"
    error_signature = _normalize_error_line(error_line)
    stderr_excerpt = _safe_text(_redact_text(error_signature), MAX_EXCERPT_CHARS)
    signature_hash = _signature_hash(command_norm, exit_code, error_signature)
    evidence = {
        "run_id": event["run_id"],
        "event_id": event["event_id"],
        "tool_use_id": event["tool_use_id"],
        "event_type": event["event_type"],
        "tool": event["tool"],
        "command_norm": command_norm,
        "exit_code": exit_code,
        "failure_kind": failure_kind,
        "error_signature_hash": signature_hash,
    }
    return {
        "run_id": event["run_id"],
        "event_id": event["event_id"],
        "tool_use_id": event["tool_use_id"],
        "tool": event["tool"],
        "command_norm": command_norm,
        "exit_code": exit_code,
        "failure_kind": failure_kind,
        "error_signature": error_signature,
        "error_signature_hash": signature_hash,
        "stderr_excerpt": stderr_excerpt,
        "artifact_ref": event["output_ref"] or event["input_ref"],
        "evidence": evidence,
    }


def _failure_kind(
    event: sqlite3.Row, meta: dict[str, Any], exit_code: int | None
) -> str | None:
    if _interrupted(meta):
        return "interrupted"
    if str(event["event_type"]) == "PostToolUseFailure":
        return "tool_failed"
    if _is_shell_tool(event["tool"]) and exit_code is not None and exit_code != 0:
        return "command_failed"
    return None


def _event_exit_code(event: sqlite3.Row, meta: dict[str, Any]) -> int | None:
    if event["exit_code"] is not None:
        return int(event["exit_code"])
    for value in _nested_strings(meta):
        exit_code = _parse_exit_code_text(value)
        if exit_code is not None:
            return exit_code
    return None


def _parse_exit_code_text(value: str) -> int | None:
    lowered = value.lower()
    for marker in ("exit_code", "exit code", "exited code", "exited", "exit"):
        start = lowered.find(marker)
        if start == -1:
            continue
        exit_code = _integer_after_marker(value, start + len(marker))
        if exit_code is not None:
            return exit_code
    return None


def _integer_after_marker(value: str, start: int) -> int | None:
    index = _skip_exit_code_separator(value, start)
    sign = 1
    if index < len(value) and value[index] == "-":
        sign = -1
        index += 1
    end = index
    while end < len(value) and value[end].isdigit():
        end += 1
    if end == index:
        return None
    return sign * int(value[index:end])


def _skip_exit_code_separator(value: str, index: int) -> int:
    while index < len(value) and value[index].isspace():
        index += 1
    if index < len(value) and value[index] in {":", "="}:
        index += 1
    while index < len(value) and value[index].isspace():
        index += 1
    return index


def _first_error_line(meta: dict[str, Any]) -> str | None:
    for value in (
        meta.get("error"),
        meta.get("stderr"),
        _nested_get(meta.get("tool_response"), "stderr"),
        _nested_get(meta.get("toolUseResult"), "stderr"),
    ):
        line = _first_meaningful_line(value)
        if line is not None:
            return line
    for value in _nested_error_strings(meta):
        line = _first_meaningful_line(value)
        if line is not None:
            return line
    return None


def _first_meaningful_line(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    for line in value.splitlines():
        normalized = _collapse_whitespace(ANSI_RE.sub("", line))
        if normalized:
            return normalized
    return None


def _normalize_error_line(value: str) -> str:
    normalized = _collapse_whitespace(ANSI_RE.sub("", value))
    normalized = WINDOWS_ABS_PATH_RE.sub("<path>", normalized)
    normalized = _mask_unix_abs_paths(normalized)
    return _safe_text(normalized, MAX_ERROR_CHARS) or "unknown failure"


def _mask_unix_abs_paths(value: str) -> str:
    masked: list[str] = []
    index = 0
    while index < len(value):
        if _starts_unix_abs_path(value, index):
            end = _path_end(value, index)
            path = value[index:end]
            if path.count("/") >= 2:
                masked.append("<path>")
                index = end
                continue
        masked.append(value[index])
        index += 1
    return "".join(masked)


def _starts_unix_abs_path(value: str, index: int) -> bool:
    if value[index] != "/":
        return False
    return index == 0 or not value[index - 1].isalnum()


def _path_end(value: str, start: int) -> int:
    end = start
    while end < len(value) and not _is_path_boundary(value[end]):
        end += 1
    return end


def _is_path_boundary(char: str) -> bool:
    return char.isspace() or char in {"'", '"'}


def _signature_hash(
    command_norm: str | None, exit_code: int | None, error_signature: str
) -> str:
    payload = f"{command_norm or ''}|{'' if exit_code is None else exit_code}|{error_signature}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _events_for_run(conn: sqlite3.Connection, run_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT event_id, run_id, seq, event_type, tool, tool_use_id,
               input_ref, output_ref, exit_code, meta
        FROM events
        WHERE run_id = ?
        ORDER BY seq
        """,
        (run_id,),
    ).fetchall()


def _ensure_run_exists(conn: sqlite3.Connection, run_id: str) -> None:
    row = conn.execute("SELECT 1 FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        raise ValueError(f"unknown run: {run_id}")


def _candidate_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["evidence"] = _decode_json_object(result["evidence"])
    return result


def _input_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        collected = []
        for key in INPUT_CONTAINER_KEYS:
            if key in value:
                collected.append(value[key])
        return collected
    return {}


def _nested_command(value: Any) -> str | None:
    return _nested_find(value, _command_from_dict)


def _command_from_dict(value: dict[str, Any]) -> str | None:
    for key in ("command", "cmd"):
        child = value.get(key)
        if isinstance(child, str):
            return child
    return None


def _interrupted(value: Any) -> bool:
    return _nested_match(value, _dict_has_interrupted)


def _dict_has_interrupted(value: dict[str, Any]) -> bool:
    return any(key.lower() == "interrupted" and child is True for key, child in value.items())


def _nested_find(value: Any, reader: Callable[[dict[str, Any]], str | None]) -> str | None:
    if isinstance(value, dict):
        found = reader(value)
        if found is not None:
            return found
        return _nested_find_in_children(value.values(), reader)
    if isinstance(value, list):
        return _nested_find_in_children(value, reader)
    return None


def _nested_find_in_children(
    values: Iterable[Any], reader: Callable[[dict[str, Any]], str | None]
) -> str | None:
    for child in values:
        found = _nested_find(child, reader)
        if found is not None:
            return found
    return None


def _nested_match(value: Any, predicate: Callable[[dict[str, Any]], bool]) -> bool:
    if isinstance(value, dict):
        return predicate(value) or any(
            _nested_match(child, predicate) for child in value.values()
        )
    if isinstance(value, list):
        return any(_nested_match(child, predicate) for child in value)
    return False


def _nested_get(value: Any, target_key: str) -> Any:
    if isinstance(value, dict):
        if target_key in value:
            return value[target_key]
        for child in value.values():
            found = _nested_get(child, target_key)
            if found is not None:
                return found
    if isinstance(value, list):
        for child in value:
            found = _nested_get(child, target_key)
            if found is not None:
                return found
    return None


def _nested_error_strings(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if "error" in key.lower() and isinstance(child, str):
                found.append(child)
            found.extend(_nested_error_strings(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_nested_error_strings(child))
    return found


def _nested_strings(value: Any) -> list[str]:
    strings: list[str] = []
    if isinstance(value, dict):
        for child in value.values():
            strings.extend(_nested_strings(child))
    elif isinstance(value, list):
        for child in value:
            strings.extend(_nested_strings(child))
    elif isinstance(value, str):
        strings.append(value)
    return strings


def _is_shell_tool(tool: Any) -> bool:
    return str(tool or "").lower() in {"bash", "shell", "powershell", "pwsh", "cmd"}


def _decode_meta(meta_json: str | None) -> dict[str, Any]:
    if not meta_json:
        return {}
    try:
        decoded = json.loads(meta_json)
    except (TypeError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _decode_json_object(value: str) -> dict[str, Any]:
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return {"decode_error": "invalid_json"}
    return decoded if isinstance(decoded, dict) else {"decode_error": "non_object"}


def _redact_text(value: str | None) -> str | None:
    if value is None:
        return None
    return redact(value.encode("utf-8")).data.decode("utf-8", errors="replace")


def _required_redacted_text(name: str, value: str | None) -> str:
    if value is None or not value.strip():
        raise ValueError(f"{name} is required")
    return _redact_text(value.strip()) or ""


def _redact_json(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return redact(encoded).data.decode("utf-8", errors="replace")


def _safe_text(value: str | None, max_chars: int) -> str:
    if value is None:
        return ""
    collapsed = _collapse_whitespace(value)
    if len(collapsed) <= max_chars:
        return collapsed
    return collapsed[: max_chars - 14].rstrip() + "...[truncated]"


def _collapse_whitespace(value: str) -> str:
    return " ".join(value.strip().split())


def _validate_choice(name: str, value: str, allowed: set[str]) -> None:
    if value not in allowed:
        allowed_text = ", ".join(sorted(allowed))
        raise ValueError(f"invalid {name}: {value}; expected one of: {allowed_text}")


def _next_commit_seq(conn: sqlite3.Connection) -> int:
    # Increment in place so the read and write happen under one write lock.
    updated = conn.execute(
        "UPDATE meta SET value = CAST(value AS INTEGER) + 1 WHERE key = 'commit_seq'"
    )
    if updated.rowcount == 0:
        conn.execute("INSERT INTO meta(key, value) VALUES('commit_seq', '1')")
        return 1
    row = conn.execute("SELECT value FROM meta WHERE key = 'commit_seq'").fetchone()
    return int(row["value"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
