import re

import pytest

from omni import cli


def _help_output(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    with pytest.raises(SystemExit) as exc:
        cli.main([*args, "--help"])
    assert exc.value.code == 0
    return capsys.readouterr().out


def test_top_level_help_includes_cli_only_v1_commands(
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = _help_output(capsys)

    for command in (
        "init",
        "audit",
        "ingest",
        "status",
        "doctor",
        "eval",
        "outcome",
        "experience",
        "failure",
        "preference",
        "task",
        "project",
        "verify",
        "render",
        "inject",
        "review",
    ):
        assert command in output


def test_top_level_help_keeps_internal_commands_hidden(
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = _help_output(capsys)

    for command in ("hook", "parse", "run"):
        assert re.search(rf"^\s+{command}\s", output, flags=re.MULTILINE) is None


def test_audit_and_ingest_help_are_discoverable(
    capsys: pytest.CaptureFixture[str],
) -> None:
    audit_output = _help_output(capsys, "audit")
    ingest_output = _help_output(capsys, "ingest")

    assert "secrets" in audit_output
    assert "--transcript" in ingest_output
    assert "--run-id" in ingest_output
