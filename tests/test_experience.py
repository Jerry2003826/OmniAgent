from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from omni import cli
from omni import db
from omni import experience
from omni import outcome


def test_extract_failed_validation_creates_rediscovery_waste_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = _fixture_db(tmp_path)
    outcome_row = _insert_outcome(
        conn,
        "run_failed_help",
        status="failed",
        tests_status="not_run",
        memory_effect="failed_to_help",
        task_type="validation",
    )
    _fake_eval(
        monkeypatch,
        memory_effect="failed_to_help",
        reason="rediscovery before command",
        rediscovery_count=4,
        first_expected_command=None,
    )

    candidates = experience.extract_candidates(conn, "run_failed_help")

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["run_id"] == "run_failed_help"
    assert candidate["outcome_id"] == outcome_row["outcome_id"]
    assert candidate["kind"] == "rediscovery_waste"
    assert candidate["state"] == "pending"
    assert candidate["task_type"] == "validation"
    assert candidate["claim"] == (
        "Memory context was available, but the run performed rediscovery and did not "
        "execute the known verification command."
    )
    assert candidate["suggested_action"] == (
        "For validation tasks, execute the known verification command before broad "
        "README/package/deployment rediscovery."
    )
    assert candidate["evidence"] == {
        "run_id": "run_failed_help",
        "outcome_id": outcome_row["outcome_id"],
        "eval": {
            "memory_effect": "failed_to_help",
            "reason": "rediscovery before command",
            "rediscovery_count": 4,
            "first_expected_command": None,
        },
        "outcome": {
            "status": "failed",
            "tests_status": "not_run",
            "task_type": "validation",
        },
    }


def test_extract_success_validation_creates_fast_path_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = _fixture_db(tmp_path)
    _insert_outcome(
        conn,
        "run_fast_path",
        status="success",
        tests_status="passed",
        memory_effect="helped",
        task_type="validation",
    )
    _fake_eval(
        monkeypatch,
        memory_effect="helped",
        reason="expected command executed before rediscovery: pnpm run test",
        rediscovery_count=0,
        first_expected_command="pnpm run test",
    )

    candidates = experience.extract_candidates(conn, "run_fast_path")

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["kind"] == "fast_path"
    assert candidate["claim"] == (
        "For validation tasks, the known verification command worked before rediscovery."
    )
    assert candidate["suggested_action"] == (
        "Prefer the known verification command early in future validation tasks."
    )
    assert candidate["evidence"]["eval"]["first_expected_command"] == "pnpm run test"
    assert candidate["evidence"]["outcome"]["tests_status"] == "passed"


def test_approve_pending_rediscovery_waste_candidate_creates_active_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = _fixture_db(tmp_path)
    _insert_outcome(
        conn,
        "run_note_failed",
        status="failed",
        tests_status="not_run",
        memory_effect="failed_to_help",
        task_type="validation",
    )
    _fake_eval(monkeypatch, memory_effect="failed_to_help", rediscovery_count=3)
    [candidate] = experience.extract_candidates(conn, "run_note_failed")

    approved = experience.approve_candidate(conn, candidate["exp_cand_id"])
    note = _active_note_for_candidate(conn, candidate["exp_cand_id"])

    assert approved["state"] == "approved"
    assert approved["note_id"] == note["note_id"]
    assert note["source_cand_id"] == candidate["exp_cand_id"]
    assert note["scope"] == "project"
    assert note["task_type"] == "validation"
    assert note["kind"] == "rediscovery_waste"
    assert note["body"] == candidate["claim"]
    assert note["suggested_action"] == candidate["suggested_action"]
    assert note["trust"] == 2
    assert note["status"] == "active"
    assert json.loads(note["evidence"]) == candidate["evidence"]
    assert note["created_seq"] == 1
    assert note["created_at"]
    assert note["updated_at"]


def test_approve_pending_fast_path_candidate_creates_active_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = _fixture_db(tmp_path)
    _insert_outcome(
        conn,
        "run_note_fast",
        status="success",
        tests_status="passed",
        memory_effect="helped",
        task_type="validation",
    )
    _fake_eval(monkeypatch, memory_effect="helped", first_expected_command="pnpm run test")
    [candidate] = experience.extract_candidates(conn, "run_note_fast")

    approved = experience.approve_candidate(conn, candidate["exp_cand_id"])
    note = _active_note_for_candidate(conn, candidate["exp_cand_id"])

    assert approved["state"] == "approved"
    assert approved["note_id"] == note["note_id"]
    assert note["kind"] == "fast_path"
    assert note["body"] == (
        "For validation tasks, the known verification command worked before rediscovery."
    )


def test_approve_twice_is_idempotent_for_existing_active_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = _fixture_db(tmp_path)
    _insert_outcome(
        conn,
        "run_note_idempotent",
        status="success",
        tests_status="passed",
        memory_effect="helped",
        task_type="validation",
    )
    _fake_eval(monkeypatch, memory_effect="helped")
    [candidate] = experience.extract_candidates(conn, "run_note_idempotent")

    first = experience.approve_candidate(conn, candidate["exp_cand_id"])
    second = experience.approve_candidate(conn, candidate["exp_cand_id"])

    assert second["state"] == "approved"
    assert second["note_id"] == first["note_id"]
    assert _active_note_count(conn, candidate["exp_cand_id"]) == 1


def test_approved_candidate_cannot_be_rejected_in_v0(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = _fixture_db(tmp_path)
    _insert_outcome(
        conn,
        "run_approved_then_reject",
        status="success",
        tests_status="passed",
        memory_effect="helped",
        task_type="validation",
    )
    _fake_eval(monkeypatch, memory_effect="helped")
    [candidate] = experience.extract_candidates(conn, "run_approved_then_reject")
    approved = experience.approve_candidate(conn, candidate["exp_cand_id"])

    with pytest.raises(ValueError, match="approved candidate cannot be rejected in v0"):
        experience.reject_candidate(conn, candidate["exp_cand_id"])

    assert experience.show_candidate(conn, candidate["exp_cand_id"])["state"] == "approved"
    assert _active_note_count(conn, candidate["exp_cand_id"]) == 1
    assert _active_note_for_candidate(conn, candidate["exp_cand_id"])["note_id"] == approved["note_id"]


def test_rejected_candidate_cannot_be_approved_in_v0(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = _fixture_db(tmp_path)
    _insert_outcome(
        conn,
        "run_reject_then_approve",
        status="success",
        tests_status="passed",
        memory_effect="helped",
        task_type="validation",
    )
    _fake_eval(monkeypatch, memory_effect="helped")
    [candidate] = experience.extract_candidates(conn, "run_reject_then_approve")
    experience.reject_candidate(conn, candidate["exp_cand_id"])

    with pytest.raises(ValueError, match="rejected candidate cannot be approved in v0"):
        experience.approve_candidate(conn, candidate["exp_cand_id"])
    assert _active_note_count(conn, candidate["exp_cand_id"]) == 0


def test_extract_without_outcome_creates_no_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "run_no_outcome")
    _fake_eval(monkeypatch, memory_effect="helped")

    assert experience.extract_candidates(conn, "run_no_outcome") == []
    assert experience.list_candidates(conn, state="all") == []


def test_extract_unknown_run_raises_clear_error(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)

    with pytest.raises(ValueError, match="unknown run: missing_run"):
        experience.extract_candidates(conn, "missing_run")


def test_extract_unknown_eval_creates_no_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = _fixture_db(tmp_path)
    _insert_outcome(
        conn,
        "run_unknown_eval",
        status="success",
        tests_status="passed",
        memory_effect="helped",
        task_type="validation",
    )
    _fake_eval(monkeypatch, memory_effect="unknown", reason="insufficient evidence")

    assert experience.extract_candidates(conn, "run_unknown_eval") == []


def test_extract_does_not_duplicate_existing_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = _fixture_db(tmp_path)
    _insert_outcome(
        conn,
        "run_dedupe",
        status="success",
        tests_status="unknown",
        memory_effect="helped",
        task_type="validation",
    )
    _fake_eval(monkeypatch, memory_effect="helped", first_expected_command="pnpm run test")

    first = experience.extract_candidates(conn, "run_dedupe")
    second = experience.extract_candidates(conn, "run_dedupe")

    assert len(first) == 1
    assert second == []
    assert len(experience.list_candidates(conn, state="all")) == 1


def test_reject_prevents_recreation_in_v0(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _fixture_db(tmp_path)
    _insert_outcome(
        conn,
        "run_rejected",
        status="failed",
        tests_status="unknown",
        memory_effect="failed_to_help",
        task_type="validation",
    )
    _fake_eval(monkeypatch, memory_effect="failed_to_help", rediscovery_count=2)
    [candidate] = experience.extract_candidates(conn, "run_rejected")

    rejected = experience.reject_candidate(conn, candidate["exp_cand_id"])
    recreated = experience.extract_candidates(conn, "run_rejected")

    assert rejected["state"] == "rejected"
    assert recreated == []
    assert len(experience.list_candidates(conn, state="all")) == 1


def test_list_show_approve_and_reject_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = _fixture_db(tmp_path)
    _insert_outcome(
        conn,
        "run_review",
        status="success",
        tests_status="passed",
        memory_effect="helped",
        task_type="validation",
    )
    _insert_outcome(
        conn,
        "run_review_reject",
        status="success",
        tests_status="passed",
        memory_effect="helped",
        task_type="validation",
    )
    _fake_eval(monkeypatch, memory_effect="helped")
    [candidate] = experience.extract_candidates(conn, "run_review")
    [reject_candidate] = experience.extract_candidates(conn, "run_review_reject")

    pending = experience.list_candidates(conn)
    shown = experience.show_candidate(conn, candidate["exp_cand_id"])
    approved = experience.approve_candidate(conn, candidate["exp_cand_id"])
    approved_list = experience.list_candidates(conn, state="approved")
    rejected = experience.reject_candidate(conn, reject_candidate["exp_cand_id"])
    approved_candidate = {key: value for key, value in approved.items() if key != "note_id"}

    assert {item["exp_cand_id"] for item in pending} == {
        candidate["exp_cand_id"],
        reject_candidate["exp_cand_id"],
    }
    assert shown == candidate
    assert approved["state"] == "approved"
    assert approved["note_id"]
    assert approved["reviewed_at"]
    assert approved_list == [approved_candidate]
    assert rejected["state"] == "rejected"
    assert _active_note_count(conn, rejected["exp_cand_id"]) == 0


def test_cli_extract_ls_show_approve_reject_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    conn = _fixture_db(tmp_path)
    _insert_outcome(
        conn,
        "run_cli_exp",
        status="success",
        tests_status="passed",
        memory_effect="helped",
        task_type="validation",
    )
    _insert_outcome(
        conn,
        "run_cli_reject",
        status="success",
        tests_status="passed",
        memory_effect="helped",
        task_type="validation",
    )
    conn.close()
    _fake_eval(monkeypatch, memory_effect="helped", first_expected_command="pnpm run test")
    monkeypatch.chdir(tmp_path)

    extract_code = cli.main(["experience", "extract", "run_cli_exp"])
    extracted = json.loads(capsys.readouterr().out)
    exp_cand_id = extracted["candidates"][0]["exp_cand_id"]
    reject_extract_code = cli.main(["experience", "extract", "run_cli_reject"])
    reject_extracted = json.loads(capsys.readouterr().out)
    reject_exp_cand_id = reject_extracted["candidates"][0]["exp_cand_id"]
    ls_code = cli.main(["experience", "ls"])
    listed = json.loads(capsys.readouterr().out)
    show_code = cli.main(["experience", "show", exp_cand_id])
    shown = json.loads(capsys.readouterr().out)
    approve_code = cli.main(["experience", "approve", exp_cand_id])
    approved = json.loads(capsys.readouterr().out)
    reject_code = cli.main(["experience", "reject", reject_exp_cand_id])
    rejected = json.loads(capsys.readouterr().out)

    assert extract_code == 0
    assert extracted["created"] == 1
    assert reject_extract_code == 0
    assert reject_extracted["created"] == 1
    assert ls_code == 0
    assert {item["exp_cand_id"] for item in listed["candidates"]} == {
        exp_cand_id,
        reject_exp_cand_id,
    }
    assert show_code == 0
    assert shown["exp_cand_id"] == exp_cand_id
    assert approve_code == 0
    assert approved["state"] == "approved"
    assert approved["note_id"]
    assert reject_code == 0
    assert rejected["state"] == "rejected"


def test_cli_reject_approved_candidate_exits_nonzero_with_clear_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    conn = _fixture_db(tmp_path)
    _insert_outcome(
        conn,
        "run_cli_approved_reject",
        status="success",
        tests_status="passed",
        memory_effect="helped",
        task_type="validation",
    )
    conn.close()
    _fake_eval(monkeypatch, memory_effect="helped", first_expected_command="pnpm run test")
    monkeypatch.chdir(tmp_path)

    extract_code = cli.main(["experience", "extract", "run_cli_approved_reject"])
    extracted = json.loads(capsys.readouterr().out)
    exp_cand_id = extracted["candidates"][0]["exp_cand_id"]
    approve_code = cli.main(["experience", "approve", exp_cand_id])
    approved = json.loads(capsys.readouterr().out)
    reject_code = cli.main(["experience", "reject", exp_cand_id])
    captured = capsys.readouterr()

    assert extract_code == 0
    assert approve_code == 0
    assert approved["state"] == "approved"
    assert reject_code == 2
    assert f"approved candidate cannot be rejected in v0: {exp_cand_id}" in captured.err
    assert captured.out == ""


def test_cli_extract_unknown_run_exits_nonzero_with_clear_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    conn = _fixture_db(tmp_path)
    conn.close()
    monkeypatch.chdir(tmp_path)

    code = cli.main(["experience", "extract", "missing_run"])
    captured = capsys.readouterr()

    assert code == 2
    assert "unknown run: missing_run" in captured.err
    assert captured.out == ""


def test_cli_extract_known_run_without_outcome_returns_created_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "run_without_outcome")
    conn.close()
    monkeypatch.chdir(tmp_path)

    code = cli.main(["experience", "extract", "run_without_outcome"])
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output == {"created": 0, "candidates": []}


def test_evidence_contains_eval_and_outcome_summary_without_raw_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "candidate-secret-value-123"
    monkeypatch.setenv("OMNI_EXPERIENCE_SECRET", secret)
    conn = _fixture_db(tmp_path)
    _insert_outcome(
        conn,
        "run_secret_candidate",
        status="failed",
        tests_status="failed",
        memory_effect="failed_to_help",
        task_type="validation",
    )
    _fake_eval(
        monkeypatch,
        memory_effect="failed_to_help",
        reason=f"rediscovery leaked {secret}",
        rediscovery_count=3,
    )

    [candidate] = experience.extract_candidates(conn, "run_secret_candidate")
    row = conn.execute(
        """
        SELECT claim, suggested_action, evidence
        FROM experience_candidates
        WHERE exp_cand_id = ?
        """,
        (candidate["exp_cand_id"],),
    ).fetchone()
    encoded = experience.as_json(candidate)

    assert secret not in row["claim"]
    assert secret not in row["suggested_action"]
    assert secret not in row["evidence"]
    assert secret not in encoded
    assert "REDACTED:" in encoded
    assert candidate["evidence"]["eval"]["memory_effect"] == "failed_to_help"
    assert candidate["evidence"]["outcome"]["status"] == "failed"


def test_cli_experience_ls_on_outdated_schema_is_read_only_and_exits_clearly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".omni").mkdir()
    setup = sqlite3.connect(tmp_path / ".omni" / "omni.sqlite3")
    setup.executescript(db.migration_sql("001_init.sql"))
    setup.executescript(db.migration_sql("002_outcomes.sql"))
    setup.executescript(db.migration_sql("003_experience_candidates.sql"))
    setup.commit()
    setup.close()
    monkeypatch.chdir(tmp_path)

    code = cli.main(["experience", "ls"])
    captured = capsys.readouterr()
    check = sqlite3.connect(tmp_path / ".omni" / "omni.sqlite3")
    version = check.execute(
        "SELECT value FROM meta WHERE key = 'schema_version'"
    ).fetchone()[0]
    check.close()

    assert code == 2
    assert "OmniMemory schema is outdated (found 3, need 4)" in captured.err
    assert "omni render" in captured.err
    assert captured.out == ""
    assert version == "3"


def test_connect_project_readonly_serves_reads_and_blocks_writes(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    conn.close()

    readonly = experience.connect_project_readonly(tmp_path)
    try:
        assert experience.list_candidates(readonly, state="all") == []
        with pytest.raises(sqlite3.OperationalError):
            readonly.execute("INSERT INTO meta(key, value) VALUES('probe', '1')")
    finally:
        readonly.close()


def test_connect_project_readonly_missing_db_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="OmniMemory database is missing"):
        experience.connect_project_readonly(tmp_path)


def test_reject_twice_is_idempotent_and_preserves_reviewed_at(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = _fixture_db(tmp_path)
    _insert_outcome(
        conn,
        "run_double_reject",
        status="success",
        tests_status="passed",
        memory_effect="helped",
        task_type="validation",
    )
    _fake_eval(monkeypatch, memory_effect="helped")
    [candidate] = experience.extract_candidates(conn, "run_double_reject")

    first = experience.reject_candidate(conn, candidate["exp_cand_id"])
    second = experience.reject_candidate(conn, candidate["exp_cand_id"])

    assert first["state"] == "rejected"
    assert second == first
    assert second["reviewed_at"] == first["reviewed_at"]
    assert _active_note_count(conn, candidate["exp_cand_id"]) == 0


def test_approve_recovers_when_note_appears_concurrently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = _fixture_db(tmp_path)
    _insert_outcome(
        conn,
        "run_race",
        status="success",
        tests_status="passed",
        memory_effect="helped",
        task_type="validation",
    )
    _fake_eval(monkeypatch, memory_effect="helped")
    [candidate] = experience.extract_candidates(conn, "run_race")
    row = conn.execute(
        "SELECT * FROM experience_candidates WHERE exp_cand_id = ?",
        (candidate["exp_cand_id"],),
    ).fetchone()
    existing_note_id = experience._create_experience_note(conn, row)
    conn.commit()
    real_lookup = experience._active_note_id_for_candidate
    calls = {"count": 0}

    def racing_lookup(conn_arg: sqlite3.Connection, exp_cand_id: str) -> str | None:
        calls["count"] += 1
        if calls["count"] == 1:
            return None
        return real_lookup(conn_arg, exp_cand_id)

    monkeypatch.setattr(experience, "_active_note_id_for_candidate", racing_lookup)

    approved = experience.approve_candidate(conn, candidate["exp_cand_id"])

    assert approved["state"] == "approved"
    assert approved["note_id"] == existing_note_id
    assert _active_note_count(conn, candidate["exp_cand_id"]) == 1


def test_approve_rejects_unknown_candidate_kind(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "run_weird_kind")
    conn.execute(
        """
        INSERT INTO experience_candidates(
          exp_cand_id, run_id, outcome_id, task_type, kind, trigger,
          claim, suggested_action, evidence, state, created_at,
          reviewed_at, review_note
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "exp_cand_weird",
            "run_weird_kind",
            None,
            "validation",
            "weird",
            None,
            "claim",
            "action",
            "{}",
            "pending",
            "2026-06-13T00:00:00+00:00",
            None,
            None,
        ),
    )
    conn.commit()

    with pytest.raises(ValueError, match="invalid kind: weird"):
        experience.approve_candidate(conn, "exp_cand_weird")
    assert _active_note_count(conn, "exp_cand_weird") == 0


def test_extract_warns_on_stderr_when_eval_crashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    conn = _fixture_db(tmp_path)
    _insert_outcome(
        conn,
        "run_eval_crash",
        status="failed",
        tests_status="not_run",
        memory_effect="failed_to_help",
        task_type="validation",
    )

    def boom(root: Path | str, run_id: str) -> dict[str, object]:
        raise RuntimeError("eval exploded")

    monkeypatch.setattr(experience.behavior_eval, "evaluate_run", boom)

    assert experience.extract_candidates(conn, "run_eval_crash") == []
    captured = capsys.readouterr()
    assert "warning: eval unavailable for run_eval_crash: RuntimeError" in captured.err


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


def _insert_outcome(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    status: str,
    tests_status: str,
    memory_effect: str,
    task_type: str,
) -> dict[str, object]:
    _insert_run(conn, run_id)
    return outcome.mark_outcome(
        conn,
        run_id,
        status=status,
        tests_status=tests_status,
        memory_effect=memory_effect,
        task_type=task_type,
    )


def _fake_eval(
    monkeypatch: pytest.MonkeyPatch,
    *,
    memory_effect: str,
    reason: str = "eval reason",
    rediscovery_count: int = 0,
    first_expected_command: str | None = "pnpm run test",
) -> None:
    def fake_evaluate_run(root: Path | str, run_id: str) -> dict[str, object]:
        return {
            "run_id": run_id,
            "memory_effect": memory_effect,
            "reason": reason,
            "rediscovery_count": rediscovery_count,
            "first_expected_command": first_expected_command,
        }

    monkeypatch.setattr(experience.behavior_eval, "evaluate_run", fake_evaluate_run)


def _active_note_for_candidate(conn: sqlite3.Connection, exp_cand_id: str) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT *
        FROM experience_notes
        WHERE source_cand_id = ? AND status = 'active'
        """,
        (exp_cand_id,),
    ).fetchone()
    assert row is not None
    return row


def _active_note_count(conn: sqlite3.Connection, exp_cand_id: str) -> int:
    return conn.execute(
        """
        SELECT COUNT(*)
        FROM experience_notes
        WHERE source_cand_id = ? AND status = 'active'
        """,
        (exp_cand_id,),
    ).fetchone()[0]
