from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from omni import cli
from omni import db
import omni.eval as eval_module
import omni.redact as redact_module


def test_eval_run_reports_helped_when_expected_command_precedes_rediscovery(
    tmp_path: Path,
) -> None:
    conn = _fixture_db(tmp_path)
    _insert_fact(conn, "uses_test_command", "pnpm run test")
    _insert_event(conn, "warm_run", 1, tool="Read", meta={"tool_input": {"file_path": "CLAUDE.md"}})
    _insert_event(conn, "warm_run", 2, tool="Bash", meta={"tool_input": {"command": "pnpm run test"}})
    _insert_event(conn, "warm_run", 3, tool="Read", meta={"tool_input": {"file_path": "README.md"}})
    conn.commit()

    result = eval_module.evaluate_run(tmp_path, "warm_run")

    assert result["run_id"] == "warm_run"
    assert result["active_expected_commands"]["uses_test_command"] == ["pnpm run test"]
    assert result["observed_commands"] == [
        {"seq": 2, "tool": "Bash", "command": "pnpm run test"}
    ]
    assert result["first_expected_command_position"] == 2
    assert result["expected_verification_executed"] is True
    assert result["rediscovery_events_before_first_expected_command"] == []
    assert result["memory_effect"] == "helped"


def test_eval_run_keeps_memory_effect_neutral_without_memory_evidence(
    tmp_path: Path,
) -> None:
    conn = _fixture_db(tmp_path)
    _insert_fact(conn, "uses_test_command", "pnpm run test")
    _insert_event(conn, "aligned_run", 1, tool="Bash", meta={"tool_input": {"command": "pnpm run test"}})
    conn.commit()

    result = eval_module.evaluate_run(tmp_path, "aligned_run")

    assert result["first_expected_command_position"] == 1
    assert result["rediscovery_events_before_first_expected_command"] == []
    assert result["memory_effect"] == "neutral"
    assert "memory context not observed" in result["reason"]


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
    assert "CLAUDE.md or memory context was seen" in result["reason"]
    assert "expected commands include pnpm run test" in result["reason"]
    assert "no expected verification command executed" in result["reason"]
    assert "README.md" in result["reason"]
    assert "package.json" in result["reason"]
    assert "DEPLOY.md" in result["reason"]
    assert "broad_scan" in result["reason"]


def test_eval_run_does_not_dump_raw_event_payload_in_json_output(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    _insert_fact(conn, "uses_test_command", "pnpm run test")
    raw_payload = "README.md\n" + ("private project narrative " * 80)
    _insert_event(
        conn,
        "safe_output_run",
        1,
        tool="Read",
        meta={"tool_response": {"stdout": raw_payload}},
    )
    conn.commit()

    encoded = eval_module.as_json(eval_module.evaluate_run(tmp_path, "safe_output_run"))

    assert "private project narrative" not in encoded
    assert "rediscovery_events_before_first_expected_command" in encoded


def test_eval_json_caps_large_observed_commands_without_payload_truncation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(redact_module, "_MAX_FULL_REDACTION_BYTES", 64 * 1024)
    conn = _fixture_db(tmp_path)
    _insert_fact(conn, "uses_test_command", "pnpm run test")
    _insert_event(conn, "large_run", 1, tool="Read", meta={"tool_input": {"file_path": "CLAUDE.md"}})
    for index in range(120):
        _insert_event(
            conn,
            "large_run",
            index + 2,
            tool="Read",
            meta={"tool_input": {"file_path": f"packages/pkg-{index}/package.json"}},
        )
    for index in range(5000):
        command = f"echo command-{index} {'x' * 80}"
        _insert_event(
            conn,
            "large_run",
            index + 200,
            tool="Bash",
            meta={"tool_input": {"command": command}},
        )
    conn.commit()

    encoded = eval_module.as_json(eval_module.evaluate_run(tmp_path, "large_run"))
    if "payload_truncated" in encoded:
        pytest.fail("eval JSON used payload_truncated wrapper")
    parsed = json.loads(encoded)

    assert len(parsed["observed_commands"]) == 100
    assert parsed["observed_commands_omitted"] == 4900
    assert len(parsed["rediscovery_events_before_first_expected_command"]) == 100
    assert parsed["rediscovery_events_omitted"] == 20
    assert all(len(command["command"]) <= 200 for command in parsed["observed_commands"])


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


@pytest.mark.parametrize(
    ("observed", "matches"),
    [
        ("pnpm run test", True),
        ("pnpm run test -- --watch=false", True),
        ("pnpm test", True),
        ("npm test", False),
    ],
)
def test_eval_run_matches_expected_commands_conservatively(
    tmp_path: Path, observed: str, matches: bool
) -> None:
    conn = _fixture_db(tmp_path)
    _insert_fact(conn, "uses_test_command", "pnpm run test")
    _insert_event(conn, "match_run", 1, tool="Read", meta={"tool_input": {"file_path": "CLAUDE.md"}})
    _insert_event(conn, "match_run", 2, tool="Bash", meta={"tool_input": {"command": observed}})
    conn.commit()

    result = eval_module.evaluate_run(tmp_path, "match_run")

    assert result["expected_verification_executed"] is matches
    assert result["first_expected_command_position"] == (2 if matches else None)
    assert result["memory_effect"] == ("helped" if matches else "unknown")


@pytest.mark.parametrize(
    ("tool", "meta", "expected_kind"),
    [
        ("Read", {"tool_input": {"file_path": "package.json"}}, "package.json"),
        ("Read", {"tool_input": {"file_path": "README.md"}}, "README.md"),
        ("Read", {"tool_input": {"file_path": "DEPLOY.md"}}, "DEPLOY.md"),
        ("Glob", {"tool_input": {"pattern": "**/*.{json,md,ts,js}"}}, "broad_scan"),
        ("Bash", {"tool_input": {"command": "ls"}}, "broad_scan"),
        ("Bash", {"tool_input": {"command": "find . -maxdepth 2 -type f"}}, "broad_scan"),
        ("Bash", {"tool_input": {"command": "tree -L 2"}}, "broad_scan"),
        ("Bash", {"tool_input": {"command": "rg --files"}}, "broad_scan"),
    ],
)
def test_eval_run_counts_rediscovery_from_tool_input(
    tmp_path: Path, tool: str, meta: dict[str, object], expected_kind: str
) -> None:
    conn = _fixture_db(tmp_path)
    _insert_fact(conn, "uses_test_command", "pnpm run test")
    _insert_event(conn, "rediscovery_run", 1, tool=tool, meta=meta)
    conn.commit()

    result = eval_module.evaluate_run(tmp_path, "rediscovery_run")

    assert [event["kind"] for event in result["rediscovery_events_before_first_expected_command"]] == [
        expected_kind
    ]


def test_eval_run_ignores_rediscovery_mentions_from_tool_output_alone(
    tmp_path: Path,
) -> None:
    conn = _fixture_db(tmp_path)
    _insert_fact(conn, "uses_test_command", "pnpm run test")
    _insert_event(conn, "output_run", 1, tool="Read", meta={"tool_input": {"file_path": "CLAUDE.md"}})
    _insert_event(
        conn,
        "output_run",
        2,
        tool="Bash",
        meta={"tool_response": {"stdout": "README.md\npackage.json\nDEPLOY.md"}},
    )
    _insert_event(conn, "output_run", 3, tool="Bash", meta={"tool_input": {"command": "pnpm run test"}})
    conn.commit()

    result = eval_module.evaluate_run(tmp_path, "output_run")

    assert result["rediscovery_events_before_first_expected_command"] == []
    assert result["memory_effect"] == "helped"


def test_eval_run_ignores_commands_from_tool_output_alone(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    _insert_fact(conn, "uses_test_command", "pnpm run test")
    _insert_event(conn, "output_command_run", 1, tool="Read", meta={"tool_input": {"file_path": "CLAUDE.md"}})
    _insert_event(
        conn,
        "output_command_run",
        2,
        tool="Bash",
        meta={"tool_response": {"command": "pnpm run test"}},
    )
    conn.commit()

    result = eval_module.evaluate_run(tmp_path, "output_command_run")

    assert result["observed_commands"] == []
    assert result["expected_verification_executed"] is False
    assert result["first_expected_command_position"] is None


def test_eval_run_ignores_context_fields_for_hard_eval_signals(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    _insert_fact(conn, "uses_test_command", "pnpm run test")
    _insert_event(
        conn,
        "context_run",
        1,
        tool="Bash",
        meta={
            "message": {
                "content": [
                    {"text": "README.md package.json DEPLOY.md"},
                    {"command": "pnpm run test"},
                ]
            },
            "toolUseResult": {
                "command": "pnpm run test",
                "stdout": "README.md\npackage.json\nDEPLOY.md",
            },
        },
    )
    conn.commit()

    result = eval_module.evaluate_run(tmp_path, "context_run")

    assert result["observed_commands"] == []
    assert result["rediscovery_events_before_first_expected_command"] == []
    assert result["expected_verification_executed"] is False


def test_eval_run_ignores_input_containers_under_unknown_contexts(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    _insert_fact(conn, "uses_test_command", "pnpm run test")
    _insert_event(
        conn,
        "unknown_context_run",
        1,
        tool="Bash",
        meta={
            "transcript": {
                "input": {"command": "pnpm run test"},
                "parameters": {"file_path": "README.md"},
            }
        },
    )
    conn.commit()

    result = eval_module.evaluate_run(tmp_path, "unknown_context_run")

    assert result["observed_commands"] == []
    assert result["rediscovery_events_before_first_expected_command"] == []
    assert result["expected_verification_executed"] is False


def test_eval_run_ignores_output_alias_input_containers(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    _insert_fact(conn, "uses_test_command", "pnpm run test")
    _insert_event(
        conn,
        "output_alias_run",
        1,
        tool="Bash",
        meta={
            "tool_result": {
                "input": {"command": "pnpm run test"},
                "parameters": {"file_path": "package.json"},
            },
            "response": {"args": {"pattern": "**/*"}},
        },
    )
    conn.commit()

    result = eval_module.evaluate_run(tmp_path, "output_alias_run")

    assert result["observed_commands"] == []
    assert result["rediscovery_events_before_first_expected_command"] == []
    assert result["expected_verification_executed"] is False


def test_eval_run_reads_reconciled_hook_input_for_hard_eval_signals(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    _insert_fact(conn, "uses_test_command", "pnpm run test")
    _insert_event(
        conn,
        "reconciled_run",
        1,
        tool="Bash",
        meta={
            "transcript": {
                "toolUseResult": {
                    "command": "pnpm run test",
                    "stdout": "README.md\npackage.json",
                }
            },
            "hook": {"tool_input": {"command": "pnpm run test"}},
        },
    )
    conn.commit()

    result = eval_module.evaluate_run(tmp_path, "reconciled_run")

    assert result["observed_commands"] == [
        {"seq": 1, "tool": "Bash", "command": "pnpm run test"}
    ]
    assert result["rediscovery_events_before_first_expected_command"] == []
    assert result["expected_verification_executed"] is True


def test_eval_run_marks_memory_seen_without_expected_command_when_intent_unknown(
    tmp_path: Path,
) -> None:
    conn = _fixture_db(tmp_path)
    _insert_fact(conn, "uses_test_command", "pnpm run test")
    _insert_event(
        conn,
        "memory_only_run",
        1,
        tool="Read",
        meta={"tool_input": {"file_path": "CLAUDE.md"}},
    )
    conn.commit()

    result = eval_module.evaluate_run(tmp_path, "memory_only_run")

    assert result["memory_context_seen_but_no_expected_command"] is True
    assert result["memory_effect"] == "unknown"
    assert "memory context observed but no expected command and no rediscovery" in result["reason"]


def test_eval_run_reports_unknown_without_facts_or_events(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    _insert_run(conn, "empty_run")
    conn.commit()

    result = eval_module.evaluate_run(tmp_path, "empty_run")

    assert result["active_expected_commands"]["uses_test_command"] == []
    assert result["observed_commands"] == []
    assert result["memory_effect"] == "unknown"
    assert "insufficient evidence" in result["reason"]


def test_eval_run_reports_unknown_without_active_facts(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    _insert_event(conn, "no_facts_run", 1, tool="Bash", meta={"tool_input": {"command": "pnpm run test"}})
    conn.commit()

    result = eval_module.evaluate_run(tmp_path, "no_facts_run")

    assert result["memory_effect"] == "unknown"
    assert "no active expected facts" in result["reason"]


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
        "summary": "warm adopted expected command or reduced rediscovery",
    }


def test_eval_dogfood_reports_improvement_when_warm_adopts_command_after_cold_missed(
    tmp_path: Path,
) -> None:
    conn = _fixture_db(tmp_path)
    _insert_fact(conn, "uses_test_command", "pnpm run test")
    _insert_event(conn, "cold_run", 1, tool="Read", meta={"tool_input": {"file_path": "CLAUDE.md"}})
    _insert_event(conn, "cold_run", 2, tool="Read", meta={"tool_input": {"file_path": "README.md"}})
    _insert_event(conn, "warm_run", 1, tool="Read", meta={"tool_input": {"file_path": "CLAUDE.md"}})
    _insert_event(conn, "warm_run", 2, tool="Bash", meta={"tool_input": {"command": "pnpm run test"}})
    conn.commit()

    result = eval_module.evaluate_dogfood(tmp_path, cold_run_id="cold_run", warm_run_id="warm_run")

    assert result["cold_first_expected_command_position"] is None
    assert result["warm_first_expected_command_position"] == 2
    assert result["improvement"] is True
    assert result["memory_effect_summary"]["summary"] == (
        "warm adopted expected command or reduced rediscovery"
    )


def test_eval_dogfood_does_not_improve_when_cold_run_is_missing(
    tmp_path: Path,
) -> None:
    conn = _fixture_db(tmp_path)
    _insert_fact(conn, "uses_test_command", "pnpm run test")
    _insert_event(conn, "warm_run", 1, tool="Read", meta={"tool_input": {"file_path": "CLAUDE.md"}})
    _insert_event(conn, "warm_run", 2, tool="Bash", meta={"tool_input": {"command": "pnpm run test"}})
    conn.commit()

    result = eval_module.evaluate_dogfood(tmp_path, cold_run_id="missing_run", warm_run_id="warm_run")

    assert result["cold_comparable"] is False
    assert result["command_adopted"] is False
    assert result["improvement"] is False
    assert result["memory_effect_summary"]["summary"] == "cold run not comparable"


def test_eval_dogfood_does_not_improve_when_cold_run_has_no_events(
    tmp_path: Path,
) -> None:
    conn = _fixture_db(tmp_path)
    _insert_fact(conn, "uses_test_command", "pnpm run test")
    _insert_run(conn, "cold_run")
    _insert_event(conn, "warm_run", 1, tool="Read", meta={"tool_input": {"file_path": "CLAUDE.md"}})
    _insert_event(conn, "warm_run", 2, tool="Bash", meta={"tool_input": {"command": "pnpm run test"}})
    conn.commit()

    result = eval_module.evaluate_dogfood(tmp_path, cold_run_id="cold_run", warm_run_id="warm_run")

    assert result["cold_comparable"] is False
    assert result["command_adopted"] is False
    assert result["improvement"] is False
    assert result["memory_effect_summary"]["summary"] == "cold run not comparable"


def test_eval_dogfood_reports_no_improvement_when_warm_fails_to_run_expected_command(
    tmp_path: Path,
) -> None:
    conn = _fixture_db(tmp_path)
    _insert_fact(conn, "uses_test_command", "pnpm run test")
    _insert_event(conn, "cold_run", 1, tool="Read", meta={"tool_input": {"file_path": "README.md"}})
    _insert_event(conn, "cold_run", 2, tool="Read", meta={"tool_input": {"file_path": "package.json"}})
    _insert_event(conn, "cold_run", 3, tool="Bash", meta={"tool_input": {"command": "pnpm run test"}})
    _insert_event(conn, "warm_run", 1, tool="Read", meta={"tool_input": {"file_path": "CLAUDE.md"}})
    _insert_event(conn, "warm_run", 2, tool="Read", meta={"tool_input": {"file_path": "README.md"}})
    conn.commit()

    result = eval_module.evaluate_dogfood(tmp_path, cold_run_id="cold_run", warm_run_id="warm_run")

    assert result["improvement"] is False
    assert result["memory_effect_summary"] == {
        "cold": "neutral",
        "warm": "failed_to_help",
        "summary": "no measurable warm-run improvement",
    }


def test_eval_run_cli_outputs_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    conn = _fixture_db(tmp_path)
    _insert_fact(conn, "uses_test_command", "pnpm run test")
    _insert_event(conn, "cli_run", 1, tool="Read", meta={"tool_input": {"file_path": "CLAUDE.md"}})
    _insert_event(conn, "cli_run", 2, tool="Bash", meta={"tool_input": {"command": "pnpm run test"}})
    conn.commit()
    monkeypatch.chdir(tmp_path)

    assert cli.main(["eval", "run", "cli_run"]) == 0
    output = json.loads(capsys.readouterr().out)

    assert output["run_id"] == "cli_run"
    assert output["memory_effect"] == "helped"


def test_eval_json_redacts_final_output(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    secret = "sk-" + "a" * 48
    _insert_fact(conn, "uses_test_command", "pnpm run test")
    _insert_event(
        conn,
        "secret_run",
        1,
        tool="Bash",
        meta={"tool_input": {"command": f"curl -H 'Authorization: Bearer {secret}' /health"}},
    )
    conn.commit()

    encoded = eval_module.as_json(eval_module.evaluate_run(tmp_path, "secret_run"))

    assert secret not in encoded
    assert "REDACTED:" in encoded


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
