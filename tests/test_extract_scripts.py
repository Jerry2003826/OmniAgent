from __future__ import annotations

import sqlite3
from pathlib import Path

from omni import db
from omni import gate


REPOS = Path(__file__).parent / "fixtures" / "repos"


def process_repo(tmp_path: Path, name: str) -> sqlite3.Connection:
    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")
    db.migrate(conn)
    gate.extract_static_facts(REPOS / name, conn)
    return conn


def command_facts(conn: sqlite3.Connection) -> dict[tuple[str, str], str]:
    rows = conn.execute(
        """
        SELECT predicate, qualifier, object_norm
        FROM facts
        WHERE predicate LIKE 'uses_%_command' AND retired_seq IS NULL
        """
    ).fetchall()
    return {(row["predicate"], row["qualifier"]): row["object_norm"] for row in rows}


def test_a2_a3_node_pnpm_test_and_build_commands(tmp_path: Path) -> None:
    commands = command_facts(process_repo(tmp_path, "node-pnpm"))

    assert commands[("uses_test_command", "node")] == "pnpm run test"
    assert commands[("uses_build_command", "node")] == "pnpm run build"


def test_a5_node_npm_default_placeholder_test_is_ignored(tmp_path: Path) -> None:
    commands = command_facts(process_repo(tmp_path, "node-npm"))

    assert ("uses_test_command", "node") not in commands


def test_a8_python_uv_test_command(tmp_path: Path) -> None:
    commands = command_facts(process_repo(tmp_path, "python-uv"))

    assert commands[("uses_test_command", "python")] == "uv run pytest"


def test_a9_python_poetry_test_command(tmp_path: Path) -> None:
    commands = command_facts(process_repo(tmp_path, "python-poetry"))

    assert commands[("uses_test_command", "python")] == "poetry run pytest"


def test_python_optional_dev_dependency_detects_pytest(tmp_path: Path) -> None:
    commands = command_facts(process_repo(tmp_path, "python-optional-pytest"))

    assert commands[("uses_test_command", "python")] == "uv run pytest"


def test_mixed_node_python_repo_preserves_both_test_commands(tmp_path: Path) -> None:
    commands = command_facts(process_repo(tmp_path, "mixed-node-python"))

    assert commands[("uses_test_command", "node")] == "pnpm run test"
    assert commands[("uses_test_command", "python")] == "uv run pytest"


def test_a10_a11_make_only_commands(tmp_path: Path) -> None:
    commands = command_facts(process_repo(tmp_path, "make-only"))

    assert commands[("uses_test_command", "default")] == "make test"
    assert commands[("uses_build_command", "default")] == "make build"
