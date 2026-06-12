"""SQLite connection and migration helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
MIGRATIONS = (
    ("1", "001_init.sql"),
    ("2", "002_outcomes.sql"),
    ("3", "003_experience_candidates.sql"),
    ("4", "004_experience_notes.sql"),
)
LATEST_SCHEMA_VERSION = MIGRATIONS[-1][0]


def connect(path: Path | str) -> sqlite3.Connection:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def connect_readonly(path: Path | str) -> sqlite3.Connection:
    db_path = Path(path).resolve()
    conn = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    current = _current_schema_version(conn)
    if current == LATEST_SCHEMA_VERSION:
        return
    current_int = 0 if current is None else int(current)
    for version, filename in MIGRATIONS:
        if int(version) > current_int:
            _apply_migration(conn, filename)
    conn.commit()


def _apply_migration(conn: sqlite3.Connection, filename: str) -> None:
    # executescript runs statements in autocommit mode; the explicit BEGIN/COMMIT
    # makes each migration all-or-nothing so a mid-script failure cannot leave
    # tables created while schema_version stays behind.
    try:
        conn.executescript(f"BEGIN;\n{migration_sql(filename)}\nCOMMIT;")
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def migration_sql(filename: str) -> str:
    return (MIGRATIONS_DIR / filename).read_text(encoding="utf-8")


def schema_version(conn: sqlite3.Connection) -> str | None:
    return _current_schema_version(conn)


def _current_schema_version(conn: sqlite3.Connection) -> str | None:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'meta'"
    ).fetchone()
    if not exists:
        return None
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    return row["value"] if row else None
