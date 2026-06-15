"""Task lifecycle: operational unit-of-work state (not memory)."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Any

from omni import outcome
from omni import verify
from omni._common import (
    OUTCOME_STATUS_VALUES,
    TASK_TYPE_VALUES,
    now_iso,
    validate_choice,
)
from omni.dbaccess import next_commit_seq, root_from_connection
from omni.ids import new_id, project_id_for_path
from omni.jsonio import decode_json_dict, redact_mapping_str, redact_text

CURRENT_TASK_META_KEY = "current_task_id"
READ_VIEW_SCHEMA_VERSION = 1
TASK_STATUS_VALUES = frozenset({"open", "closed", "abandoned"})
TASK_TERMINAL_STATUS_VALUES = frozenset({"closed", "abandoned"})
LIST_TASK_STATUS_VALUES = frozenset({"open", "closed", "abandoned", "all"})

TASK_READ_VIEW_FIELDS: tuple[tuple[str, bool], ...] = (
    ("title", False),
    ("task_type", True),
    ("status", True),
    ("outcome_status", False),
    ("tests_status", False),
    ("run_count", False),
)


def current_task_id_for_ingest(conn: sqlite3.Connection) -> str | None:
    task_id = _meta_value(conn, CURRENT_TASK_META_KEY)
    if task_id is None:
        return None
    row = conn.execute(
        "SELECT status FROM tasks WHERE task_id = ?",
        (task_id,),
    ).fetchone()
    if row is None or row["status"] != "open":
        return None
    return task_id


def start_task(
    conn: sqlite3.Connection,
    root: Path | str,
    title: str,
    *,
    task_type: str = "unknown",
) -> dict[str, Any]:
    validate_choice("task_type", task_type, TASK_TYPE_VALUES)
    project_id = project_id_for_path(root)
    if _open_task_row(conn, project_id) is not None:
        raise ValueError(
            "an open task already exists; close or abandon it before starting another"
        )

    now = now_iso()
    task_id = new_id("task")
    redacted_title = redact_text(title)
    try:
        conn.execute(
            """
            INSERT INTO tasks(
              task_id, project_id, title, task_type, status, created_seq,
              created_at, updated_at, evidence
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                task_id,
                project_id,
                redacted_title,
                task_type,
                "open",
                next_commit_seq(conn),
                now,
                now,
                redact_mapping_str({}),
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError(
            "an open task already exists; close or abandon it before starting another"
        ) from exc
    _set_meta_value(conn, CURRENT_TASK_META_KEY, task_id)
    conn.commit()
    return show_task(conn, task_id)


def task_status(conn: sqlite3.Connection, root: Path | str) -> dict[str, Any]:
    project_id = project_id_for_path(root)
    task_row = _open_task_row(conn, project_id)
    if task_row is None:
        return {"open": None, "attached_run_count": 0}
    task_id = task_row["task_id"]
    return {
        "open": _task_from_row(task_row),
        "attached_run_count": _attached_run_count(conn, task_id),
    }


def list_tasks(conn: sqlite3.Connection, *, status: str = "open") -> dict[str, Any]:
    validate_choice("status", status, LIST_TASK_STATUS_VALUES)
    project_id = _project_id_from_conn(conn)
    where, params = ("", [project_id])
    if status != "all":
        where = "AND status = ?"
        params.append(status)
    rows = conn.execute(
        f"""
        SELECT * FROM tasks
        WHERE project_id = ?
        {where}
        ORDER BY created_seq DESC, task_id DESC
        """,
        params,
    ).fetchall()
    tasks = [_task_summary_from_row(row, conn) for row in rows]
    return {"tasks": tasks}


def show_task(conn: sqlite3.Connection, task_id: str) -> dict[str, Any]:
    row = _task_row(conn, task_id)
    result = _task_from_row(row)
    result["attached_run_count"] = _attached_run_count(conn, task_id)
    return result


def close_task(
    conn: sqlite3.Connection,
    root: Path | str,
    *,
    status: str = "unknown",
    from_verify: bool = False,
    timeout_seconds: int = verify.DEFAULT_TIMEOUT_SECONDS,
    qualifier: str | None = None,
    profile: str | None = None,
    close_reason: str | None = None,
) -> dict[str, Any]:
    validate_choice("status", status, OUTCOME_STATUS_VALUES)
    task_id = _require_open_task(conn, root)
    representative_run_id = _representative_run_id(conn, task_id)
    if from_verify and representative_run_id is None:
        raise ValueError("cannot use --from-verify without an attached run")
    outcome_status = status
    tests_status = "not_run"
    evidence: dict[str, Any] = {"source": "task_close", "run_count": _attached_run_count(conn, task_id)}
    task_type = _task_row(conn, task_id)["task_type"]

    now = now_iso()
    try:
        if representative_run_id is not None:
            if from_verify:
                outcome_result = outcome.mark_outcome_from_verify(
                    conn,
                    representative_run_id,
                    root,
                    status=status,
                    task_type=task_type,
                    timeout_seconds=timeout_seconds,
                    qualifier=qualifier,
                    profile=profile,
                    commit=False,
                )
            else:
                outcome_result = outcome.mark_outcome(
                    conn,
                    representative_run_id,
                    status=status,
                    tests_status="unknown",
                    task_type=task_type,
                    commit=False,
                )
            outcome_status = outcome_result["status"]
            tests_status = outcome_result["tests_status"]
            evidence["verify_reason_code"] = _verify_reason_code(
                outcome_result.get("evidence", {})
            )
        _transition_task(conn, task_id, target="closed", now=now)
        conn.execute(
            """
            UPDATE tasks
            SET outcome_status = ?,
                tests_status = ?,
                closed_at = ?,
                close_reason = ?,
                evidence = ?,
                updated_at = ?
            WHERE task_id = ?
            """,
            (
                outcome_status,
                tests_status,
                now,
                redact_text(close_reason),
                redact_mapping_str(evidence),
                now,
                task_id,
            ),
        )
        _clear_current_task_if(conn, task_id)
        conn.commit()
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    return show_task(conn, task_id)


def abandon_task(
    conn: sqlite3.Connection,
    root: Path | str,
    *,
    reason: str | None = None,
) -> dict[str, Any]:
    task_id = _require_open_task(conn, root)
    now = now_iso()
    _transition_task(conn, task_id, target="abandoned", now=now)
    conn.execute(
        """
        UPDATE tasks
        SET close_reason = ?, closed_at = ?, updated_at = ?
        WHERE task_id = ?
        """,
        (redact_text(reason), now, now, task_id),
    )
    _clear_current_task_if(conn, task_id)
    conn.commit()
    return show_task(conn, task_id)


def read_view(conn: sqlite3.Connection) -> dict[str, Any]:
    """Return a leak-free machine-read view of open tasks only."""
    rows = conn.execute(
        """
        SELECT * FROM tasks
        WHERE status = 'open'
        ORDER BY created_seq DESC, task_id DESC
        """
    ).fetchall()
    return {
        "schema_version": READ_VIEW_SCHEMA_VERSION,
        "tasks": [_project_task_read_view(row, conn) for row in rows],
    }


def cli_command_readonly(args: argparse.Namespace) -> bool:
    return args.task_command in {"status", "ls", "show", "read"}


def handle_cli_action(
    conn: sqlite3.Connection,
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    *,
    root: Path | str,
) -> Any:
    if args.task_command == "start":
        return start_task(conn, root, args.intent, task_type=args.task_type)
    if args.task_command == "status":
        return task_status(conn, root)
    if args.task_command == "ls":
        return list_tasks(conn, status=args.status)
    if args.task_command == "show":
        return show_task(conn, args.task_id)
    if args.task_command == "read":
        return read_view(conn)
    if args.task_command == "close":
        _validate_verify_options(args, parser)
        outcome_status = _cli_outcome_status(args)
        return close_task(
            conn,
            root,
            status=outcome_status,
            from_verify=args.from_verify,
            timeout_seconds=(
                args.timeout_seconds
                if args.timeout_seconds is not None
                else verify.DEFAULT_TIMEOUT_SECONDS
            ),
            qualifier=args.qualifier,
            profile=args.profile,
            close_reason=args.reason,
        )
    if args.task_command == "abandon":
        return abandon_task(conn, root, reason=args.reason)
    parser.error(f"unknown task command: {args.task_command}")


def _validate_verify_options(
    args: argparse.Namespace, parser: argparse.ArgumentParser
) -> None:
    verify_options = {
        "--timeout-seconds": args.timeout_seconds,
        "--qualifier": args.qualifier,
        "--profile": args.profile,
    }
    if args.from_verify:
        return
    used = [name for name, value in verify_options.items() if value is not None]
    if used:
        parser.error(f"{', '.join(used)} requires --from-verify")


def _cli_outcome_status(args: argparse.Namespace) -> str:
    if args.success:
        return "success"
    if args.failed:
        return "failed"
    if args.unknown:
        return "unknown"
    return "unknown"


def _require_open_task(conn: sqlite3.Connection, root: Path | str) -> str:
    project_id = project_id_for_path(root)
    row = _open_task_row(conn, project_id)
    if row is None:
        raise ValueError("no open task")
    return row["task_id"]


def _open_task_row(conn: sqlite3.Connection, project_id: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT * FROM tasks
        WHERE project_id = ? AND status = 'open'
        ORDER BY created_seq DESC, task_id DESC
        LIMIT 1
        """,
        (project_id,),
    ).fetchone()


def _task_row(conn: sqlite3.Connection, task_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
    if row is None:
        raise ValueError(f"unknown task: {task_id}")
    return row


def _task_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["evidence"] = decode_json_dict(result["evidence"])
    return result


def _task_summary_from_row(row: sqlite3.Row, conn: sqlite3.Connection) -> dict[str, Any]:
    summary = _task_from_row(row)
    summary["attached_run_count"] = _attached_run_count(conn, row["task_id"])
    return summary


def _attached_run_count(conn: sqlite3.Connection, task_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS count FROM runs WHERE task_id = ?",
        (task_id,),
    ).fetchone()
    return int(row["count"])


def _representative_run_id(conn: sqlite3.Connection, task_id: str) -> str | None:
    row = conn.execute(
        """
        SELECT run_id FROM runs
        WHERE task_id = ?
        ORDER BY COALESCE(started_at, '') DESC, run_id DESC
        LIMIT 1
        """,
        (task_id,),
    ).fetchone()
    return row["run_id"] if row else None


def _transition_task(
    conn: sqlite3.Connection,
    task_id: str,
    *,
    target: str,
    now: str,
) -> None:
    validate_choice("status", target, TASK_STATUS_VALUES)
    row = _task_row(conn, task_id)
    current = row["status"]
    if current == target:
        return
    if current in TASK_TERMINAL_STATUS_VALUES:
        raise ValueError(f"task already {current}: {task_id}")
    if current != "open":
        raise ValueError(f"task cannot transition from {current}: {task_id}")
    updated = conn.execute(
        """
        UPDATE tasks
        SET status = ?, updated_at = ?
        WHERE task_id = ? AND status = 'open'
        """,
        (target, now, task_id),
    )
    if updated.rowcount != 1:
        refreshed = _task_row(conn, task_id)
        if refreshed["status"] == target:
            return
        raise ValueError(
            f"task transition failed: {task_id} "
            f"(current={refreshed['status']}, target={target})"
        )


def _project_id_from_conn(conn: sqlite3.Connection) -> str:
    root = root_from_connection(conn)
    if root is None:
        raise ValueError("could not resolve project root from database connection")
    return project_id_for_path(root)


def _meta_value(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def _set_meta_value(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO meta(key, value) VALUES(?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )


def _clear_current_task_if(conn: sqlite3.Connection, task_id: str) -> None:
    if _meta_value(conn, CURRENT_TASK_META_KEY) == task_id:
        conn.execute("DELETE FROM meta WHERE key = ?", (CURRENT_TASK_META_KEY,))


def _verify_reason_code(evidence: dict[str, Any]) -> str | None:
    verify_block = evidence.get("verify")
    if isinstance(verify_block, dict):
        reason_code = verify_block.get("reason_code")
        return str(reason_code) if reason_code is not None else None
    return None


def _project_task_read_view(row: sqlite3.Row, conn: sqlite3.Connection) -> dict[str, Any]:
    base = _task_from_row(row)
    projected: dict[str, Any] = {"run_count": _attached_run_count(conn, row["task_id"])}
    for field, required in TASK_READ_VIEW_FIELDS:
        if field == "run_count":
            continue
        value = base.get(field)
        if value is None or value == "":
            if required:
                projected[field] = ""
            continue
        projected[field] = redact_text(str(value)) if field == "title" else value
    return projected
