from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from omni import cli
from omni import db
from omni import preference
from omni import render


def test_extract_creates_preference_candidate_from_boundary_fact(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    conn.execute(
        """
        INSERT INTO fact_candidates(
          cand_id, scope, subject, predicate, qualifier, object_norm, value_type,
          claim, trust, evidence, extractor_version, state, created_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "cand_pref_1",
            "project",
            ".",
            "prefers_small_prs",
            "default",
            "true",
            "string",
            "Keep pull requests small and reviewable.",
            2,
            "{}",
            "test@1",
            "pending",
            "2026-06-15T00:00:00Z",
        ),
    )
    conn.commit()

    created = preference.extract_candidates(conn)

    assert len(created) == 1
    assert created[0]["kind"] == "prefers"
    assert created[0]["state"] == "pending"
    assert "small" in created[0]["body"].lower()


def test_preference_approve_render_and_retire(tmp_path: Path) -> None:
    conn = _fixture_db(tmp_path)
    conn.execute(
        """
        INSERT INTO preference_candidates(
          pref_cand_id, source_cand_id, scope, kind, predicate, qualifier,
          body, suggested_action, evidence, state, created_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "pref_cand_1",
            None,
            "project",
            "prefers",
            "prefers_small_prs",
            "default",
            "prefers small prs: true",
            "Keep pull requests small.",
            "{}",
            "pending",
            "2026-06-15T00:00:00Z",
        ),
    )
    conn.commit()

    note = preference.approve_candidate(conn, "pref_cand_1")
    result = render.render_project(conn, tmp_path, force=True)

    body = result.body
    assert "## Preferences" in body
    assert "Keep pull requests small." in body
    assert "pref_cand_1" not in body
    assert note["note_id"].startswith("pref_note")

    preference.retire_note(conn, note["note_id"])
    rerendered = render.render_project(conn, tmp_path, force=True)
    assert "Keep pull requests small." not in rerendered.body


def test_cli_preference_extract_outputs_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    conn = _fixture_db(tmp_path)
    conn.execute(
        """
        INSERT INTO fact_candidates(
          cand_id, scope, subject, predicate, qualifier, object_norm, value_type,
          claim, trust, evidence, extractor_version, state, created_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "cand_cli",
            "project",
            ".",
            "avoids_force_push",
            "default",
            "main",
            "string",
            "Never force-push main.",
            2,
            "{}",
            "test@1",
            "pending",
            "2026-06-15T00:00:00Z",
        ),
    )
    conn.commit()
    conn.close()
    monkeypatch.chdir(tmp_path)

    code = cli.main(["preference", "extract"])
    captured = capsys.readouterr()
    output = json.loads(captured.out)

    assert code == 0
    assert captured.err == ""
    assert output["created"] == 1


def _fixture_db(root: Path) -> sqlite3.Connection:
    (root / ".omni").mkdir()
    conn = db.connect(root / ".omni" / "omni.sqlite3")
    db.migrate(conn)
    return conn
