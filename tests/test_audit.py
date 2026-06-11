from __future__ import annotations

import json
from pathlib import Path

from omni import audit


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


def test_audit_cli_scans_omni_tree_and_reports_json(tmp_path: Path) -> None:
    (tmp_path / ".omni" / "generated").mkdir(parents=True)
    (tmp_path / ".omni" / "generated" / "memory.md").write_text("no secrets\n", encoding="utf-8")

    code, body = audit.run_audit_cli(tmp_path, fixtures_root=FIXTURE_ROOT)
    report = json.loads(body)

    assert code == 0
    assert report["ok"] is True
    assert report["omni_leaks"] == []
