"""Run classification, rediscovery detection, and dogfood evaluation."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from omni import db
from omni.eval.command_match import (
    _contains_path,
    _has_unresolved_directory_change_prefix,
    _matches_any_expected_command,
    _normalize_command,
    _path_in_text,
    _target_detail,
)
from omni.eval.meta import (
    _decode_meta,
    _input_metadata,
    _nested_command,
    _nested_strings,
)
from omni.jsonio import safe_json_string

EXPECTED_PREDICATES = (
    "uses_test_command",
    "uses_build_command",
    "uses_lint_command",
    "uses_typecheck_command",
)

REDISCOVERY_FILES = (
    "README.md",
    "package.json",
    "pnpm-lock.yaml",
    "package-lock.json",
    "yarn.lock",
    "DEPLOY.md",
)

MEMORY_PATH = ".omni/generated/memory.md"
MAX_OBSERVED_COMMANDS = 100
MAX_REDISCOVERY_EVENTS = 100
MAX_COMMAND_CHARS = 200
MAX_DETAIL_CHARS = 200


def evaluate_run(root: Path | str, run_id: str) -> dict[str, Any]:
    """Classify whether one ingested run appears to use memory effectively."""

    project_root = Path(root).resolve()
    db_path = project_root / ".omni" / "omni.sqlite3"
    if not db_path.exists():
        return _unknown_result(
            run_id,
            "insufficient evidence: OmniMemory database is missing",
        )

    try:
        conn = _connect_readonly(db_path)
    except sqlite3.Error as exc:
        return _unknown_result(run_id, f"insufficient evidence: cannot open database: {exc}")

    try:
        expected_commands = _active_expected_commands(conn)
        events = _events_for_run(conn, run_id)
    except sqlite3.Error as exc:
        return _unknown_result(run_id, f"insufficient evidence: cannot read database: {exc}")
    finally:
        conn.close()

    expected_norm = [
        _normalize_command(command, project_root=project_root)
        for commands in expected_commands.values()
        for command in commands
    ]
    observed_commands = _observed_commands(events, project_root=project_root)
    first_expected = _first_expected_command(observed_commands, expected_norm)
    first_expected_seq = None if first_expected is None else first_expected["seq"]
    rediscovery = _rediscovery_before(events, first_expected_seq, project_root=project_root)
    claude_md_read = any(_mentions_path(event, "CLAUDE.md") for event in events)
    memory_md_read = any(_mentions_path(event, MEMORY_PATH) for event in events)
    memory_context_seen_but_no_expected = (
        (claude_md_read or memory_md_read) and first_expected is None
    )
    observed_report, observed_omitted = _limit_observed_commands(observed_commands)
    rediscovery_report, rediscovery_omitted = _limit_report_items(
        rediscovery, MAX_REDISCOVERY_EVENTS
    )

    result = {
        "run_id": run_id,
        "claude_md_read": claude_md_read,
        "memory_md_read": memory_md_read,
        "active_expected_commands": expected_commands,
        "observed_commands": observed_report,
        "observed_commands_omitted": observed_omitted,
        "first_expected_command_position": first_expected_seq,
        "first_expected_command": (
            None if first_expected is None else _safe_command(first_expected["command"])
        ),
        "rediscovery_events_before_first_expected_command": rediscovery_report,
        "rediscovery_events_omitted": rediscovery_omitted,
        "rediscovery_count": len(rediscovery),
        "expected_verification_executed": first_expected is not None,
        "memory_context_seen_but_no_expected_command": memory_context_seen_but_no_expected,
    }
    effect, reason = _classify(result, has_expected=bool(expected_norm), has_events=bool(events))
    result["memory_effect"] = effect
    result["reason"] = reason
    return result


def evaluate_dogfood(
    root: Path | str, *, cold_run_id: str, warm_run_id: str
) -> dict[str, Any]:
    """Compare cold and warm run behavior using behavior-eval v0 signals."""

    cold = evaluate_run(root, cold_run_id)
    warm = evaluate_run(root, warm_run_id)
    cold_position = cold["first_expected_command_position"]
    warm_position = warm["first_expected_command_position"]
    cold_comparable = _run_is_comparable(root, cold_run_id)
    command_adopted = (
        cold_comparable and cold_position is None and isinstance(warm_position, int)
    )
    position_improved = (
        cold_comparable
        and isinstance(cold_position, int)
        and isinstance(warm_position, int)
        and warm_position < cold_position
    )
    rediscovery_improved = (
        cold_comparable and warm["rediscovery_count"] < cold["rediscovery_count"]
    )
    warm_executed_expected = bool(warm["expected_verification_executed"])
    improvement = bool(
        cold_comparable
        and warm_executed_expected
        and (command_adopted or rediscovery_improved or position_improved)
    )
    if not cold_comparable:
        summary = "cold run not comparable"
    elif improvement:
        summary = "warm adopted expected command or reduced rediscovery"
    else:
        summary = "no measurable warm-run improvement"

    return {
        "cold_run_id": cold_run_id,
        "warm_run_id": warm_run_id,
        "cold_comparable": cold_comparable,
        "cold_rediscovery_count": cold["rediscovery_count"],
        "warm_rediscovery_count": warm["rediscovery_count"],
        "cold_first_expected_command_position": cold_position,
        "warm_first_expected_command_position": warm_position,
        "command_adopted": command_adopted,
        "improvement": improvement,
        "memory_effect_summary": {
            "cold": cold["memory_effect"],
            "warm": warm["memory_effect"],
            "summary": summary,
        },
    }


def review_dogfood(
    root: Path | str,
    *,
    warm_run_id: str,
    cold_run_id: str | None = None,
) -> dict[str, Any]:
    """Read-only consolidated dogfood review for one warm run."""

    project_root = Path(root).resolve()
    warm_eval = evaluate_run(project_root, warm_run_id)

    warm_outcome: dict[str, Any] | None = None
    from omni import outcome
    from omni.dbaccess import connect_project_readonly

    try:
        conn = connect_project_readonly(project_root)
    except (FileNotFoundError, ValueError):
        warm_outcome = None
    else:
        try:
            try:
                warm_outcome = outcome.show_outcome(conn, warm_run_id)
            except ValueError:
                warm_outcome = None
        finally:
            conn.close()

    pairwise = None
    if cold_run_id is not None:
        pairwise = evaluate_dogfood(
            project_root,
            cold_run_id=cold_run_id,
            warm_run_id=warm_run_id,
        )

    return {
        "warm_run_id": warm_run_id,
        "cold_run_id": cold_run_id,
        "warm_eval": warm_eval,
        "warm_outcome": warm_outcome,
        "pairwise": pairwise,
    }


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    return db.connect_readonly(db_path)


def _run_is_comparable(root: Path | str, run_id: str) -> bool:
    db_path = Path(root).resolve() / ".omni" / "omni.sqlite3"
    if not db_path.exists():
        return False
    try:
        conn = _connect_readonly(db_path)
    except sqlite3.Error:
        return False
    try:
        row = conn.execute(
            """
            SELECT
              EXISTS(SELECT 1 FROM runs WHERE run_id = ?) AS has_run,
              EXISTS(SELECT 1 FROM events WHERE run_id = ?) AS has_events
            """,
            (run_id, run_id),
        ).fetchone()
    except sqlite3.Error:
        return False
    finally:
        conn.close()
    return bool(row and row["has_run"] and row["has_events"])


def _active_expected_commands(conn: sqlite3.Connection) -> dict[str, list[str]]:
    commands: dict[str, list[str]] = {predicate: [] for predicate in EXPECTED_PREDICATES}
    rows = conn.execute(
        f"""
        SELECT predicate, object_norm
        FROM facts
        WHERE retired_seq IS NULL
          AND predicate IN ({",".join("?" for _ in EXPECTED_PREDICATES)})
        ORDER BY predicate, qualifier, created_seq, object_norm
        """,
        EXPECTED_PREDICATES,
    ).fetchall()
    for row in rows:
        predicate = str(row["predicate"])
        command = str(row["object_norm"])
        if command not in commands[predicate]:
            commands[predicate].append(command)
    return commands


def _events_for_run(conn: sqlite3.Connection, run_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT seq, event_type, tool, meta, input_ref, output_ref, source
        FROM events
        WHERE run_id = ?
        ORDER BY seq
        """,
        (run_id,),
    ).fetchall()
    return [
        {
            "seq": row["seq"],
            "event_type": row["event_type"],
            "tool": row["tool"],
            "meta": _decode_meta(row["meta"]),
            "input_ref": row["input_ref"],
            "output_ref": row["output_ref"],
            "source": row["source"],
        }
        for row in rows
    ]


def _observed_commands(
    events: list[dict[str, Any]], *, project_root: Path
) -> list[dict[str, Any]]:
    observed: list[dict[str, Any]] = []
    for event in events:
        command = _nested_command(_input_metadata(event["meta"]))
        if command is None:
            continue
        observed.append(
            {
                "seq": event["seq"],
                "tool": event["tool"],
                "command": _normalize_command(str(command), project_root=project_root),
            }
        )
    return observed


def _first_expected_command(
    observed_commands: list[dict[str, Any]], expected_norm: list[str]
) -> dict[str, Any] | None:
    if not expected_norm:
        return None
    for command in observed_commands:
        if _matches_any_expected_command(command["command"], expected_norm):
            return command
    return None


def _rediscovery_before(
    events: list[dict[str, Any]], first_expected_seq: int | None, *, project_root: Path
) -> list[dict[str, Any]]:
    boundary = float("inf") if first_expected_seq is None else first_expected_seq
    rediscovery: list[dict[str, Any]] = []
    for event in events:
        if int(event["seq"]) >= boundary:
            continue
        rediscovery.extend(_rediscovery_for_event(event, project_root=project_root))
    return rediscovery


def _rediscovery_for_event(
    event: dict[str, Any], *, project_root: Path
) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    input_meta = _input_metadata(event["meta"])
    strings = list(_nested_strings(input_meta))
    command = _nested_command(input_meta)

    for filename in REDISCOVERY_FILES:
        if _contains_path(strings, filename):
            found.append(
                _rediscovery_event(
                    event,
                    filename,
                    _detail_for(event, filename, input_meta, project_root=project_root),
                )
            )

    broad_detail = _broad_scan_detail(
        event, command, strings, input_meta, project_root=project_root
    )
    if broad_detail is not None:
        found.append(_rediscovery_event(event, "broad_scan", broad_detail))

    return found


def _rediscovery_event(event: dict[str, Any], kind: str, detail: str) -> dict[str, Any]:
    return {
        "seq": event["seq"],
        "kind": kind,
        "tool": event["tool"],
        "detail": _safe_detail(detail),
    }


def _mentions_path(event: dict[str, Any], target: str) -> bool:
    input_meta = _input_metadata(event["meta"])
    command = _nested_command(input_meta)
    if command is not None and _path_in_text(str(command), target):
        return True
    return _contains_path(_nested_strings(input_meta), target)


def _broad_scan_detail(
    event: dict[str, Any],
    command: Any | None,
    strings: list[str],
    input_meta: Any,
    *,
    project_root: Path,
) -> str | None:
    tool = str(event["tool"] or "").lower()
    if tool == "glob":
        return _first_with_glob(strings) or "Glob"
    if tool == "ls":
        return _detail_for(event, "LS", input_meta, project_root=project_root)

    if command is None:
        return None
    if _has_unresolved_directory_change_prefix(str(command), project_root):
        return None
    normalized = _normalize_command(str(command), project_root=project_root)
    lowered = normalized.lower()
    if (
        "get-childitem" in lowered
        or "rg --files" in lowered
        or lowered.startswith("find .")
        or lowered.startswith("tree")
        or lowered in {"ls", "dir"}
        or lowered.startswith("ls ")
        or lowered.startswith("dir ")
    ):
        return normalized
    return None


def _first_with_glob(values: list[str]) -> str | None:
    for value in values:
        if "*" in value:
            return value
    return None


def _detail_for(
    event: dict[str, Any], target: str, input_meta: Any, *, project_root: Path
) -> str:
    command = _nested_command(input_meta)
    if command is not None:
        return f"command: {_normalize_command(str(command), project_root=project_root)}"
    for value in _nested_strings(input_meta):
        if target == "LS" or _path_in_text(value, target):
            return _target_detail(value, target)
    return str(event["tool"] or event["event_type"] or "")


def _classify(
    result: dict[str, Any], *, has_expected: bool, has_events: bool
) -> tuple[str, str]:
    if not has_expected or not has_events:
        return ("unknown", "insufficient evidence: no active expected facts or no events")
    if result["expected_verification_executed"] and result["rediscovery_count"] == 0:
        if not (result["claude_md_read"] or result["memory_md_read"]):
            return (
                "neutral",
                "expected command executed before rediscovery, but memory context not observed",
            )
        return (
            "helped",
            f"expected command executed before rediscovery: {result['first_expected_command']}",
        )
    if result["expected_verification_executed"]:
        return (
            "neutral",
            "expected command executed after rediscovery: "
            f"{result['first_expected_command']}; rediscovery before expected command: "
            f"{_rediscovery_kinds(result)}",
        )
    if (result["claude_md_read"] or result["memory_md_read"]) and result["rediscovery_count"] > 0:
        return (
            "failed_to_help",
            "CLAUDE.md or memory context was seen if detectable; "
            f"expected commands include {_expected_commands_summary(result)}; "
            "no expected verification command executed; "
            f"rediscovery occurred before expected command: {_rediscovery_kinds(result)}",
        )
    if result["memory_context_seen_but_no_expected_command"]:
        return (
            "unknown",
            "memory context observed but no expected command and no rediscovery; "
            "task intent unknown",
        )
    return ("unknown", "insufficient evidence")


def _safe_detail(detail: str) -> str:
    normalized = _normalize_command(detail)
    if len(normalized) <= MAX_DETAIL_CHARS:
        return normalized
    return normalized[: MAX_DETAIL_CHARS - 14].rstrip() + "...[truncated]"


def _safe_command(command: str) -> str:
    return safe_json_string(_normalize_command(command), MAX_COMMAND_CHARS)


def _limit_observed_commands(
    commands: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], int]:
    limited, omitted = _limit_report_items(commands, MAX_OBSERVED_COMMANDS)
    return (
        [
            {
                **command,
                "command": _safe_command(str(command["command"])),
            }
            for command in limited
        ],
        omitted,
    )


def _limit_report_items(
    items: list[dict[str, Any]], limit: int
) -> tuple[list[dict[str, Any]], int]:
    return (items[:limit], max(0, len(items) - limit))


def _expected_commands_summary(result: dict[str, Any]) -> str:
    commands = [
        command
        for predicate in EXPECTED_PREDICATES
        for command in result["active_expected_commands"].get(predicate, [])
    ]
    return ", ".join(commands) if commands else "none"


def _rediscovery_kinds(result: dict[str, Any]) -> str:
    kinds = []
    for event in result["rediscovery_events_before_first_expected_command"]:
        kind = event["kind"]
        if kind not in kinds:
            kinds.append(kind)
    return ", ".join(kinds) if kinds else "none"


def _unknown_result(run_id: str, reason: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "claude_md_read": False,
        "memory_md_read": False,
        "active_expected_commands": {predicate: [] for predicate in EXPECTED_PREDICATES},
        "observed_commands": [],
        "observed_commands_omitted": 0,
        "first_expected_command_position": None,
        "first_expected_command": None,
        "rediscovery_events_before_first_expected_command": [],
        "rediscovery_events_omitted": 0,
        "rediscovery_count": 0,
        "expected_verification_executed": False,
        "memory_context_seen_but_no_expected_command": False,
        "memory_effect": "unknown",
        "reason": reason,
    }
