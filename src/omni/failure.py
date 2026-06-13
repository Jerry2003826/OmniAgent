"""Reviewable failure candidates derived from redacted event evidence."""

from __future__ import annotations

import hashlib
import json
import re
import shlex
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from omni import db
from omni import eval as behavior_eval
from omni.ids import new_id
from omni.redact import redact

STATE_VALUES = {"pending", "rejected"}
LIST_STATE_VALUES = STATE_VALUES | {"all"}
MAX_ERROR_CHARS = 300
MAX_EXCERPT_CHARS = 300
MAX_COMMAND_CHARS = 200
INPUT_CONTAINER_KEYS = ("tool_input", "input", "parameters", "args")
OUTPUT_CONTAINER_KEYS = ("tool_response", "toolUseResult")
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
WINDOWS_ABS_PATH_RE = re.compile(r"(?i)\b[A-Z]:[\\/][^\s\"']+")
UNIX_ABS_PATH_RE = re.compile(r"(?<!\w)/(?:[^\s\"']+/)+[^\s\"']+")


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


def reject_candidate(conn: sqlite3.Connection, failure_cand_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT state FROM failure_candidates WHERE failure_cand_id = ?",
        (failure_cand_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown failure candidate: {failure_cand_id}")
    if row["state"] == "rejected":
        return show_candidate(conn, failure_cand_id)
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
    if command is None:
        return None
    collapsed = _primary_command_segment(_collapse_whitespace(command))
    if not collapsed:
        return None
    tokens = _shell_tokens(collapsed)
    if not tokens:
        return None
    lowered = [token.lower() for token in tokens]
    first = lowered[0]

    if first in {"pnpm", "npm", "yarn"}:
        if len(lowered) >= 3 and lowered[1] == "run":
            return f"{first} run {lowered[2]}"
        if len(lowered) >= 2:
            return f"{first} run {lowered[1]}"
        return first
    if first == "bun":
        if len(lowered) >= 2:
            return f"bun {lowered[1]}"
        return "bun"
    if first == "uv" and len(lowered) >= 3 and lowered[1] == "run":
        return f"uv run {lowered[2]}"
    if first in {"python", "python3", "py"} and len(lowered) >= 3 and lowered[1] == "-m":
        return f"{first} -m {lowered[2]}"
    if first == "pytest":
        return "pytest"
    if first in {"bash", "sh", "pwsh", "powershell", "cmd"}:
        return first
    return _safe_text(collapsed, MAX_COMMAND_CHARS)


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
        match = re.search(r"\b(?:exit(?:ed)?(?:\s+code)?|exit_code)\s*[:=]?\s*(-?\d+)\b", value, re.I)
        if match:
            return int(match.group(1))
    return None


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
    normalized = UNIX_ABS_PATH_RE.sub("<path>", normalized)
    return _safe_text(normalized, MAX_ERROR_CHARS) or "unknown failure"


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
    if isinstance(value, dict):
        for key in ("command", "cmd"):
            if key in value and isinstance(value[key], str):
                return value[key]
        for child in value.values():
            found = _nested_command(child)
            if found is not None:
                return found
    if isinstance(value, list):
        for child in value:
            found = _nested_command(child)
            if found is not None:
                return found
    return None


def _interrupted(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() == "interrupted" and child is True:
                return True
            if key in INPUT_CONTAINER_KEYS or key in OUTPUT_CONTAINER_KEYS:
                if _interrupted(child):
                    return True
        return any(_interrupted(child) for child in value.values())
    if isinstance(value, list):
        return any(_interrupted(child) for child in value)
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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
