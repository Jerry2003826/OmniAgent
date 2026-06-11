from __future__ import annotations

import hashlib
import os
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from omni import cli
from omni import hook
from omni.ids import project_id_for_path

REPO_ROOT = Path(__file__).resolve().parents[1]
FAKE_GITHUB_TOKEN = "ghp_" + "abcdefghijklmnopqrstuvwxyz1234567890"
FAKE_AWS_KEY = "AKIA" + "IOSFODNN7EXAMPLE"


def rendered_memory(body: str = "# Project memory\n") -> str:
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return f"<!-- omni:generated render_ver=1 sha256={digest} DO NOT EDIT -->\n{body}"


def run_omni(
    cwd: Path,
    *args: str,
    input_text: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "omni.cli", *args],
        cwd=cwd,
        env=env,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )


def test_init_creates_layout_and_is_idempotent(tmp_path: Path) -> None:
    first = run_omni(tmp_path, "init")
    second = run_omni(tmp_path, "init")

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr

    omni_dir = tmp_path / ".omni"
    assert omni_dir.is_dir()
    for dirname in ("spool", "spike", "artifacts", "generated"):
        assert (omni_dir / dirname).is_dir()
    assert (omni_dir / "config.toml").read_text(encoding="utf-8")

    gitignore = (tmp_path / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert gitignore.count(".omni/") == 1
    assert ".claude/*.omni-tmp" in gitignore
    assert ".claude/settings.json.omni-bak" in gitignore
    assert [line for line in gitignore if line.startswith(".omni")] == [".omni/"]
    assert ".omni/generated/" not in gitignore
    assert ".omni/project_id" not in gitignore


def test_init_adds_entire_omni_ignore_when_narrow_entry_exists(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text(".omni/generated/\nnode_modules/\n", encoding="utf-8")

    result = run_omni(tmp_path, "init")

    assert result.returncode == 0, result.stderr
    gitignore = (tmp_path / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".omni/" in gitignore
    assert ".claude/*.omni-tmp" in gitignore
    assert ".claude/settings.json.omni-bak" in gitignore
    assert ".omni/project_id" not in gitignore


def test_init_creates_project_id_file_and_keeps_it_after_path_move(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    first = run_omni(repo, "init")

    assert first.returncode == 0, first.stderr
    project_id = (repo / ".omni" / "project_id").read_text(encoding="utf-8").strip()
    assert project_id.startswith("proj_")

    moved = tmp_path / "moved-repo"
    repo.rename(moved)

    assert project_id_for_path(moved) == project_id


def test_git_remote_project_id_is_stable_across_repo_paths(tmp_path: Path) -> None:
    remote = "https://github.com/example/omni-agent.git"
    ids: list[str] = []
    for name in ("repo-a", "repo-b"):
        repo = tmp_path / name
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, text=True, capture_output=True, check=True)
        subprocess.run(
            ["git", "remote", "add", "origin", remote],
            cwd=repo,
            text=True,
            capture_output=True,
            check=True,
        )
        result = run_omni(repo, "init")
        assert result.returncode == 0, result.stderr
        ids.append((repo / ".omni" / "project_id").read_text(encoding="utf-8").strip())

    assert ids[0] == ids[1]


def test_existing_project_id_wins_when_remote_changes_later(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, text=True, capture_output=True, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/example/original.git"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )
    init = run_omni(repo, "init")
    original_project_id = (repo / ".omni" / "project_id").read_text(encoding="utf-8").strip()

    assert init.returncode == 0, init.stderr

    subprocess.run(
        ["git", "remote", "set-url", "origin", "https://github.com/example/renamed.git"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )
    second_init = run_omni(repo, "init")

    assert second_init.returncode == 0, second_init.stderr
    assert project_id_for_path(repo) == original_project_id
    assert (repo / ".omni" / "project_id").read_text(encoding="utf-8").strip() == original_project_id


def test_init_does_not_modify_claude_settings(tmp_path: Path) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    settings = claude_dir / "settings.json"
    original = '{"hooks":[]}\n'
    settings.write_text(original, encoding="utf-8")

    result = run_omni(tmp_path, "init")

    assert result.returncode == 0, result.stderr
    assert settings.read_text(encoding="utf-8") == original
    assert not (claude_dir / "settings.json.omni-bak").exists()


def test_init_install_claude_hooks_requires_yes_until_audit_passes(tmp_path: Path) -> None:
    result = run_omni(tmp_path, "init", "--install-claude-hooks")

    assert result.returncode == 2
    assert "--yes" in result.stderr
    assert not (tmp_path / ".claude" / "settings.json").exists()


def test_init_install_claude_hooks_prints_diff_and_preserves_project_settings(
    tmp_path: Path,
) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    settings = claude_dir / "settings.json"
    diff_secret = "diff-secret-value-123456"
    original = json.dumps(
        {
            "permissions": {},
            "hooks": {
                "Notification": [
                    {
                        "matcher": "*",
                        "hooks": [
                            {
                                "type": "command",
                                "command": f"echo token={diff_secret}",
                            }
                        ],
                    }
                ]
            },
        },
        indent=2,
        sort_keys=True,
    ) + "\n"
    settings.write_text(original, encoding="utf-8")

    home = tmp_path / "home"
    global_claude = home / ".claude"
    global_claude.mkdir(parents=True)
    global_settings = global_claude / "settings.json"
    global_original = '{"hooks":{"Stop":[]}}\n'
    global_settings.write_text(global_original, encoding="utf-8")

    result = run_omni(
        tmp_path,
        "init",
        "--install-claude-hooks",
        "--yes",
        extra_env={"HOME": str(home), "USERPROFILE": str(home)},
    )

    assert result.returncode == 0, result.stderr
    assert "--- .claude/settings.json" in result.stdout
    assert "+++ .claude/settings.json (omni)" in result.stdout
    assert "omni.cli hook" in result.stdout
    assert diff_secret not in result.stdout
    assert not (claude_dir / "settings.json.omni-bak").exists()
    assert not (tmp_path / ".omni" / "backups").exists()
    assert global_settings.read_text(encoding="utf-8") == global_original

    updated = json.loads(settings.read_text(encoding="utf-8"))
    command = updated["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert updated["permissions"] == {}
    assert "omni.cli hook" in command
    assert command != "omni hook"
    user_commands = [
        handler["command"]
        for group in updated["hooks"]["Notification"]
        for handler in group["hooks"]
    ]
    assert f"echo token={diff_secret}" in user_commands
    assert updated["hooks"]["PostToolUse"][0]["hooks"][0]["command"] == command
    assert updated["hooks"]["Stop"][0]["hooks"][0]["command"] == command
    assert updated["hooks"]["SessionEnd"][0]["hooks"][0]["command"] == command


def test_install_claude_hooks_does_not_write_raw_settings_backup_under_omni(
    tmp_path: Path,
) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    secret = "sk-" + "settingsbackupsecretvalue1234567890"
    (claude_dir / "settings.json").write_text(
        json.dumps({"hooks": {}, "env": {"TOKEN": secret}}) + "\n",
        encoding="utf-8",
    )

    result = run_omni(tmp_path, "init", "--install-claude-hooks", "--yes")

    assert result.returncode == 0, result.stderr
    omni_files = [path for path in (tmp_path / ".omni").rglob("*") if path.is_file()]
    omni_bytes = b"".join(path.read_bytes() for path in omni_files)
    assert secret.encode("utf-8") not in omni_bytes
    assert not list((tmp_path / ".omni").glob("backups/*"))


def test_init_install_claude_hooks_redacts_printed_diff(tmp_path: Path) -> None:
    diff_secret = "diff-secret-value-123456"
    result = run_omni(
        tmp_path,
        "init",
        "--install-claude-hooks",
        "--yes",
        extra_env={"OMNI_HOOK_COMMAND": f"python -m omni.cli hook --token={diff_secret}"},
    )

    assert result.returncode == 0, result.stderr
    assert diff_secret not in result.stdout
    assert "REDACTED:secret_assignment:" in result.stdout
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert diff_secret in settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]


def test_install_claude_hooks_returned_diff_is_redacted(tmp_path: Path, monkeypatch) -> None:
    diff_secret = "diff-secret-value-123456"
    monkeypatch.setenv("OMNI_HOOK_COMMAND", f"python -m omni.cli hook --token={diff_secret}")

    result = hook.install_claude_hooks(tmp_path, yes=True)

    assert result.ok is True
    assert diff_secret not in result.diff
    assert "REDACTED:secret_assignment:" in result.diff
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert diff_secret in settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]


def test_install_claude_hooks_writes_settings_through_temp_file(
    tmp_path: Path, monkeypatch
) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    settings = claude_dir / "settings.json"
    original = '{"permissions":{}}\n'
    settings.write_text(original, encoding="utf-8")
    original_write_text = Path.write_text

    def fail_direct_final_write(
        self: Path,
        data: str,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> int:
        if self == settings and "omni.cli hook" in data:
            raise AssertionError("settings.json must be replaced from a temp file")
        return original_write_text(
            self, data, encoding=encoding, errors=errors, newline=newline
        )

    monkeypatch.setattr(Path, "write_text", fail_direct_final_write)

    result = hook.install_claude_hooks(tmp_path, yes=True)

    assert result.ok is True
    assert "omni.cli hook" in settings.read_text(encoding="utf-8")
    assert not (claude_dir / "settings.json.omni-tmp").exists()


def test_init_install_claude_hooks_fails_closed_on_invalid_project_settings(
    tmp_path: Path,
) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    settings = claude_dir / "settings.json"
    original = "{ invalid json\n"
    settings.write_text(original, encoding="utf-8")

    result = run_omni(tmp_path, "init", "--install-claude-hooks", "--yes")

    assert result.returncode == 2
    assert settings.read_text(encoding="utf-8") == original
    assert "invalid" in result.stderr.lower()
    assert "omni hook" not in settings.read_text(encoding="utf-8")
    assert not (claude_dir / "settings.json.omni-bak").exists()


def test_init_install_claude_hooks_fails_closed_on_non_object_project_settings(
    tmp_path: Path,
) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    settings = claude_dir / "settings.json"
    original = "[]\n"
    settings.write_text(original, encoding="utf-8")

    result = run_omni(tmp_path, "init", "--install-claude-hooks", "--yes")

    assert result.returncode == 2
    assert settings.read_text(encoding="utf-8") == original
    assert "json object" in result.stderr.lower()
    assert not (claude_dir / "settings.json.omni-bak").exists()


def test_install_claude_hooks_honors_hook_command_override(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("OMNI_HOOK_COMMAND", "custom omni hook")

    result = hook.install_claude_hooks(tmp_path, yes=True)
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))

    assert result.ok is True
    assert settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == "custom omni hook"


def test_install_claude_hooks_replaces_legacy_omni_hook_command(tmp_path: Path) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    settings = claude_dir / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "*",
                            "hooks": [
                                {"type": "command", "command": "omni hook", "timeout": 5},
                                {"type": "command", "command": "echo keep-user-hook"},
                            ],
                        }
                    ]
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = hook.install_claude_hooks(tmp_path, yes=True)
    updated = json.loads(settings.read_text(encoding="utf-8"))
    commands = [
        handler["command"]
        for group in updated["hooks"]["PreToolUse"]
        for handler in group["hooks"]
    ]
    omni_commands = [command for command in commands if "omni" in command]

    assert result.ok is True
    assert "omni hook" not in commands
    assert len(omni_commands) == 1
    assert "omni.cli hook" in omni_commands[0]
    assert "echo keep-user-hook" in commands


def test_init_install_claude_hooks_handles_utf8_bom_settings_with_non_utf8_stdout(tmp_path: Path) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    settings = claude_dir / "settings.json"
    original = b"\xef\xbb\xbf{\"permissions\":{}}\n"
    settings.write_bytes(original)

    result = run_omni(
        tmp_path,
        "init",
        "--install-claude-hooks",
        "--yes",
        extra_env={"PYTHONIOENCODING": "gbk"},
    )

    assert result.returncode == 0, result.stderr
    assert "UnicodeEncodeError" not in result.stderr
    assert not (claude_dir / "settings.json.omni-bak").exists()
    assert not (tmp_path / ".omni" / "backups").exists()


def test_cli_help_smoke(tmp_path: Path) -> None:
    result = run_omni(tmp_path, "--help")

    assert result.returncode == 0
    assert "init" in result.stdout
    assert "status" in result.stdout
    assert "doctor" not in result.stdout
    assert "review" not in result.stdout


def test_review_interactive_is_hidden_from_review_help(tmp_path: Path) -> None:
    result = run_omni(tmp_path, "review", "--help")

    assert result.returncode == 0
    assert "approve" in result.stdout
    assert "reject" in result.stdout
    assert "interactive" not in result.stdout


def test_review_interactive_cli_is_disabled_for_week1(tmp_path: Path) -> None:
    result = run_omni(tmp_path, "review", "interactive", input_text="")

    assert result.returncode == 2
    assert "experimental disabled in Week-1" in result.stderr
    assert not (tmp_path / ".omni").exists()


def test_status_cli_reports_project_state_without_creating_layout(tmp_path: Path) -> None:
    empty_status = run_omni(tmp_path, "status")

    assert empty_status.returncode == 0, empty_status.stderr
    assert not (tmp_path / ".omni").exists()
    empty = json.loads(empty_status.stdout)
    assert empty["ok"] is True
    assert empty["omni_dir"] is False
    assert empty["generated_memory"] is False
    assert empty["claude_link"] is False
    assert "hook_elapsed_ms_p50" not in empty
    assert "hook_elapsed_ms_p95" not in empty

    init = run_omni(tmp_path, "init")
    initialized_status = run_omni(tmp_path, "status")

    assert init.returncode == 0, init.stderr
    assert initialized_status.returncode == 0, initialized_status.stderr
    initialized = json.loads(initialized_status.stdout)
    assert initialized["ok"] is True
    assert initialized["omni_dir"] is True
    assert initialized["generated_memory"] is False
    assert initialized["claude_link"] is False


def test_status_cli_reports_hook_elapsed_percentiles_when_available(tmp_path: Path) -> None:
    spool = tmp_path / ".omni" / "spool"
    spool.mkdir(parents=True)
    (spool / "hook-a.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"meta": {"elapsed_ms": 10}, "payload": "{}"}),
                json.dumps({"meta": {"elapsed_ms": 20}, "payload": "{}"}),
                json.dumps({"meta": {"elapsed_ms": 40}, "payload": "{}"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = run_omni(tmp_path, "status")
    body = json.loads(result.stdout)

    assert result.returncode == 0, result.stderr
    assert body["hook_elapsed_ms_p50"] == 20
    assert body["hook_elapsed_ms_p95"] == 40


def test_status_cli_reports_hook_elapsed_percentiles_after_ingest_processed_spool(
    tmp_path: Path,
) -> None:
    run_omni(
        tmp_path,
        "hook",
        input_text=json.dumps(
            {
                "hook_event_name": "PostToolUse",
                "session_id": "s1",
                "tool_use_id": "toolu_status",
                "tool": "Bash",
            }
        ),
    )
    ingest_result = run_omni(tmp_path, "ingest")

    result = run_omni(tmp_path, "status")
    body = json.loads(result.stdout)

    assert ingest_result.returncode == 0, ingest_result.stderr
    assert result.returncode == 0, result.stderr
    assert "hook_elapsed_ms_p50" in body
    assert "hook_elapsed_ms_p95" in body


def test_doctor_cli_is_disabled_for_week1(tmp_path: Path) -> None:
    result = run_omni(tmp_path, "doctor")

    assert result.returncode == 2
    assert not (tmp_path / ".omni").exists()
    assert "experimental disabled in Week-1" in result.stderr


def test_hook_cli_redacts_stdin_to_spool_and_exits_zero(tmp_path: Path) -> None:
    result = run_omni(
        tmp_path,
        "hook",
        input_text='{"hook_event_name":"PreToolUse","token":"secret-from-env-123"}',
        extra_env={"OMNI_TEST_SECRET": "secret-from-env-123"},
    )

    assert result.returncode == 0
    assert result.stderr == ""
    omni_tree = b"".join(path.read_bytes() for path in (tmp_path / ".omni").rglob("*") if path.is_file())
    assert b"secret-from-env-123" not in omni_tree

    spool_files = sorted((tmp_path / ".omni" / "spool").glob("hook-*.jsonl"))
    assert len(spool_files) == 1
    record = json.loads(spool_files[0].read_text(encoding="utf-8"))
    assert record["meta"]["elapsed_ms"] >= 0
    assert record["meta"]["redaction_status"] == "redacted"
    assert record["meta"]["detectors"] == ["env"]
    assert "secret-from-env-123" not in record["payload"]
    assert "REDACTED:env:" in record["payload"]


def test_hook_cli_exits_zero_when_capture_boundary_raises(monkeypatch) -> None:
    def fail_capture():
        raise FileNotFoundError("cwd vanished")

    monkeypatch.setattr(cli, "run_from_stdin", fail_capture)

    assert cli.main(["hook"]) == 0


def test_hook_cli_enqueues_ingest_for_stop_events(tmp_path: Path) -> None:
    result = run_omni(
        tmp_path,
        "hook",
        input_text='{"hook_event_name":"SessionEnd","session_id":"s1","transcript_path":"transcript.jsonl"}',
    )

    assert result.returncode == 0
    queue_files = sorted((tmp_path / ".omni" / "spool").glob("ingest-*.json"))
    assert len(queue_files) == 1
    request = json.loads(queue_files[0].read_text(encoding="utf-8"))
    assert request["event"] == "SessionEnd"
    assert request["session_id"] == "s1"
    assert request["transcript_path"] == "transcript.jsonl"


def test_parse_cli_outputs_events_and_redacted_archive(tmp_path: Path) -> None:
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        '{"type":"tool_use","timestamp":"2026-06-11T00:00:00Z","name":"Bash"}\n'
        "not-json cli-secret-value-123\n",
        encoding="utf-8",
    )

    result = run_omni(
        tmp_path,
        "parse",
        str(transcript),
        extra_env={"OMNI_PARSE_CLI_SECRET": "cli-secret-value-123"},
    )

    assert result.returncode == 0, result.stderr
    event = json.loads(result.stdout)
    assert event["event_type"] == "tool_use"
    assert event["tool"] == "Bash"
    assert not (tmp_path / ".omni").exists()
    assert not (tmp_path / ".omni" / "omni.sqlite3").exists()
    assert not (tmp_path / ".omni" / "artifacts" / "transcript_archive.jsonl").exists()


def test_parse_cli_redacts_known_event_meta_in_stdout(tmp_path: Path) -> None:
    transcript = tmp_path / "transcript.jsonl"
    secrets = {
        "api_key": "parse-known-meta-api-key-123",
        "token": "parse-known-meta-token-456",
        "secret": "parse-known-meta-secret-789",
    }
    transcript.write_text(
        json.dumps(
            {
                "type": "tool_use",
                "timestamp": "2026-06-11T00:00:00Z",
                "name": "Bash",
                **secrets,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = run_omni(
        tmp_path,
        "parse",
        str(transcript),
    )

    assert result.returncode == 0, result.stderr
    for secret in secrets.values():
        assert secret not in result.stdout
    assert "REDACTED:secret_assignment:" in result.stdout
    assert not (tmp_path / ".omni").exists()
    assert not (tmp_path / ".omni" / "omni.sqlite3").exists()
    assert not (tmp_path / ".omni" / "artifacts" / "transcript_archive.jsonl").exists()


def test_ingest_and_run_show_cli(tmp_path: Path) -> None:
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        '{"type":"tool_use","timestamp":"2026-06-11T00:00:00Z","id":"toolu_cli","name":"Bash","exit_code":0}\n',
        encoding="utf-8",
    )

    ingest_result = run_omni(tmp_path, "ingest", "cli_run", "--transcript", str(transcript))
    show_result = run_omni(tmp_path, "run", "show", "cli_run")
    expanded_result = run_omni(tmp_path, "run", "show", "cli_run", "--seq", "1")

    assert ingest_result.returncode == 0, ingest_result.stderr
    assert "events_inserted=1" in ingest_result.stdout
    assert show_result.returncode == 0, show_result.stderr
    assert "seq | ts | type | tool | exit | artifact" in show_result.stdout
    assert "1 | 2026-06-11T00:00:00Z | tool_use | Bash | 0 |" in show_result.stdout
    assert expanded_result.returncode == 0, expanded_result.stderr
    assert '"tool_use_id": "toolu_cli"' in expanded_result.stdout
    assert '"source": "transcript"' in expanded_result.stdout


def test_run_show_summary_includes_bash_command_preview_for_g6_review(tmp_path: Path) -> None:
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "tool_use",
                        "timestamp": "2026-06-11T00:00:00Z",
                        "id": "toolu_read",
                        "name": "Bash",
                        "input": {"command": "cat package.json"},
                        "exit_code": 0,
                    }
                ),
                json.dumps(
                    {
                        "type": "tool_use",
                        "timestamp": "2026-06-11T00:00:01Z",
                        "id": "toolu_test",
                        "name": "Bash",
                        "input": {"command": "pnpm run test"},
                        "exit_code": 0,
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    ingest_result = run_omni(tmp_path, "ingest", "g6_run", "--transcript", str(transcript))
    show_result = run_omni(tmp_path, "run", "show", "g6_run")

    assert ingest_result.returncode == 0, ingest_result.stderr
    assert show_result.returncode == 0, show_result.stderr
    assert "command" in show_result.stdout
    assert "cat package.json" in show_result.stdout
    assert "pnpm run test" in show_result.stdout


def test_ingest_extracts_static_facts_for_render_cli(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "name": "demo",
                "packageManager": "pnpm@10.0.0",
                "scripts": {"test": "node test.js", "build": "node build.js"},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

    ingest_result = run_omni(tmp_path, "ingest")
    second_ingest = run_omni(tmp_path, "ingest")
    render_result = run_omni(tmp_path, "render")
    memory = (tmp_path / ".omni" / "generated" / "memory.md").read_text(encoding="utf-8")
    conn = sqlite3.connect(tmp_path / ".omni" / "omni.sqlite3")

    assert ingest_result.returncode == 0, ingest_result.stderr
    assert second_ingest.returncode == 0, second_ingest.stderr
    assert render_result.returncode == 0, render_result.stderr
    assert conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 3
    assert conn.execute("SELECT COUNT(*) FROM fact_candidates").fetchone()[0] == 0
    assert "node package manager: pnpm" in memory
    assert "Use pnpm run test for Node tests." in memory
    assert "Use pnpm run build to build Node." in memory


def test_audit_secrets_cli_passes_clean_omni_tree(tmp_path: Path) -> None:
    (tmp_path / ".omni" / "spool").mkdir(parents=True)
    (tmp_path / ".omni" / "spool" / "safe.jsonl").write_text("safe\n", encoding="utf-8")

    result = run_omni(tmp_path, "audit", "secrets")

    assert result.returncode == 0, result.stderr
    assert '"ok": true' in result.stdout
    assert (tmp_path / ".omni" / "audit" / "secrets.passed").exists()


def test_create_sandbox_script_creates_repo_fixture(tmp_path: Path) -> None:
    bash_check = subprocess.run(
        ["bash", "-lc", "true"],
        text=True,
        capture_output=True,
        check=False,
    )
    if bash_check.returncode != 0:
        pytest.skip(f"bash is not usable: {bash_check.stderr.strip()}")

    target = tmp_path / "sandbox"

    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "create_sandbox.sh"), str(target)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (target / ".git").is_dir()
    assert (target / "package.json").is_file()
    assert (target / "pnpm-lock.yaml").is_file()
    assert (target / "CLAUDE.md").is_file()
    assert f"FAKE_AWS={FAKE_AWS_KEY}" in (target / ".env").read_text(encoding="utf-8")
    assert "OMNI_FAKE_SECRET=hunter2hunter2" in (target / ".env").read_text(encoding="utf-8")
    assert FAKE_GITHUB_TOKEN in (target / "fake_config.py").read_text(encoding="utf-8")
    tracked = subprocess.run(
        ["git", "-C", str(target), "ls-files", "--", "fake_config.py", ".env"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert tracked.returncode == 0, tracked.stderr
    assert tracked.stdout == ""
    gitignore = (target / ".gitignore").read_text(encoding="utf-8")
    assert ".omni/" in gitignore
    assert ".env" in gitignore
    assert "fake_config.py" in gitignore
    assert ".omni/generated/" not in gitignore


def test_create_sandbox_script_declares_pnpm_lockfile_fixture() -> None:
    script = (REPO_ROOT / "scripts" / "create_sandbox.sh").read_text(encoding="utf-8")

    assert "pnpm-lock.yaml" in script
    assert "lockfileVersion:" in script


def test_create_sandbox_scripts_do_not_embed_complete_fake_github_token() -> None:
    for script_name in ("create_sandbox.sh", "create_sandbox.ps1"):
        script = (REPO_ROOT / "scripts" / script_name).read_text(encoding="utf-8")

        assert FAKE_GITHUB_TOKEN not in script
        assert FAKE_AWS_KEY not in script
        assert '"ghp_"' in script
        assert '"AKIA"' in script


def test_shell_scripts_are_executable_in_git_index() -> None:
    result = subprocess.run(
        [
            "git",
            "ls-files",
            "-s",
            "scripts/create_sandbox.sh",
            "scripts/golden_demo.sh",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    if result.returncode != 0:
        pytest.skip(f"git index is not available: {result.stderr.strip()}")
    if not result.stdout.strip():
        pytest.skip("git index did not return tracked shell scripts")
    modes = {
        parts[3]: parts[0]
        for line in result.stdout.splitlines()
        if (parts := line.split(maxsplit=3))
    }
    assert modes == {
        "scripts/create_sandbox.sh": "100755",
        "scripts/golden_demo.sh": "100755",
    }


def test_create_sandbox_powershell_script_creates_repo_fixture(tmp_path: Path) -> None:
    powershell_check = subprocess.run(
        ["powershell", "-NoProfile", "-Command", "$PSVersionTable.PSVersion.Major"],
        text=True,
        capture_output=True,
        check=False,
    )
    if powershell_check.returncode != 0:
        pytest.skip(f"powershell is not usable: {powershell_check.stderr.strip()}")

    target = tmp_path / "sandbox-ps"

    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(REPO_ROOT / "scripts" / "create_sandbox.ps1"),
            str(target),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (target / ".git").is_dir()
    assert (target / "package.json").is_file()
    assert (target / "pnpm-lock.yaml").is_file()
    assert (target / "CLAUDE.md").is_file()
    assert f"FAKE_AWS={FAKE_AWS_KEY}" in (target / ".env").read_text(encoding="utf-8")
    assert "OMNI_FAKE_SECRET=hunter2hunter2" in (target / ".env").read_text(encoding="utf-8")
    assert FAKE_GITHUB_TOKEN in (target / "fake_config.py").read_text(encoding="utf-8")
    tracked = subprocess.run(
        ["git", "-C", str(target), "ls-files", "--", "fake_config.py", ".env"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert tracked.returncode == 0, tracked.stderr
    assert tracked.stdout == ""
    gitignore = (target / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gitignore
    assert "fake_config.py" in gitignore
    assert not (target / "package.json").read_bytes().startswith(b"\xef\xbb\xbf")


def test_golden_demo_script_declares_full_automation_steps() -> None:
    script = (REPO_ROOT / "scripts" / "golden_demo.sh").read_text(encoding="utf-8")

    assert "create_sandbox.sh" in script
    assert "omni.cli" in script
    assert "claude" in script
    assert "omni inject claude --mode link" in script
    assert "G6 robust" in script


def test_golden_demo_script_evaluator_handles_nested_meta_and_allowed_prelude() -> None:
    script = (REPO_ROOT / "scripts" / "golden_demo.sh").read_text(encoding="utf-8")

    assert "def nested_command" in script
    assert "allowed_prelude_commands" in script
    assert '"pwd"' in script
    assert '"git status"' in script


def test_golden_demo_script_runs_with_fake_claude(tmp_path: Path) -> None:
    bash_check = subprocess.run(
        ["bash", "-lc", "true"],
        text=True,
        capture_output=True,
        check=False,
    )
    if bash_check.returncode != 0:
        pytest.skip(f"bash is not usable: {bash_check.stderr.strip()}")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_claude = fake_bin / "claude"
    fake_claude.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
sid=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --session-id)
      sid="$2"
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done
if [ -z "$sid" ]; then
  echo "missing --session-id" >&2
  exit 2
fi
printf '{"hook_event_name":"PostToolUse","session_id":"%s","tool_use_id":"toolu_%s","tool":"Bash","tool_input":{"command":"pnpm run test"},"tool_response":{"stdout":"sandbox test ok","stderr":""}}\\n' "$sid" "$sid" | "$PYTHON_BIN" -m omni.cli hook
printf '{"hook_event_name":"SessionEnd","session_id":"%s","transcript_path":null}\\n' "$sid" | "$PYTHON_BIN" -m omni.cli hook
echo "fake claude ran tests"
""",
        encoding="utf-8",
    )
    fake_claude.chmod(0o755)
    target = tmp_path / "golden"
    env = os.environ.copy()
    env["PATH"] = str(fake_bin) + os.pathsep + env["PATH"]
    env["PYTHONPATH"] = str(REPO_ROOT / "src")

    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "golden_demo.sh"), str(target)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "G6 robust: 3/3" in result.stdout
    assert (target / ".omni" / "generated" / "memory.md").is_file()
    assert "@.omni/generated/memory.md" in (target / "CLAUDE.md").read_text(encoding="utf-8")
