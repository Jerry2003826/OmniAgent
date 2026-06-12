from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from omni import cli
from omni import db
from omni import outcome


def test_mark_outcome_success_records_user_evidence(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "run_success")

    result = outcome.mark_outcome(
        conn,
        "run_success",
        status="success",
        tests_status="passed",
        memory_effect="helped",
        task_type="validation",
        task_summary="validated sandbox run",
        final_command="pytest -q",
        note="manual pass",
    )

    assert result["run_id"] == "run_success"
    assert result["status"] == "success"
    assert result["tests_status"] == "passed"
    assert result["memory_effect"] == "helped"
    assert result["task_type"] == "validation"
    assert result["task_summary"] == "validated sandbox run"
    assert result["final_command"] == "pytest -q"
    assert result["note"] == "manual pass"
    assert result["evidence"] == {"source": "user", "run_id": "run_success"}
    assert result["created_at"]
    assert result["updated_at"] == result["created_at"]


def test_mark_outcome_failed_and_tests_failed(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "run_failed")

    result = outcome.mark_outcome(
        conn,
        "run_failed",
        status="failed",
        tests_status="failed",
        task_type="bugfix",
        note="tests failed",
    )

    assert result["status"] == "failed"
    assert result["tests_status"] == "failed"
    assert result["task_type"] == "bugfix"
    assert result["memory_effect"] == "unknown"


def test_mark_outcome_records_tests_not_run(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "run_no_tests")

    result = outcome.mark_outcome(
        conn,
        "run_no_tests",
        status="unknown",
        tests_status="not_run",
    )

    assert result["status"] == "unknown"
    assert result["tests_status"] == "not_run"


def test_show_outcome_returns_existing_record(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "run_show")
    marked = outcome.mark_outcome(conn, "run_show", status="success")

    shown = outcome.show_outcome(conn, "run_show")

    assert shown == marked


def test_mark_outcome_idempotent_update_preserves_created_at_and_updates_updated_at(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "run_update")
    times = iter(("2026-06-13T00:00:00+00:00", "2026-06-13T00:01:00+00:00"))
    monkeypatch.setattr(outcome, "_now", lambda: next(times))

    first = outcome.mark_outcome(conn, "run_update", status="failed")
    second = outcome.mark_outcome(conn, "run_update", status="success", tests_status="passed")

    assert first["created_at"] == "2026-06-13T00:00:00+00:00"
    assert second["created_at"] == first["created_at"]
    assert second["updated_at"] == "2026-06-13T00:01:00+00:00"
    assert second["status"] == "success"
    assert second["tests_status"] == "passed"
    assert conn.execute("SELECT COUNT(*) FROM outcomes WHERE run_id = 'run_update'").fetchone()[0] == 1


def test_mark_outcome_unknown_run_gives_clear_error(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)

    with pytest.raises(ValueError, match="unknown run: missing_run"):
        outcome.mark_outcome(conn, "missing_run", status="success")


def test_show_outcome_unknown_run_gives_clear_error(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)

    with pytest.raises(ValueError, match="unknown outcome for run: missing_run"):
        outcome.show_outcome(conn, "missing_run")


def test_mark_outcome_redacts_free_text_before_db_and_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "note-secret-value-123"
    monkeypatch.setenv("OMNI_OUTCOME_SECRET", secret)
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "run_secret")

    result = outcome.mark_outcome(
        conn,
        "run_secret",
        status="failed",
        task_summary=f"summary {secret}",
        final_command=f"echo {secret}",
        note=f"note {secret}",
    )
    row = conn.execute(
        """
        SELECT task_summary, final_command, note
        FROM outcomes
        WHERE run_id = 'run_secret'
        """
    ).fetchone()
    encoded = outcome.as_json(result)

    assert secret not in row["task_summary"]
    assert secret not in row["final_command"]
    assert secret not in row["note"]
    assert secret not in encoded
    assert "REDACTED:" in encoded


def test_cli_mark_and_show_outputs_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "run_cli")
    conn.close()
    monkeypatch.chdir(tmp_path)

    code = cli.main(
        [
            "outcome",
            "mark",
            "run_cli",
            "--success",
            "--tests-passed",
            "--memory-effect",
            "neutral",
            "--task-type",
            "validation",
            "--summary",
            "cli summary",
            "--final-command",
            "pytest -q",
            "--note",
            "cli note",
        ]
    )
    marked = json.loads(capsys.readouterr().out)
    show_code = cli.main(["outcome", "show", "run_cli"])
    shown = json.loads(capsys.readouterr().out)

    assert code == 0
    assert show_code == 0
    assert marked["run_id"] == "run_cli"
    assert marked["status"] == "success"
    assert marked["tests_status"] == "passed"
    assert marked["memory_effect"] == "neutral"
    assert shown == marked


def test_cli_unknown_run_exits_nonzero_with_clear_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    conn = _fixture_db(tmp_path)
    conn.close()
    monkeypatch.chdir(tmp_path)

    code = cli.main(["outcome", "mark", "missing_run", "--success"])
    captured = capsys.readouterr()

    assert code == 2
    assert "unknown run: missing_run" in captured.err
    assert captured.out == ""


def test_memory_effect_can_be_supplied_manually(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "run_manual_memory")

    result = outcome.mark_outcome(
        conn,
        "run_manual_memory",
        memory_effect="failed_to_help",
    )

    assert result["memory_effect"] == "failed_to_help"


def test_memory_effect_omitted_uses_eval_safely_when_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "run_eval_memory")

    def fake_evaluate_run(root: Path | str, run_id: str) -> dict[str, object]:
        assert Path(root) == tmp_path
        assert run_id == "run_eval_memory"
        return {"memory_effect": "helped"}

    monkeypatch.setattr(outcome.behavior_eval, "evaluate_run", fake_evaluate_run)

    result = outcome.mark_outcome(conn, "run_eval_memory")

    assert result["memory_effect"] == "helped"


def test_memory_effect_omitted_defaults_unknown_when_eval_not_feasible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "run_eval_error")

    def fail_evaluate_run(root: Path | str, run_id: str) -> dict[str, object]:
        raise RuntimeError("eval unavailable")

    monkeypatch.setattr(outcome.behavior_eval, "evaluate_run", fail_evaluate_run)

    result = outcome.mark_outcome(conn, "run_eval_error")

    assert result["memory_effect"] == "unknown"


def _fixture_db(root: Path) -> sqlite3.Connection:
    (root / ".omni").mkdir()
    conn = db.connect(root / ".omni" / "omni.sqlite3")
    db.migrate(conn)
    return conn


def _insert_run(conn: sqlite3.Connection, run_id: str) -> None:
    conn.execute(
        "INSERT INTO runs(run_id, project_id, snapshot_seq, status) VALUES(?,?,?,?)",
        (run_id, "project", 0, "closed"),
    )
    conn.commit()
