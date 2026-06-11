"""Read-only project diagnostics."""

from __future__ import annotations

import json
import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from omni.inject import MANAGED_REGION
from omni.render import HEADER_RE

REQUIRED_TABLES = {
    "artifacts",
    "block_deps",
    "blocks",
    "events",
    "fact_candidates",
    "facts",
    "meta",
    "runs",
    "suppressions",
}


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    ok: bool
    message: str

    def as_dict(self) -> dict[str, object]:
        return {"name": self.name, "ok": self.ok, "message": self.message}


@dataclass(frozen=True)
class DoctorResult:
    ok: bool
    checks: tuple[DoctorCheck, ...]

    def as_json(self) -> str:
        return json.dumps(
            {
                "ok": self.ok,
                "checks": [check.as_dict() for check in self.checks],
            },
            sort_keys=True,
        ) + "\n"


def run(root: Path | str | None = None) -> DoctorResult:
    base = Path(root or Path.cwd()).resolve()
    omni_dir = base / ".omni"
    memory = omni_dir / "generated" / "memory.md"
    claude = base / "CLAUDE.md"
    checks = (
        _check_path("omni_dir", omni_dir, is_dir=True),
        _check_path("config", omni_dir / "config.toml"),
        _check_path("database", omni_dir / "omni.sqlite3"),
        _check_database_schema(omni_dir / "omni.sqlite3"),
        _check_generated_memory(memory),
        _check_claude_link(claude),
        _check_path("audit_passed", omni_dir / "audit" / "secrets.passed"),
    )
    return DoctorResult(ok=all(check.ok for check in checks), checks=checks)


def _check_path(name: str, path: Path, *, is_dir: bool = False) -> DoctorCheck:
    ok = path.is_dir() if is_dir else path.is_file()
    kind = "directory" if is_dir else "file"
    message = f"{kind} exists: {path}" if ok else f"missing {kind}: {path}"
    return DoctorCheck(name=name, ok=ok, message=message)


def _check_generated_memory(path: Path) -> DoctorCheck:
    if not path.is_file():
        return DoctorCheck("generated_memory", False, f"missing file: {path}")
    body = path.read_text(encoding="utf-8", errors="replace")
    match = HEADER_RE.match(body)
    if not match:
        return DoctorCheck("generated_memory", False, "generated memory header missing")
    rendered_body = body[match.end() :]
    digest = hashlib.sha256(rendered_body.encode("utf-8")).hexdigest()
    ok = digest == match.group(1)
    message = "generated memory hash matches body" if ok else "generated memory hash mismatch"
    return DoctorCheck("generated_memory", ok, message)


def _check_database_schema(path: Path) -> DoctorCheck:
    if not path.is_file():
        return DoctorCheck("database_schema", False, f"missing file: {path}")
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return DoctorCheck("database_schema", False, f"database unreadable: {exc}")
    tables = {row[0] for row in rows}
    missing = sorted(REQUIRED_TABLES - tables)
    if missing:
        return DoctorCheck("database_schema", False, f"missing tables: {', '.join(missing)}")
    return DoctorCheck("database_schema", True, "required tables present")


def _check_claude_link(path: Path) -> DoctorCheck:
    if not path.is_file():
        return DoctorCheck("claude_link", False, f"missing file: {path}")
    body = path.read_text(encoding="utf-8", errors="replace")
    ok = MANAGED_REGION.rstrip("\n") in body
    message = "CLAUDE.md managed region present" if ok else "CLAUDE.md managed region missing"
    return DoctorCheck("claude_link", ok, message)
