from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace
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


def test_mark_outcome_redacts_serialized_evidence_before_db_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    canary = "outcome-evidence-sentinel-123456"
    monkeypatch.setenv("OMNI_OUTCOME_EVIDENCE_SECRET", canary)
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "run_evidence_key")

    result = outcome.mark_outcome(
        conn,
        "run_evidence_key",
        evidence={"source": "user", "run_id": "run_evidence_key", canary: "key"},
    )
    row = conn.execute(
        "SELECT evidence FROM outcomes WHERE run_id = 'run_evidence_key'"
    ).fetchone()
    encoded = outcome.as_json(result)

    assert canary not in row["evidence"]
    assert canary not in encoded
    assert "REDACTED:" in row["evidence"]


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


def test_mark_outcome_from_verify_passed_records_tests_without_success_inference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "run_verify_passed")

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
        assert timeout_seconds == 120
        assert qualifier is None
        return {
            "status": "passed",
            "reason_code": "passed",
            "command": "pytest -q",
            "exit_code": 0,
            "timed_out": False,
            "reason": "verification command passed",
            "selection_mode": "auto",
            "selection_reason": "selected active uses_test_command fact",
            "duration_ms": 12,
            "timeout_seconds": 120,
            "predicate": "uses_test_command",
            "qualifier": "python",
            "candidate_commands": [{"qualifier": "python", "command": "pytest -q"}],
            "candidate_commands_omitted": 0,
            "stdout_excerpt": "should not be stored",
            "stderr_excerpt": "should not be stored",
        }

    monkeypatch.setattr(
        outcome,
        "verify",
        SimpleNamespace(run_preflight=fake_run_preflight),
        raising=False,
    )

    result = outcome.mark_outcome_from_verify(conn, "run_verify_passed", tmp_path)

    assert result["run_id"] == "run_verify_passed"
    assert result["status"] == "unknown"
    assert result["tests_status"] == "passed"
    assert result["memory_effect"] == "unknown"
    assert result["final_command"] == "pytest -q"
    assert result["evidence"] == {
        "source": "verify",
        "run_id": "run_verify_passed",
        "verify": {
            "status": "passed",
            "reason_code": "passed",
            "command": "pytest -q",
            "exit_code": 0,
            "timed_out": False,
            "reason": "verification command passed",
            "selection_mode": "auto",
            "selection_reason": "selected active uses_test_command fact",
            "duration_ms": 12,
            "timeout_seconds": 120,
            "predicate": "uses_test_command",
            "qualifier": "python",
            "candidate_commands": [{"qualifier": "python", "command": "pytest -q"}],
            "candidate_commands_omitted": 0,
        },
    }


def test_mark_outcome_from_verify_passes_explicit_qualifier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "run_verify_qualified")

    def fake_run_preflight(
        verify_conn: sqlite3.Connection,
        root: Path | str,
        *,
        timeout_seconds: int,
        qualifier: str | None = None,
        **kwargs: object,
    ) -> dict[str, object]:
        assert timeout_seconds == 45
        assert qualifier == "node:web"
        return {
            "status": "passed",
            "reason_code": "passed",
            "command": "pnpm --filter web test",
            "exit_code": 0,
            "timed_out": False,
            "reason": "verification command passed",
            "selection_mode": "qualifier",
            "selection_reason": "selected active uses_test_command fact for qualifier node:web",
            "duration_ms": 34,
            "timeout_seconds": 45,
            "predicate": "uses_test_command",
            "qualifier": "node:web",
        }

    monkeypatch.setattr(
        outcome,
        "verify",
        SimpleNamespace(run_preflight=fake_run_preflight),
        raising=False,
    )

    result = outcome.mark_outcome_from_verify(
        conn,
        "run_verify_qualified",
        tmp_path,
        qualifier="node:web",
        timeout_seconds=45,
    )

    assert result["tests_status"] == "passed"
    assert result["final_command"] == "pnpm --filter web test"
    assert result["evidence"]["verify"]["selection_mode"] == "qualifier"
    assert result["evidence"]["verify"]["qualifier"] == "node:web"


def test_mark_outcome_from_verify_failed_marks_tests_failed_and_keeps_user_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "run_verify_failed")

    def fake_run_preflight(
        verify_conn: sqlite3.Connection,
        root: Path | str,
        *,
        timeout_seconds: int,
        qualifier: str | None = None,
        **kwargs: object,
    ) -> dict[str, object]:
        return {
            "status": "failed",
            "reason_code": "failed_exit_code",
            "command": "pytest -q",
            "exit_code": 1,
            "timed_out": False,
            "reason": "verification command failed with exit code 1",
        }

    monkeypatch.setattr(
        outcome,
        "verify",
        SimpleNamespace(run_preflight=fake_run_preflight),
        raising=False,
    )

    result = outcome.mark_outcome_from_verify(
        conn,
        "run_verify_failed",
        tmp_path,
        status="failed",
        memory_effect="neutral",
        task_type="validation",
        timeout_seconds=30,
    )

    assert result["status"] == "failed"
    assert result["tests_status"] == "failed"
    assert result["memory_effect"] == "neutral"
    assert result["task_type"] == "validation"
    assert result["final_command"] == "pytest -q"
    assert result["evidence"]["source"] == "verify"
    assert result["evidence"]["verify"]["exit_code"] == 1


def test_mark_outcome_from_verify_startup_failure_keeps_tests_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "run_verify_startup_failed")

    def fake_run_preflight(
        verify_conn: sqlite3.Connection,
        root: Path | str,
        *,
        timeout_seconds: int,
        qualifier: str | None = None,
        **kwargs: object,
    ) -> dict[str, object]:
        return {
            "status": "failed",
            "reason_code": "start_failed",
            "command": "missing-test-runner",
            "exit_code": None,
            "timed_out": False,
            "reason": "verification command could not be started",
        }

    monkeypatch.setattr(
        outcome,
        "verify",
        SimpleNamespace(run_preflight=fake_run_preflight),
        raising=False,
    )

    result = outcome.mark_outcome_from_verify(
        conn,
        "run_verify_startup_failed",
        tmp_path,
    )

    assert result["tests_status"] == "unknown"
    assert result["evidence"]["verify"]["exit_code"] is None


def test_mark_outcome_from_verify_unknown_run_does_not_execute_verify(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = _fixture_db(tmp_path)

    def fail_run_preflight(
        verify_conn: sqlite3.Connection,
        root: Path | str,
        *,
        timeout_seconds: int,
        qualifier: str | None = None,
        **kwargs: object,
    ) -> dict[str, object]:
        raise AssertionError("verify should not run for an unknown run")

    monkeypatch.setattr(
        outcome,
        "verify",
        SimpleNamespace(run_preflight=fail_run_preflight),
        raising=False,
    )

    with pytest.raises(ValueError, match="unknown run: missing_run"):
        outcome.mark_outcome_from_verify(conn, "missing_run", tmp_path)


def test_mark_outcome_from_verify_redacts_evidence_and_omits_output_excerpts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    canary = "verify-outcome-sentinel-123456"
    monkeypatch.setenv("OMNI_OUTCOME_VERIFY_SECRET", canary)
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "run_verify_secret")

    def fake_run_preflight(
        verify_conn: sqlite3.Connection,
        root: Path | str,
        *,
        timeout_seconds: int,
        qualifier: str | None = None,
        **kwargs: object,
    ) -> dict[str, object]:
        return {
            "status": "failed",
            "reason_code": "failed_exit_code",
            "command": f"curl -H 'X-Canary: {canary}'",
            "exit_code": 22,
            "timed_out": False,
            "reason": f"failed with {canary}",
            "stdout_excerpt": f"stdout {canary}",
            "stderr_excerpt": f"stderr {canary}",
        }

    monkeypatch.setattr(
        outcome,
        "verify",
        SimpleNamespace(run_preflight=fake_run_preflight),
        raising=False,
    )

    result = outcome.mark_outcome_from_verify(conn, "run_verify_secret", tmp_path)
    row = conn.execute(
        "SELECT final_command, evidence FROM outcomes WHERE run_id = 'run_verify_secret'"
    ).fetchone()
    evidence = json.loads(row["evidence"])
    encoded = outcome.as_json(result)

    assert canary not in row["final_command"]
    assert canary not in row["evidence"]
    assert canary not in encoded
    assert "REDACTED:" in row["final_command"]
    assert "REDACTED:" in row["evidence"]
    assert "stdout_excerpt" not in evidence["verify"]
    assert "stderr_excerpt" not in evidence["verify"]


@pytest.mark.parametrize(
    ("reason_code", "expected"),
    [
        ("passed", "passed"),
        ("failed_exit_code", "failed"),
        ("timed_out", "failed"),
        ("start_failed", "unknown"),
        ("no_active_test_command", "unknown"),
        ("ambiguous_active_test_command", "unknown"),
        ("qualifier_not_found", "unknown"),
        ("ambiguous_qualifier", "unknown"),
        ("parse_error_empty_command", "unknown"),
        ("parse_error_shell_wrapper", "unknown"),
        ("parse_error_invalid_command", "unknown"),
    ],
)
def test_tests_status_from_verify_maps_each_reason_code(
    reason_code: str, expected: str
) -> None:
    # Only a command that ran to a result is passed/failed; everything else stays
    # conservative. This locks the v0.5 tests_status contract to the verify
    # reason_code surface.
    assert outcome._tests_status_from_verify({"reason_code": reason_code}) == expected


def test_mark_outcome_from_verify_ambiguous_selection_stays_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "run_verify_ambiguous")

    def fake_run_preflight(
        verify_conn: sqlite3.Connection,
        root: Path | str,
        *,
        timeout_seconds: int,
        qualifier: str | None = None,
        **kwargs: object,
    ) -> dict[str, object]:
        return {
            "status": "unknown",
            "reason_code": "ambiguous_active_test_command",
            "command": None,
            "exit_code": None,
            "timed_out": False,
            "reason": "ambiguous active uses_test_command facts",
        }

    monkeypatch.setattr(
        outcome,
        "verify",
        SimpleNamespace(run_preflight=fake_run_preflight),
        raising=False,
    )

    result = outcome.mark_outcome_from_verify(
        conn, "run_verify_ambiguous", tmp_path, task_type="validation"
    )

    # No command ran, so tests_status is unknown and status is never inferred.
    assert result["tests_status"] == "unknown"
    assert result["status"] == "unknown"
    assert result["final_command"] is None
    assert result["evidence"]["verify"]["reason_code"] == "ambiguous_active_test_command"


def test_mark_outcome_from_verify_is_idempotent_and_preserves_created_at(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "run_verify_idempotent")

    def fake_run_preflight(
        verify_conn: sqlite3.Connection,
        root: Path | str,
        *,
        timeout_seconds: int,
        qualifier: str | None = None,
        **kwargs: object,
    ) -> dict[str, object]:
        return {
            "status": "passed",
            "reason_code": "passed",
            "command": "pytest -q",
            "exit_code": 0,
            "timed_out": False,
            "reason": "verification command passed",
        }

    monkeypatch.setattr(
        outcome,
        "verify",
        SimpleNamespace(run_preflight=fake_run_preflight),
        raising=False,
    )

    first = outcome.mark_outcome_from_verify(conn, "run_verify_idempotent", tmp_path)
    second = outcome.mark_outcome_from_verify(conn, "run_verify_idempotent", tmp_path)

    assert first["tests_status"] == "passed"
    assert second["tests_status"] == "passed"
    assert second["created_at"] == first["created_at"]
    assert second["updated_at"] >= first["updated_at"]
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM outcomes WHERE run_id = 'run_verify_idempotent'"
        ).fetchone()[0]
        == 1
    )


def test_cli_outcome_mark_from_verify_writes_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "run_cli_verify")
    conn.close()
    monkeypatch.chdir(tmp_path)

    def fake_run_preflight(
        verify_conn: sqlite3.Connection,
        root: Path | str,
        *,
        timeout_seconds: int,
        qualifier: str | None = None,
        **kwargs: object,
    ) -> dict[str, object]:
        return {
            "status": "passed",
            "reason_code": "passed",
            "command": "pytest -q",
            "exit_code": 0,
            "timed_out": False,
            "reason": "verification command passed",
        }

    monkeypatch.setattr(
        outcome,
        "verify",
        SimpleNamespace(run_preflight=fake_run_preflight),
        raising=False,
    )

    code = cli.main(
        [
            "outcome",
            "mark-from-verify",
            "run_cli_verify",
            "--success",
            "--memory-effect",
            "helped",
            "--task-type",
            "validation",
        ]
    )
    marked = json.loads(capsys.readouterr().out)

    assert code == 0
    assert marked["run_id"] == "run_cli_verify"
    assert marked["status"] == "success"
    assert marked["tests_status"] == "passed"
    assert marked["memory_effect"] == "helped"
    assert marked["task_type"] == "validation"
    assert marked["final_command"] == "pytest -q"
    assert marked["evidence"]["source"] == "verify"


def test_cli_outcome_mark_from_verify_accepts_qualifier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "run_cli_verify_qualifier")
    conn.close()
    monkeypatch.chdir(tmp_path)

    def fake_run_preflight(
        verify_conn: sqlite3.Connection,
        root: Path | str,
        *,
        timeout_seconds: int,
        qualifier: str | None = None,
        **kwargs: object,
    ) -> dict[str, object]:
        assert qualifier == "node:web"
        return {
            "status": "passed",
            "reason_code": "passed",
            "command": "pnpm --filter web test",
            "exit_code": 0,
            "timed_out": False,
            "reason": "verification command passed",
            "selection_mode": "qualifier",
            "selection_reason": "selected active uses_test_command fact for qualifier node:web",
            "qualifier": "node:web",
        }

    monkeypatch.setattr(
        outcome,
        "verify",
        SimpleNamespace(run_preflight=fake_run_preflight),
        raising=False,
    )

    code = cli.main(
        [
            "outcome",
            "mark-from-verify",
            "run_cli_verify_qualifier",
            "--qualifier",
            "node:web",
        ]
    )
    marked = json.loads(capsys.readouterr().out)

    assert code == 0
    assert marked["tests_status"] == "passed"
    assert marked["final_command"] == "pnpm --filter web test"
    assert marked["evidence"]["verify"]["selection_mode"] == "qualifier"
    assert marked["evidence"]["verify"]["qualifier"] == "node:web"


def test_cli_outcome_mark_from_verify_accepts_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "run_cli_verify_profile")
    conn.close()
    monkeypatch.chdir(tmp_path)

    def fake_run_preflight(
        verify_conn: sqlite3.Connection,
        root: Path | str,
        *,
        timeout_seconds: int,
        qualifier: str | None = None,
        profile: str | None = None,
        **kwargs: object,
    ) -> dict[str, object]:
        assert profile == "release"
        return {
            "status": "passed",
            "reason_code": "passed",
            "command": "pnpm run release-check",
            "exit_code": 0,
            "timed_out": False,
            "reason": "verification command passed",
            "selection_mode": "profile",
            "selection_reason": "selected release profile verification command",
            "profile": "release",
        }

    monkeypatch.setattr(outcome.verify, "run_preflight", fake_run_preflight)

    code = cli.main(
        [
            "outcome",
            "mark-from-verify",
            "run_cli_verify_profile",
            "--profile",
            "release",
        ]
    )
    marked = json.loads(capsys.readouterr().out)

    assert code == 0
    assert marked["tests_status"] == "passed"
    assert marked["final_command"] == "pnpm run release-check"
    assert marked["evidence"]["verify"]["selection_mode"] == "profile"
    assert marked["evidence"]["verify"]["profile"] == "release"


def test_cli_outcome_show_on_outdated_schema_is_read_only_and_exits_clearly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".omni").mkdir()
    setup = sqlite3.connect(tmp_path / ".omni" / "omni.sqlite3")
    setup.executescript(db.migration_sql("001_init.sql"))
    setup.executescript(db.migration_sql("002_outcomes.sql"))
    setup.commit()
    setup.close()
    monkeypatch.chdir(tmp_path)

    code = cli.main(["outcome", "show", "any_run"])
    captured = capsys.readouterr()
    check = sqlite3.connect(tmp_path / ".omni" / "omni.sqlite3")
    version = check.execute(
        "SELECT value FROM meta WHERE key = 'schema_version'"
    ).fetchone()[0]
    check.close()

    assert code == 2
    assert "OmniMemory schema is outdated (found 2, need 7)" in captured.err
    assert captured.out == ""
    assert version == "2"


def test_connect_project_readonly_supports_show_and_blocks_writes(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "run_ro_show")
    outcome.mark_outcome(conn, "run_ro_show", status="success")
    conn.close()

    readonly = outcome.connect_project_readonly(tmp_path)
    try:
        shown = outcome.show_outcome(readonly, "run_ro_show")
        listed = outcome.list_outcomes(readonly)
        with pytest.raises(sqlite3.OperationalError):
            readonly.execute("INSERT INTO meta(key, value) VALUES('probe', '1')")
    finally:
        readonly.close()

    assert shown["status"] == "success"
    assert listed["count"] == 1
    assert listed["outcomes"][0]["run_id"] == "run_ro_show"


def test_list_outcomes_returns_rows_summary_and_count(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "run_a")
    _insert_run(conn, "run_b")
    outcome.mark_outcome(
        conn, "run_a", status="success", tests_status="passed",
        memory_effect="neutral", task_type="validation",
    )
    outcome.mark_outcome(
        conn, "run_b", status="failed", tests_status="failed",
        memory_effect="failed_to_help", task_type="bugfix",
    )

    result = outcome.list_outcomes(conn)

    assert result["count"] == 2
    assert result["filters"] == {}
    assert {row["run_id"] for row in result["outcomes"]} == {"run_a", "run_b"}
    assert result["summary"]["status"] == {"success": 1, "failed": 1}
    assert result["summary"]["tests_status"] == {"passed": 1, "failed": 1}
    assert result["summary"]["memory_effect"] == {"neutral": 1, "failed_to_help": 1}
    assert result["summary"]["task_type"] == {"validation": 1, "bugfix": 1}
    first = result["outcomes"][0]
    assert "evidence" not in first
    assert "note" not in first
    assert "task_summary" not in first


def test_list_outcomes_empty_is_zero_count(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)

    result = outcome.list_outcomes(conn)

    assert result["count"] == 0
    assert result["filters"] == {}
    assert result["outcomes"] == []
    assert result["summary"]["status"] == {}


def test_list_outcomes_filter_by_task_type(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "run_a")
    _insert_run(conn, "run_b")
    outcome.mark_outcome(
        conn, "run_a", status="success", tests_status="passed",
        memory_effect="neutral", task_type="validation",
    )
    outcome.mark_outcome(
        conn, "run_b", status="failed", tests_status="failed",
        memory_effect="failed_to_help", task_type="bugfix",
    )

    result = outcome.list_outcomes(conn, task_type="validation")

    assert result["count"] == 1
    assert result["filters"] == {"task_type": "validation"}
    assert result["outcomes"][0]["run_id"] == "run_a"
    assert result["summary"]["task_type"] == {"validation": 1}


def test_list_outcomes_combined_filters(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "run_a")
    _insert_run(conn, "run_b")
    _insert_run(conn, "run_c")
    outcome.mark_outcome(
        conn, "run_a", status="success", tests_status="passed",
        memory_effect="helped", task_type="validation",
    )
    outcome.mark_outcome(
        conn, "run_b", status="success", tests_status="failed",
        memory_effect="neutral", task_type="validation",
    )
    outcome.mark_outcome(
        conn, "run_c", status="failed", tests_status="failed",
        memory_effect="failed_to_help", task_type="bugfix",
    )

    result = outcome.list_outcomes(
        conn,
        task_type="validation",
        status="success",
        memory_effect="helped",
    )

    assert result["count"] == 1
    assert result["filters"] == {
        "task_type": "validation",
        "status": "success",
        "memory_effect": "helped",
    }
    assert result["outcomes"][0]["run_id"] == "run_a"


def test_list_outcomes_filter_empty_result(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "run_a")
    outcome.mark_outcome(
        conn, "run_a", status="success", tests_status="passed", task_type="validation",
    )

    result = outcome.list_outcomes(conn, status="failed")

    assert result["count"] == 0
    assert result["filters"] == {"status": "failed"}
    assert result["outcomes"] == []
    assert result["summary"]["status"] == {}


def test_list_outcomes_invalid_filter_raises(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)

    with pytest.raises(ValueError, match="invalid status"):
        outcome.list_outcomes(conn, status="bogus")


def test_cli_outcome_ls_outputs_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "run_ls")
    outcome.mark_outcome(
        conn, "run_ls", status="success", tests_status="passed", task_type="validation",
    )
    conn.close()
    monkeypatch.chdir(tmp_path)

    code = cli.main(["outcome", "ls"])
    captured = capsys.readouterr()
    output = json.loads(captured.out)

    assert code == 0
    assert captured.err == ""
    assert output["count"] == 1
    assert output["outcomes"][0]["run_id"] == "run_ls"
    assert output["summary"]["status"] == {"success": 1}


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
