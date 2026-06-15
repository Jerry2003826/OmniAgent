from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from omni import cli
from omni import db
from omni import render
from omni import verify
from omni.dbaccess import connect_project_readonly
from omni.failure.repo import read_view as failure_read_view
from omni.render import READ_VIEW_SCHEMA_VERSION


REPO_ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_KEY_FRAGMENTS = (
    "run_id",
    "_cand_id",
    "note_id",
    "pattern_id",
    "evidence",
    "created_at",
    "updated_at",
    "confidence",
    "timestamp",
    "trust",
)


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


def assert_no_metadata_leak(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            key_lower = str(key).lower()
            for forbidden in FORBIDDEN_KEY_FRAGMENTS:
                assert forbidden not in key_lower, f"leaked key: {key}"
            assert_no_metadata_leak(item)
    elif isinstance(value, list):
        for item in value:
            assert_no_metadata_leak(item)
    elif isinstance(value, str):
        lowered = value.lower()
        assert "fact_" not in lowered
        assert "failure_cand_" not in lowered
        assert "exp_cand_" not in lowered


def connect(tmp_path: Path) -> sqlite3.Connection:
    (tmp_path / ".omni").mkdir()
    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")
    db.migrate(conn)
    return conn


def seed_project_facts(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        INSERT INTO facts(
          fact_id, scope, subject, predicate, qualifier, object_norm, value_type,
          claim, trust, confidence, sensitivity, origin, pinned, created_seq,
          retired_seq, superseded_by, last_confirmed_at, created_at, evidence
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "fact_test_cmd",
            "project",
            ".",
            "uses_test_command",
            "node",
            "pnpm run test",
            "string",
            "Use pnpm run test for Node tests.",
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


def seed_failure_pattern(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        INSERT INTO failure_patterns(
          pattern_id, source_failure_cand_id, scope, command_norm, failure_kind,
          error_signature, error_signature_hash, summary, suggested_action, trust,
          status, evidence, created_seq, retired_seq, superseded_by, created_at,
          updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "failure_pattern_read",
            "failure_cand_read",
            "project",
            "pnpm run build",
            "command_failed",
            "exit 1: dependency resolution failed",
            "hash_read",
            "Build failed because dependency resolution failed.",
            "Inspect the lockfile before changing package managers.",
            2,
            "active",
            json.dumps(
                {
                    "run_id": "run_hidden",
                    "pattern_id": "failure_pattern_read",
                    "confidence": 0.99,
                },
                sort_keys=True,
            ),
            1,
            None,
            None,
            "2026-06-13T00:00:00+00:00",
            "2026-06-13T00:00:00+00:00",
        ),
    )
    conn.commit()


def test_memory_read_view_shape_and_schema_version(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    seed_project_facts(conn)

    view = render.read_view(conn)
    conn.close()

    assert view["schema_version"] == READ_VIEW_SCHEMA_VERSION
    assert isinstance(view["sections"], list)
    assert any(section["kind"] == "Commands" for section in view["sections"])
    assert_no_metadata_leak(view)


def test_failure_read_view_shape_and_leak_free(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    seed_failure_pattern(conn)

    patterns = failure_read_view(conn)
    conn.close()

    assert len(patterns) == 1
    assert set(patterns[0]) <= {"summary", "suggested_action", "command_norm"}
    assert "Build failed because dependency resolution failed." in patterns[0]["summary"]
    assert_no_metadata_leak(patterns)


def test_verify_plan_view_shape_without_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = connect(tmp_path)
    seed_project_facts(conn)

    def fail_if_spawned(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("verify plan must not spawn a subprocess")

    monkeypatch.setattr(verify, "run_preflight", fail_if_spawned)

    plan = verify.plan_view(conn)
    conn.close()

    assert plan["schema_version"] == 1
    assert plan["predicate"] == "uses_test_command"
    assert plan["selection_mode"] == "auto"
    assert plan["candidate_commands"] == [{"qualifier": "node", "command": "pnpm run test"}]
    assert_no_metadata_leak(plan)


def test_read_commands_use_readonly_connection_without_migrate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = connect(tmp_path)
    seed_project_facts(conn)
    seed_failure_pattern(conn)
    conn.close()

    def fail_migrate(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("read commands must not migrate")

    monkeypatch.setattr(db, "migrate", fail_migrate)

    readonly = connect_project_readonly(tmp_path)
    try:
        render.read_view(readonly)
        failure_read_view(readonly)
        verify.plan_view(readonly)
    finally:
        readonly.close()


def test_cli_memory_read_smoke(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    seed_project_facts(conn)
    conn.close()

    result = run_omni(tmp_path, "memory", "read")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == READ_VIEW_SCHEMA_VERSION
    assert_no_metadata_leak(payload)


def test_cli_failure_read_smoke(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    seed_failure_pattern(conn)
    conn.close()

    result = run_omni(tmp_path, "failure", "read")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert isinstance(payload, list)
    assert_no_metadata_leak(payload)


def test_cli_verify_plan_smoke(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    conn = connect(tmp_path)
    seed_project_facts(conn)
    conn.close()
    monkeypatch.chdir(tmp_path)

    def fail_if_spawned(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("verify plan must not spawn a subprocess")

    monkeypatch.setattr(verify, "run_preflight", fail_if_spawned)

    code = cli.main(["verify", "plan"])
    captured = capsys.readouterr()

    assert code == 0
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["schema_version"] == 1
    assert payload["selection_mode"] == "auto"
    assert_no_metadata_leak(payload)