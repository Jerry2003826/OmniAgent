from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from omni import db
from omni import gate
from omni import render


REPO_ROOT = Path(__file__).resolve().parents[1]


def run_omni(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", "omni.cli", *args],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def connect(tmp_path: Path):
    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")
    db.migrate(conn)
    return conn


def add_fact(conn, *, predicate: str, qualifier: str, object_norm: str) -> None:
    gate.insert_fact(
        conn,
        gate.FactCandidate(
            scope="project",
            subject=".",
            predicate=predicate,
            qualifier=qualifier,
            object_norm=object_norm,
            value_type="string",
            claim=f"{predicate}: {object_norm}",
            trust=2,
            sensitivity="low",
            origin="test@1",
            evidence={"files": [{"path": "package.json", "hash": "abc"}]},
        ),
    )
    conn.commit()


def seed_project_facts(conn) -> None:
    add_fact(conn, predicate="uses_package_manager", qualifier="node", object_norm="pnpm")
    add_fact(conn, predicate="uses_test_command", qualifier="node", object_norm="pnpm run test")
    add_fact(conn, predicate="uses_build_command", qualifier="node", object_norm="pnpm run build")


def test_render_generates_byte_stable_memory_without_internal_metadata(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    seed_project_facts(conn)

    first = render.render_project(conn, tmp_path)
    first_text = first.path.read_text(encoding="utf-8")
    second = render.render_project(conn, tmp_path)
    second_text = second.path.read_text(encoding="utf-8")

    assert first.path == tmp_path / ".omni" / "generated" / "memory.md"
    assert first_text == second_text
    assert first_text.startswith("<!-- omni:generated render_ver=1 sha256=")
    assert "# Project memory" in first_text
    assert "## Commands" in first_text
    assert "## Boundaries" in first_text
    assert "## Project" in first_text
    assert "Use pnpm run test for Node tests." in first_text
    assert "Use pnpm run build to build Node." in first_text
    assert first_text.index("Use pnpm run test") < first_text.index("Use pnpm run build")
    assert first_text.index("Use pnpm run test") < first_text.index("node package manager: pnpm")
    assert "fact_" not in first_text
    assert "confidence" not in first_text.lower()
    assert "created_at" not in first_text.lower()


def test_render_dirty_changes_only_when_visible_line_hash_changes(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    add_fact(conn, predicate="uses_test_command", qualifier="node", object_norm="pnpm run test")

    render.render_project(conn, tmp_path)
    first_hashes = [
        row["dep_line_hash"]
        for row in conn.execute("SELECT dep_line_hash FROM block_deps ORDER BY dep_line_hash")
    ]
    assert conn.execute("SELECT dirty FROM blocks WHERE block_id = 'project_memory'").fetchone()["dirty"] == 1

    conn.execute("UPDATE facts SET confidence = 0.9, evidence = ? WHERE predicate = 'uses_test_command'", ('{"files":[]}',))
    render.render_project(conn, tmp_path)
    evidence_only_hashes = [
        row["dep_line_hash"]
        for row in conn.execute("SELECT dep_line_hash FROM block_deps ORDER BY dep_line_hash")
    ]
    assert evidence_only_hashes == first_hashes
    assert conn.execute("SELECT dirty FROM blocks WHERE block_id = 'project_memory'").fetchone()["dirty"] == 0

    conn.execute("UPDATE facts SET object_norm = 'npm test' WHERE predicate = 'uses_test_command'")
    render.render_project(conn, tmp_path)
    visible_change_hashes = [
        row["dep_line_hash"]
        for row in conn.execute("SELECT dep_line_hash FROM block_deps ORDER BY dep_line_hash")
    ]
    assert visible_change_hashes != first_hashes
    assert conn.execute("SELECT dirty FROM blocks WHERE block_id = 'project_memory'").fetchone()["dirty"] == 1


def test_render_refuses_manual_edit_without_force(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    seed_project_facts(conn)
    result = render.render_project(conn, tmp_path)
    result.path.write_text(result.path.read_text(encoding="utf-8") + "\nmanual edit\n", encoding="utf-8")

    with pytest.raises(render.ManualEditError):
        render.render_project(conn, tmp_path)

    forced = render.render_project(conn, tmp_path, force=True)
    assert "manual edit" not in forced.path.read_text(encoding="utf-8")


def test_render_cli_diff_previews_without_writing_and_render_writes_file(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    seed_project_facts(conn)
    conn.close()

    diff = run_omni(tmp_path, "render", "--diff")
    assert diff.returncode == 0, diff.stderr
    assert "pnpm run test" in diff.stdout
    assert not (tmp_path / ".omni" / "generated" / "memory.md").exists()

    written = run_omni(tmp_path, "render")
    assert written.returncode == 0, written.stderr
    assert (tmp_path / ".omni" / "generated" / "memory.md").exists()


def test_render_orders_commands_by_explicit_predicate_priority(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    add_fact(conn, predicate="uses_dev_command", qualifier="node", object_norm="pnpm run dev")
    add_fact(conn, predicate="uses_typecheck_command", qualifier="node", object_norm="pnpm run typecheck")
    add_fact(conn, predicate="uses_lint_command", qualifier="node", object_norm="pnpm run lint")
    add_fact(conn, predicate="uses_build_command", qualifier="node", object_norm="pnpm run build")
    add_fact(conn, predicate="uses_test_command", qualifier="node", object_norm="pnpm run test")

    result = render.render_project(conn, tmp_path)
    text = result.path.read_text(encoding="utf-8")

    assert [
        text.index("pnpm run test"),
        text.index("pnpm run build"),
        text.index("pnpm run lint"),
        text.index("pnpm run typecheck"),
        text.index("pnpm run dev"),
    ] == sorted(
        [
            text.index("pnpm run test"),
            text.index("pnpm run build"),
            text.index("pnpm run lint"),
            text.index("pnpm run typecheck"),
            text.index("pnpm run dev"),
        ]
    )


def test_render_marks_omitted_facts_when_body_limit_is_reached(
    tmp_path: Path, monkeypatch
) -> None:
    conn = connect(tmp_path)
    monkeypatch.setattr(render, "MAX_BODY_CHARS", 220)
    for index in range(20):
        add_fact(
            conn,
            predicate=f"boundary_rule_{index:02d}",
            qualifier="default",
            object_norm=f"keep generated memory concise rule {index:02d}",
        )

    result = render.render_project(conn, tmp_path)
    text = result.path.read_text(encoding="utf-8")

    assert result.body == text
    assert "Additional facts omitted due to size limit." in text
    assert len(result.body.split("\n", 1)[1]) <= render.MAX_BODY_CHARS


def test_render_redacts_fact_values_before_writing_generated_memory(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    raw_secret = "ghp_abcdefghijklmnopqrstuvwxyz1234567890"
    add_fact(
        conn,
        predicate="boundary_rule",
        qualifier="default",
        object_norm=f"never print {raw_secret}",
    )

    result = render.render_project(conn, tmp_path)
    text = result.path.read_text(encoding="utf-8")

    assert raw_secret not in text
    assert "REDACTED:github_token:" in text
    assert result.body == text
