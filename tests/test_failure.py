from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from omni import cli
from omni import db
from omni import failure
from omni import render


def test_migration_006_creates_failure_patterns_and_sets_schema_version(
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
    assert "failure_patterns" in tables
    assert db.schema_version(conn) == "8"
    failure_candidate_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(failure_candidates)")
    }
    assert "pattern_id" in failure_candidate_columns
    assert {
        "idx_failure_candidates_state",
        "idx_failure_candidates_run",
        "idx_failure_candidates_signature",
        "uq_failure_candidate_run_signature",
        "idx_failure_patterns_scope",
        "idx_failure_patterns_signature",
        "uq_failure_patterns_active_source",
        "uq_failure_patterns_active_signature",
    }.issubset(indexes)


def test_migration_001_to_006_path_works(tmp_path: Path) -> None:
    (tmp_path / ".omni").mkdir()
    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")
    conn.executescript(db.migration_sql("001_init.sql"))
    conn.commit()

    db.migrate(conn)

    assert db.schema_version(conn) == "8"
    assert conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'failure_candidates'"
    ).fetchone()
    assert conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'failure_patterns'"
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


def test_unix_path_is_redacted_in_error_signature(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "run_unix_path")
    _insert_event(
        conn,
        "run_unix_path",
        1,
        event_type="PostToolUseFailure",
        tool="Read",
        meta={"error": "ENOENT: no such file or directory, open /repo/app/missing.txt"},
    )

    [candidate] = failure.extract_candidates(conn, "run_unix_path")

    assert candidate["error_signature"] == "ENOENT: no such file or directory, open <path>"


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


def test_exit_code_is_extracted_from_text_without_event_exit_code(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "run_exit_text")
    _insert_event(
        conn,
        "run_exit_text",
        1,
        tool="Bash",
        meta={
            "tool_input": {"command": "pnpm run build"},
            "tool_response": {"stderr": "Build failed\nExit code: 2"},
        },
    )

    [candidate] = failure.extract_candidates(conn, "run_exit_text")

    assert candidate["failure_kind"] == "command_failed"
    assert candidate["exit_code"] == 2


def test_shell_output_with_plain_exit_text_does_not_create_candidate(
    tmp_path: Path,
) -> None:
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "run_plain_exit_text")
    _insert_event(
        conn,
        "run_plain_exit_text",
        1,
        tool="Bash",
        meta={
            "tool_input": {"command": "pnpm run dev"},
            "tool_response": {"stdout": "Press q to exit 1 panel"},
        },
    )

    assert failure.extract_candidates(conn, "run_plain_exit_text") == []


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
    secret = "-".join(("failure", "secret", "value", "123"))
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


def test_secret_in_command_norm_is_redacted_in_candidate_and_pattern(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "-".join(("failure", "command", "secret", "123"))
    monkeypatch.setenv("OMNI_FAILURE_COMMAND_SECRET", secret)
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "run_secret_command")
    _insert_event(
        conn,
        "run_secret_command",
        1,
        tool="Bash",
        exit_code=1,
        meta={
            "tool_input": {
                "command": f'curl -H "Authorization: Bearer {secret}" https://example.invalid'
            },
            "tool_response": {"stderr": "curl failed"},
        },
    )

    [candidate] = failure.extract_candidates(conn, "run_secret_command")
    approved = failure.approve_candidate(
        conn,
        candidate["failure_cand_id"],
        summary="Curl failed.",
        suggested_action="Use a safe local repro without inline secrets.",
    )
    candidate_row = conn.execute(
        """
        SELECT command_norm, evidence
        FROM failure_candidates
        WHERE failure_cand_id = ?
        """,
        (candidate["failure_cand_id"],),
    ).fetchone()
    pattern = conn.execute(
        """
        SELECT command_norm, evidence
        FROM failure_patterns
        WHERE pattern_id = ?
        """,
        (approved["pattern_id"],),
    ).fetchone()
    encoded = failure.as_json(approved)

    assert secret not in candidate_row["command_norm"]
    assert secret not in candidate_row["evidence"]
    assert secret not in pattern["command_norm"]
    assert secret not in pattern["evidence"]
    assert secret not in encoded
    assert "REDACTED:" in candidate_row["command_norm"]
    assert "REDACTED:" in pattern["command_norm"]


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


def test_approve_pending_candidate_creates_active_failure_pattern(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    candidate = _create_failure_candidate(conn, run_id="run_approve")

    approved = failure.approve_candidate(
        conn,
        candidate["failure_cand_id"],
        summary="Build failed because dependency resolution failed.",
        suggested_action="Inspect the package manager and lockfile before changing installs.",
    )

    pattern = conn.execute(
        "SELECT * FROM failure_patterns WHERE pattern_id = ?",
        (approved["pattern_id"],),
    ).fetchone()
    evidence = json.loads(pattern["evidence"])

    assert approved["state"] == "approved"
    assert approved["pattern_id"]
    assert approved["reviewed_at"]
    assert pattern["source_failure_cand_id"] == candidate["failure_cand_id"]
    assert pattern["scope"] == "project"
    assert pattern["command_norm"] == "pnpm run build"
    assert pattern["failure_kind"] == "command_failed"
    assert pattern["error_signature"] == "Build failed"
    assert pattern["error_signature_hash"] == candidate["error_signature_hash"]
    assert pattern["summary"] == "Build failed because dependency resolution failed."
    assert pattern["suggested_action"] == (
        "Inspect the package manager and lockfile before changing installs."
    )
    assert pattern["trust"] == 2
    assert pattern["status"] == "active"
    assert pattern["created_seq"] == 1
    assert evidence["source_failure_cand_id"] == candidate["failure_cand_id"]
    assert evidence["run_id"] == "run_approve"
    assert evidence["event_id"] == candidate["event_id"]
    assert evidence["tool_use_id"] == candidate["tool_use_id"]
    assert evidence["command_norm"] == "pnpm run build"
    assert evidence["exit_code"] == 1
    assert evidence["failure_kind"] == "command_failed"
    assert evidence["error_signature_hash"] == candidate["error_signature_hash"]
    assert evidence["candidate_evidence"] == candidate["evidence"]
    assert "stderr" not in json.dumps(evidence).lower()


def test_approve_same_candidate_twice_is_idempotent(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    candidate = _create_failure_candidate(conn, run_id="run_idempotent")

    first = failure.approve_candidate(
        conn,
        candidate["failure_cand_id"],
        summary="First summary.",
        suggested_action="First action.",
    )
    second = failure.approve_candidate(
        conn,
        candidate["failure_cand_id"],
        summary="Different summary ignored for idempotent approve.",
        suggested_action="Different action ignored for idempotent approve.",
    )

    assert second == first
    assert conn.execute("SELECT COUNT(*) FROM failure_patterns").fetchone()[0] == 1


def test_approve_second_candidate_reuses_active_signature_pattern(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    first_candidate = _create_failure_candidate(conn, run_id="run_first_same")
    second_candidate = _create_failure_candidate(conn, run_id="run_second_same")

    first = failure.approve_candidate(
        conn,
        first_candidate["failure_cand_id"],
        summary="Shared failure.",
        suggested_action="Use the existing remediation.",
    )
    second = failure.approve_candidate(
        conn,
        second_candidate["failure_cand_id"],
        summary="Would duplicate.",
        suggested_action="Would duplicate.",
    )

    assert second["pattern_id"] == first["pattern_id"]
    assert conn.execute("SELECT COUNT(*) FROM failure_patterns").fetchone()[0] == 1
    assert conn.execute(
        "SELECT source_failure_cand_id FROM failure_patterns WHERE pattern_id = ?",
        (first["pattern_id"],),
    ).fetchone()["source_failure_cand_id"] == first_candidate["failure_cand_id"]


def test_list_show_and_retire_failure_pattern(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    candidate = _create_failure_candidate(conn, run_id="run_pattern_lifecycle")
    approved = failure.approve_candidate(
        conn,
        candidate["failure_cand_id"],
        summary="Known build failure.",
        suggested_action="Use the known remediation.",
    )
    pattern_id = approved["pattern_id"]

    active_patterns = failure.list_patterns(conn)
    shown = failure.show_pattern(conn, pattern_id)
    retired = failure.retire_pattern(conn, pattern_id)
    retired_again = failure.retire_pattern(conn, pattern_id)

    assert active_patterns == [shown]
    assert shown["pattern_id"] == pattern_id
    assert shown["status"] == "active"
    assert shown["lifecycle"] == {
        "renders": True,
        "can_retire": True,
        "can_reactivate": False,
        "supersede_supported": False,
        "message": "active pattern renders into memory.md; retire it to stop rendering",
    }
    assert shown["evidence"]["run_id"] == "run_pattern_lifecycle"
    assert retired["pattern_id"] == pattern_id
    assert retired["status"] == "retired"
    assert retired["lifecycle"] == {
        "renders": False,
        "can_retire": False,
        "can_reactivate": False,
        "supersede_supported": False,
        "message": (
            "retired pattern does not render into memory.md; "
            "v0 does not reactivate retired patterns"
        ),
    }
    assert retired["retired_seq"] is not None
    assert retired["created_at"] == shown["created_at"]
    assert retired["updated_at"] >= shown["updated_at"]
    assert retired_again == retired
    assert failure.list_patterns(conn) == []
    assert failure.list_patterns(conn, status="retired") == [retired]
    assert failure.list_patterns(conn, status="all") == [retired]
    assert failure.show_candidate(conn, candidate["failure_cand_id"])["state"] == "approved"
    assert failure.show_candidate(conn, candidate["failure_cand_id"])["pattern_id"] == pattern_id


def test_approved_candidate_with_retired_pattern_reports_reactivation_boundary(
    tmp_path: Path,
) -> None:
    conn = _fixture_db(tmp_path)
    candidate = _create_failure_candidate(conn, run_id="run_retired_reapprove")
    approved = failure.approve_candidate(
        conn,
        candidate["failure_cand_id"],
        summary="Known failure.",
        suggested_action="Known action.",
    )

    failure.retire_pattern(conn, approved["pattern_id"])

    with pytest.raises(
        ValueError,
        match=(
            f"failure pattern for {candidate['failure_cand_id']} was retired; "
            "v0 does not reactivate retired patterns"
        ),
    ):
        failure.approve_candidate(
            conn,
            candidate["failure_cand_id"],
            summary="Known failure.",
            suggested_action="Known action.",
        )


def test_retired_failure_pattern_no_longer_renders(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    candidate = _create_failure_candidate(conn, run_id="run_retire_render")
    approved = failure.approve_candidate(
        conn,
        candidate["failure_cand_id"],
        summary="Known build failure.",
        suggested_action="Use the known remediation.",
    )

    before = render.render_project(conn, tmp_path)
    before_text = before.path.read_text(encoding="utf-8")
    retired = failure.retire_pattern(conn, approved["pattern_id"])
    after = render.render_project(conn, tmp_path)
    after_text = after.path.read_text(encoding="utf-8")

    assert retired["status"] == "retired"
    assert "## Known Failures" in before_text
    assert "pnpm run build" in before_text
    assert "## Known Failures" not in after_text
    assert "pnpm run build" not in after_text
    assert approved["pattern_id"] not in before_text
    assert approved["pattern_id"] not in after_text


def test_failure_candidate_state_machine_for_approve_and_reject(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    approved_candidate = _create_failure_candidate(conn, run_id="run_state_approved")
    rejected_candidate = _create_failure_candidate(
        conn,
        run_id="run_state_rejected",
        stderr="Different failure",
    )
    pending_reject_candidate = _create_failure_candidate(
        conn,
        run_id="run_state_pending_reject",
        stderr="Third failure",
    )

    approved = failure.approve_candidate(
        conn,
        approved_candidate["failure_cand_id"],
        summary="Known build failure.",
        suggested_action="Use the known remediation.",
    )
    rejected = failure.reject_candidate(conn, rejected_candidate["failure_cand_id"])
    rejected_again = failure.reject_candidate(conn, rejected_candidate["failure_cand_id"])
    pending_rejected = failure.reject_candidate(conn, pending_reject_candidate["failure_cand_id"])

    with pytest.raises(
        ValueError,
        match=f"approved failure candidate cannot be rejected in v0: {approved_candidate['failure_cand_id']}",
    ):
        failure.reject_candidate(conn, approved_candidate["failure_cand_id"])
    with pytest.raises(
        ValueError,
        match=f"rejected failure candidate cannot be approved in v0: {rejected_candidate['failure_cand_id']}",
    ):
        failure.approve_candidate(
            conn,
            rejected_candidate["failure_cand_id"],
            summary="No",
            suggested_action="No",
        )

    assert approved["state"] == "approved"
    assert rejected["state"] == "rejected"
    assert rejected_again == rejected
    assert pending_rejected["state"] == "rejected"
    assert pending_rejected["pattern_id"] is None
    assert failure.list_candidates(conn, state="approved") == [approved]


def test_approve_requires_summary_and_suggested_action(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    candidate = _create_failure_candidate(conn, run_id="run_required")

    with pytest.raises(ValueError, match="summary is required"):
        failure.approve_candidate(
            conn,
            candidate["failure_cand_id"],
            summary=" ",
            suggested_action="Do something.",
        )
    with pytest.raises(ValueError, match="suggested_action is required"):
        failure.approve_candidate(
            conn,
            candidate["failure_cand_id"],
            summary="Known failure.",
            suggested_action=" ",
        )


def test_secret_in_approval_text_is_redacted_in_db_and_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "-".join(("failure", "pattern", "secret", "123"))
    monkeypatch.setenv("OMNI_FAILURE_PATTERN_SECRET", secret)
    conn = _fixture_db(tmp_path)
    candidate = _create_failure_candidate(conn, run_id="run_pattern_secret")

    approved = failure.approve_candidate(
        conn,
        candidate["failure_cand_id"],
        summary=f"Summary mentions {secret}",
        suggested_action=f"Action mentions {secret}",
    )
    pattern = conn.execute(
        "SELECT summary, suggested_action, evidence FROM failure_patterns WHERE pattern_id = ?",
        (approved["pattern_id"],),
    ).fetchone()
    encoded = failure.as_json(approved)

    assert secret not in pattern["summary"]
    assert secret not in pattern["suggested_action"]
    assert secret not in pattern["evidence"]
    assert secret not in encoded
    assert "REDACTED:" in pattern["summary"]
    assert "REDACTED:" in pattern["suggested_action"]


def test_show_unknown_candidate_raises_clear_error(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)

    with pytest.raises(ValueError, match="unknown failure candidate: missing"):
        failure.show_candidate(conn, "missing")


def test_show_and_retire_unknown_pattern_raise_clear_error(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)

    with pytest.raises(ValueError, match="unknown failure pattern: missing"):
        failure.show_pattern(conn, "missing")
    with pytest.raises(ValueError, match="unknown failure pattern: missing"):
        failure.retire_pattern(conn, "missing")


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


def test_cli_failure_approve_works(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    conn = _fixture_db(tmp_path)
    candidate = _create_failure_candidate(conn, run_id="run_cli_approve")
    conn.close()
    monkeypatch.chdir(tmp_path)

    approve_code = cli.main(
        [
            "failure",
            "approve",
            candidate["failure_cand_id"],
            "--summary",
            "Tests failed because dependency resolution failed.",
            "--suggested-action",
            "Inspect the lockfile before changing package managers.",
        ]
    )
    approved = json.loads(capsys.readouterr().out)
    ls_code = cli.main(["failure", "ls", "--state", "approved"])
    listed = json.loads(capsys.readouterr().out)

    assert approve_code == 0
    assert approved["state"] == "approved"
    assert approved["pattern_id"]
    assert ls_code == 0
    assert listed["candidates"][0]["failure_cand_id"] == candidate["failure_cand_id"]
    assert listed["candidates"][0]["pattern_id"] == approved["pattern_id"]


def test_cli_failure_pattern_ls_show_retire_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    conn = _fixture_db(tmp_path)
    candidate = _create_failure_candidate(conn, run_id="run_cli_pattern")
    approved = failure.approve_candidate(
        conn,
        candidate["failure_cand_id"],
        summary="Known failure.",
        suggested_action="Known action.",
    )
    conn.close()
    monkeypatch.chdir(tmp_path)

    ls_code = cli.main(["failure", "pattern", "ls"])
    listed = json.loads(capsys.readouterr().out)
    show_code = cli.main(["failure", "pattern", "show", approved["pattern_id"]])
    shown = json.loads(capsys.readouterr().out)
    retire_code = cli.main(["failure", "pattern", "retire", approved["pattern_id"]])
    retired = json.loads(capsys.readouterr().out)
    active_code = cli.main(["failure", "pattern", "ls"])
    active = json.loads(capsys.readouterr().out)
    retired_ls_code = cli.main(["failure", "pattern", "ls", "--status", "retired"])
    retired_ls = json.loads(capsys.readouterr().out)

    assert ls_code == 0
    assert listed["patterns"][0]["pattern_id"] == approved["pattern_id"]
    assert listed["patterns"][0]["status"] == "active"
    assert listed["patterns"][0]["lifecycle"]["renders"] is True
    assert listed["patterns"][0]["lifecycle"]["can_retire"] is True
    assert show_code == 0
    assert shown["pattern_id"] == approved["pattern_id"]
    assert shown["lifecycle"]["message"] == (
        "active pattern renders into memory.md; retire it to stop rendering"
    )
    assert retire_code == 0
    assert retired["status"] == "retired"
    assert retired["lifecycle"] == {
        "renders": False,
        "can_retire": False,
        "can_reactivate": False,
        "supersede_supported": False,
        "message": (
            "retired pattern does not render into memory.md; "
            "v0 does not reactivate retired patterns"
        ),
    }
    assert retired["retired_seq"] is not None
    assert active_code == 0
    assert active == {"patterns": []}
    assert retired_ls_code == 0
    assert retired_ls["patterns"][0]["pattern_id"] == approved["pattern_id"]
    assert retired_ls["patterns"][0]["lifecycle"]["renders"] is False


def test_cli_failure_approve_retired_pattern_exits_2_with_clear_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    conn = _fixture_db(tmp_path)
    candidate = _create_failure_candidate(conn, run_id="run_cli_retired_reapprove")
    approved = failure.approve_candidate(
        conn,
        candidate["failure_cand_id"],
        summary="Known failure.",
        suggested_action="Known action.",
    )
    failure.retire_pattern(conn, approved["pattern_id"])
    conn.close()
    monkeypatch.chdir(tmp_path)

    code = cli.main(
        [
            "failure",
            "approve",
            candidate["failure_cand_id"],
            "--summary",
            "Known failure.",
            "--suggested-action",
            "Known action.",
        ]
    )
    captured = capsys.readouterr()

    assert code == 2
    assert (
        f"failure pattern for {candidate['failure_cand_id']} was retired; "
        "v0 does not reactivate retired patterns"
    ) in captured.err
    assert captured.out == ""


def test_cli_failure_approve_requires_summary_and_suggested_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    conn = _fixture_db(tmp_path)
    candidate = _create_failure_candidate(conn, run_id="run_cli_required")
    conn.close()
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as missing_summary:
        cli.main(
            [
                "failure",
                "approve",
                candidate["failure_cand_id"],
                "--suggested-action",
                "Do something.",
            ]
        )
    summary_captured = capsys.readouterr()
    with pytest.raises(SystemExit) as missing_action:
        cli.main(
            [
                "failure",
                "approve",
                candidate["failure_cand_id"],
                "--summary",
                "Known failure.",
            ]
        )
    action_captured = capsys.readouterr()

    assert missing_summary.value.code == 2
    assert "the following arguments are required: --summary" in summary_captured.err
    assert missing_action.value.code == 2
    assert "the following arguments are required: --suggested-action" in action_captured.err


def test_cli_failure_approve_error_paths_exit_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    conn = _fixture_db(tmp_path)
    rejected_candidate = _create_failure_candidate(conn, run_id="run_cli_rejected")
    approved_candidate = _create_failure_candidate(
        conn,
        run_id="run_cli_approved",
        stderr="approved failure",
    )
    failure.reject_candidate(conn, rejected_candidate["failure_cand_id"])
    failure.approve_candidate(
        conn,
        approved_candidate["failure_cand_id"],
        summary="Known failure.",
        suggested_action="Known action.",
    )
    conn.close()
    monkeypatch.chdir(tmp_path)

    unknown_code = cli.main(
        [
            "failure",
            "approve",
            "missing_candidate",
            "--summary",
            "Missing.",
            "--suggested-action",
            "Missing.",
        ]
    )
    unknown = capsys.readouterr()
    rejected_code = cli.main(
        [
            "failure",
            "approve",
            rejected_candidate["failure_cand_id"],
            "--summary",
            "Rejected.",
            "--suggested-action",
            "Rejected.",
        ]
    )
    rejected = capsys.readouterr()
    approved_reject_code = cli.main(["failure", "reject", approved_candidate["failure_cand_id"]])
    approved_reject = capsys.readouterr()

    assert unknown_code == 2
    assert "unknown failure candidate: missing_candidate" in unknown.err
    assert rejected_code == 2
    assert "rejected failure candidate cannot be approved in v0" in rejected.err
    assert approved_reject_code == 2
    assert "approved failure candidate cannot be rejected in v0" in approved_reject.err


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


def test_cli_unknown_pattern_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    conn = _fixture_db(tmp_path)
    conn.close()
    monkeypatch.chdir(tmp_path)

    show_code = cli.main(["failure", "pattern", "show", "missing_pattern"])
    show_captured = capsys.readouterr()
    retire_code = cli.main(["failure", "pattern", "retire", "missing_pattern"])
    retire_captured = capsys.readouterr()

    assert show_code == 2
    assert "unknown failure pattern: missing_pattern" in show_captured.err
    assert show_captured.out == ""
    assert retire_code == 2
    assert "unknown failure pattern: missing_pattern" in retire_captured.err
    assert retire_captured.out == ""


def test_command_not_found_exit_127_is_skipped(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "run_127")
    _insert_event(
        conn,
        "run_127",
        1,
        event_type="PostToolUseFailure",
        tool="Bash",
        tool_use_id="toolu_probe",
        exit_code=127,
        meta={
            "tool_input": {"command": "bash -lc 'pnpm run test'"},
            "tool_response": {"stderr": "bash: command not found"},
        },
    )
    _insert_event(
        conn,
        "run_127",
        2,
        tool="Bash",
        tool_use_id="toolu_real",
        exit_code=1,
        meta={
            "tool_input": {"command": "pnpm run test"},
            "tool_response": {"stderr": "1 test failed"},
        },
    )

    candidates = failure.extract_candidates(conn, "run_127")

    assert [candidate["exit_code"] for candidate in candidates] == [1]


def test_only_command_not_found_yields_no_candidates(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "run_127_only")
    _insert_event(
        conn,
        "run_127_only",
        1,
        event_type="PostToolUseFailure",
        tool="Bash",
        tool_use_id="toolu_probe",
        exit_code=127,
        meta={
            "tool_input": {"command": "bash -lc 'pnpm run test'"},
            "tool_response": {"stderr": "bash: command not found"},
        },
    )

    assert failure.extract_candidates(conn, "run_127_only") == []


def _create_failure_candidate(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    stderr: str = "Build failed",
    command: str = "pnpm run build",
    exit_code: int = 1,
) -> dict[str, object]:
    _insert_run(conn, run_id)
    _insert_event(
        conn,
        run_id,
        1,
        tool="Bash",
        tool_use_id=f"toolu_{run_id}",
        exit_code=exit_code,
        meta={
            "tool_input": {"command": command},
            "tool_response": {"stderr": stderr},
        },
    )
    [candidate] = failure.extract_candidates(conn, run_id)
    return candidate


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
