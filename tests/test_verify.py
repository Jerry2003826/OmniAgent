from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

from omni import cli
from omni import db
from omni import verify


def test_verify_preflight_runs_selected_test_command(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    script = _script(tmp_path, "pass_verify.py", "print('verify ok')\n")
    command = _python_command(script)
    _insert_fact(conn, command)

    result = verify.run_preflight(conn, tmp_path)

    assert result["status"] == "passed"
    assert result["command"] == command
    assert result["qualifier"] == "node"
    assert result["exit_code"] == 0
    assert result["stdout_excerpt"] == "verify ok"
    assert result["stderr_excerpt"] == ""
    assert result["timed_out"] is False


def test_verify_preflight_reports_failed_command(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    script = _script(
        tmp_path,
        "fail_verify.py",
        "import sys\nprint('bad stderr', file=sys.stderr)\nraise SystemExit(7)\n",
    )
    _insert_fact(conn, _python_command(script))

    result = verify.run_preflight(conn, tmp_path)

    assert result["status"] == "failed"
    assert result["exit_code"] == 7
    assert result["stderr_excerpt"] == "bad stderr"
    assert result["reason"] == "verification command failed with exit code 7"


def test_verify_preflight_prefers_unscoped_qualifier_over_scoped_commands(
    tmp_path: Path,
) -> None:
    conn = _fixture_db(tmp_path)
    base_script = _script(tmp_path, "base_verify.py", "print('base')\n")
    scoped_script = _script(tmp_path, "scoped_verify.py", "raise SystemExit(9)\n")
    base_command = _python_command(base_script)
    _insert_fact(conn, base_command, qualifier="node")
    _insert_fact(conn, _python_command(scoped_script), qualifier="node:web")

    result = verify.run_preflight(conn, tmp_path)

    assert result["status"] == "passed"
    assert result["qualifier"] == "node"
    assert result["command"] == base_command
    assert result["stdout_excerpt"] == "base"


def test_verify_preflight_reports_unknown_for_ambiguous_test_commands(
    tmp_path: Path,
) -> None:
    conn = _fixture_db(tmp_path)
    _insert_fact(conn, "echo node", qualifier="node")
    _insert_fact(conn, "echo python", qualifier="python")

    result = verify.run_preflight(conn, tmp_path)

    assert result["status"] == "unknown"
    assert result["reason"] == "ambiguous active uses_test_command facts"
    assert result["command"] is None
    assert result["candidate_commands"] == [
        {"qualifier": "node", "command": "echo node"},
        {"qualifier": "python", "command": "echo python"},
    ]


def test_verify_preflight_reports_unknown_without_active_test_command(
    tmp_path: Path,
) -> None:
    conn = _fixture_db(tmp_path)
    _insert_fact(conn, "echo retired")
    conn.execute("UPDATE facts SET retired_seq = 2")
    conn.commit()

    result = verify.run_preflight(conn, tmp_path)

    assert result["status"] == "unknown"
    assert result["reason"] == "no active uses_test_command facts"
    assert result["candidate_commands"] == []


def test_verify_preflight_does_not_execute_shell_operator_commands(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    _insert_fact(conn, "echo before && echo after")

    result = verify.run_preflight(conn, tmp_path)

    assert result["status"] == "unknown"
    assert result["stdout_excerpt"] == ""
    assert result["reason"] == (
        "could not parse verification command: shell operators are not supported"
    )


def test_verify_preflight_rejects_attached_shell_operator_commands(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    script = _script(tmp_path, "semicolon_verify.py", "raise SystemExit(0)\n")
    _insert_fact(conn, f'{_python_command(script)}; false')

    result = verify.run_preflight(conn, tmp_path)

    assert result["status"] == "unknown"
    assert result["reason"] == (
        "could not parse verification command: shell operators are not supported"
    )


def test_verify_preflight_rejects_or_shell_operator_commands(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    _insert_fact(conn, "echo before || echo fallback")

    result = verify.run_preflight(conn, tmp_path)

    assert result["status"] == "unknown"
    assert result["reason"] == (
        "could not parse verification command: shell operators are not supported"
    )


@pytest.mark.parametrize(
    ("command", "expected_filter"),
    [
        ('pytest -k "api|cli;smoke"', "api|cli;smoke"),
        ('pytest -k "|"', "|"),
        ('pytest -k ";"', ";"),
        ('pytest -k "&&"', "&&"),
    ],
)
def test_verify_command_args_allows_quoted_operator_characters_in_arguments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    expected_filter: str,
) -> None:
    def fake_which(executable: str, path: str | None = None) -> str | None:
        return "C:\\Tools\\pytest.exe" if executable == "pytest" else None

    monkeypatch.setattr(verify.shutil, "which", fake_which)

    assert verify._command_args(command, tmp_path) == [
        "C:\\Tools\\pytest.exe",
        "-k",
        expected_filter,
    ]


def test_verify_command_args_preserves_unquoted_parentheses_in_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_which(executable: str, path: str | None = None) -> str | None:
        return "C:\\Tools\\python.exe" if executable == "python" else None

    monkeypatch.setattr(verify.shutil, "which", fake_which)

    assert verify._command_args("python run(lint).py", tmp_path) == [
        "C:\\Tools\\python.exe",
        "run(lint).py",
    ]


def test_verify_command_args_preserves_hash_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_which(executable: str, path: str | None = None) -> str | None:
        return "C:\\Tools\\pytest.exe" if executable == "pytest" else None

    monkeypatch.setattr(verify.shutil, "which", fake_which)

    assert verify._command_args("pytest -k issue#123", tmp_path) == [
        "C:\\Tools\\pytest.exe",
        "-k",
        "issue#123",
    ]


@pytest.mark.parametrize(
    "command",
    [
        'bash -c "echo before && echo after"',
        'bash -cl "echo before && echo after"',
        'bash.exe -c "echo before && echo after"',
        'sh.exe -c "echo before && echo after"',
        'cmd.exe /c "echo before && echo after"',
        'pwsh -e "ZQBjAGgAbwAgAGIAZQBmAG8AcgBl"',
        'pwsh -ec "ZQBjAGgAbwAgAGIAZQBmAG8AcgBl"',
        'pwsh -CommandWithArgs "echo before && echo after"',
        'pwsh -cwa "echo before && echo after"',
        'env bash -c "echo before && echo after"',
        'env FOO=bar bash -c "echo before && echo after"',
        '/usr/bin/env pwsh -Command "echo before && echo after"',
    ],
)
def test_verify_command_args_rejects_shell_interpreter_wrappers(
    tmp_path: Path,
    command: str,
) -> None:
    with pytest.raises(
        ValueError,
        match="could not parse verification command: shell interpreter wrappers",
    ):
        verify._command_args(command, tmp_path)


def test_verify_command_args_does_not_reject_non_command_shell_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_which(executable: str, path: str | None = None) -> str | None:
        return "C:\\Tools\\sh.exe" if executable == "sh" else None

    monkeypatch.setattr(verify.shutil, "which", fake_which)

    assert verify._command_args("sh -cluster script.sh", tmp_path) == [
        "C:\\Tools\\sh.exe",
        "-cluster",
        "script.sh",
    ]


def test_verify_preflight_decodes_invalid_bytes_lossily(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    script = _script(
        tmp_path,
        "bytes_verify.py",
        (
            "import sys\n"
            "sys.stdout.buffer.write(bytes([255, 254, 10]))\n"
            "sys.stderr.buffer.write(bytes([253, 10]))\n"
        ),
    )
    _insert_fact(conn, _python_command(script))

    result = verify.run_preflight(conn, tmp_path)

    assert result["status"] == "passed"
    assert "\ufffd" in result["stdout_excerpt"]
    assert "\ufffd" in result["stderr_excerpt"]


def test_verify_preflight_bounds_large_output_while_running(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    script = _script(
        tmp_path,
        "large_output_verify.py",
        "import sys\nsys.stdout.buffer.write(b'x' * 200000)\n",
    )
    _insert_fact(conn, _python_command(script))

    result = verify.run_preflight(conn, tmp_path)

    assert result["status"] == "passed"
    assert len(result["stdout_excerpt"]) <= verify.MAX_OUTPUT_CHARS
    assert result["stdout_excerpt"].endswith("...[truncated]")


def test_verify_command_args_resolves_path_executable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_which(executable: str, path: str | None = None) -> str | None:
        return "C:\\Tools\\pnpm.CMD" if executable == "pnpm" else None

    monkeypatch.setattr(verify.shutil, "which", fake_which)

    assert verify._command_args("pnpm run test", tmp_path) == [
        "C:\\Tools\\pnpm.CMD",
        "run",
        "test",
    ]


def test_verify_command_args_resolves_relative_path_entries_against_verify_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    absolute_bin = tmp_path / "global-bin"
    monkeypatch.setenv("PATH", f"node_modules/.bin{os.pathsep}{absolute_bin}")
    calls: list[str | None] = []

    def fake_which(executable: str, path: str | None = None) -> str | None:
        calls.append(path)
        return str(root / "node_modules" / ".bin" / "pytest") if executable == "pytest" else None

    monkeypatch.setattr(verify.shutil, "which", fake_which)

    args = verify._command_args("pytest -q", root)
    path_entries = str(calls[0]).split(os.pathsep)

    assert args == [str(root / "node_modules" / ".bin" / "pytest"), "-q"]
    assert path_entries[0] == str(root / "node_modules" / ".bin")
    assert path_entries[1] == str(absolute_bin)


def test_verify_command_args_rejects_batch_metacharacters_for_batch_targets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_which(executable: str, path: str | None = None) -> str | None:
        return "C:\\Tools\\pnpm.CMD" if executable == "pnpm" else None

    monkeypatch.setattr(verify.shutil, "which", fake_which)

    with pytest.raises(ValueError, match="Windows batch metacharacters"):
        verify._command_args("pnpm run test -- --grep ok & type .env", tmp_path)


def test_verify_json_redacts_stdout_and_stderr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    canary = "verify-redaction-canary-123456"
    monkeypatch.setenv("OMNI_VERIFY_TOKEN", canary)
    conn = _fixture_db(tmp_path)
    script = _script(
        tmp_path,
        "redact_verify.py",
        (
            "import os, sys\n"
            "value = os.environ['OMNI_VERIFY_TOKEN']\n"
            "print(value)\n"
            "print(value, file=sys.stderr)\n"
        ),
    )
    _insert_fact(conn, _python_command(script))

    encoded = verify.as_json(verify.run_preflight(conn, tmp_path))

    assert canary not in encoded
    assert "REDACTED:" in encoded


def test_cli_verify_outputs_json_and_returns_command_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    conn = _fixture_db(tmp_path)
    script = _script(tmp_path, "cli_pass.py", "print('cli ok')\n")
    _insert_fact(conn, _python_command(script))
    conn.close()
    monkeypatch.chdir(tmp_path)

    code = cli.main(["verify", "--timeout-seconds", "10"])
    captured = capsys.readouterr()
    output = json.loads(captured.out)

    assert code == 0
    assert captured.err == ""
    assert output["status"] == "passed"
    assert output["stdout_excerpt"] == "cli ok"


def test_cli_verify_failed_command_returns_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    conn = _fixture_db(tmp_path)
    script = _script(tmp_path, "cli_fail.py", "raise SystemExit(3)\n")
    _insert_fact(conn, _python_command(script))
    conn.close()
    monkeypatch.chdir(tmp_path)

    code = cli.main(["verify"])
    output = json.loads(capsys.readouterr().out)

    assert code == 1
    assert output["status"] == "failed"
    assert output["exit_code"] == 3


def test_cli_verify_unknown_command_returns_two(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    conn = _fixture_db(tmp_path)
    conn.close()
    monkeypatch.chdir(tmp_path)

    code = cli.main(["verify"])
    captured = capsys.readouterr()
    output = json.loads(captured.out)

    assert code == 2
    assert captured.err == ""
    assert output["status"] == "unknown"
    assert output["reason"] == "no active uses_test_command facts"


def test_cli_verify_missing_db_does_not_create_omni(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    code = cli.main(["verify"])
    captured = capsys.readouterr()

    assert code == 2
    assert "OmniMemory database not found" in captured.err
    assert captured.out == ""
    assert not (tmp_path / ".omni").exists()


def test_connect_project_readonly_supports_verify_and_blocks_writes(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    script = _script(tmp_path, "readonly_verify.py", "print('ok')\n")
    _insert_fact(conn, _python_command(script))
    conn.close()

    readonly = verify.connect_project_readonly(tmp_path)
    try:
        result = verify.run_preflight(readonly, tmp_path)
        with pytest.raises(sqlite3.OperationalError):
            readonly.execute("INSERT INTO meta(key, value) VALUES('probe', '1')")
    finally:
        readonly.close()

    assert result["status"] == "passed"


def _fixture_db(root: Path) -> sqlite3.Connection:
    (root / ".omni").mkdir()
    conn = db.connect(root / ".omni" / "omni.sqlite3")
    db.migrate(conn)
    return conn


def _insert_fact(
    conn: sqlite3.Connection,
    command: str,
    *,
    qualifier: str = "node",
) -> None:
    safe_id = "".join(ch if ch.isalnum() else "_" for ch in f"{qualifier}_{command}")[:80]
    conn.execute(
        """
        INSERT INTO facts(
          fact_id, scope, subject, predicate, qualifier, object_norm, value_type,
          claim, trust, confidence, sensitivity, origin, pinned, created_seq,
          retired_seq, superseded_by, last_confirmed_at, created_at, evidence
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            f"fact_{safe_id}",
            "project",
            ".",
            "uses_test_command",
            qualifier,
            command,
            "string",
            f"Use {command}",
            2,
            None,
            "low",
            "test",
            0,
            1,
            None,
            None,
            None,
            "2026-06-13T00:00:00Z",
            "{}",
        ),
    )
    conn.commit()


def _script(root: Path, name: str, body: str) -> Path:
    path = root / name
    path.write_text(body, encoding="utf-8")
    return path


def _python_command(script: Path) -> str:
    return f'"{sys.executable}" "{script}"'
