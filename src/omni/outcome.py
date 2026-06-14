"""User-marked outcome log for ingested runs."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from omni import eval as behavior_eval
from omni import verify
from omni._common import now_iso, validate_choice
from omni.dbaccess import ensure_run_exists, root_from_connection
from omni.ids import new_id
from omni.jsonio import as_json, redact_text
from omni.redact import redact
from omni.verify import (
    REASON_CODE_FAILED_EXIT_CODE,
    REASON_CODE_PASSED,
    REASON_CODE_TIMED_OUT,
)

STATUS_VALUES = {"success", "failed", "unknown"}
TESTS_STATUS_VALUES = {"passed", "failed", "not_run", "unknown"}
MEMORY_EFFECT_VALUES = {"helped", "neutral", "failed_to_help", "unknown"}
TASK_TYPE_VALUES = {"validation", "bugfix", "docs", "refactor", "exploration", "unknown"}


def mark_outcome(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    status: str = "unknown",
    tests_status: str = "unknown",
    memory_effect: str | None = None,
    task_type: str = "unknown",
    task_summary: str | None = None,
    final_command: str | None = None,
    note: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ensure_run_exists(conn, run_id)
    validate_choice("status", status, STATUS_VALUES)
    validate_choice("tests_status", tests_status, TESTS_STATUS_VALUES)
    validate_choice("task_type", task_type, TASK_TYPE_VALUES)
    if memory_effect is None:
        memory_effect = _memory_effect_from_eval(conn, run_id)
    validate_choice("memory_effect", memory_effect, MEMORY_EFFECT_VALUES)

    existing = conn.execute(
        "SELECT outcome_id, created_at FROM outcomes WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    now = now_iso()
    evidence_json = _evidence_json(evidence or {"source": "user", "run_id": run_id})
    values = {
        "run_id": run_id,
        "task_type": task_type,
        "status": status,
        "tests_status": tests_status,
        "memory_effect": memory_effect,
        "task_summary": redact_text(task_summary),
        "final_command": redact_text(final_command),
        "note": redact_text(note),
        "evidence": evidence_json,
        "updated_at": now,
    }

    if existing is None:
        conn.execute(
            """
            INSERT INTO outcomes(
              outcome_id, run_id, task_type, status, tests_status,
              memory_effect, task_summary, final_command, note,
              evidence, created_at, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                new_id("outcome"),
                values["run_id"],
                values["task_type"],
                values["status"],
                values["tests_status"],
                values["memory_effect"],
                values["task_summary"],
                values["final_command"],
                values["note"],
                values["evidence"],
                now,
                values["updated_at"],
            ),
        )
    else:
        conn.execute(
            """
            UPDATE outcomes
            SET task_type = ?,
                status = ?,
                tests_status = ?,
                memory_effect = ?,
                task_summary = ?,
                final_command = ?,
                note = ?,
                evidence = ?,
                updated_at = ?
            WHERE run_id = ?
            """,
            (
                values["task_type"],
                values["status"],
                values["tests_status"],
                values["memory_effect"],
                values["task_summary"],
                values["final_command"],
                values["note"],
                values["evidence"],
                values["updated_at"],
                run_id,
            ),
        )
    conn.commit()
    return show_outcome(conn, run_id)


def mark_outcome_from_verify(
    conn: sqlite3.Connection,
    run_id: str,
    root: Path | str,
    *,
    status: str = "unknown",
    memory_effect: str | None = None,
    task_type: str = "unknown",
    task_summary: str | None = None,
    note: str | None = None,
    timeout_seconds: int = verify.DEFAULT_TIMEOUT_SECONDS,
    qualifier: str | None = None,
    profile: str | None = None,
) -> dict[str, Any]:
    ensure_run_exists(conn, run_id)
    validate_choice("status", status, STATUS_VALUES)
    validate_choice("task_type", task_type, TASK_TYPE_VALUES)
    if memory_effect is not None:
        validate_choice("memory_effect", memory_effect, MEMORY_EFFECT_VALUES)
    if profile is not None and profile not in verify.PROFILE_VALUES:
        allowed = ", ".join(sorted(verify.PROFILE_VALUES))
        raise ValueError(f"invalid profile: {profile!r}; expected one of: {allowed}")

    verify_result = verify.run_preflight(
        conn,
        root,
        timeout_seconds=timeout_seconds,
        qualifier=qualifier,
        task_type=None if task_type == "unknown" else task_type,
        profile=profile,
    )
    return mark_outcome(
        conn,
        run_id,
        status=status,
        tests_status=_tests_status_from_verify(verify_result),
        memory_effect=memory_effect,
        task_type=task_type,
        task_summary=task_summary,
        final_command=_verify_command(verify_result),
        note=note,
        evidence={
            "source": "verify",
            "run_id": run_id,
            "verify": _verify_evidence(verify_result),
        },
    )


def show_outcome(conn: sqlite3.Connection, run_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT outcome_id, run_id, task_type, status, tests_status,
               memory_effect, task_summary, final_command, note,
               evidence, created_at, updated_at
        FROM outcomes
        WHERE run_id = ?
        """,
        (run_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown outcome for run: {run_id}")
    result = dict(row)
    result["evidence"] = _decode_evidence(result["evidence"])
    return result


def list_outcomes(
    conn: sqlite3.Connection,
    *,
    task_type: str | None = None,
    status: str | None = None,
    tests_status: str | None = None,
    memory_effect: str | None = None,
) -> dict[str, Any]:
    """Return recorded outcomes plus a per-field tally (read-only)."""

    filters: dict[str, str] = {}
    if task_type is not None:
        validate_choice("task_type", task_type, TASK_TYPE_VALUES)
        filters["task_type"] = task_type
    if status is not None:
        validate_choice("status", status, STATUS_VALUES)
        filters["status"] = status
    if tests_status is not None:
        validate_choice("tests_status", tests_status, TESTS_STATUS_VALUES)
        filters["tests_status"] = tests_status
    if memory_effect is not None:
        validate_choice("memory_effect", memory_effect, MEMORY_EFFECT_VALUES)
        filters["memory_effect"] = memory_effect

    where_clauses: list[str] = []
    params: list[str] = []
    if task_type is not None:
        where_clauses.append("task_type = ?")
        params.append(task_type)
    if status is not None:
        where_clauses.append("status = ?")
        params.append(status)
    if tests_status is not None:
        where_clauses.append("tests_status = ?")
        params.append(tests_status)
    if memory_effect is not None:
        where_clauses.append("memory_effect = ?")
        params.append(memory_effect)

    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)

    rows = conn.execute(
        f"""
        SELECT run_id, task_type, status, tests_status, memory_effect,
               final_command, created_at, updated_at
        FROM outcomes
        {where_sql}
        ORDER BY updated_at DESC, run_id
        """,
        params,
    ).fetchall()
    outcomes = [
        {
            "run_id": row["run_id"],
            "task_type": row["task_type"],
            "status": row["status"],
            "tests_status": row["tests_status"],
            "memory_effect": row["memory_effect"],
            "final_command": row["final_command"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]
    return {
        "count": len(outcomes),
        "filters": filters,
        "summary": _summarize_outcomes(outcomes),
        "outcomes": outcomes,
    }


def _summarize_outcomes(outcomes: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    fields = ("status", "tests_status", "memory_effect", "task_type")
    summary: dict[str, dict[str, int]] = {field: {} for field in fields}
    for row in outcomes:
        for field in fields:
            value = str(row[field])
            summary[field][value] = summary[field].get(value, 0) + 1
    return summary


def _redact_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _redact_json(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_redact_json(child) for child in value]
    if isinstance(value, str):
        return redact_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_text(str(value))


def _evidence_json(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        _redact_json(value),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return redact(encoded).data.decode("utf-8", errors="replace")


def _decode_evidence(value: str) -> dict[str, Any]:
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return {"source": "user", "decode_error": "invalid_json"}
    return decoded if isinstance(decoded, dict) else {"source": "user"}


def _memory_effect_from_eval(conn: sqlite3.Connection, run_id: str) -> str:
    root = root_from_connection(conn)
    if root is None:
        return "unknown"
    try:
        result = behavior_eval.evaluate_run(root, run_id)
    except Exception:
        return "unknown"
    effect = result.get("memory_effect")
    return effect if isinstance(effect, str) and effect in MEMORY_EFFECT_VALUES else "unknown"


def _tests_status_from_verify(verify_result: dict[str, Any]) -> str:
    # Tie tests_status to the stable verify reason_code rather than re-deriving it
    # from field shapes. Only a verification command that actually ran to a result
    # is passed or failed. A command that could not start (start_failed), a
    # missing/ambiguous selection, or a parse error stays "unknown" because verify
    # cannot observe whether the user ran tests another way. This never infers task
    # success and never sets status from the verify result.
    reason_code = verify_result.get("reason_code")
    if reason_code == REASON_CODE_PASSED:
        return "passed"
    if reason_code in (REASON_CODE_FAILED_EXIT_CODE, REASON_CODE_TIMED_OUT):
        return "failed"
    return "unknown"


def _verify_command(verify_result: dict[str, Any]) -> str | None:
    command = verify_result.get("command")
    return command if isinstance(command, str) and command else None


def _verify_evidence(verify_result: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "status",
        "reason_code",
        "command",
        "exit_code",
        "timed_out",
        "reason",
        "selection_mode",
        "selection_reason",
        "duration_ms",
        "timeout_seconds",
        "predicate",
        "qualifier",
        "profile",
        "candidate_commands",
        "candidate_commands_omitted",
    )
    return {key: verify_result[key] for key in keys if key in verify_result}


def cli_command_readonly(args: argparse.Namespace) -> bool:
    return args.outcome_command in {"show", "ls"}


def handle_cli_action(
    conn: sqlite3.Connection,
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    *,
    root: Path,
) -> Any:
    if args.outcome_command == "mark":
        return mark_outcome(
            conn,
            args.run_id,
            status=args.outcome_status or "unknown",
            tests_status=args.tests_status or "unknown",
            memory_effect=args.memory_effect,
            task_type=args.task_type,
            task_summary=args.task_summary,
            final_command=args.final_command,
            note=args.note,
        )
    if args.outcome_command == "mark-from-verify":
        return mark_outcome_from_verify(
            conn,
            args.run_id,
            root,
            status=args.outcome_status or "unknown",
            memory_effect=args.memory_effect,
            task_type=args.task_type,
            task_summary=args.task_summary,
            note=args.note,
            timeout_seconds=args.timeout_seconds,
            qualifier=args.qualifier,
            profile=args.profile,
        )
    if args.outcome_command == "show":
        return show_outcome(conn, args.run_id)
    if args.outcome_command == "ls":
        return list_outcomes(
            conn,
            task_type=args.task_type,
            status=args.status,
            tests_status=args.tests_status,
            memory_effect=args.memory_effect,
        )
    parser.error(f"unknown outcome command: {args.outcome_command}")
