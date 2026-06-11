from __future__ import annotations

from pathlib import Path


def test_project_id_gitignore_decision_is_documented() -> None:
    body = Path("docs/DECISIONS.md").read_text(encoding="utf-8")

    assert ".omni/" in body
    assert ".omni/project_id" in body
    assert "local-only" in body.lower()
    assert "no exceptions" in body.lower()
    assert "ignored" in body.lower()
    assert "entire" in body.lower()
    assert "git remote origin" in body
