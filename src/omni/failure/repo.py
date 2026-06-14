"""Failure candidate and pattern CRUD."""

from __future__ import annotations

import sqlite3
from typing import Any

from omni._common import now_iso, validate_choice
from omni.dbaccess import ensure_run_exists
from omni.ids import new_id
from omni.jsonio import as_json, redact_mapping_str, redact_text

from omni.failure._text import (
    MAX_EXCERPT_CHARS,
    _required_redacted_text,
    _safe_text,
)
from omni.failure.command_norm import normalize_command
from omni.failure.error_lines import (
    _first_error_line,
    _normalize_error_line,
    _signature_hash,
)
from omni.failure.exit_code import COMMAND_NOT_FOUND_EXIT_CODE, _event_exit_code
from omni.failure.meta import (
    _decode_json_object,
    _decode_meta,
    _input_metadata,
    _interrupted,
    _is_shell_tool,
    _nested_command,
)

STATE_VALUES = {"pending", "approved", "rejected"}
LIST_STATE_VALUES = STATE_VALUES | {"all"}
PATTERN_STATUS_VALUES = {"active", "retired"}
LIST_PATTERN_STATUS_VALUES = PATTERN_STATUS_VALUES | {"all"}


def extract_candidates(conn: sqlite3.Connection, run_id: str) -> list[dict[str, Any]]:
    ensure_run_exists(conn, run_id)
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
    validate_choice("state", state, LIST_STATE_VALUES)
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


def list_patterns(conn: sqlite3.Connection, status: str = "active") -> list[dict[str, Any]]:
    validate_choice("status", status, LIST_PATTERN_STATUS_VALUES)
    if status == "all":
        rows = conn.execute(
            """
            SELECT *
            FROM failure_patterns
            ORDER BY created_seq, pattern_id
            """
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT *
            FROM failure_patterns
            WHERE status = ?
            ORDER BY created_seq, pattern_id
            """,
            (status,),
        ).fetchall()
    return [_pattern_from_row(row) for row in rows]


def show_pattern(conn: sqlite3.Connection, pattern_id: str) -> dict[str, Any]:
    row = _pattern_row(conn, pattern_id)
    return _pattern_from_row(row)


def retire_pattern(conn: sqlite3.Connection, pattern_id: str) -> dict[str, Any]:
    try:
        conn.execute("BEGIN")
        pattern = _pattern_row(conn, pattern_id)
        status = pattern["status"]
        validate_choice("status", status, PATTERN_STATUS_VALUES)
        if status == "retired":
            conn.commit()
            return show_pattern(conn, pattern_id)

        updated = conn.execute(
            """
            UPDATE failure_patterns
            SET status = 'retired', retired_seq = ?, updated_at = ?
            WHERE pattern_id = ? AND status = 'active'
            """,
            (_next_commit_seq(conn), now_iso(), pattern_id),
        )
        if updated.rowcount != 1:
            raise ValueError(f"failure pattern could not be retired: {pattern_id}")
        conn.commit()
        return show_pattern(conn, pattern_id)
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


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
        validate_choice("state", state, STATE_VALUES)
        if state == "rejected":
            raise ValueError(
                f"rejected failure candidate cannot be approved in v0: {failure_cand_id}"
            )
        if state == "approved":
            return _approved_candidate_result(
                conn, failure_cand_id, candidate["pattern_id"]
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
            (now_iso(), pattern_id, failure_cand_id),
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
    validate_choice("state", row["state"], STATE_VALUES)
    conn.execute(
        """
        UPDATE failure_candidates
        SET state = 'rejected', reviewed_at = ?
        WHERE failure_cand_id = ? AND state = 'pending'
        """,
        (now_iso(), failure_cand_id),
    )
    conn.commit()
    return show_candidate(conn, failure_cand_id)


def _insert_candidate(
    conn: sqlite3.Connection, spec: dict[str, Any]
) -> dict[str, Any] | None:
    failure_cand_id = new_id("failure_cand")
    now = now_iso()
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
            redact_text(spec["command_norm"]),
            spec["exit_code"],
            spec["failure_kind"],
            redact_text(spec["error_signature"]),
            spec["error_signature_hash"],
            redact_text(spec["stderr_excerpt"]),
            spec["artifact_ref"],
            redact_mapping_str(spec["evidence"]),
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


def _pattern_row(conn: sqlite3.Connection, pattern_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM failure_patterns WHERE pattern_id = ?",
        (pattern_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown failure pattern: {pattern_id}")
    return row


def _approved_candidate_result(
    conn: sqlite3.Connection, failure_cand_id: str, pattern_id: str | None
) -> dict[str, Any]:
    if pattern_id:
        pattern = conn.execute(
            "SELECT status FROM failure_patterns WHERE pattern_id = ?",
            (pattern_id,),
        ).fetchone()
        if pattern is not None and pattern["status"] == "active":
            conn.commit()
            return show_candidate(conn, failure_cand_id)
        if pattern is not None and pattern["status"] == "retired":
            raise ValueError(
                f"failure pattern for {failure_cand_id} was retired; "
                "v0 does not reactivate retired patterns"
            )
    raise ValueError(
        f"approved failure candidate has no active pattern in v0: {failure_cand_id}"
    )


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
    now = now_iso()
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
            redact_text(candidate["command_norm"]),
            candidate["failure_kind"],
            candidate["error_signature"],
            candidate["error_signature_hash"],
            summary,
            suggested_action,
            2,
            "active",
            redact_mapping_str(_pattern_evidence(candidate)),
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
    if exit_code == COMMAND_NOT_FOUND_EXIT_CODE:
        return None
    error_line = _first_error_line(meta)
    if error_line is None:
        error_line = "unknown failure"
        failure_kind = "unknown_failure"
    error_signature = _normalize_error_line(error_line)
    # Legacy column name: this stores a redacted signature, not raw stderr.
    stderr_excerpt = _safe_text(redact_text(error_signature), MAX_EXCERPT_CHARS)
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


def _candidate_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["evidence"] = _decode_json_object(result["evidence"])
    return result


def _pattern_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["evidence"] = _decode_json_object(result["evidence"])
    result["lifecycle"] = _pattern_lifecycle(result["status"])
    return result


def _pattern_lifecycle(status: str) -> dict[str, Any]:
    validate_choice("status", status, PATTERN_STATUS_VALUES)
    if status == "active":
        return {
            "renders": True,
            "can_retire": True,
            "can_reactivate": False,
            "supersede_supported": False,
            "message": "active pattern renders into memory.md; retire it to stop rendering",
        }
    return {
        "renders": False,
        "can_retire": False,
        "can_reactivate": False,
        "supersede_supported": False,
        "message": (
            "retired pattern does not render into memory.md; "
            "v0 does not reactivate retired patterns"
        ),
    }


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
