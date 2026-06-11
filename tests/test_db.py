from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from omni import db
from omni import hook
from omni import ingest
from omni import store


EXPECTED_TABLES = {
    "artifacts",
    "block_deps",
    "blocks",
    "events",
    "fact_candidates",
    "facts",
    "meta",
    "runs",
    "suppressions",
}


def table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {row[0] for row in rows}


def test_connect_sets_required_pragmas(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")

    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_migration_creates_schema_and_seed_meta(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")

    db.migrate(conn)

    assert table_names(conn) == EXPECTED_TABLES
    assert dict(conn.execute("SELECT key, value FROM meta")) == {
        "schema_version": "1",
        "commit_seq": "0",
        "redaction_ver": "1",
    }
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_migration_is_idempotent(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")

    db.migrate(conn)
    db.migrate(conn)

    assert table_names(conn) == EXPECTED_TABLES
    assert conn.execute("SELECT COUNT(*) FROM meta").fetchone()[0] == 3


def test_migration_sql_does_not_set_pragmas() -> None:
    sql = db.migration_sql("001_init.sql")
    executable_sql = "\n".join(
        line for line in sql.splitlines() if not line.strip().startswith("--")
    )

    assert "PRAGMA journal_mode=WAL;" not in executable_sql
    assert "PRAGMA busy_timeout=5000;" not in executable_sql
    assert "PRAGMA foreign_keys=ON;" not in executable_sql


def test_content_addressed_artifact_store_redacts_and_deduplicates(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("OMNI_STORE_SECRET", "store-secret-value-123")
    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")
    db.migrate(conn)

    first = store.put_artifact(
        tmp_path,
        conn,
        kind="transcript_event",
        data=b'{"token":"store-secret-value-123"}\n',
    )
    second = store.put_artifact(
        tmp_path,
        conn,
        kind="transcript_event",
        data=b'{"token":"store-secret-value-123"}\n',
    )

    assert first.hash == second.hash
    assert first.path == second.path
    assert (
        first.path
        == tmp_path / ".omni" / "artifacts" / first.hash[7:9] / first.hash[9:11] / first.hash
    )
    assert first.path.read_bytes() == second.path.read_bytes()
    assert b"store-secret-value-123" not in first.path.read_bytes()
    assert b"REDACTED:env:" in first.path.read_bytes()
    assert conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 1


def test_ingest_transcript_is_idempotent_and_redacts_db_content(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("OMNI_INGEST_SECRET", "ingest-secret-value-123")
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "type": "tool_use",
                "timestamp": "2026-06-11T00:00:00Z",
                "id": "toolu_1",
                "name": "Bash",
                "api_key": "ingest-secret-value-123",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    first = ingest.ingest(root=tmp_path, run_id="run_transcript", transcript=transcript)
    second = ingest.ingest(root=tmp_path, run_id="run_transcript", transcript=transcript)
    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")

    assert first.events_inserted == 1
    assert second.events_inserted == 0
    assert (
        conn.execute("SELECT COUNT(*) FROM runs WHERE run_id = 'run_transcript'").fetchone()[0]
        == 1
    )
    assert (
        conn.execute("SELECT COUNT(*) FROM events WHERE run_id = 'run_transcript'").fetchone()[0]
        == 1
    )
    event = conn.execute("SELECT source, meta, input_ref FROM events").fetchone()
    assert event["source"] == "transcript"
    assert "ingest-secret-value-123" not in event["meta"]
    assert "REDACTED:env:" in event["meta"]
    assert event["input_ref"]
    omni_bytes = b"".join(
        path.read_bytes() for path in (tmp_path / ".omni").rglob("*") if path.is_file()
    )
    assert b"ingest-secret-value-123" not in omni_bytes


def test_ingest_reconciles_hook_and_transcript_by_tool_use_id(tmp_path: Path) -> None:
    hook.capture_hook(
        b'{"hook_event_name":"PreToolUse","timestamp":"2026-06-11T00:00:00Z",'
        b'"tool_use_id":"toolu_1","tool":"Bash"}',
        root=tmp_path,
    )
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        '{"type":"tool_use","timestamp":"2026-06-11T00:00:01Z",'
        '"id":"toolu_1","name":"Bash","exit_code":0}\n',
        encoding="utf-8",
    )

    result = ingest.ingest(root=tmp_path, run_id="run_reconciled", transcript=transcript)
    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")
    rows = conn.execute(
        "SELECT event_type, tool, tool_use_id, source, exit_code FROM events WHERE run_id = ?",
        ("run_reconciled",),
    ).fetchall()

    assert result.events_inserted == 1
    assert [dict(row) for row in rows] == [
        {
            "event_type": "tool_use",
            "tool": "Bash",
            "tool_use_id": "toolu_1",
            "source": "reconciled",
            "exit_code": 0,
        }
    ]


def test_ingest_calculates_hook_duration_when_possible(tmp_path: Path) -> None:
    hook.capture_hook(
        b'{"hook_event_name":"PreToolUse","timestamp":"2026-06-11T00:00:00Z",'
        b'"tool_use_id":"toolu_2","tool":"Bash"}',
        root=tmp_path,
    )
    hook.capture_hook(
        b'{"hook_event_name":"PostToolUse","timestamp":"2026-06-11T00:00:02Z",'
        b'"tool_use_id":"toolu_2","tool":"Bash","exit_code":0}',
        root=tmp_path,
    )

    ingest.ingest(root=tmp_path, run_id="run_hooks")
    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")
    row = conn.execute(
        "SELECT event_type, source, duration_ms FROM events WHERE run_id = ? AND tool_use_id = ?",
        ("run_hooks", "toolu_2"),
    ).fetchone()

    assert row["event_type"] == "PostToolUse"
    assert row["source"] == "hook"
    assert row["duration_ms"] == 2000


def test_ingest_drains_queue_and_watchdog_closes_stale_open_runs(tmp_path: Path) -> None:
    transcript = tmp_path / "queued.jsonl"
    transcript.write_text(
        '{"type":"tool_use","id":"toolu_q","timestamp":"2026-06-11T00:00:00Z"}\n',
        encoding="utf-8",
    )
    hook.capture_hook(
        json.dumps(
            {
                "hook_event_name": "SessionEnd",
                "session_id": "queued_run",
                "transcript_path": "queued.jsonl",
            }
        ).encode("utf-8"),
        root=tmp_path,
    )

    queued = ingest.ingest(root=tmp_path)
    queue_path = tmp_path / ".omni" / "spool" / "ingest_queue.jsonl"
    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")
    conn.execute(
        "INSERT INTO runs(run_id, project_id, snapshot_seq, transcript_path, status) VALUES(?,?,?,?,?)",
        ("stale_run", "project", 0, str(transcript), "open"),
    )
    conn.commit()
    old_time = 1
    os.utime(transcript, (old_time, old_time))

    closed = ingest.close_stale_runs(conn, older_than_seconds=0, now_ts=10)
    stale = conn.execute(
        "SELECT status, end_reason FROM runs WHERE run_id = 'stale_run'"
    ).fetchone()

    assert queued.events_inserted >= 1
    assert conn.execute(
        "SELECT COUNT(*) FROM events WHERE run_id = ? AND tool_use_id = ?",
        ("queued_run", "toolu_q"),
    ).fetchone()[0] == 1
    assert queue_path.exists()
    assert queue_path.read_text(encoding="utf-8") == ""
    assert closed >= 1
    assert dict(stale) == {"status": "closed", "end_reason": "watchdog"}
