from __future__ import annotations

from pathlib import Path

import pytest

from omni import cli
from omni import db
from omni import doctor


def test_doctor_reports_missing_layout(tmp_path: Path) -> None:
    result = doctor.run(tmp_path)

    assert result.ok is False
    assert any(check.name == "omni_dir" and not check.ok for check in result.checks)
    assert result.experimental is False


def test_doctor_reports_initialized_project(tmp_path: Path) -> None:
    (tmp_path / ".omni").mkdir()
    (tmp_path / ".omni" / "config.toml").write_text("", encoding="utf-8")
    db_path = tmp_path / ".omni" / "omni.sqlite3"
    conn = db.connect(db_path)
    db.migrate(conn)
    conn.close()

    result = doctor.run(tmp_path)

    assert result.ok is False
    names = {check.name: check.ok for check in result.checks}
    assert names["omni_dir"] is True
    assert names["database"] is True
    assert names["database_schema"] is True
    assert names["schema_version"] is True
    assert names["generated_memory"] is False


def test_doctor_reports_outdated_schema_version(tmp_path: Path) -> None:
    (tmp_path / ".omni").mkdir()
    (tmp_path / ".omni" / "config.toml").write_text("", encoding="utf-8")
    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")
    db.migrate(conn)
    conn.execute(
        "UPDATE meta SET value = ? WHERE key = 'schema_version'",
        ("6",),
    )
    conn.commit()
    conn.close()

    result = doctor.run(tmp_path)
    names = {check.name: check for check in result.checks}

    assert result.ok is False
    assert names["database_schema"].ok is True
    assert names["schema_version"].ok is False
    assert "schema_version '6' != expected '8'" in names["schema_version"].message


def test_cli_doctor_outputs_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".omni").mkdir()
    monkeypatch.chdir(tmp_path)

    code = cli.main(["doctor"])
    captured = capsys.readouterr()

    assert code == 1
    assert captured.err == ""
    assert '"checks"' in captured.out
    assert '"experimental": false' in captured.out
