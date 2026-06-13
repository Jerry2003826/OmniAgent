from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from omni import cli
from omni import db
from omni import failure


def test_migration_005_creates_failure_candidates_and_sets_schema_version(
    tmp_path: Path,
) -> None:
    conn = _fixture_db(tmp_path)

    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    indexes = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        )
    }

    assert "failure_candidates" in tables
    assert db.schema_version(conn) == "5"
    assert {
        "idx_failure_candidates_state",
        "idx_failure_candidates_run",
        "idx_failure_candidates_signature",
        "uq_failure_candidate_run_signature",
    }.issubset(indexes)


def test_migration_001_to_005_path_works(tmp_path: Path) -> None:
    (tmp_path / ".omni").mkdir()
    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")
    conn.executescript(db.migration_sql("001_init.sql"))
    conn.commit()

    db.migrate(conn)

    assert db.schema_version(conn) == "5"
    assert conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'failure_candidates'"
    ).fetchone()


def test_post_tool_use_failure_creates_candidate(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "run_tool_fail")
    _insert_event(
        conn,
        "run_tool_fail",
        1,
        event_type="PostToolUseFailure",
        tool="Read",
        tool_use_id="toolu_read",
        meta={"error": "ENOENT: no such file or directory, open C:\\repo\\missing.txt"},
    )

    [candidate] = failure.extract_candidates(conn, "run_tool_fail")

    assert candidate["run_id"] == "run_tool_fail"
    assert candidate["event_id"] == "event_run_tool_fail_1"
    assert candidate["tool_use_id"] == "toolu_read"
    assert candidate["tool"] == "Read"
    assert candidate["failure_kind"] == "tool_failed"
    assert candidate["error_signature"] == "ENOENT: no such file or directory, open <path>"
    assert candidate["error_signature_hash"]
    assert candidate["state"] == "pending"
    assert candidate["evidence"]["event_type"] == "PostToolUseFailure"
    assert "meta" not in candidate["evidence"]


def test_bash_nonzero_exit_creates_command_failed_candidate(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "run_bash_fail")
    _insert_event(
        conn,
        "run_bash_fail",
        1,
        tool="Bash",
        exit_code=7,
        meta={
            "tool_input": {"command": "pnpm run test -- --watch=false"},
            "tool_response": {"stderr": "FAIL tests/foo.test.ts"},
        },
    )

    [candidate] = failure.extract_candidates(conn, "run_bash_fail")

    assert candidate["failure_kind"] == "command_failed"
    assert candidate["command_norm"] == "pnpm run test"
    assert candidate["exit_code"] == 7
    assert candidate["error_signature"] == "FAIL tests/foo.test.ts"


def test_successful_bash_event_does_not_create_candidate(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "run_success")
    _insert_event(
        conn,
        "run_success",
        1,
        tool="Bash",
        exit_code=0,
        meta={
            "tool_input": {"command": "pnpm run test"},
            "tool_response": {"stderr": "warning only"},
        },
    )

    assert failure.extract_candidates(conn, "run_success") == []
    assert failure.list_candidates(conn, state="all") == []


def test_interrupted_event_creates_interrupted_candidate(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "run_interrupted")
    _insert_event(
        conn,
        "run_interrupted",
        1,
        tool="Bash",
        meta={
            "tool_input": {"command": "python -m pytest tests/foo -q"},
            "toolUseResult": {"interrupted": True, "stderr": "Interrupted by user"},
        },
    )

    [candidate] = failure.extract_candidates(conn, "run_interrupted")

    assert candidate["failure_kind"] == "interrupted"
    assert candidate["command_norm"] == "python -m pytest"
    assert candidate["error_signature"] == "Interrupted by user"


def test_no_failure_events_returns_empty_created_zero(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "run_no_failures")

    assert failure.extract_candidates(conn, "run_no_failures") == []


def test_unknown_run_raises_clear_value_error(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)

    with pytest.raises(ValueError, match="unknown run: missing_run"):
        failure.extract_candidates(conn, "missing_run")


def test_duplicate_extract_does_not_duplicate_candidate(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "run_dedupe")
    _insert_event(
        conn,
        "run_dedupe",
        1,
        tool="Bash",
        exit_code=1,
        meta={
            "tool_input": {"command": "npm test"},
            "tool_response": {"stderr": "same failure"},
        },
    )

    first = failure.extract_candidates(conn, "run_dedupe")
    second = failure.extract_candidates(conn, "run_dedupe")

    assert len(first) == 1
    assert second == []
    assert len(failure.list_candidates(conn, state="all")) == 1


def test_rejected_candidate_is_not_recreated(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "run_rejected")
    _insert_event(
        conn,
        "run_rejected",
        1,
        tool="Bash",
        exit_code=1,
        meta={
            "tool_input": {"command": "pytest tests/foo -q"},
            "tool_response": {"stderr": "assertion failed"},
        },
    )
    [candidate] = failure.extract_candidates(conn, "run_rejected")

    rejected = failure.reject_candidate(conn, candidate["failure_cand_id"])
    recreated = failure.extract_candidates(conn, "run_rejected")

    assert rejected["state"] == "rejected"
    assert recreated == []
    assert len(failure.list_candidates(conn, state="all")) == 1


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("pnpm run test -- --watch=false", "pnpm run test"),
        ("pnpm test", "pnpm run test"),
        ("npm test", "npm run test"),
        ("yarn test", "yarn run test"),
        ("bun test", "bun test"),
        ("uv run pytest tests/foo -q", "uv run pytest"),
        ("python -m pytest tests/foo -q", "python -m pytest"),
        ("pytest tests/foo -q", "pytest"),
        ("bash -c 'echo error >&2; exit 7'", "bash"),
        ('cd "C:\\repo" ; pnpm run test 2>&1', "pnpm run test"),
        ('cd "C:\\repo\\apps\\web" ; pnpm test -- --run 2>&1', "pnpm run test"),
        ('cd "C:\\repo" ; pnpm run lint ; if ($?) { pnpm run test } 2>&1', "pnpm run lint"),
    ],
)
def test_command_normalization(raw: str, expected: str) -> None:
    assert failure.normalize_command(raw) == expected


def test_secret_in_stderr_is_redacted_in_db_and_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "failure-secret-value-123"
    monkeypatch.setenv("OMNI_FAILURE_SECRET", secret)
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "run_secret")
    _insert_event(
        conn,
        "run_secret",
        1,
        tool="Bash",
        exit_code=1,
        meta={
            "tool_input": {"command": "pnpm test"},
            "tool_response": {"stderr": f"Error: token {secret} failed"},
        },
    )

    [candidate] = failure.extract_candidates(conn, "run_secret")
    row = conn.execute(
        """
        SELECT stderr_excerpt, evidence
        FROM failure_candidates
        WHERE failure_cand_id = ?
        """,
        (candidate["failure_cand_id"],),
    ).fetchone()
    encoded = failure.as_json(candidate)

    assert secret not in row["stderr_excerpt"]
    assert secret not in row["evidence"]
    assert secret not in encoded
    assert "REDACTED:" in encoded
    assert secret not in json.dumps(candidate["evidence"])


def test_list_show_and_reject_candidates(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "run_review")
    _insert_event(
        conn,
        "run_review",
        1,
        tool="Bash",
        exit_code=1,
        meta={"tool_input": {"command": "uv run pytest tests/foo -q"}, "stderr": "boom"},
    )
    [candidate] = failure.extract_candidates(conn, "run_review")

    pending = failure.list_candidates(conn)
    shown = failure.show_candidate(conn, candidate["failure_cand_id"])
    rejected = failure.reject_candidate(conn, candidate["failure_cand_id"])
    rejected_again = failure.reject_candidate(conn, candidate["failure_cand_id"])

    assert pending == [candidate]
    assert shown == candidate
    assert rejected["state"] == "rejected"
    assert rejected_again == rejected
    assert failure.list_candidates(conn) == []
    assert failure.list_candidates(conn, state="rejected") == [rejected]
    assert failure.list_candidates(conn, state="all") == [rejected]


def test_show_unknown_candidate_raises_clear_error(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)

    with pytest.raises(ValueError, match="unknown failure candidate: missing"):
        failure.show_candidate(conn, "missing")


def test_cli_extract_ls_show_reject_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "run_cli")
    _insert_event(
        conn,
        "run_cli",
        1,
        tool="Bash",
        exit_code=1,
        meta={
            "tool_input": {"command": "python -m pytest tests/foo -q"},
            "tool_response": {"stderr": "failed cli"},
        },
    )
    conn.close()
    monkeypatch.chdir(tmp_path)

    extract_code = cli.main(["failure", "extract", "run_cli"])
    extracted = json.loads(capsys.readouterr().out)
    failure_cand_id = extracted["candidates"][0]["failure_cand_id"]
    ls_code = cli.main(["failure", "ls"])
    listed = json.loads(capsys.readouterr().out)
    show_code = cli.main(["failure", "show", failure_cand_id])
    shown = json.loads(capsys.readouterr().out)
    reject_code = cli.main(["failure", "reject", failure_cand_id])
    rejected = json.loads(capsys.readouterr().out)
    pending_code = cli.main(["failure", "ls"])
    pending = json.loads(capsys.readouterr().out)
    rejected_ls_code = cli.main(["failure", "ls", "--state", "rejected"])
    rejected_ls = json.loads(capsys.readouterr().out)

    assert extract_code == 0
    assert extracted["created"] == 1
    assert ls_code == 0
    assert listed["candidates"][0]["failure_cand_id"] == failure_cand_id
    assert show_code == 0
    assert shown["failure_cand_id"] == failure_cand_id
    assert reject_code == 0
    assert rejected["state"] == "rejected"
    assert pending_code == 0
    assert pending == {"candidates": []}
    assert rejected_ls_code == 0
    assert rejected_ls["candidates"][0]["failure_cand_id"] == failure_cand_id


def test_cli_unknown_run_and_candidate_exit_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    conn = _fixture_db(tmp_path)
    conn.close()
    monkeypatch.chdir(tmp_path)

    extract_code = cli.main(["failure", "extract", "missing_run"])
    extract_captured = capsys.readouterr()
    show_code = cli.main(["failure", "show", "missing_candidate"])
    show_captured = capsys.readouterr()

    assert extract_code == 2
    assert "unknown run: missing_run" in extract_captured.err
    assert extract_captured.out == ""
    assert show_code == 2
    assert "unknown failure candidate: missing_candidate" in show_captured.err
    assert show_captured.out == ""


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

def _insert_event(
    conn: sqlite3.Connection,
    run_id: str,
    seq: int,
    *,
    event_type: str = "PostToolUse",
    tool: str | None = None,
    tool_use_id: str | None = None,
    exit_code: int | None = None,
    meta: dict[str, object] | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO events(
          event_id, run_id, seq, hook_seq, ts, event_type, tool, tool_use_id,
          input_ref, output_ref, exit_code, duration_ms, redaction_status,
          redaction_ver, source, meta
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            f"event_{run_id}_{seq}",
            run_id,
            seq,
            None,
            "2026-06-13T00:00:00+00:00",
            event_type,
            tool,
            tool_use_id,
            None,
            None,
            exit_code,
            None,
            "clean",
            1,
            "test",
            json.dumps(meta or {}, sort_keys=True),
        ),
    )
    conn.commit()
