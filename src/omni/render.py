"""Deterministic project memory renderer."""

from __future__ import annotations

import difflib
import hashlib
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from omni import db
from omni.redact import redact

RENDER_VER = 1
BLOCK_ID = "project_memory"
GENERATED_PATH = Path(".omni") / "generated" / "memory.md"
HEADER_RE = re.compile(
    r"^<!-- omni:generated render_ver=1 sha256=([0-9a-f]{64}) DO NOT EDIT -->\r?\n"
)
MAX_BODY_CHARS = 6000
TRUNCATION_NOTICE = "- Additional facts omitted due to size limit."
Dependency = tuple[str, str]


@dataclass(frozen=True)
class RenderResult:
    path: Path
    body: str
    diff: str
    wrote: bool
    dirty: bool


class ManualEditError(RuntimeError):
    def __init__(self, diff: str) -> None:
        super().__init__("generated memory was manually edited; rerun with --force to overwrite")
        self.diff = diff


def connect_project(root: Path | str | None = None) -> sqlite3.Connection:
    base = Path(root or Path.cwd()).resolve()
    conn = db.connect(base / ".omni" / "omni.sqlite3")
    db.migrate(conn)
    return conn


def render_project(
    conn: sqlite3.Connection,
    root: Path | str,
    *,
    diff: bool = False,
    force: bool = False,
) -> RenderResult:
    base = Path(root).resolve()
    path = base / GENERATED_PATH
    facts = _active_facts(conn)
    notes = _active_experience_notes(conn)
    body, line_hashes = _render_body(facts, notes)
    text = _with_header(body)
    rendered_diff = _diff(path, text)

    if diff:
        return RenderResult(path=path, body=text, diff=rendered_diff, wrote=False, dirty=False)

    if path.exists() and not force and _manual_edit_detected(path):
        raise ManualEditError(rendered_diff)

    dirty = _update_block_state(conn, body, line_hashes)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    conn.commit()
    return RenderResult(path=path, body=text, diff=rendered_diff, wrote=True, dirty=dirty)


def _active_facts(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT fact_id, scope, subject, predicate, qualifier, object_norm
        FROM facts
        WHERE retired_seq IS NULL
        ORDER BY
          CASE predicate
            WHEN 'uses_test_command' THEN 0
            WHEN 'uses_build_command' THEN 1
            WHEN 'uses_lint_command' THEN 2
            WHEN 'uses_typecheck_command' THEN 3
            WHEN 'uses_dev_command' THEN 4
            ELSE 5
          END,
          predicate,
          qualifier,
          subject,
          object_norm
        """
    ).fetchall()


def _active_experience_notes(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT note_id, scope, task_type, kind, trigger, body, suggested_action
        FROM experience_notes
        WHERE status = 'active'
        ORDER BY task_type, kind, suggested_action, body
        """
    ).fetchall()


def _render_body(
    facts: list[sqlite3.Row],
    notes: list[sqlite3.Row],
) -> tuple[str, dict[Dependency, str]]:
    sections: dict[str, list[tuple[Dependency, str]]] = {
        "Commands": [],
        "Fast Path": [],
        "Experience Notes": [],
        "Boundaries": [],
        "Project": [],
    }

    for fact in facts:
        rendered = _render_fact_line(fact)
        if rendered is None:
            continue
        section, line = rendered
        sections[section].append((("fact", fact["fact_id"]), line))

    test_command = _first_test_command(facts)
    for note in notes:
        rendered = _render_experience_note_line(note, test_command)
        if rendered is None:
            continue
        section, line = rendered
        sections[section].append((("experience_note", note["note_id"]), line))

    lines: list[tuple[str, Dependency | None]] = [("# Project memory", None), ("", None)]
    omitted = False
    for section in ("Commands", "Fast Path", "Experience Notes", "Boundaries", "Project"):
        lines.append((f"## {section}", None))
        for dep, line in sections[section]:
            if _body_length(_line_texts(lines)) + len(line) + 1 > MAX_BODY_CHARS:
                omitted = True
                break
            lines.append((line, dep))
        lines.append(("", None))
    if omitted:
        lines = _with_truncation_notice(lines)
    rendered_lines = _line_texts(lines)
    body = _redact_text("\n".join(rendered_lines).rstrip() + "\n")
    redacted_lines = body.rstrip("\n").split("\n")
    line_hashes = {
        dep: _sha256(redacted_lines[index])
        for index, (_line, dep) in enumerate(lines)
        if dep is not None and index < len(redacted_lines)
    }
    return body, line_hashes


def _render_fact_line(fact: sqlite3.Row) -> tuple[str, str] | None:
    predicate = fact["predicate"]
    qualifier = fact["qualifier"]
    object_norm = fact["object_norm"]

    if predicate.startswith("uses_") and predicate.endswith("_command"):
        command_kind = predicate.removeprefix("uses_").removesuffix("_command").replace("_", " ")
        return ("Commands", f"- {_command_instruction(command_kind, qualifier, object_norm)}")

    if predicate == "uses_package_manager":
        return ("Project", f"- {qualifier} package manager: {object_norm}")

    if predicate.startswith(("boundary_", "prefers_", "avoids_")):
        label = predicate.replace("_", " ")
        return ("Boundaries", f"- {label}: {object_norm}")

    label = predicate.replace("_", " ")
    return ("Project", f"- {qualifier} {label}: {object_norm}")


def _render_experience_note_line(
    note: sqlite3.Row, test_command: str | None
) -> tuple[str, str] | None:
    task_type = note["task_type"]
    kind = note["kind"]

    if task_type == "validation" and kind == "rediscovery_waste":
        return (
            "Fast Path",
            "- For validation tasks, run "
            f"{_verification_command_text(test_command)} before broad "
            "README/package/deployment rediscovery.",
        )
    if task_type == "validation" and kind == "fast_path":
        if test_command:
            return (
                "Fast Path",
                f"- For validation tasks, prefer running {_inline_code(test_command)} early.",
            )
        return (
            "Fast Path",
            "- For validation tasks, prefer the known verification command early.",
        )

    action = str(note["suggested_action"] or "").strip()
    if not action:
        action = str(note["body"] or "").strip()
    if not action:
        return None
    return ("Experience Notes", f"- {action}")


def _with_header(body: str) -> str:
    return f"<!-- omni:generated render_ver={RENDER_VER} sha256={_sha256(body)} DO NOT EDIT -->\n{body}"


def _redact_text(value: str) -> str:
    return redact(value.encode("utf-8")).data.decode("utf-8", errors="replace")


def _command_instruction(command_kind: str, qualifier: str, object_norm: str) -> str:
    label = _qualifier_label(qualifier)
    if command_kind == "test":
        return f"Use {object_norm} for {label} tests."
    if command_kind == "build":
        return f"Use {object_norm} to build {label}."
    if command_kind == "lint":
        return f"Use {object_norm} to lint {label}."
    if command_kind == "typecheck":
        return f"Use {object_norm} to type-check {label}."
    if command_kind == "dev":
        return f"Use {object_norm} to start {label} development."
    return f"Use {object_norm} for {label} {command_kind}."


def _first_test_command(facts: list[sqlite3.Row]) -> str | None:
    for fact in facts:
        if fact["predicate"] == "uses_test_command":
            return str(fact["object_norm"])
    return None


def _verification_command_text(command: str | None) -> str:
    if command:
        return _inline_code(command)
    return "the known verification command"


def _inline_code(value: str) -> str:
    return f"`{value.replace('`', '')}`"


def _qualifier_label(qualifier: str) -> str:
    parts = qualifier.split(":")
    if parts[0] == "node":
        base = "Node"
    elif parts[0] == "python":
        base = "Python"
    elif parts[0] == "default":
        base = "project"
    else:
        base = parts[0].replace("_", " ")
    if len(parts) == 1:
        return base
    suffix = " ".join(part.replace("_", " ") for part in parts[1:])
    return f"{base} {suffix}"


def _manual_edit_detected(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    match = HEADER_RE.match(text)
    if not match:
        return True
    body = text[match.end() :]
    return _sha256(body) != match.group(1)


def _update_block_state(
    conn: sqlite3.Connection,
    body: str,
    line_hashes: dict[Dependency, str],
) -> bool:
    previous = {
        (row["dep_kind"], row["dep_id"]): row["dep_line_hash"]
        for row in conn.execute(
            "SELECT dep_kind, dep_id, dep_line_hash FROM block_deps WHERE block_id = ?",
            (BLOCK_ID,),
        )
    }
    block_exists = conn.execute("SELECT 1 FROM blocks WHERE block_id = ?", (BLOCK_ID,)).fetchone()
    dirty = block_exists is None or previous != line_hashes
    now = datetime.now(timezone.utc).isoformat()

    conn.execute(
        """
        INSERT INTO blocks(block_id, scope, render_ver, content_hash, body, dirty, updated_at)
        VALUES(?,?,?,?,?,?,?)
        ON CONFLICT(block_id) DO UPDATE SET
          scope = excluded.scope,
          render_ver = excluded.render_ver,
          content_hash = excluded.content_hash,
          body = excluded.body,
          dirty = excluded.dirty,
          updated_at = excluded.updated_at
        """,
        (BLOCK_ID, "project", RENDER_VER, _sha256(body), body, 1 if dirty else 0, now),
    )
    conn.execute("DELETE FROM block_deps WHERE block_id = ?", (BLOCK_ID,))
    conn.executemany(
        """
        INSERT INTO block_deps(block_id, dep_kind, dep_id, dep_line_hash)
        VALUES(?,?,?,?)
        """,
        [
            (BLOCK_ID, dep_kind, dep_id, line_hash)
            for (dep_kind, dep_id), line_hash in line_hashes.items()
        ],
    )
    return dirty


def _diff(path: Path, rendered: str) -> str:
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    return "".join(
        difflib.unified_diff(
            current.splitlines(keepends=True),
            rendered.splitlines(keepends=True),
            fromfile=str(GENERATED_PATH),
            tofile=f"{GENERATED_PATH} (omni)",
        )
    )


def _body_length(lines: list[str]) -> int:
    if not lines:
        return 0
    return len("\n".join(lines)) + 1


def _line_texts(lines: list[tuple[str, Dependency | None]]) -> list[str]:
    return [line for line, _fact_id in lines]


def _with_truncation_notice(
    lines: list[tuple[str, Dependency | None]],
) -> list[tuple[str, Dependency | None]]:
    trimmed = list(lines)
    while trimmed and trimmed[-1][0] == "":
        trimmed.pop()
    while _body_length(_line_texts(trimmed)) + len(TRUNCATION_NOTICE) + 1 > MAX_BODY_CHARS:
        removable = next(
            (
                index
                for index in range(len(trimmed) - 1, -1, -1)
                if trimmed[index][1] is not None
            ),
            None,
        )
        if removable is None:
            break
        del trimmed[removable]
    if _body_length(_line_texts(trimmed)) + len(TRUNCATION_NOTICE) + 1 <= MAX_BODY_CHARS:
        trimmed.append((TRUNCATION_NOTICE, None))
    return trimmed


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
