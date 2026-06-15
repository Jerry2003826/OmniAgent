from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from omni import db
from omni import ingest
from omni import outcome
from omni import task
from omni.dbaccess import connect_project_readonly
from omni.ids import project_id_for_path
from tests.leak_helpers import assert_no_metadata_leak


REPO_ROOT = Path(__file__).resolve().parents[1]


def run_omni(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", "omni.cli", *args],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def connect(tmp_path: Path) -> sqlite3.Connection:
    (tmp_path / ".omni").mkdir(parents=True, exist_ok=True)
    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")
    db.migrate(conn)
    return conn


def seed_run(conn: sqlite3.Connection, tmp_path: Path, run_id: str = "run_task_test") -> None:
    conn.execute(
        """
        INSERT INTO runs(run_id, project_id, snapshot_seq, status, started_at)
        VALUES(?,?,?,?,?)
        """,
        (run_id, project_id_for_path(tmp_path), 0, "closed", "2026-06-15T00:00:00Z"),
    )
    conn.commit()


def test_migration_008_creates_tasks_and_sets_schema_version(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    assert db.schema_version(conn) == "8"
    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    assert "tasks" in tables
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(runs)").fetchall()
    }
    assert "task_id" in columns
    indexes = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        ).fetchall()
    }
    assert "uq_tasks_one_open_per_project" in indexes
    conn.close()


def test_unique_index_blocks_second_open_task_row(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    started = task.start_task(conn, tmp_path, "first")
    project_id = project_id_for_path(tmp_path)
    now = "2026-06-15T00:00:00Z"
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO tasks(
              task_id, project_id, title, task_type, status, created_seq,
              created_at, updated_at, evidence
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                "task_duplicate_open",
                project_id,
                "second open",
                "unknown",
                "open",
                99,
                now,
                now,
                "{}",
            ),
        )
    conn.rollback()
    assert conn.execute(
        "SELECT COUNT(*) AS count FROM tasks WHERE project_id = ? AND status = 'open'",
        (project_id,),
    ).fetchone()["count"] == 1
    assert started["status"] == "open"
    conn.close()


def test_migration_007_to_008_preserves_existing_runs(tmp_path: Path) -> None:
    (tmp_path / ".omni").mkdir()
    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")
    for version, filename in db.MIGRATIONS:
        if int(version) > 7:
            break
        conn.executescript(f"BEGIN;\n{db.migration_sql(filename)}\nCOMMIT;")
    conn.commit()
    conn.execute(
        """
        INSERT INTO runs(run_id, project_id, snapshot_seq, status)
        VALUES('run_legacy', ?, 0, 'closed')
        """,
        (project_id_for_path(tmp_path),),
    )
    conn.commit()
    assert db.schema_version(conn) == "7"
    conn.close()

    conn = connect(tmp_path)
    row = conn.execute(
        "SELECT run_id, task_id FROM runs WHERE run_id = 'run_legacy'"
    ).fetchone()
    assert row is not None
    assert row["task_id"] is None
    assert db.schema_version(conn) == "8"
    conn.close()


def test_readonly_rejects_schema_version_7(tmp_path: Path) -> None:
    (tmp_path / ".omni").mkdir()
    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")
    for version, filename in db.MIGRATIONS:
        if int(version) > 7:
            break
        conn.executescript(f"BEGIN;\n{db.migration_sql(filename)}\nCOMMIT;")
    conn.commit()
    conn.close()

    with pytest.raises(ValueError, match="found 7, need 8"):
        connect_project_readonly(tmp_path)


def test_task_start_and_status(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    started = task.start_task(conn, tmp_path, "fix the flaky test", task_type="bugfix")
    assert started["status"] == "open"
    assert started["title"] == "fix the flaky test"
    status = task.task_status(conn, tmp_path)
    assert status["open"]["task_id"] == started["task_id"]
    assert status["attached_run_count"] == 0
    conn.close()


def test_double_start_is_refused(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    task.start_task(conn, tmp_path, "first intent")
    with pytest.raises(ValueError, match="open task already exists"):
        task.start_task(conn, tmp_path, "second intent")
    conn.close()


def test_ingest_attaches_run_to_open_task(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    started = task.start_task(conn, tmp_path, "attach run")
    ingest._ensure_run(conn, tmp_path, "run_attached", None)
    conn.commit()
    row = conn.execute(
        "SELECT task_id FROM runs WHERE run_id = 'run_attached'"
    ).fetchone()
    assert row["task_id"] == started["task_id"]
    conn.close()


def test_ingest_without_task_leaves_task_id_null(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    ingest._ensure_run(conn, tmp_path, "run_unattached", None)
    conn.commit()
    row = conn.execute(
        "SELECT task_id FROM runs WHERE run_id = 'run_unattached'"
    ).fetchone()
    assert row["task_id"] is None
    conn.close()


def test_close_task_records_outcome_on_representative_run(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    started = task.start_task(conn, tmp_path, "close me", task_type="validation")
    seed_run(conn, tmp_path, "run_close")
    conn.execute(
        "UPDATE runs SET task_id = ? WHERE run_id = 'run_close'",
        (started["task_id"],),
    )
    conn.commit()
    closed = task.close_task(conn, tmp_path, status="success")
    assert closed["status"] == "closed"
    assert closed["outcome_status"] == "success"
    outcome = conn.execute(
        "SELECT status FROM outcomes WHERE run_id = 'run_close'"
    ).fetchone()
    assert outcome["status"] == "success"
    assert task.current_task_id_for_ingest(conn) is None
    conn.close()


def test_close_without_runs_sets_not_run_tests_status(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    task.start_task(conn, tmp_path, "close empty")
    closed = task.close_task(conn, tmp_path, status="unknown")
    assert closed["tests_status"] == "not_run"
    assert closed["outcome_status"] == "unknown"
    conn.close()


def test_abandon_clears_current_task_pointer(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    task.start_task(conn, tmp_path, "give up")
    abandoned = task.abandon_task(conn, tmp_path, reason="blocked")
    assert abandoned["status"] == "abandoned"
    assert abandoned["closed_at"] is not None
    assert task.current_task_id_for_ingest(conn) is None
    conn.close()


def test_close_from_verify_without_runs_raises(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    task.start_task(conn, tmp_path, "empty verify close")
    with pytest.raises(ValueError, match="attached run"):
        task.close_task(conn, tmp_path, from_verify=True)
    row = conn.execute(
        "SELECT status FROM tasks WHERE status = 'open'"
    ).fetchone()
    assert row is not None
    conn.close()


def test_close_task_rolls_back_when_outcome_marking_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = connect(tmp_path)
    started = task.start_task(conn, tmp_path, "rollback close")
    seed_run(conn, tmp_path, "run_rollback")
    conn.execute(
        "UPDATE runs SET task_id = ? WHERE run_id = 'run_rollback'",
        (started["task_id"],),
    )
    conn.commit()

    def fail_mark(*args: object, **kwargs: object) -> dict[str, object]:
        raise ValueError("verify failed")

    monkeypatch.setattr(outcome, "mark_outcome_from_verify", fail_mark)

    with pytest.raises(ValueError, match="verify failed"):
        task.close_task(conn, tmp_path, status="failed", from_verify=True)

    task_row = conn.execute(
        "SELECT status FROM tasks WHERE task_id = ?",
        (started["task_id"],),
    ).fetchone()
    assert task_row["status"] == "open"
    assert (
        conn.execute(
            "SELECT 1 FROM outcomes WHERE run_id = 'run_rollback'"
        ).fetchone()
        is None
    )
    other = db.connect(tmp_path / ".omni" / "omni.sqlite3")
    try:
        assert (
            other.execute(
                "SELECT 1 FROM outcomes WHERE run_id = 'run_rollback'"
            ).fetchone()
            is None
        )
    finally:
        other.close()
    conn.close()


def test_transition_to_closed_is_idempotent(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    started = task.start_task(conn, tmp_path, "once")
    now = "2026-06-15T00:00:00Z"
    task._transition_task(conn, started["task_id"], target="closed", now=now)
    task._transition_task(conn, started["task_id"], target="closed", now=now)
    conn.close()


def test_ingest_ignores_stale_meta_for_closed_task(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    started = task.start_task(conn, tmp_path, "stale meta")
    task_id = started["task_id"]
    task.close_task(conn, tmp_path, status="unknown")
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?)",
        (task.CURRENT_TASK_META_KEY, task_id),
    )
    conn.commit()
    ingest._ensure_run(conn, tmp_path, "run_stale_meta", None)
    conn.commit()
    row = conn.execute(
        "SELECT task_id FROM runs WHERE run_id = 'run_stale_meta'"
    ).fetchone()
    assert row["task_id"] is None
    conn.close()


def test_representative_run_picks_most_recent_started_at(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    started = task.start_task(conn, tmp_path, "multi run")
    task_id = started["task_id"]
    seed_run(conn, tmp_path, "run_older")
    seed_run(conn, tmp_path, "run_newer")
    conn.execute(
        "UPDATE runs SET task_id = ?, started_at = ? WHERE run_id = ?",
        (task_id, "2026-06-14T00:00:00Z", "run_older"),
    )
    conn.execute(
        "UPDATE runs SET task_id = ?, started_at = ? WHERE run_id = ?",
        (task_id, "2026-06-15T12:00:00Z", "run_newer"),
    )
    conn.commit()
    assert task._representative_run_id(conn, task_id) == "run_newer"
    conn.close()


def test_close_from_verify_matches_standalone_outcome_reason_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = connect(tmp_path)
    started = task.start_task(conn, tmp_path, "verify close", task_type="validation")
    seed_run(conn, tmp_path, "run_verify_close")
    seed_run(conn, tmp_path, "run_verify_standalone")
    conn.execute(
        "UPDATE runs SET task_id = ? WHERE run_id = 'run_verify_close'",
        (started["task_id"],),
    )
    conn.commit()

    verify_payload = {
        "status": "failed",
        "reason_code": "failed_exit_code",
        "command": "pytest -q",
        "exit_code": 1,
        "timed_out": False,
        "reason": "verification command failed",
        "selection_mode": "auto",
        "selection_reason": "selected active uses_test_command fact",
        "duration_ms": 9,
        "timeout_seconds": 120,
        "predicate": "uses_test_command",
        "qualifier": "python",
    }

    def fake_run_preflight(
        verify_conn: sqlite3.Connection,
        root: Path | str,
        *,
        timeout_seconds: int,
        qualifier: str | None = None,
        **kwargs: object,
    ) -> dict[str, object]:
        assert verify_conn is conn
        assert Path(root) == tmp_path
        return verify_payload

    monkeypatch.setattr(
        outcome,
        "verify",
        SimpleNamespace(run_preflight=fake_run_preflight),
        raising=False,
    )

    standalone = outcome.mark_outcome_from_verify(
        conn, "run_verify_standalone", tmp_path, status="failed"
    )
    closed = task.close_task(
        conn, tmp_path, status="failed", from_verify=True, timeout_seconds=120
    )
    task_outcome = conn.execute(
        "SELECT tests_status, evidence FROM outcomes WHERE run_id = 'run_verify_close'"
    ).fetchone()
    assert closed["tests_status"] == standalone["tests_status"] == "failed"
    task_evidence = json.loads(task_outcome["evidence"])
    assert task_evidence["verify"]["reason_code"] == "failed_exit_code"
    assert (
        task_evidence["verify"]["reason_code"]
        == standalone["evidence"]["verify"]["reason_code"]
    )
    conn.close()


def test_close_loses_race_to_abandon_and_writes_no_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = connect(tmp_path)
    started = task.start_task(conn, tmp_path, "race close")
    seed_run(conn, tmp_path, "run_race_close")
    conn.execute(
        "UPDATE runs SET task_id = ? WHERE run_id = 'run_race_close'",
        (started["task_id"],),
    )
    conn.commit()

    real_transition = task._transition_task
    flipped = {"done": False}

    def racing_transition(
        conn_arg: sqlite3.Connection,
        task_id: str,
        *,
        target: str,
        now: str,
    ) -> None:
        if not flipped["done"]:
            flipped["done"] = True
            conn_arg.rollback()
            other = db.connect(tmp_path / ".omni" / "omni.sqlite3")
            try:
                task.abandon_task(other, tmp_path, reason="won race")
            finally:
                other.close()
        return real_transition(conn_arg, task_id, target=target, now=now)

    monkeypatch.setattr(task, "_transition_task", racing_transition)

    with pytest.raises(
        ValueError,
        match=r"task already abandoned|task transition failed:.*current=.*target=",
    ):
        task.close_task(conn, tmp_path, status="success")

    assert (
        conn.execute(
            "SELECT 1 FROM outcomes WHERE run_id = 'run_race_close'"
        ).fetchone()
        is None
    )
    row = conn.execute(
        "SELECT status FROM tasks WHERE task_id = ?",
        (started["task_id"],),
    ).fetchone()
    assert row["status"] == "abandoned"
    conn.close()


def test_task_read_view_is_leak_free(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    task.start_task(conn, tmp_path, "read view")
    seed_run(conn, tmp_path, "run_hidden")
    task_id = task.current_task_id_for_ingest(conn)
    conn.execute(
        "UPDATE runs SET task_id = ? WHERE run_id = 'run_hidden'",
        (task_id,),
    )
    conn.execute(
        """
        UPDATE tasks
        SET evidence = ?
        WHERE task_id = ?
        """,
        (
            json.dumps(
                {
                    "task_id": task_id,
                    "run_id": "run_hidden",
                    "confidence": 0.99,
                },
                sort_keys=True,
            ),
            task_id,
        ),
    )
    conn.commit()
    view = task.read_view(conn)
    assert view["schema_version"] == task.READ_VIEW_SCHEMA_VERSION
    assert_no_metadata_leak(view)
    conn.close()


def test_cli_task_start_and_read_smoke(tmp_path: Path) -> None:
    init = run_omni(tmp_path, "init")
    assert init.returncode == 0, init.stderr
    result = run_omni(tmp_path, "task", "start", "smoke intent", "--task-type", "docs")
    assert result.returncode == 0, result.stderr
    read_result = run_omni(tmp_path, "task", "read")
    assert read_result.returncode == 0, read_result.stderr
    payload = json.loads(read_result.stdout)
    assert_no_metadata_leak(payload)


def test_cli_task_status_smoke(tmp_path: Path) -> None:
    init = run_omni(tmp_path, "init")
    assert init.returncode == 0, init.stderr
    start = run_omni(tmp_path, "task", "start", "status smoke")
    assert start.returncode == 0, start.stderr
    status = run_omni(tmp_path, "task", "status")
    assert status.returncode == 0, status.stderr
    payload = json.loads(status.stdout)
    assert payload["attached_run_count"] == 0
    assert payload["open"]["title"] == "status smoke"


def test_cli_task_ls_show_close_abandon_smoke(tmp_path: Path) -> None:
    init = run_omni(tmp_path, "init")
    assert init.returncode == 0, init.stderr
    start = run_omni(tmp_path, "task", "start", "full smoke", "--task-type", "bugfix")
    assert start.returncode == 0, start.stderr
    started = json.loads(start.stdout)
    task_id = started["task_id"]

    ls = run_omni(tmp_path, "task", "ls", "--status", "open")
    assert ls.returncode == 0, ls.stderr
    assert len(json.loads(ls.stdout)["tasks"]) == 1

    show = run_omni(tmp_path, "task", "show", task_id)
    assert show.returncode == 0, show.stderr
    assert json.loads(show.stdout)["status"] == "open"

    close = run_omni(tmp_path, "task", "close", "--success")
    assert close.returncode == 0, close.stderr
    assert json.loads(close.stdout)["status"] == "closed"

    start2 = run_omni(tmp_path, "task", "start", "abandon me")
    assert start2.returncode == 0, start2.stderr
    abandon = run_omni(tmp_path, "task", "abandon", "--reason", "smoke stop")
    assert abandon.returncode == 0, abandon.stderr
    assert json.loads(abandon.stdout)["status"] == "abandoned"
