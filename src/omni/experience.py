"""Reviewable experience candidates derived from eval and outcome evidence."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from omni import eval as behavior_eval
from omni._common import now_iso, validate_choice
from omni.dbaccess import ensure_run_exists, root_from_connection
from omni.ids import new_id
from omni.jsonio import as_json, redact_mapping_str, redact_text

KIND_VALUES = {
    "fast_path",
    "rediscovery_waste",
    "verification_hint",
    "project_workflow",
}
STATE_VALUES = {"pending", "approved", "rejected"}
LIST_STATE_VALUES = STATE_VALUES | {"all"}
NOTE_STATUS_VALUES = {"active", "retired"}
LIST_NOTE_STATUS_VALUES = NOTE_STATUS_VALUES | {"all"}

REDISCOVERY_WASTE_CLAIM = (
    "Memory context was available, but the run performed rediscovery and did not "
    "execute the known verification command."
)
REDISCOVERY_WASTE_ACTION = (
    "For validation tasks, execute the known verification command before broad "
    "README/package/deployment rediscovery."
)
FAST_PATH_CLAIM = (
    "For validation tasks, the known verification command worked before rediscovery."
)
FAST_PATH_ACTION = (
    "Prefer the known verification command early in future validation tasks."
)


def extract_candidates(conn: sqlite3.Connection, run_id: str) -> list[dict[str, Any]]:
    ensure_run_exists(conn, run_id)
    outcome_row = _outcome_for_run(conn, run_id)
    if outcome_row is None:
        return []
    eval_result = _evaluate_run(conn, run_id)
    spec = _candidate_spec(eval_result, outcome_row)
    if spec is None:
        return []
    if _candidate_exists(conn, run_id, spec["kind"]):
        return []

    now = now_iso()
    exp_cand_id = new_id("exp_cand")
    evidence = _evidence_for(run_id, outcome_row, eval_result)
    # The NOT EXISTS guard re-checks (run_id, kind) inside the write statement so
    # two concurrent extracts cannot both pass _candidate_exists and insert
    # duplicate candidates for the same run.
    inserted = conn.execute(
        """
        INSERT INTO experience_candidates(
          exp_cand_id, run_id, outcome_id, task_type, kind, trigger,
          claim, suggested_action, evidence, state, created_at,
          reviewed_at, review_note
        )
        SELECT ?,?,?,?,?,?,?,?,?,?,?,?,?
        WHERE NOT EXISTS(
          SELECT 1 FROM experience_candidates WHERE run_id = ? AND kind = ?
        )
        """,
        (
            exp_cand_id,
            run_id,
            outcome_row["outcome_id"],
            outcome_row["task_type"],
            spec["kind"],
            redact_text(spec["trigger"]),
            redact_text(spec["claim"]),
            redact_text(spec["suggested_action"]),
            redact_mapping_str(evidence),
            "pending",
            now,
            None,
            None,
            run_id,
            spec["kind"],
        ),
    )
    conn.commit()
    if inserted.rowcount == 0:
        return []
    return [show_candidate(conn, exp_cand_id)]


def list_candidates(conn: sqlite3.Connection, state: str = "pending") -> list[dict[str, Any]]:
    validate_choice("state", state, LIST_STATE_VALUES)
    if state == "all":
        rows = conn.execute(
            """
            SELECT *
            FROM experience_candidates
            ORDER BY created_at, exp_cand_id
            """
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT *
            FROM experience_candidates
            WHERE state = ?
            ORDER BY created_at, exp_cand_id
            """,
            (state,),
        ).fetchall()
    return [_candidate_from_row(row) for row in rows]


def show_candidate(conn: sqlite3.Connection, exp_cand_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM experience_candidates WHERE exp_cand_id = ?",
        (exp_cand_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown experience candidate: {exp_cand_id}")
    return _candidate_from_row(row)


def approve_candidate(conn: sqlite3.Connection, exp_cand_id: str) -> dict[str, Any]:
    candidate = conn.execute(
        "SELECT * FROM experience_candidates WHERE exp_cand_id = ?",
        (exp_cand_id,),
    ).fetchone()
    if candidate is None:
        raise ValueError(f"unknown experience candidate: {exp_cand_id}")

    note_id = _active_note_id_for_candidate(conn, exp_cand_id)
    if candidate["state"] == "approved":
        if note_id is None:
            raise ValueError(f"approved candidate has no active note: {exp_cand_id}")
        result = show_candidate(conn, exp_cand_id)
        result["note_id"] = note_id
        return result
    if candidate["state"] == "rejected":
        raise ValueError(f"rejected candidate cannot be approved in v0: {exp_cand_id}")

    validate_choice("state", candidate["state"], STATE_VALUES)
    validate_choice("kind", candidate["kind"], KIND_VALUES)
    if note_id is None:
        try:
            note_id = _create_experience_note(conn, candidate)
        except sqlite3.IntegrityError:
            # Another writer approved this candidate after our existence check;
            # recover by reusing its committed active note.
            conn.rollback()
            note_id = _active_note_id_for_candidate(conn, exp_cand_id)
            if note_id is None:
                raise
    updated = conn.execute(
        """
        UPDATE experience_candidates
        SET state = 'approved', reviewed_at = ?
        WHERE exp_cand_id = ? AND state != 'rejected'
        """,
        (now_iso(), exp_cand_id),
    )
    if updated.rowcount == 0:
        # A concurrent reviewer rejected this candidate after our state check;
        # discard the uncommitted note instead of resurrecting the candidate.
        conn.rollback()
        raise ValueError(f"rejected candidate cannot be approved in v0: {exp_cand_id}")
    conn.commit()
    result = show_candidate(conn, exp_cand_id)
    result["note_id"] = note_id
    return result


def reject_candidate(conn: sqlite3.Connection, exp_cand_id: str) -> dict[str, Any]:
    candidate = conn.execute(
        "SELECT state FROM experience_candidates WHERE exp_cand_id = ?",
        (exp_cand_id,),
    ).fetchone()
    if candidate is None:
        raise ValueError(f"unknown experience candidate: {exp_cand_id}")
    if candidate["state"] == "approved":
        raise ValueError(f"approved candidate cannot be rejected in v0: {exp_cand_id}")
    if candidate["state"] == "rejected":
        return show_candidate(conn, exp_cand_id)
    validate_choice("state", candidate["state"], STATE_VALUES)
    updated = conn.execute(
        """
        UPDATE experience_candidates
        SET state = 'rejected', reviewed_at = ?
        WHERE exp_cand_id = ? AND state = 'pending'
        """,
        (now_iso(), exp_cand_id),
    )
    if updated.rowcount == 0:
        # Another writer changed the state between our check and this update;
        # re-apply the v0 transition rules against the committed state.
        conn.rollback()
        current = conn.execute(
            "SELECT state FROM experience_candidates WHERE exp_cand_id = ?",
            (exp_cand_id,),
        ).fetchone()
        if current is not None and current["state"] == "approved":
            raise ValueError(
                f"approved candidate cannot be rejected in v0: {exp_cand_id}"
            )
        return show_candidate(conn, exp_cand_id)
    conn.commit()
    return show_candidate(conn, exp_cand_id)


def list_notes(conn: sqlite3.Connection, status: str = "active") -> list[dict[str, Any]]:
    validate_choice("status", status, LIST_NOTE_STATUS_VALUES)
    if status == "all":
        rows = conn.execute(
            """
            SELECT *
            FROM experience_notes
            ORDER BY created_seq, note_id
            """
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT *
            FROM experience_notes
            WHERE status = ?
            ORDER BY created_seq, note_id
            """,
            (status,),
        ).fetchall()
    return [_note_from_row(row) for row in rows]


def show_note(conn: sqlite3.Connection, note_id: str) -> dict[str, Any]:
    return _note_from_row(_note_row(conn, note_id))


def retire_note(conn: sqlite3.Connection, note_id: str) -> dict[str, Any]:
    try:
        conn.execute("BEGIN")
        note = _note_row(conn, note_id)
        status = note["status"]
        validate_choice("status", status, NOTE_STATUS_VALUES)
        if status == "retired":
            # Idempotent: a retired note stays retired and the source candidate is
            # never touched.
            conn.commit()
            return show_note(conn, note_id)

        updated = conn.execute(
            """
            UPDATE experience_notes
            SET status = 'retired', retired_seq = ?, updated_at = ?
            WHERE note_id = ? AND status = 'active'
            """,
            (_next_commit_seq(conn), now_iso(), note_id),
        )
        if updated.rowcount != 1:
            raise ValueError(f"experience note could not be retired: {note_id}")
        conn.commit()
        return show_note(conn, note_id)
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def _candidate_spec(
    eval_result: dict[str, Any], outcome_row: sqlite3.Row
) -> dict[str, str] | None:
    eval_effect = str(eval_result.get("memory_effect") or "unknown")
    task_type = str(outcome_row["task_type"])
    outcome_status = str(outcome_row["status"])
    outcome_tests_status = str(outcome_row["tests_status"])
    outcome_memory_effect = str(outcome_row["memory_effect"])

    if (
        eval_effect == "failed_to_help"
        and (outcome_memory_effect == "failed_to_help" or outcome_status in {"failed", "unknown"})
        and task_type == "validation"
    ):
        return {
            "kind": "rediscovery_waste",
            "trigger": "validation_failed_to_help",
            "claim": REDISCOVERY_WASTE_CLAIM,
            "suggested_action": REDISCOVERY_WASTE_ACTION,
        }

    if (
        eval_effect == "helped"
        and outcome_status == "success"
        and outcome_tests_status in {"passed", "unknown"}
        and task_type == "validation"
    ):
        return {
            "kind": "fast_path",
            "trigger": "validation_fast_path",
            "claim": FAST_PATH_CLAIM,
            "suggested_action": FAST_PATH_ACTION,
        }

    return None


def _evidence_for(
    run_id: str, outcome_row: sqlite3.Row, eval_result: dict[str, Any]
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "outcome_id": outcome_row["outcome_id"],
        "eval": {
            "memory_effect": eval_result.get("memory_effect", "unknown"),
            "reason": eval_result.get("reason", ""),
            "rediscovery_count": eval_result.get("rediscovery_count", 0),
            "first_expected_command": eval_result.get("first_expected_command"),
        },
        "outcome": {
            "status": outcome_row["status"],
            "tests_status": outcome_row["tests_status"],
            "task_type": outcome_row["task_type"],
        },
    }


def _outcome_for_run(conn: sqlite3.Connection, run_id: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT outcome_id, run_id, task_type, status, tests_status, memory_effect
        FROM outcomes
        WHERE run_id = ?
        """,
        (run_id,),
    ).fetchone()


def _evaluate_run(conn: sqlite3.Connection, run_id: str) -> dict[str, Any]:
    root = root_from_connection(conn)
    if root is None:
        return {"memory_effect": "unknown", "reason": "insufficient evidence"}
    try:
        return behavior_eval.evaluate_run(root, run_id)
    except Exception as exc:
        print(
            f"warning: eval unavailable for {run_id}: {type(exc).__name__}",
            file=sys.stderr,
        )
        return {"memory_effect": "unknown", "reason": "eval unavailable"}


def _candidate_exists(conn: sqlite3.Connection, run_id: str, kind: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM experience_candidates
        WHERE run_id = ? AND kind = ?
        LIMIT 1
        """,
        (run_id, kind),
    ).fetchone()
    return row is not None


def _active_note_id_for_candidate(conn: sqlite3.Connection, exp_cand_id: str) -> str | None:
    row = conn.execute(
        """
        SELECT note_id
        FROM experience_notes
        WHERE source_cand_id = ? AND status = 'active'
        """,
        (exp_cand_id,),
    ).fetchone()
    return row["note_id"] if row is not None else None


def _create_experience_note(conn: sqlite3.Connection, candidate: sqlite3.Row) -> str:
    now = now_iso()
    note_id = new_id("note")
    conn.execute(
        """
        INSERT INTO experience_notes(
          note_id, source_cand_id, scope, task_type, kind, trigger,
          body, suggested_action, trust, status, evidence, created_seq,
          retired_seq, superseded_by, created_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            note_id,
            candidate["exp_cand_id"],
            "project",
            candidate["task_type"],
            candidate["kind"],
            redact_text(candidate["trigger"]),
            redact_text(candidate["claim"]),
            redact_text(candidate["suggested_action"]),
            2,
            "active",
            redact_mapping_str(_decode_json_object(candidate["evidence"])),
            _next_commit_seq(conn),
            None,
            None,
            now,
            now,
        ),
    )
    return note_id


def _next_commit_seq(conn: sqlite3.Connection) -> int:
    # Increment in place so the read and the write happen under one write lock;
    # a separate read-then-write pair can hand the same sequence number to two
    # concurrent writers.
    updated = conn.execute(
        "UPDATE meta SET value = CAST(value AS INTEGER) + 1 WHERE key = 'commit_seq'"
    )
    if updated.rowcount == 0:
        conn.execute("INSERT INTO meta(key, value) VALUES('commit_seq', '1')")
        return 1
    row = conn.execute("SELECT value FROM meta WHERE key = 'commit_seq'").fetchone()
    return int(row["value"])


def _candidate_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["evidence"] = _decode_json_object(result["evidence"])
    return result


def _note_row(conn: sqlite3.Connection, note_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM experience_notes WHERE note_id = ?",
        (note_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown experience note: {note_id}")
    return row


def _note_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["evidence"] = _decode_json_object(result["evidence"])
    result["lifecycle"] = _note_lifecycle(result["status"])
    return result


def _note_lifecycle(status: str) -> dict[str, Any]:
    validate_choice("status", status, NOTE_STATUS_VALUES)
    if status == "active":
        return {
            "renders": True,
            "can_retire": True,
            "can_reactivate": False,
            "supersede_supported": False,
            "message": "active note renders into memory.md; retire it to stop rendering",
        }
    return {
        "renders": False,
        "can_retire": False,
        "can_reactivate": False,
        "supersede_supported": False,
        "message": (
            "retired note does not render into memory.md; "
            "v1 does not reactivate retired notes"
        ),
    }


def _decode_json_object(value: str) -> dict[str, Any]:
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return {"decode_error": "invalid_json"}
    return decoded if isinstance(decoded, dict) else {"decode_error": "non_object"}


def cli_command_readonly(args: argparse.Namespace) -> bool:
    from omni._common import memory_cli_readonly

    return memory_cli_readonly(
        args.experience_command,
        getattr(args, "experience_note_command", None),
        nested_parent="note",
    )


def handle_cli_action(
    conn: sqlite3.Connection,
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
) -> Any:
    if args.experience_command == "extract":
        candidates = extract_candidates(conn, args.run_id)
        return {"created": len(candidates), "candidates": candidates}
    if args.experience_command == "ls":
        return {"candidates": list_candidates(conn, args.state)}
    if args.experience_command == "show":
        return show_candidate(conn, args.exp_cand_id)
    if args.experience_command == "approve":
        return approve_candidate(conn, args.exp_cand_id)
    if args.experience_command == "reject":
        return reject_candidate(conn, args.exp_cand_id)
    if args.experience_command == "note":
        if args.experience_note_command == "ls":
            return {"notes": list_notes(conn, status=args.status)}
        if args.experience_note_command == "show":
            return show_note(conn, args.note_id)
        if args.experience_note_command == "retire":
            return retire_note(conn, args.note_id)
        parser.error(f"unknown experience note command: {args.experience_note_command}")
        return 2
    parser.error(f"unknown experience command: {args.experience_command}")
    return 2
