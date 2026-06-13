"""User-marked outcome log for ingested runs."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from omni import db
from omni import eval as behavior_eval
from omni import verify
from omni.ids import new_id
from omni.redact import redact

STATUS_VALUES = {"success", "failed", "unknown"}
TESTS_STATUS_VALUES = {"passed", "failed", "not_run", "unknown"}
MEMORY_EFFECT_VALUES = {"helped", "neutral", "failed_to_help", "unknown"}
TASK_TYPE_VALUES = {"validation", "bugfix", "docs", "refactor", "exploration", "unknown"}


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
    _ensure_run_exists(conn, run_id)
    _validate_choice("status", status, STATUS_VALUES)
    _validate_choice("tests_status", tests_status, TESTS_STATUS_VALUES)
    _validate_choice("task_type", task_type, TASK_TYPE_VALUES)
    if memory_effect is None:
        memory_effect = _memory_effect_from_eval(conn, run_id)
    _validate_choice("memory_effect", memory_effect, MEMORY_EFFECT_VALUES)

    existing = conn.execute(
        "SELECT outcome_id, created_at FROM outcomes WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    now = _now()
    evidence_json = _evidence_json(evidence or {"source": "user", "run_id": run_id})
    values = {
        "run_id": run_id,
        "task_type": task_type,
        "status": status,
        "tests_status": tests_status,
        "memory_effect": memory_effect,
        "task_summary": _redact_text(task_summary),
        "final_command": _redact_text(final_command),
        "note": _redact_text(note),
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
) -> dict[str, Any]:
    _ensure_run_exists(conn, run_id)
    _validate_choice("status", status, STATUS_VALUES)
    _validate_choice("task_type", task_type, TASK_TYPE_VALUES)
    if memory_effect is not None:
        _validate_choice("memory_effect", memory_effect, MEMORY_EFFECT_VALUES)

    verify_result = verify.run_preflight(
        conn,
        root,
        timeout_seconds=timeout_seconds,
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


def as_json(value: dict[str, Any]) -> str:
    return behavior_eval.as_json(value)


def _ensure_run_exists(conn: sqlite3.Connection, run_id: str) -> None:
    row = conn.execute("SELECT 1 FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        raise ValueError(f"unknown run: {run_id}")


def _validate_choice(name: str, value: str, allowed: set[str]) -> None:
    if value not in allowed:
        allowed_text = ", ".join(sorted(allowed))
        raise ValueError(f"invalid {name}: {value}; expected one of: {allowed_text}")


def _redact_text(value: str | None) -> str | None:
    if value is None:
        return None
    return redact(value.encode("utf-8")).data.decode("utf-8", errors="replace")


def _redact_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _redact_json(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_redact_json(child) for child in value]
    if isinstance(value, str):
        return _redact_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _redact_text(str(value))


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
    root = _root_from_connection(conn)
    if root is None:
        return "unknown"
    try:
        result = behavior_eval.evaluate_run(root, run_id)
    except Exception:
        return "unknown"
    effect = result.get("memory_effect")
    return effect if isinstance(effect, str) and effect in MEMORY_EFFECT_VALUES else "unknown"


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


def _tests_status_from_verify(verify_result: dict[str, Any]) -> str:
    status = verify_result.get("status")
    if status == "passed":
        return "passed"
    if status == "failed":
        if isinstance(verify_result.get("exit_code"), int) or verify_result.get("timed_out") is True:
            return "failed"
        return "unknown"
    return "unknown"


def _verify_command(verify_result: dict[str, Any]) -> str | None:
    command = verify_result.get("command")
    return command if isinstance(command, str) and command else None


def _verify_evidence(verify_result: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "status",
        "command",
        "exit_code",
        "timed_out",
        "reason",
        "duration_ms",
        "timeout_seconds",
        "predicate",
        "qualifier",
    )
    return {key: verify_result[key] for key in keys if key in verify_result}
