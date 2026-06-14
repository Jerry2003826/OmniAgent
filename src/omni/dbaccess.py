"""Shared SQLite project connection helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from omni import db


def _project_db_path(root: Path | str | None) -> Path:
    base = Path(root or Path.cwd()).resolve()
    return base / ".omni" / "omni.sqlite3"


def connect_project(
    root: Path | str | None = None,
    *,
    create_if_missing: bool = False,
) -> sqlite3.Connection:
    db_path = _project_db_path(root)
    if not create_if_missing and not db_path.exists():
        raise FileNotFoundError(f"OmniMemory database is missing: {db_path}")
    conn = db.connect(db_path)
    db.migrate(conn)
    return conn


def connect_project_migrate(root: Path | str | None = None) -> sqlite3.Connection:
    """Open project DB for approved write commands that may create or migrate schema."""
    return connect_project(root, create_if_missing=True)


def ensure_run_exists(conn: sqlite3.Connection, run_id: str) -> None:
    row = conn.execute("SELECT 1 FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        raise ValueError(f"unknown run: {run_id}")


def connect_project_readonly(
    root: Path | str | None = None,
    *,
    check_schema: bool = True,
) -> sqlite3.Connection:
    db_path = _project_db_path(root)
    if not db_path.exists():
        raise FileNotFoundError(f"OmniMemory database is missing: {db_path}")
    conn = db.connect_readonly(db_path)
    if check_schema:
        version = db.schema_version(conn)
        if version != db.LATEST_SCHEMA_VERSION:
            conn.close()
            raise ValueError(
                f"OmniMemory schema is outdated (found {version or 'none'}, need "
                f"{db.LATEST_SCHEMA_VERSION}); run an approved write command such as "
                "'omni render' to migrate"
            )
    return conn


def connect_project_readonly_verify(root: Path | str | None = None) -> sqlite3.Connection:
    db_path = _project_db_path(root)
    if not db_path.exists():
        raise FileNotFoundError(f"OmniMemory database not found: {db_path}")
    conn = db.connect_readonly(db_path)
    version = db.schema_version(conn)
    if version != db.LATEST_SCHEMA_VERSION:
        conn.close()
        raise ValueError(
            f"OmniMemory schema is outdated (found {version or 'none'}, "
            f"need {db.LATEST_SCHEMA_VERSION})"
        )
    return conn


def root_from_connection(conn: sqlite3.Connection) -> Path | None:
    rows = conn.execute("PRAGMA database_list").fetchall()
    for row in rows:
        if row["name"] != "main" or not row["file"]:
            continue
        db_path = Path(row["file"]).resolve()
        if db_path.parent.name == ".omni":
            return db_path.parent.parent
    return None
