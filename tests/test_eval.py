from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from omni import cli
from omni import db
import omni.eval as eval_module


def test_eval_run_reports_helped_when_expected_command_precedes_rediscovery(
    tmp_path: Path,
) -> None:
    conn = _fixture_db(tmp_path)
    _insert_fact(conn, "uses_test_command", "pnpm run test")
    _insert_event(conn, "warm_run", 1, tool="Bash", meta={"tool_input": {"command": "pnpm run test"}})
    _insert_event(conn, "warm_run", 2, tool="Read", meta={"tool_input": {"file_path": "README.md"}})
    conn.commit()

    result = eval_module.evaluate_run(tmp_path, "warm_run")

    assert result["run_id"] == "warm_run"
    assert result["active_expected_commands"]["uses_test_command"] == ["pnpm run test"]
    assert result["observed_commands"] == [
        {"seq": 1, "tool": "Bash", "command": "pnpm run test"}
    ]
    assert result["first_expected_command_position"] == 1
    assert result["expected_verification_executed"] is True
    assert result["rediscovery_events_before_first_expected_command"] == []
    assert result["memory_effect"] == "helped"


def test_eval_run_reports_failed_to_help_for_unihack_style_negative_sample(
    tmp_path: Path,
) -> None:
    conn = _fixture_db(tmp_path)
    _insert_fact(conn, "uses_test_command", "pnpm run test")
    _insert_event(conn, "negative_run", 1, tool="Read", meta={"tool_input": {"file_path": "CLAUDE.md"}})
    _insert_event(conn, "negative_run", 2, tool="Read", meta={"tool_input": {"file_path": "README.md"}})
    _insert_event(conn, "negative_run", 3, tool="Read", meta={"tool_input": {"file_path": "package.json"}})
    _insert_event(conn, "negative_run", 4, tool="Read", meta={"tool_input": {"file_path": "DEPLOY.md"}})
    _insert_event(conn, "negative_run", 5, tool="Glob", meta={"tool_input": {"pattern": "**/*.{json,md,ts,js}"}})
    conn.commit()

    result = eval_module.evaluate_run(tmp_path, "negative_run")

    assert result["claude_md_read"] is True
    assert result["memory_md_read"] is False
    assert result["expected_verification_executed"] is False
    assert result["first_expected_command_position"] is None
    assert [event["kind"] for event in result["rediscovery_events_before_first_expected_command"]] == [
        "README.md",
        "package.json",
        "DEPLOY.md",
        "broad_scan",
    ]
    assert result["memory_effect"] == "failed_to_help"
    assert "CLAUDE.md or memory was read" in result["reason"]


def test_eval_run_reports_neutral_when_expected_command_follows_rediscovery(
    tmp_path: Path,
) -> None:
    conn = _fixture_db(tmp_path)
    _insert_fact(conn, "uses_test_command", "pnpm run test")
    _insert_event(conn, "neutral_run", 1, tool="Read", meta={"tool_input": {"file_path": "README.md"}})
    _insert_event(conn, "neutral_run", 2, tool="Bash", meta={"tool_input": {"command": "pnpm run test"}})
    conn.commit()

    result = eval_module.evaluate_run(tmp_path, "neutral_run")

    assert result["first_expected_command_position"] == 2
    assert result["rediscovery_events_before_first_expected_command"][0]["kind"] == "README.md"
    assert result["memory_effect"] == "neutral"


def test_eval_run_reports_unknown_without_facts_or_events(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "empty_run")
    conn.commit()

    result = eval_module.evaluate_run(tmp_path, "empty_run")

    assert result["active_expected_commands"]["uses_test_command"] == []
    assert result["observed_commands"] == []
    assert result["memory_effect"] == "unknown"
    assert "insufficient evidence" in result["reason"]


def test_eval_run_missing_database_reports_unknown_without_creating_layout(
    tmp_path: Path,
) -> None:
    result = eval_module.evaluate_run(tmp_path, "missing_run")

    assert result["memory_effect"] == "unknown"
    assert result["reason"] == "insufficient evidence: OmniMemory database is missing"
    assert not (tmp_path / ".omni").exists()


def test_eval_dogfood_reports_improvement_when_warm_has_less_rediscovery(
    tmp_path: Path,
) -> None:
    conn = _fixture_db(tmp_path)
    _insert_fact(conn, "uses_test_command", "pnpm run test")
    _insert_event(conn, "cold_run", 1, tool="Read", meta={"tool_input": {"file_path": "README.md"}})
    _insert_event(conn, "cold_run", 2, tool="Read", meta={"tool_input": {"file_path": "package.json"}})
    _insert_event(conn, "cold_run", 3, tool="Bash", meta={"tool_input": {"command": "pnpm run test"}})
    _insert_event(conn, "warm_run", 1, tool="Read", meta={"tool_input": {"file_path": "README.md"}})
    _insert_event(conn, "warm_run", 2, tool="Bash", meta={"tool_input": {"command": "pnpm run test"}})
    conn.commit()

    result = eval_module.evaluate_dogfood(tmp_path, cold_run_id="cold_run", warm_run_id="warm_run")

    assert result["cold_rediscovery_count"] == 2
    assert result["warm_rediscovery_count"] == 1
    assert result["cold_first_expected_command_position"] == 3
    assert result["warm_first_expected_command_position"] == 2
    assert result["improvement"] is True
    assert result["memory_effect_summary"] == {
        "cold": "neutral",
        "warm": "neutral",
        "summary": "warm reduced rediscovery or reached expected commands earlier",
    }


def test_eval_run_cli_outputs_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    conn = _fixture_db(tmp_path)
    _insert_fact(conn, "uses_test_command", "pnpm run test")
    _insert_event(conn, "cli_run", 1, tool="Bash", meta={"tool_input": {"command": "pnpm run test"}})
    conn.commit()
    monkeypatch.chdir(tmp_path)

    assert cli.main(["eval", "run", "cli_run"]) == 0
    output = json.loads(capsys.readouterr().out)

    assert output["run_id"] == "cli_run"
    assert output["memory_effect"] == "helped"


def _fixture_db(root: Path) -> sqlite3.Connection:
    (root / ".omni").mkdir()
    conn = db.connect(root / ".omni" / "omni.sqlite3")
    db.migrate(conn)
    return conn


def _insert_run(conn: sqlite3.Connection, run_id: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO runs(run_id, project_id, snapshot_seq, status) VALUES(?,?,?,?)",
        (run_id, "project", 0, "closed"),
    )


def _insert_fact(conn: sqlite3.Connection, predicate: str, command: str) -> None:
    conn.execute(
        """
        INSERT INTO facts(
          fact_id, scope, subject, predicate, qualifier, object_norm, value_type,
          claim, trust, confidence, sensitivity, origin, pinned, created_seq,
          retired_seq, superseded_by, last_confirmed_at, created_at, evidence
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            f"fact_{predicate}_{command.replace(' ', '_')}",
            "project",
            ".",
            predicate,
            "node",
            command,
            "string",
            f"Use {command}",
            2,
            None,
            "low",
            "script_extractor@1",
            0,
            1,
            None,
            None,
            None,
            "2026-06-13T00:00:00Z",
            "{}",
        ),
    )


def _insert_event(
    conn: sqlite3.Connection,
    run_id: str,
    seq: int,
    *,
    tool: str,
    meta: dict[str, object],
) -> None:
    _insert_run(conn, run_id)
    conn.execute(
        """
        INSERT INTO events(
          event_id, run_id, seq, hook_seq, ts, event_type, tool, tool_use_id,
          input_ref, output_ref, exit_code, duration_ms, redaction_status,
          redaction_ver, source, meta
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            f"evt_{run_id}_{seq}",
            run_id,
            seq,
            None,
            f"2026-06-13T00:00:{seq:02d}Z",
            "PostToolUse",
            tool,
            f"toolu_{run_id}_{seq}",
            None,
            None,
            0,
            None,
            "clean",
            1,
            "hook",
            json.dumps(meta, sort_keys=True),
        ),
    )
