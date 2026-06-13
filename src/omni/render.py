"""Deterministic project memory renderer."""

from __future__ import annotations

import difflib
import hashlib
import os
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
TRUNCATION_NOTICE = "- Additional entries omitted due to size limit."
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
    failure_patterns = _active_failure_patterns(conn)
    body, line_hashes = _render_body(facts, notes, failure_patterns)
    text = _with_header(body)
    rendered_diff = _diff(path, text)

    if diff:
        return RenderResult(path=path, body=text, diff=rendered_diff, wrote=False, dirty=False)

    if path.exists() and not force and _manual_edit_detected(path):
        raise ManualEditError(rendered_diff)

    dirty = _update_block_state(conn, body, line_hashes)
    path.parent.mkdir(parents=True, exist_ok=True)
    _replace_file_text(path, text)
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
        SELECT note_id, scope, task_type, kind, body, suggested_action
        FROM experience_notes
        WHERE status = 'active'
        ORDER BY task_type, kind, suggested_action, body, note_id
        """
    ).fetchall()


def _active_failure_patterns(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT pattern_id, scope, command_norm, failure_kind, error_signature,
               error_signature_hash, summary, suggested_action
        FROM failure_patterns
        WHERE status = 'active'
        ORDER BY command_norm, failure_kind, error_signature_hash, summary, suggested_action
        """
    ).fetchall()


def _render_body(
    facts: list[sqlite3.Row],
    notes: list[sqlite3.Row],
    failure_patterns: list[sqlite3.Row],
) -> tuple[str, dict[Dependency, str]]:
    sections: dict[str, list[tuple[Dependency, str]]] = {
        "Commands": [],
        "Fast Path": [],
        "Known Failures": [],
        "Experience Notes": [],
        "Boundaries": [],
        "Project": [],
    }

    seen_lines: set[tuple[str, str]] = set()

    def append_unique(dep: Dependency, rendered: tuple[str, str] | None) -> None:
        if rendered is None:
            return
        section, line = rendered
        if (section, line) in seen_lines:
            return
        seen_lines.add((section, line))
        sections[section].append((dep, line))

    for fact in facts:
        append_unique(("fact", fact["fact_id"]), _render_fact_line(fact))

    test_command = _known_test_command(facts)
    for note in notes:
        append_unique(
            ("experience_note", note["note_id"]),
            _render_experience_note_line(note, test_command),
        )

    for pattern in failure_patterns:
        append_unique(
            ("failure_pattern", pattern["pattern_id"]),
            _render_failure_pattern_line(pattern),
        )

    lines: list[tuple[str, Dependency | None]] = [("# Project memory", None), ("", None)]
    omitted = False
    section_order = (
        "Fast Path",
        "Commands",
        "Known Failures",
        "Experience Notes",
        "Boundaries",
        "Project",
    )
    for section in section_order:
        if section == "Known Failures" and not sections[section]:
            continue
        lines.append((f"## {section}", None))
        for dep, line in sections[section]:
            # Once the budget is hit, stop content lines in every later section
            # too; otherwise a short low-priority line could render while a
            # higher-priority line was dropped.
            if omitted or _body_length(_line_texts(lines)) + len(line) + 1 > MAX_BODY_CHARS:
                omitted = True
                break
            lines.append((line, dep))
        lines.append(("", None))
    if omitted:
        lines = _with_truncation_notice(lines)
    rendered_lines = _line_texts(lines)
    joined = "\n".join(rendered_lines).rstrip() + "\n"
    body = _redact_text(joined)
    redacted_lines = body.rstrip("\n").split("\n")
    if len(redacted_lines) != len(joined.rstrip("\n").split("\n")):
        # Redaction changed the line count, so per-line hashes would misalign;
        # dropping them forces the block dirty instead of recording wrong hashes.
        return body, {}
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
        return ("Fast Path", _rediscovery_waste_fast_path_line(test_command))
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

    action = _collapse_whitespace(str(note["suggested_action"] or ""))
    if not action:
        action = _collapse_whitespace(str(note["body"] or ""))
    if not action:
        return None
    return ("Experience Notes", f"- {action}")


def _render_failure_pattern_line(pattern: sqlite3.Row) -> tuple[str, str] | None:
    error_signature = _collapse_whitespace(str(pattern["error_signature"] or ""))
    suggested_action = _plain_text(str(pattern["suggested_action"] or ""))
    if not error_signature or not suggested_action:
        return None

    command = _collapse_whitespace(str(pattern["command_norm"] or ""))
    if command:
        return (
            "Known Failures",
            (
                f"- If {_inline_code(command)} fails with {_inline_code(error_signature)}: "
                f"{suggested_action}"
            ),
        )
    return (
        "Known Failures",
        f"- If this failure recurs with {_inline_code(error_signature)}: {suggested_action}",
    )


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


def _known_test_command(facts: list[sqlite3.Row]) -> str | None:
    test_facts = [
        (str(fact["qualifier"]), _collapse_whitespace(str(fact["object_norm"])))
        for fact in facts
        if fact["predicate"] == "uses_test_command"
    ]
    commands = {command for _qualifier, command in test_facts if command}
    if len(commands) == 1:
        return next(iter(commands))
    base_commands = {
        command
        for qualifier, command in test_facts
        if command and ":" not in qualifier
    }
    if len(base_commands) == 1:
        return next(iter(base_commands))
    return None


def _rediscovery_waste_fast_path_line(command: str | None) -> str:
    if command:
        return (
            f"- For validation tasks, first run {_inline_code(command)}. Do not rediscover "
            "package scripts, README, or deployment docs before trying this known command "
            "unless it fails or the user explicitly asks for exploration."
        )
    return (
        "- For validation tasks, first run the known verification command. Do not rediscover "
        "package scripts, README, or deployment docs before trying it unless it fails or the "
        "user explicitly asks for exploration."
    )


def _inline_code(value: str) -> str:
    return f"`{_collapse_whitespace(value).replace('`', '')}`"


def _plain_text(value: str) -> str:
    return _collapse_whitespace(value).replace("`", "")


def _collapse_whitespace(value: str) -> str:
    return " ".join(value.split())


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
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # A non-UTF-8 file cannot be omni-generated; treat it as a manual edit
        # instead of crashing so --force can recover.
        return True
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


def _replace_file_text(path: Path, text: str) -> None:
    # Write through a temp file and atomically replace so an interrupted render
    # cannot leave a half-written memory.md behind for readers or later renders.
    tmp_path = path.with_name(path.name + ".omni-tmp")
    try:
        tmp_path.write_text(text, encoding="utf-8")
        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)


def _diff(path: Path, rendered: str) -> str:
    try:
        current = path.read_text(encoding="utf-8") if path.exists() else ""
    except UnicodeDecodeError:
        current = ""
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
    return [line for line, _dep in lines]


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
