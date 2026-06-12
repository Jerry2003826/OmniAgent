from __future__ import annotations

import json
from pathlib import Path

from omni import audit
from omni import hook
from omni import redact
from omni.redact import RedactionResult


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "redaction"


def test_audit_secrets_passes_curated_corpus_and_clean_omni_tree(tmp_path: Path) -> None:
    (tmp_path / ".omni" / "spool").mkdir(parents=True)
    (tmp_path / ".omni" / "spool" / "hook.jsonl").write_text(
        '{"payload":"safe redacted text"}\n', encoding="utf-8"
    )

    result = audit.audit_secrets(tmp_path, fixtures_root=FIXTURE_ROOT)

    assert result.ok is True
    assert result.positive_failures == []
    assert result.negative_failures == []
    assert result.omni_leaks == []
    assert (tmp_path / ".omni" / "audit" / "secrets.passed").exists()


def test_audit_ignores_own_success_marker(tmp_path: Path) -> None:
    marker = tmp_path / ".omni" / "audit" / "secrets.passed"
    marker.parent.mkdir(parents=True)
    marker.write_text("ok\n", encoding="utf-8")

    result = audit.audit_secrets(tmp_path, fixtures_root=FIXTURE_ROOT)

    assert result.ok is True
    assert result.omni_leaks == []


def test_audit_secrets_fails_on_planted_omni_secret(tmp_path: Path) -> None:
    (tmp_path / ".omni" / "spool").mkdir(parents=True)
    leak = tmp_path / ".omni" / "spool" / "leak.jsonl"
    leak.write_text("token=ghp_abcdefghijklmnopqrstuvwxyz1234567890\n", encoding="utf-8")
    spike_leak = tmp_path / ".omni" / "spike" / "leak.txt"
    spike_leak.parent.mkdir(parents=True)
    spike_leak.write_text("password=spike-secret-value-123456\n", encoding="utf-8")

    result = audit.audit_secrets(tmp_path, fixtures_root=FIXTURE_ROOT)

    assert result.ok is False
    assert result.omni_leaks == [spike_leak, leak]
    assert not (tmp_path / ".omni" / "audit" / "secrets.passed").exists()


def test_audit_fails_on_positive_fixture_literal_even_if_redactor_misses(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / ".omni" / "spool").mkdir(parents=True)
    leak = tmp_path / ".omni" / "spool" / "missed.jsonl"
    leak.write_text(
        "tool output included ghp_abcdefghijklmnopqrstuvwxyz1234567890\n",
        encoding="utf-8",
    )

    def miss_path(path: Path, allow_values: set[str] | None = None) -> RedactionResult:
        return RedactionResult(
            data=Path(path).read_bytes(),
            status="clean",
            detectors=(),
        )

    monkeypatch.setattr(audit, "redact_path", miss_path)

    result = audit.audit_secrets(tmp_path, fixtures_root=FIXTURE_ROOT)

    assert result.ok is False
    assert result.omni_leaks == [leak]
    assert not (tmp_path / ".omni" / "audit" / "secrets.passed").exists()


def test_audit_uses_redaction_allow_file_for_exact_values(tmp_path: Path) -> None:
    allowed = "ghp_allowedallowedallowedallowedallowedallowed12"
    (tmp_path / ".omni").mkdir()
    (tmp_path / ".omni" / "redaction-allow.txt").write_text(allowed + "\n", encoding="utf-8")
    (tmp_path / ".omni" / "spool").mkdir()
    (tmp_path / ".omni" / "spool" / "allowed.jsonl").write_text(
        f"token={allowed}\n", encoding="utf-8"
    )

    result = audit.audit_secrets(tmp_path, fixtures_root=FIXTURE_ROOT)

    assert result.ok is True
    assert result.omni_leaks == []


def test_audit_accepts_already_redacted_placeholders_on_second_scan(tmp_path: Path) -> None:
    (tmp_path / ".omni" / "spool").mkdir(parents=True)
    redacted = redact.redact(b"token=ghp_abcdefghijklmnopqrstuvwxyz1234567890\n")
    (tmp_path / ".omni" / "spool" / "redacted.jsonl").write_bytes(redacted.data)

    result = audit.audit_secrets(tmp_path, fixtures_root=FIXTURE_ROOT)

    assert result.ok is True
    assert result.omni_leaks == []


def test_audit_accepts_generated_memory_redaction_placeholder(tmp_path: Path) -> None:
    memory = tmp_path / ".omni" / "generated" / "memory.md"
    memory.parent.mkdir(parents=True)
    memory.write_text(
        "token=\u27e8REDACTED:env:abcd1234\u27e9\n",
        encoding="utf-8",
    )

    result = audit.audit_secrets(tmp_path, fixtures_root=FIXTURE_ROOT)

    assert result.ok is True
    assert result.omni_leaks == []


def test_audit_accepts_redacted_hook_spool_after_capture(tmp_path: Path) -> None:
    result = hook.capture_hook(
        json.dumps(
            {
                "hook_event_name": "PostToolUse",
                "tool": "Read",
                "tool_input": {"file_path": "safe.txt"},
                "tool_response": {"content": "secret=captured-secret-value-123456"},
            }
        ).encode("utf-8"),
        root=tmp_path,
    )

    audit_result = audit.audit_secrets(tmp_path, fixtures_root=FIXTURE_ROOT)

    assert result.ok is True
    assert result.spool_path is not None
    assert b"captured-secret-value-123456" not in result.spool_path.read_bytes()
    assert audit_result.ok is True
    assert audit_result.omni_leaks == []


def test_audit_cli_scans_omni_tree_and_reports_json(tmp_path: Path) -> None:
    (tmp_path / ".omni" / "generated").mkdir(parents=True)
    (tmp_path / ".omni" / "generated" / "memory.md").write_text("no secrets\n", encoding="utf-8")

    code, body = audit.run_audit_cli(tmp_path, fixtures_root=FIXTURE_ROOT)
    report = json.loads(body)

    assert code == 0
    assert report["ok"] is True
    assert report["omni_leaks"] == []


def test_audit_fails_when_fixture_corpus_is_missing(tmp_path: Path) -> None:
    code, body = audit.run_audit_cli(tmp_path, fixtures_root=tmp_path / "missing")
    report = json.loads(body)

    assert code == 1
    assert report["ok"] is False
    assert report["fixtures_missing"] is True
    assert not (tmp_path / ".omni" / "audit" / "secrets.passed").exists()


def test_audit_fails_when_positive_or_negative_fixture_corpus_is_empty(
    tmp_path: Path,
) -> None:
    fixtures = tmp_path / "fixtures"
    (fixtures / "positives").mkdir(parents=True)
    (fixtures / "negatives").mkdir()

    code, body = audit.run_audit_cli(tmp_path, fixtures_root=fixtures)
    report = json.loads(body)

    assert code == 1
    assert report["ok"] is False
    assert report["fixtures_missing"] is True

    (fixtures / "positives" / "token.txt").write_text(
        "token=ghp_abcdefghijklmnopqrstuvwxyz1234567890\n",
        encoding="utf-8",
    )
    code, body = audit.run_audit_cli(tmp_path, fixtures_root=fixtures)
    report = json.loads(body)

    assert code == 1
    assert report["ok"] is False
    assert report["fixtures_missing"] is True


def test_audit_fails_when_fixture_corpus_contains_only_empty_files(
    tmp_path: Path,
) -> None:
    fixtures = tmp_path / "fixtures"
    (fixtures / "positives").mkdir(parents=True)
    (fixtures / "negatives").mkdir()
    (fixtures / "positives" / "empty.txt").write_text("", encoding="utf-8")
    (fixtures / "negatives" / "empty.txt").write_text("", encoding="utf-8")

    code, body = audit.run_audit_cli(tmp_path, fixtures_root=fixtures)
    report = json.loads(body)

    assert code == 1
    assert report["ok"] is False
    assert report["fixtures_missing"] is True
    assert not (tmp_path / ".omni" / "audit" / "secrets.passed").exists()
