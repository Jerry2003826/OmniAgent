from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

from omni import db
from omni import gate
from omni import hook
from omni import ingest
from omni import store


EXPECTED_TABLES = {
    "artifacts",
    "block_deps",
    "blocks",
    "events",
    "experience_candidates",
    "experience_notes",
    "failure_candidates",
    "fact_candidates",
    "facts",
    "meta",
    "outcomes",
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


def test_connect_readonly_sets_busy_timeout(tmp_path: Path) -> None:
    setup = db.connect(tmp_path / ".omni" / "omni.sqlite3")
    db.migrate(setup)
    setup.close()

    readonly = db.connect_readonly(tmp_path / ".omni" / "omni.sqlite3")
    try:
        assert readonly.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    finally:
        readonly.close()


def test_migration_creates_schema_and_seed_meta(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")

    db.migrate(conn)

    assert table_names(conn) == EXPECTED_TABLES
    assert dict(conn.execute("SELECT key, value FROM meta")) == {
        "schema_version": "5",
        "commit_seq": "0",
        "redaction_ver": "1",
    }
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    event_indexes = conn.execute("PRAGMA index_list(events)").fetchall()
    for index in event_indexes:
        if not index["unique"]:
            continue
        columns = [
            row["name"]
            for row in conn.execute(f"PRAGMA index_info({index['name']})").fetchall()
        ]
        assert columns != ["run_id", "seq"]


def test_migration_is_idempotent(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")

    db.migrate(conn)
    db.migrate(conn)

    assert table_names(conn) == EXPECTED_TABLES
    assert conn.execute("SELECT COUNT(*) FROM meta").fetchone()[0] == 3


def test_migration_002_adds_outcomes_to_existing_schema_1_database(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")
    conn.executescript(db.migration_sql("001_init.sql"))
    conn.commit()

    db.migrate(conn)

    assert "outcomes" in table_names(conn)
    assert conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0] == "5"
    indexes = conn.execute("PRAGMA index_list(outcomes)").fetchall()
    assert any(index["name"] == "uq_outcomes_run_id" and index["unique"] for index in indexes)
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_migration_003_adds_experience_candidates_to_existing_schema_2_database(
    tmp_path: Path,
) -> None:
    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")
    conn.executescript(db.migration_sql("001_init.sql"))
    conn.executescript(db.migration_sql("002_outcomes.sql"))
    conn.commit()

    db.migrate(conn)

    assert "experience_candidates" in table_names(conn)
    assert conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0] == "5"
    indexes = conn.execute("PRAGMA index_list(experience_candidates)").fetchall()
    index_names = {index["name"] for index in indexes}
    assert {
        "idx_experience_candidates_state",
        "idx_experience_candidates_run_id",
        "idx_experience_candidates_kind",
    }.issubset(index_names)
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_migration_004_adds_experience_notes_to_existing_schema_3_database(
    tmp_path: Path,
) -> None:
    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")
    conn.executescript(db.migration_sql("001_init.sql"))
    conn.executescript(db.migration_sql("002_outcomes.sql"))
    conn.executescript(db.migration_sql("003_experience_candidates.sql"))
    conn.commit()

    db.migrate(conn)

    assert "experience_notes" in table_names(conn)
    assert conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0] == "5"
    indexes = conn.execute("PRAGMA index_list(experience_notes)").fetchall()
    index_names = {index["name"] for index in indexes}
    assert {
        "idx_experience_notes_scope",
        "uq_experience_notes_active_source",
    }.issubset(index_names)
    assert any(
        index["name"] == "uq_experience_notes_active_source" and index["unique"]
        for index in indexes
    )
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_migration_005_adds_failure_candidates_to_existing_schema_4_database(
    tmp_path: Path,
) -> None:
    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")
    conn.executescript(db.migration_sql("001_init.sql"))
    conn.executescript(db.migration_sql("002_outcomes.sql"))
    conn.executescript(db.migration_sql("003_experience_candidates.sql"))
    conn.executescript(db.migration_sql("004_experience_notes.sql"))
    conn.commit()

    db.migrate(conn)

    assert "failure_candidates" in table_names(conn)
    assert conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0] == "5"
    indexes = conn.execute("PRAGMA index_list(failure_candidates)").fetchall()
    index_names = {index["name"] for index in indexes}
    assert {
        "idx_failure_candidates_state",
        "idx_failure_candidates_run",
        "idx_failure_candidates_signature",
        "uq_failure_candidate_run_signature",
    }.issubset(index_names)
    assert any(
        index["name"] == "uq_failure_candidate_run_signature" and index["unique"]
        for index in indexes
    )
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_failed_migration_rolls_back_completely_and_can_retry(
    tmp_path: Path, monkeypatch
) -> None:
    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")
    db.migrate(conn)
    original_migration_sql = db.migration_sql
    probe_sql = {
        "sql": (
            "CREATE TABLE migration_probe(x TEXT);\n"
            "INSERT INTO missing_table VALUES(1);\n"
            "UPDATE meta SET value = '6' WHERE key = 'schema_version';\n"
        )
    }

    def fake_migration_sql(filename: str) -> str:
        if filename == "006_probe.sql":
            return probe_sql["sql"]
        return original_migration_sql(filename)

    monkeypatch.setattr(db, "MIGRATIONS", db.MIGRATIONS + (("6", "006_probe.sql"),))
    monkeypatch.setattr(db, "LATEST_SCHEMA_VERSION", "6")
    monkeypatch.setattr(db, "migration_sql", fake_migration_sql)

    with pytest.raises(sqlite3.OperationalError):
        db.migrate(conn)

    assert (
        conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0]
        == "5"
    )
    assert "migration_probe" not in table_names(conn)

    probe_sql["sql"] = (
        "CREATE TABLE migration_probe(x TEXT);\n"
        "UPDATE meta SET value = '6' WHERE key = 'schema_version';\n"
    )
    db.migrate(conn)

    assert (
        conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0]
        == "6"
    )
    assert "migration_probe" in table_names(conn)


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


def test_put_artifact_does_not_commit_open_transaction(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")
    db.migrate(conn)

    conn.execute("BEGIN")
    artifact = store.put_artifact(
        tmp_path,
        conn,
        kind="transcript_archive",
        data=b'{"event":"unknown"}\n',
    )
    conn.rollback()

    assert artifact.path.exists()
    assert conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 0


def test_put_artifact_writes_content_through_temp_file(
    tmp_path: Path, monkeypatch
) -> None:
    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")
    db.migrate(conn)
    original_write_bytes = Path.write_bytes

    def fail_direct_artifact_write(self: Path, data: bytes) -> int:
        if ".omni" in self.parts and "artifacts" in self.parts and not self.name.endswith(".tmp"):
            raise AssertionError("artifact content must be replaced from a temp file")
        return original_write_bytes(self, data)

    monkeypatch.setattr(Path, "write_bytes", fail_direct_artifact_write)

    artifact = store.put_artifact(
        tmp_path,
        conn,
        kind="transcript_event",
        data=b'{"event":"tool_use"}\n',
    )

    assert artifact.path.exists()
    assert artifact.path.read_bytes() == b'{"event":"tool_use"}\n'


def test_ingest_transcript_is_idempotent_and_redacts_db_content(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("OMNI_INGEST_SECRET", "ingest-secret-value-123")
    github_secret = "ghp_" + "abcdefghijklmnopqrstuvwxyz1234567890"
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "type": "tool_use",
                "timestamp": "2026-06-11T00:00:00Z",
                "id": github_secret,
                "name": f"token={github_secret}",
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
    event = conn.execute(
        "SELECT source, tool, tool_use_id, redaction_status, meta, input_ref FROM events"
    ).fetchone()
    assert event["source"] == "transcript"
    assert github_secret not in event["tool"]
    assert github_secret not in event["tool_use_id"]
    assert "REDACTED:" in event["tool"]
    assert "REDACTED:" in event["tool_use_id"]
    assert event["redaction_status"] == "redacted"
    assert "ingest-secret-value-123" not in event["meta"]
    assert "REDACTED:" in event["meta"]
    assert event["input_ref"]
    omni_bytes = b"".join(
        path.read_bytes() for path in (tmp_path / ".omni").rglob("*") if path.is_file()
    )
    assert b"ingest-secret-value-123" not in omni_bytes
    assert github_secret.encode("utf-8") not in omni_bytes


def test_ingest_stores_transcript_archive_artifact_for_unknown_lines(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("OMNI_ARCHIVE_SECRET", "archive-secret-value-123")
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        '{"type":"tool_use","timestamp":"2026-06-11T00:00:00Z","id":"toolu_1","name":"Bash"}\n'
        "not-json archive-secret-value-123\n",
        encoding="utf-8",
    )

    ingest.ingest(root=tmp_path, run_id="run_archive", transcript=transcript)
    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")
    archive = conn.execute(
        "SELECT hash, kind, line_count FROM artifacts WHERE kind = 'transcript_archive'"
    ).fetchone()

    assert dict(archive) == {
        "hash": archive["hash"],
        "kind": "transcript_archive",
        "line_count": 1,
    }
    archive_path = (
        tmp_path
        / ".omni"
        / "artifacts"
        / archive["hash"][7:9]
        / archive["hash"][9:11]
        / archive["hash"]
    )
    archive_text = archive_path.read_text(encoding="utf-8")
    assert "archive-secret-value-123" not in archive_text
    assert "REDACTED:env:" in archive_text


def test_ingest_reconciles_hook_and_transcript_by_tool_use_id(tmp_path: Path) -> None:
    hook.capture_hook(
        b'{"hook_event_name":"PreToolUse","timestamp":"2026-06-11T00:00:00Z",'
        b'"session_id":"run_reconciled","tool_use_id":"toolu_1","tool":"Bash"}',
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


def test_ingest_redacts_secret_hook_tool_use_id_and_reconciles_transcript(
    tmp_path: Path,
) -> None:
    secret = "ghp_" + "abcdefghijklmnopqrstuvwxyz1234567890"
    hook.capture_hook(
        json.dumps(
            {
                "hook_event_name": "PostToolUse",
                "session_id": "run_secret_id",
                "timestamp": "2026-06-11T00:00:00Z",
                "tool_use_id": secret,
                "tool": "Bash",
            }
        ).encode("utf-8"),
        root=tmp_path,
    )
    transcript = tmp_path / "secret-id.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "type": "tool_use",
                "timestamp": "2026-06-11T00:00:01Z",
                "id": secret,
                "name": "Bash",
                "exit_code": 0,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    ingest.ingest(root=tmp_path, run_id="run_secret_id", transcript=transcript)
    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")
    rows = conn.execute(
        """
        SELECT source, tool_use_id, redaction_status
        FROM events
        WHERE run_id = 'run_secret_id'
        """
    ).fetchall()
    omni_bytes = b"".join(
        path.read_bytes() for path in (tmp_path / ".omni").rglob("*") if path.is_file()
    )

    assert len(rows) == 1
    assert rows[0]["source"] == "reconciled"
    assert secret not in rows[0]["tool_use_id"]
    assert "REDACTED:" in rows[0]["tool_use_id"]
    assert rows[0]["redaction_status"] == "redacted"
    assert secret.encode("utf-8") not in omni_bytes


def test_ingest_preserves_distinct_event_types_with_same_tool_use_id(
    tmp_path: Path,
) -> None:
    hook.capture_hook(
        b'{"hook_event_name":"PostToolUse","timestamp":"2026-06-11T00:00:00Z",'
        b'"session_id":"run_multi","tool_use_id":"toolu_multi","tool":"Bash"}',
        root=tmp_path,
    )
    hook_only = ingest.ingest(root=tmp_path, run_id="run_multi")
    transcript = tmp_path / "multi.jsonl"
    transcript.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "tool_use",
                        "timestamp": "2026-06-11T00:00:01Z",
                        "id": "toolu_multi",
                        "name": "Bash",
                    }
                ),
                json.dumps(
                    {
                        "type": "tool_result",
                        "timestamp": "2026-06-11T00:00:02Z",
                        "tool_use_id": "toolu_multi",
                        "tool": "Bash",
                        "exit_code": 0,
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    ingest.ingest(root=tmp_path, run_id="run_multi", transcript=transcript)
    ingest.ingest(root=tmp_path, run_id="run_multi", transcript=transcript)
    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")
    rows = conn.execute(
        """
        SELECT seq, event_type, source, tool_use_id
        FROM events
        WHERE run_id = 'run_multi'
        ORDER BY seq
        """
    ).fetchall()

    assert hook_only.events_inserted == 1
    assert [row["event_type"] for row in rows] == ["tool_use", "tool_result"]
    assert [row["source"] for row in rows] == ["transcript", "transcript"]
    assert [row["seq"] for row in rows] == [1, 2]


def test_ingest_preserves_pre_and_post_transcript_events_with_same_tool_use_id(
    tmp_path: Path,
) -> None:
    transcript = tmp_path / "pre-post.jsonl"
    transcript.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "PreToolUse",
                        "timestamp": "2026-06-11T00:00:00Z",
                        "tool_use_id": "toolu_prepost",
                        "tool": "Bash",
                    }
                ),
                json.dumps(
                    {
                        "type": "PostToolUse",
                        "timestamp": "2026-06-11T00:00:01Z",
                        "tool_use_id": "toolu_prepost",
                        "tool": "Bash",
                        "exit_code": 0,
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    ingest.ingest(root=tmp_path, run_id="run_prepost", transcript=transcript)
    ingest.ingest(root=tmp_path, run_id="run_prepost", transcript=transcript)
    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")
    rows = conn.execute(
        """
        SELECT seq, event_type, source, tool_use_id
        FROM events
        WHERE run_id = 'run_prepost'
        ORDER BY seq
        """
    ).fetchall()

    assert [(row["seq"], row["event_type"], row["source"]) for row in rows] == [
        (1, "PreToolUse", "transcript"),
        (2, "PostToolUse", "transcript"),
    ]
    assert {row["tool_use_id"] for row in rows} == {"toolu_prepost"}


def test_ingest_later_transcript_event_is_not_dropped_after_hook_only_ingest(
    tmp_path: Path,
) -> None:
    hook.capture_hook(
        b'{"hook_event_name":"PostToolUse","timestamp":"2026-06-11T00:00:00Z",'
        b'"session_id":"run_delayed","tool_use_id":"toolu_delayed","tool":"Bash"}',
        root=tmp_path,
    )

    hook_only = ingest.ingest(root=tmp_path, run_id="run_delayed")
    for path in (tmp_path / ".omni" / "spool").glob("hook-*.jsonl"):
        path.unlink()
    transcript = tmp_path / "delayed.jsonl"
    transcript.write_text(
        '{"type":"tool_use","timestamp":"2026-06-11T00:00:01Z",'
        '"id":"toolu_delayed","name":"Bash","exit_code":0}\n',
        encoding="utf-8",
    )
    with_transcript = ingest.ingest(
        root=tmp_path, run_id="run_delayed", transcript=transcript
    )
    repeated = ingest.ingest(root=tmp_path, run_id="run_delayed", transcript=transcript)

    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")
    rows = conn.execute(
        """
        SELECT seq, event_id, source, tool_use_id
        FROM events
        WHERE run_id = 'run_delayed'
        ORDER BY seq
        """
    ).fetchall()
    show = ingest.run_show(tmp_path, "run_delayed")

    assert hook_only.events_inserted == 1
    assert repeated.events_inserted == 0
    assert [row["seq"] for row in rows] == [1]
    assert [row["source"] for row in rows] == ["transcript"]
    assert len({row["event_id"] for row in rows}) == 1
    assert show.count("toolu_delayed") == 0
    assert "1 | 2026-06-11T00:00:01Z | tool_use | Bash | 0 |" in show


def test_ingest_calculates_hook_duration_when_possible(tmp_path: Path) -> None:
    hook.capture_hook(
        b'{"hook_event_name":"PreToolUse","timestamp":"2026-06-11T00:00:00Z",'
        b'"session_id":"run_hooks","tool_use_id":"toolu_2","tool":"Bash"}',
        root=tmp_path,
    )
    hook.capture_hook(
        b'{"hook_event_name":"PostToolUse","timestamp":"2026-06-11T00:00:02Z",'
        b'"session_id":"run_hooks","tool_use_id":"toolu_2","tool":"Bash","exit_code":0}',
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


def test_successful_ingest_moves_consumed_hook_spool_files_to_processed(
    tmp_path: Path,
) -> None:
    hook.capture_hook(
        b'{"hook_event_name":"PostToolUse","timestamp":"2026-06-11T00:00:00Z",'
        b'"session_id":"run_spool","tool_use_id":"toolu_spool","tool":"Bash"}',
        root=tmp_path,
    )

    first = ingest.ingest(root=tmp_path, run_id="run_spool")
    second = ingest.ingest(root=tmp_path, run_id="manual_after_spool")
    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")

    assert first.events_inserted == 1
    assert second.events_inserted == 0
    assert not list((tmp_path / ".omni" / "spool").glob("hook-*.jsonl"))
    assert len(list((tmp_path / ".omni" / "spool" / "processed").glob("hook-*.jsonl"))) == 1
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1


def test_empty_queue_ingest_without_run_id_does_not_consume_live_hook_spool(
    tmp_path: Path,
) -> None:
    hook.capture_hook(
        b'{"hook_event_name":"PostToolUse","timestamp":"2026-06-11T00:00:00Z",'
        b'"session_id":"s-live","tool_use_id":"toolu_live","tool":"Bash"}',
        root=tmp_path,
    )
    hook_file = next((tmp_path / ".omni" / "spool").glob("hook-*.jsonl"))

    result = ingest.ingest(root=tmp_path)
    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")

    assert result.run_ids == ()
    assert result.events_inserted == 0
    assert hook_file.exists()
    assert not list((tmp_path / ".omni" / "spool" / "processed").glob("hook-*.jsonl"))
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0


def test_ingest_prunes_old_processed_hook_records(tmp_path: Path) -> None:
    processed = tmp_path / ".omni" / "spool" / "processed"
    processed.mkdir(parents=True)
    old = processed / "hook-old.jsonl"
    old.write_text("{}\n", encoding="utf-8")
    os.utime(old, (1, 1))

    result = ingest.ingest(root=tmp_path)

    assert result.events_inserted == 0
    assert not old.exists()


def test_explicit_hook_recovery_scopes_hook_events_to_run_id(tmp_path: Path) -> None:
    for session_id, tool_use_id in (("session_a", "toolu_a"), ("session_b", "toolu_b")):
        hook.capture_hook(
            json.dumps(
                {
                    "hook_event_name": "PostToolUse",
                    "session_id": session_id,
                    "timestamp": "2026-06-11T00:00:00Z",
                    "tool_use_id": tool_use_id,
                    "tool": "Bash",
                }
            ).encode("utf-8"),
            root=tmp_path,
        )

    result = ingest.ingest(root=tmp_path, run_id="session_a")
    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")
    rows = conn.execute(
        "SELECT run_id, tool_use_id FROM events ORDER BY tool_use_id"
    ).fetchall()

    assert result.run_ids == ("session_a",)
    assert result.events_inserted == 1
    assert [(row["run_id"], row["tool_use_id"]) for row in rows] == [
        ("session_a", "toolu_a")
    ]
    assert len(list((tmp_path / ".omni" / "spool").glob("hook-*.jsonl"))) == 1
    assert len(list((tmp_path / ".omni" / "spool" / "processed").glob("hook-*.jsonl"))) == 1


def test_manual_transcript_ingest_does_not_consume_unrelated_queued_hook_spool(
    tmp_path: Path,
) -> None:
    hook.capture_hook(
        json.dumps(
            {
                "hook_event_name": "PostToolUse",
                "session_id": "session_a",
                "timestamp": "2026-06-11T00:00:00Z",
                "tool_use_id": "toolu_a",
                "tool": "Bash",
            }
        ).encode("utf-8"),
        root=tmp_path,
    )
    hook.capture_hook(
        json.dumps(
            {
                "hook_event_name": "SessionEnd",
                "session_id": "session_a",
                "transcript_path": None,
            }
        ).encode("utf-8"),
        root=tmp_path,
    )
    manual_transcript = tmp_path / "manual.jsonl"
    manual_transcript.write_text(
        '{"type":"tool_use","id":"toolu_b","timestamp":"2026-06-11T00:00:01Z"}\n',
        encoding="utf-8",
    )

    manual = ingest.ingest(
        root=tmp_path,
        run_id="manual_b",
        transcript=manual_transcript,
    )
    queued = ingest.ingest(root=tmp_path)
    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")
    rows = conn.execute(
        """
        SELECT run_id, tool_use_id FROM events
        WHERE tool_use_id IS NOT NULL
        ORDER BY run_id, tool_use_id
        """
    ).fetchall()

    assert manual.events_inserted == 1
    assert queued.run_ids == ("session_a",)
    assert [(row["run_id"], row["tool_use_id"]) for row in rows] == [
        ("manual_b", "toolu_b"),
        ("session_a", "toolu_a"),
    ]
    assert not list((tmp_path / ".omni" / "spool").glob("hook-*.jsonl"))
    assert len(list((tmp_path / ".omni" / "spool" / "processed").glob("hook-*.jsonl"))) == 2


def test_manual_transcript_without_run_id_does_not_scan_hook_spool(
    tmp_path: Path, monkeypatch
) -> None:
    transcript = tmp_path / "manual.jsonl"
    transcript.write_text(
        '{"type":"tool_use","id":"toolu_manual","timestamp":"2026-06-11T00:00:00Z"}\n',
        encoding="utf-8",
    )

    def fail_hook_scan(*_args, **_kwargs):
        raise AssertionError("unscoped manual transcript ingest must not scan hook spool")

    monkeypatch.setattr(ingest, "_hook_candidates", fail_hook_scan)

    result = ingest.ingest(root=tmp_path, transcript=transcript)
    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")
    rows = conn.execute("SELECT run_id, tool_use_id, source FROM events").fetchall()

    assert result.events_inserted == 1
    assert len(result.run_ids) == 1
    assert [row["tool_use_id"] for row in rows] == ["toolu_manual"]
    assert [row["source"] for row in rows] == ["transcript"]


def test_ingest_preserves_transcript_order_when_timestamps_are_missing(
    tmp_path: Path,
) -> None:
    transcript = tmp_path / "missing-ts.jsonl"
    transcript.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "tool_use",
                        "id": "toolu_order",
                        "name": "Bash",
                    }
                ),
                json.dumps(
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_order",
                        "tool": "Bash",
                        "exit_code": 0,
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    ingest.ingest(root=tmp_path, run_id="run_order", transcript=transcript)
    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")
    rows = conn.execute(
        "SELECT seq, event_type FROM events WHERE run_id = 'run_order' ORDER BY seq"
    ).fetchall()

    assert [(row["seq"], row["event_type"]) for row in rows] == [
        (1, "tool_use"),
        (2, "tool_result"),
    ]


def test_resume_transcript_uses_uuid_when_mode_row_is_inserted_before_old_rows(
    tmp_path: Path,
) -> None:
    transcript = tmp_path / "resume.jsonl"
    original_rows = [
        _claude_assistant_row("msg-old-1", "2026-06-12T00:00:00Z", "first"),
        _claude_user_row("msg-old-2", "2026-06-12T00:00:01Z", "second"),
    ]
    _write_transcript(transcript, original_rows)

    first = ingest.ingest(root=tmp_path, run_id="run_resume", transcript=transcript)
    _write_transcript(transcript, [_claude_mode_row(), *original_rows])
    second = ingest.ingest(root=tmp_path, run_id="run_resume", transcript=transcript)

    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")
    rows = conn.execute(
        """
        SELECT event_type, meta
        FROM events
        WHERE run_id = 'run_resume'
        ORDER BY seq
        """
    ).fetchall()
    uuids = [
        json.loads(row["meta"]).get("uuid")
        for row in rows
        if json.loads(row["meta"]).get("uuid")
    ]

    assert first.events_inserted == 2
    assert second.events_inserted == 1
    assert [row["event_type"] for row in rows] == ["assistant", "user", "mode"]
    assert sorted(uuids) == ["msg-old-1", "msg-old-2"]


def test_resume_transcript_uses_uuid_when_old_timestamps_are_rewritten(
    tmp_path: Path,
) -> None:
    transcript = tmp_path / "resume-rewritten-ts.jsonl"
    _write_transcript(
        transcript,
        [
            _claude_assistant_row("msg-stable-1", "2026-06-12T00:00:00Z", "first"),
            _claude_user_row("msg-stable-2", "2026-06-12T00:00:01Z", "second"),
        ],
    )

    first = ingest.ingest(root=tmp_path, run_id="run_rewritten_ts", transcript=transcript)
    _write_transcript(
        transcript,
        [
            _claude_assistant_row("msg-stable-1", "2026-06-12T01:00:00Z", "first"),
            _claude_user_row("msg-stable-2", "2026-06-12T01:00:01Z", "second"),
        ],
    )
    second = ingest.ingest(root=tmp_path, run_id="run_rewritten_ts", transcript=transcript)

    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")
    count = conn.execute(
        "SELECT COUNT(*) FROM events WHERE run_id = 'run_rewritten_ts'"
    ).fetchone()[0]

    assert first.events_inserted == 2
    assert second.events_inserted == 0
    assert count == 2


def test_transcript_rows_without_uuid_keep_existing_fallback_identity(
    tmp_path: Path,
) -> None:
    transcript = tmp_path / "mode-only.jsonl"
    _write_transcript(transcript, [_claude_mode_row()])

    first = ingest.ingest(root=tmp_path, run_id="run_mode", transcript=transcript)
    second = ingest.ingest(root=tmp_path, run_id="run_mode", transcript=transcript)

    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")
    row = conn.execute(
        "SELECT event_type, meta FROM events WHERE run_id = 'run_mode'"
    ).fetchone()

    assert first.events_inserted == 1
    assert second.events_inserted == 0
    assert row["event_type"] == "mode"
    assert json.loads(row["meta"]) == {"mode": "default", "sessionId": "session-resume"}


def _write_transcript(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )


def _claude_assistant_row(uuid: str, timestamp: str, text: str) -> dict[str, object]:
    return {
        "type": "assistant",
        "timestamp": timestamp,
        "uuid": uuid,
        "parentUuid": None,
        "sessionId": "session-resume",
        "cwd": "C:\\sandbox",
        "gitBranch": "master",
        "isSidechain": False,
        "userType": "external",
        "version": "2.1.173",
        "entrypoint": "cli",
        "message": {
            "id": f"msg-{uuid}",
            "type": "message",
            "role": "assistant",
            "model": "claude-test",
            "content": [{"type": "text", "text": text}],
            "stop_details": None,
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {},
        },
    }


def _claude_user_row(uuid: str, timestamp: str, text: str) -> dict[str, object]:
    return {
        "type": "user",
        "timestamp": timestamp,
        "uuid": uuid,
        "parentUuid": None,
        "sessionId": "session-resume",
        "cwd": "C:\\sandbox",
        "gitBranch": "master",
        "isSidechain": False,
        "userType": "external",
        "version": "2.1.173",
        "entrypoint": "cli",
        "permissionMode": "bypassPermissions",
        "promptId": "prompt-resume",
        "promptSource": "user",
        "sourceToolAssistantUUID": None,
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
    }


def _claude_mode_row() -> dict[str, object]:
    return {
        "type": "mode",
        "sessionId": "session-resume",
        "mode": "default",
    }


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
    queue_files = sorted((tmp_path / ".omni" / "spool").glob("ingest-*.json"))
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
    assert queue_files == []
    assert closed >= 1
    assert dict(stale) == {"status": "closed", "end_reason": "watchdog"}


def test_watchdog_closes_open_runs_with_missing_transcripts(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")
    db.migrate(conn)
    missing = tmp_path / "missing-transcript.jsonl"
    conn.execute(
        "INSERT INTO runs(run_id, project_id, snapshot_seq, transcript_path, status) VALUES(?,?,?,?,?)",
        ("missing_run", "project", 0, str(missing), "open"),
    )
    conn.commit()

    closed = ingest.close_stale_runs(conn, older_than_seconds=0, now_ts=10)
    row = conn.execute(
        "SELECT status, end_reason FROM runs WHERE run_id = 'missing_run'"
    ).fetchone()

    assert closed == 1
    assert dict(row) == {"status": "closed", "end_reason": "watchdog"}


def test_ingest_runs_watchdog_for_stale_open_runs(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")
    db.migrate(conn)
    missing = tmp_path / "missing-transcript.jsonl"
    conn.execute(
        "INSERT INTO runs(run_id, project_id, snapshot_seq, transcript_path, status) VALUES(?,?,?,?,?)",
        ("missing_run", "project", 0, str(missing), "open"),
    )
    conn.commit()
    conn.close()

    result = ingest.ingest(root=tmp_path)

    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")
    row = conn.execute(
        "SELECT status, end_reason FROM runs WHERE run_id = 'missing_run'"
    ).fetchone()
    assert result.events_inserted == 0
    assert dict(row) == {"status": "closed", "end_reason": "watchdog"}


def test_queued_ingest_keeps_request_file_when_transaction_fails(
    tmp_path: Path, monkeypatch
) -> None:
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
    request_file = next((tmp_path / ".omni" / "spool").glob("ingest-*.json"))

    def fail_static_extractors(*_args, **_kwargs) -> None:
        raise RuntimeError("static extractor failed")

    monkeypatch.setattr(ingest.gate, "extract_static_facts", fail_static_extractors)

    with pytest.raises(RuntimeError, match="static extractor failed"):
        ingest.ingest(root=tmp_path)

    assert request_file.exists()


def test_queued_ingest_survives_malformed_static_extractor_inputs_and_acks_request(
    tmp_path: Path,
) -> None:
    transcript = tmp_path / "queued.jsonl"
    transcript.write_text(
        '{"type":"tool_use","id":"toolu_q","timestamp":"2026-06-11T00:00:00Z"}\n',
        encoding="utf-8",
    )
    (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project\n", encoding="utf-8")
    (tmp_path / "Makefile").write_bytes(b"\xff\xfe\x00")
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
    request_file = next((tmp_path / ".omni" / "spool").glob("ingest-*.json"))

    result = ingest.ingest(root=tmp_path)
    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")

    assert result.events_inserted >= 1
    assert not request_file.exists()
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM events WHERE run_id = ? AND tool_use_id = ?",
            ("queued_run", "toolu_q"),
        ).fetchone()[0]
        == 1
    )
    assert conn.execute("SELECT COUNT(*) FROM fact_candidates").fetchone()[0] == 0


def test_ingest_static_fact_failure_rolls_back_partial_database_work(
    tmp_path: Path, monkeypatch
) -> None:
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        '{"type":"tool_use","id":"toolu_txn","timestamp":"2026-06-11T00:00:00Z"}\n',
        encoding="utf-8",
    )

    def fail_after_staging(_root: Path, conn: sqlite3.Connection, *, commit: bool = True):
        gate.apply_candidates(conn, [gate.FactCandidate(
            scope="project",
            subject=".",
            predicate="uses_test_command",
            qualifier="node",
            object_norm="pytest",
            value_type="string",
            claim="Use pytest",
            trust=1,
            sensitivity="low",
            origin="manual@1",
            evidence={"files": []},
        )], commit=commit)
        raise RuntimeError("static extraction failed")

    monkeypatch.setattr(ingest.gate, "extract_static_facts", fail_after_staging)

    with pytest.raises(RuntimeError, match="static extraction failed"):
        ingest.ingest(root=tmp_path, run_id="run_txn", transcript=transcript)

    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")
    assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM fact_candidates").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 0


def test_queued_ingest_scopes_hook_events_to_session_id(tmp_path: Path) -> None:
    for session_id, tool_use_id, command in (
        ("session_a", "toolu_a", "pnpm run test"),
        ("session_b", "toolu_b", "pnpm run build"),
    ):
        hook.capture_hook(
            json.dumps(
                {
                    "hook_event_name": "PostToolUse",
                    "session_id": session_id,
                    "timestamp": f"2026-06-11T00:00:0{1 if session_id == 'session_a' else 2}Z",
                    "tool_use_id": tool_use_id,
                    "tool": "Bash",
                    "tool_input": {"command": command},
                }
            ).encode("utf-8"),
            root=tmp_path,
        )
        hook.capture_hook(
            json.dumps(
                {
                    "hook_event_name": "SessionEnd",
                    "session_id": session_id,
                    "transcript_path": None,
                }
            ).encode("utf-8"),
            root=tmp_path,
        )

    result = ingest.ingest(root=tmp_path)
    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")
    rows = conn.execute(
        "SELECT run_id, tool_use_id, meta FROM events WHERE tool_use_id IS NOT NULL ORDER BY run_id"
    ).fetchall()

    assert result.run_ids == ("session_a", "session_b")
    assert [(row["run_id"], row["tool_use_id"]) for row in rows] == [
        ("session_a", "toolu_a"),
        ("session_b", "toolu_b"),
    ]
