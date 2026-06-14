"""Reviewable preference candidates derived from boundary fact candidates."""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from omni import db
from omni import eval as behavior_eval
from omni.ids import new_id
from omni.redact import redact

KIND_VALUES = {"prefers", "avoids", "boundary"}
STATE_VALUES = {"pending", "approved", "rejected"}
LIST_STATE_VALUES = STATE_VALUES | {"all"}
NOTE_STATUS_VALUES = {"active", "retired"}
LIST_NOTE_STATUS_VALUES = NOTE_STATUS_VALUES | {"all"}
BOUNDARY_PREDICATE_PREFIXES = ("prefers_", "avoids_", "boundary_")


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
            "'omni render' to migrate"
        )
    return conn


def extract_candidates(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    created: list[dict[str, Any]] = []
    rows = conn.execute(
        """
        SELECT cand_id, scope, predicate, qualifier, object_norm, claim, evidence
        FROM fact_candidates
        WHERE state = 'pending'
          AND (
            predicate LIKE 'prefers_%'
            OR predicate LIKE 'avoids_%'
            OR predicate LIKE 'boundary_%'
          )
        ORDER BY created_at, cand_id
        """
    ).fetchall()
    for row in rows:
        if _candidate_exists_for_source(conn, row["cand_id"]):
            continue
        spec = _candidate_spec(row)
        if spec is None:
            continue
        pref_cand_id = new_id("pref_cand")
        now = _now()
        conn.execute(
            """
            INSERT INTO preference_candidates(
              pref_cand_id, source_cand_id, scope, kind, predicate, qualifier,
              body, suggested_action, evidence, state, created_at, reviewed_at,
              review_note
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                pref_cand_id,
                row["cand_id"],
                row["scope"],
                spec["kind"],
                row["predicate"],
                row["qualifier"],
                _redact_text(spec["body"]),
                _redact_text(spec["suggested_action"]),
                _redact_json({"source_cand_id": row["cand_id"], "claim": row["claim"]}),
                "pending",
                now,
                None,
                None,
            ),
        )
        created.append(show_candidate(conn, pref_cand_id))
    conn.commit()
    return created


def list_candidates(conn: sqlite3.Connection, state: str = "pending") -> list[dict[str, Any]]:
    _validate_choice("state", state, LIST_STATE_VALUES)
    if state == "all":
        rows = conn.execute(
            """
            SELECT *
            FROM preference_candidates
            ORDER BY created_at, pref_cand_id
            """
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT *
            FROM preference_candidates
            WHERE state = ?
            ORDER BY created_at, pref_cand_id
            """,
            (state,),
        ).fetchall()
    return [_candidate_from_row(row) for row in rows]


def show_candidate(conn: sqlite3.Connection, pref_cand_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM preference_candidates WHERE pref_cand_id = ?",
        (pref_cand_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown preference candidate: {pref_cand_id}")
    return _candidate_from_row(row)


def approve_candidate(
    conn: sqlite3.Connection,
    pref_cand_id: str,
    *,
    suggested_action: str | None = None,
) -> dict[str, Any]:
    candidate = show_candidate(conn, pref_cand_id)
    if candidate["state"] == "approved":
        raise ValueError(f"preference candidate already approved: {pref_cand_id}")
    if candidate["state"] == "rejected":
        raise ValueError(f"rejected preference candidate cannot be approved: {pref_cand_id}")
    if candidate["state"] != "pending":
        raise ValueError(f"preference candidate is not pending: {pref_cand_id}")
    note_id = _create_preference_note(
        conn,
        candidate,
        suggested_action=suggested_action or candidate["suggested_action"],
    )
    now = _now()
    conn.execute(
        """
        UPDATE preference_candidates
        SET state = 'approved', reviewed_at = ?, review_note = NULL
        WHERE pref_cand_id = ?
        """,
        (now, pref_cand_id),
    )
    conn.commit()
    return show_note(conn, note_id)


def reject_candidate(conn: sqlite3.Connection, pref_cand_id: str) -> dict[str, Any]:
    candidate = _require_pending_candidate(conn, pref_cand_id)
    if candidate["state"] == "approved":
        raise ValueError(f"approved preference candidate cannot be rejected: {pref_cand_id}")
    if candidate["state"] == "rejected":
        return candidate
    now = _now()
    conn.execute(
        """
        UPDATE preference_candidates
        SET state = 'rejected', reviewed_at = ?
        WHERE pref_cand_id = ?
        """,
        (now, pref_cand_id),
    )
    conn.commit()
    return show_candidate(conn, pref_cand_id)


def list_notes(conn: sqlite3.Connection, status: str = "active") -> list[dict[str, Any]]:
    _validate_choice("status", status, LIST_NOTE_STATUS_VALUES)
    if status == "all":
        rows = conn.execute(
            """
            SELECT note_id, scope, kind, body, suggested_action, status
            FROM preference_notes
            ORDER BY created_seq, note_id
            """
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT note_id, scope, kind, body, suggested_action, status
            FROM preference_notes
            WHERE status = ?
            ORDER BY created_seq, note_id
            """,
            (status,),
        ).fetchall()
    return [dict(row) for row in rows]


def show_note(conn: sqlite3.Connection, note_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT note_id, source_cand_id, scope, kind, body, suggested_action,
               status, evidence, created_seq, retired_seq, created_at, updated_at
        FROM preference_notes
        WHERE note_id = ?
        """,
        (note_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown preference note: {note_id}")
    result = dict(row)
    result["evidence"] = _decode_evidence(result["evidence"])
    return result


def retire_note(conn: sqlite3.Connection, note_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT note_id, status FROM preference_notes WHERE note_id = ?",
        (note_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown preference note: {note_id}")
    if row["status"] == "retired":
        return show_note(conn, note_id)
    now = _now()
    conn.execute(
        """
        UPDATE preference_notes
        SET status = 'retired', retired_seq = ?, updated_at = ?
        WHERE note_id = ?
        """,
        (_next_commit_seq(conn), now, note_id),
    )
    conn.commit()
    return show_note(conn, note_id)


def as_json(value: dict[str, Any] | list[dict[str, Any]]) -> str:
    return behavior_eval.as_json(value)


def _candidate_spec(row: sqlite3.Row) -> dict[str, str] | None:
    predicate = row["predicate"]
    if predicate.startswith("prefers_"):
        kind = "prefers"
    elif predicate.startswith("avoids_"):
        kind = "avoids"
    elif predicate.startswith("boundary_"):
        kind = "boundary"
    else:
        return None
    label = predicate.replace("_", " ")
    body = f"{label}: {row['object_norm']}"
    suggested_action = row["claim"] or f"Respect this project {kind} boundary."
    return {
        "kind": kind,
        "body": body,
        "suggested_action": suggested_action,
    }


def _candidate_exists_for_source(conn: sqlite3.Connection, source_cand_id: str) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM preference_candidates WHERE source_cand_id = ? LIMIT 1
        """,
        (source_cand_id,),
    ).fetchone()
    return row is not None


def _require_pending_candidate(conn: sqlite3.Connection, pref_cand_id: str) -> dict[str, Any]:
    return show_candidate(conn, pref_cand_id)


def _create_preference_note(
    conn: sqlite3.Connection,
    candidate: dict[str, Any],
    *,
    suggested_action: str,
) -> str:
    now = _now()
    note_id = new_id("pref_note")
    conn.execute(
        """
        INSERT INTO preference_notes(
          note_id, source_cand_id, scope, kind, body, suggested_action, status,
          evidence, created_seq, retired_seq, created_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            note_id,
            candidate.get("source_cand_id"),
            candidate["scope"],
            candidate["kind"],
            candidate["body"],
            _redact_text(suggested_action),
            "active",
            _redact_json({"pref_cand_id": candidate["pref_cand_id"]}),
            _next_commit_seq(conn),
            None,
            now,
            now,
        ),
    )
    return note_id


def _candidate_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["evidence"] = _decode_evidence(result["evidence"])
    return result


def _next_commit_seq(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM meta WHERE key = 'commit_seq'").fetchone()
    current = int(row["value"]) if row else 0
    next_seq = current + 1
    conn.execute(
        "INSERT INTO meta(key, value) VALUES('commit_seq', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(next_seq),),
    )
    return next_seq


def _validate_choice(field: str, value: str, allowed: set[str]) -> None:
    if value not in allowed:
        allowed_text = ", ".join(sorted(allowed))
        raise ValueError(f"invalid {field}: {value!r}; expected one of: {allowed_text}")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _redact_text(value: str) -> str:
    return redact(value.encode("utf-8")).data.decode("utf-8", errors="replace")


def _redact_json(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return redact(encoded).data.decode("utf-8", errors="replace")


def _decode_evidence(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


if __name__ == "__main__":  # pragma: no cover
    print("Use the omni CLI.", file=sys.stderr)
