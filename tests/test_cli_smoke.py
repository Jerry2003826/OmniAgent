from __future__ import annotations

import os
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


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
    assert gitignore.count(".omni/generated/") == 1


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


def test_init_install_claude_hooks_prints_diff_and_backs_up_project_settings(tmp_path: Path) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    settings = claude_dir / "settings.json"
    original = '{\n  "permissions": {}\n}\n'
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
    assert "omni hook" in result.stdout
    assert (claude_dir / "settings.json.omni-bak").read_text(encoding="utf-8") == original
    assert global_settings.read_text(encoding="utf-8") == global_original

    updated = json.loads(settings.read_text(encoding="utf-8"))
    assert updated["permissions"] == {}
    assert updated["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == "omni hook"
    assert updated["hooks"]["PostToolUse"][0]["hooks"][0]["command"] == "omni hook"
    assert updated["hooks"]["Stop"][0]["hooks"][0]["command"] == "omni hook"
    assert updated["hooks"]["SessionEnd"][0]["hooks"][0]["command"] == "omni hook"


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
    assert (claude_dir / "settings.json.omni-bak").read_bytes() == original


def test_cli_help_smoke(tmp_path: Path) -> None:
    result = run_omni(tmp_path, "--help")

    assert result.returncode == 0
    assert "init" in result.stdout


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


def test_hook_cli_enqueues_ingest_for_stop_events(tmp_path: Path) -> None:
    result = run_omni(
        tmp_path,
        "hook",
        input_text='{"hook_event_name":"SessionEnd","session_id":"s1","transcript_path":"transcript.jsonl"}',
    )

    assert result.returncode == 0
    queue = tmp_path / ".omni" / "spool" / "ingest_queue.jsonl"
    assert queue.exists()
    request = json.loads(queue.read_text(encoding="utf-8"))
    assert request["event"] == "SessionEnd"
    assert request["session_id"] == "s1"
    assert request["transcript_path"] == "transcript.jsonl"


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
    assert (target / "CLAUDE.md").is_file()
