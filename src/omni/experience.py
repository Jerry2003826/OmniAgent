"""Reviewable experience candidates derived from eval and outcome evidence."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from omni import db
from omni import eval as behavior_eval
from omni.ids import new_id
from omni.redact import redact

KIND_VALUES = {
    "fast_path",
    "rediscovery_waste",
    "verification_hint",
    "project_workflow",
}
STATE_VALUES = {"pending", "approved", "rejected"}
LIST_STATE_VALUES = STATE_VALUES | {"all"}

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


def connect_project(root: Path | str | None = None) -> sqlite3.Connection:
    base = Path(root or Path.cwd()).resolve()
    db_path = base / ".omni" / "omni.sqlite3"
    if not db_path.exists():
        raise FileNotFoundError(f"OmniMemory database is missing: {db_path}")
    conn = db.connect(db_path)
    db.migrate(conn)
    return conn


def extract_candidates(conn: sqlite3.Connection, run_id: str) -> list[dict[str, Any]]:
    _ensure_run_exists(conn, run_id)
    outcome_row = _outcome_for_run(conn, run_id)
    if outcome_row is None:
        return []
    eval_result = _evaluate_run(conn, run_id)
    spec = _candidate_spec(eval_result, outcome_row)
    if spec is None:
        return []
    if _candidate_exists(conn, run_id, spec["kind"]):
        return []

    now = _now()
    exp_cand_id = new_id("exp_cand")
    evidence = _evidence_for(run_id, outcome_row, eval_result)
    conn.execute(
        """
        INSERT INTO experience_candidates(
          exp_cand_id, run_id, outcome_id, task_type, kind, trigger,
          claim, suggested_action, evidence, state, created_at,
          reviewed_at, review_note
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            exp_cand_id,
            run_id,
            outcome_row["outcome_id"],
            outcome_row["task_type"],
            spec["kind"],
            _redact_text(spec["trigger"]),
            _redact_text(spec["claim"]),
            _redact_text(spec["suggested_action"]),
            _redact_json(evidence),
            "pending",
            now,
            None,
            None,
        ),
    )
    conn.commit()
    return [show_candidate(conn, exp_cand_id)]


def list_candidates(conn: sqlite3.Connection, state: str = "pending") -> list[dict[str, Any]]:
    _validate_choice("state", state, LIST_STATE_VALUES)
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

    _validate_choice("state", candidate["state"], STATE_VALUES)
    if note_id is None:
        note_id = _create_experience_note(conn, candidate)
    conn.execute(
        """
        UPDATE experience_candidates
        SET state = 'approved', reviewed_at = ?, review_note = NULL
        WHERE exp_cand_id = ?
        """,
        (_now(), exp_cand_id),
    )
    conn.commit()
    result = show_candidate(conn, exp_cand_id)
    result["note_id"] = note_id
    return result


def reject_candidate(conn: sqlite3.Connection, exp_cand_id: str) -> dict[str, Any]:
    return _set_candidate_state(conn, exp_cand_id, "rejected")


def as_json(value: dict[str, Any]) -> str:
    return behavior_eval.as_json(value)


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


def _ensure_run_exists(conn: sqlite3.Connection, run_id: str) -> None:
    row = conn.execute("SELECT 1 FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        raise ValueError(f"unknown run: {run_id}")


def _evaluate_run(conn: sqlite3.Connection, run_id: str) -> dict[str, Any]:
    root = _root_from_connection(conn)
    if root is None:
        return {"memory_effect": "unknown", "reason": "insufficient evidence"}
    try:
        return behavior_eval.evaluate_run(root, run_id)
    except Exception:
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


def _set_candidate_state(
    conn: sqlite3.Connection, exp_cand_id: str, state: str
) -> dict[str, Any]:
    _validate_choice("state", state, STATE_VALUES)
    existing = conn.execute(
        "SELECT 1 FROM experience_candidates WHERE exp_cand_id = ?",
        (exp_cand_id,),
    ).fetchone()
    if existing is None:
        raise ValueError(f"unknown experience candidate: {exp_cand_id}")
    conn.execute(
        """
        UPDATE experience_candidates
        SET state = ?, reviewed_at = ?, review_note = NULL
        WHERE exp_cand_id = ?
        """,
        (state, _now(), exp_cand_id),
    )
    conn.commit()
    return show_candidate(conn, exp_cand_id)


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
    now = _now()
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
            _redact_text(candidate["trigger"]),
            _redact_text(candidate["claim"]),
            _redact_text(candidate["suggested_action"]),
            2,
            "active",
            _redact_json(_decode_json_object(candidate["evidence"])),
            _next_commit_seq(conn),
            None,
            None,
            now,
            now,
        ),
    )
    return note_id


def _next_commit_seq(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM meta WHERE key = 'commit_seq'").fetchone()
    current = int(row["value"]) if row else 0
    next_value = current + 1
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES('commit_seq', ?)",
        (str(next_value),),
    )
    return next_value


def _candidate_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["evidence"] = _decode_json_object(result["evidence"])
    return result


def _redact_text(value: str | None) -> str | None:
    if value is None:
        return None
    return redact(value.encode("utf-8")).data.decode("utf-8", errors="replace")


def _redact_json(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return redact(encoded).data.decode("utf-8", errors="replace")


def _decode_json_object(value: str) -> dict[str, Any]:
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return {"decode_error": "invalid_json"}
    return decoded if isinstance(decoded, dict) else {"decode_error": "non_object"}


def _validate_choice(name: str, value: str, allowed: set[str]) -> None:
    if value not in allowed:
        allowed_text = ", ".join(sorted(allowed))
        raise ValueError(f"invalid {name}: {value}; expected one of: {allowed_text}")


def _root_from_connection(conn: sqlite3.Connection) -> Path | None:
    rows = conn.execute("PRAGMA database_list").fetchall()
    for row in rows:
        if row["name"] != "main" or not row["file"]:
            continue
        db_path = Path(row["file"]).resolve()
        if db_path.parent.name == ".omni":
            return db_path.parent.parent
    return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
