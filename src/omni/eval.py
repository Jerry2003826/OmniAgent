"""Read-only behavior evaluation for ingested runs."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

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


def evaluate_run(root: Path | str, run_id: str) -> dict[str, Any]:
    """Classify whether one ingested run appears to use memory effectively."""

    db_path = Path(root).resolve() / ".omni" / "omni.sqlite3"
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

    expected_norm = {
        _normalize_command(command)
        for commands in expected_commands.values()
        for command in commands
    }
    observed_commands = _observed_commands(events)
    first_expected = _first_expected_command(observed_commands, expected_norm)
    first_expected_seq = None if first_expected is None else first_expected["seq"]
    rediscovery = _rediscovery_before(events, first_expected_seq)
    claude_md_read = any(_mentions_path(event, "CLAUDE.md") for event in events)
    memory_md_read = any(_mentions_path(event, MEMORY_PATH) for event in events)

    result = {
        "run_id": run_id,
        "claude_md_read": claude_md_read,
        "memory_md_read": memory_md_read,
        "active_expected_commands": expected_commands,
        "observed_commands": observed_commands,
        "first_expected_command_position": first_expected_seq,
        "first_expected_command": None if first_expected is None else first_expected["command"],
        "rediscovery_events_before_first_expected_command": rediscovery,
        "rediscovery_count": len(rediscovery),
        "expected_verification_executed": first_expected is not None,
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
    position_improved = (
        isinstance(cold_position, int)
        and isinstance(warm_position, int)
        and warm_position < cold_position
    )
    rediscovery_improved = warm["rediscovery_count"] < cold["rediscovery_count"]
    improvement = bool(rediscovery_improved or position_improved)

    return {
        "cold_run_id": cold_run_id,
        "warm_run_id": warm_run_id,
        "cold_rediscovery_count": cold["rediscovery_count"],
        "warm_rediscovery_count": warm["rediscovery_count"],
        "cold_first_expected_command_position": cold_position,
        "warm_first_expected_command_position": warm_position,
        "improvement": improvement,
        "memory_effect_summary": {
            "cold": cold["memory_effect"],
            "warm": warm["memory_effect"],
            "summary": (
                "warm reduced rediscovery or reached expected commands earlier"
                if improvement
                else "no measurable warm-run improvement"
            ),
        },
    }


def as_json(value: dict[str, Any]) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


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


def _observed_commands(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    observed: list[dict[str, Any]] = []
    for event in events:
        command = _nested_command(event["meta"])
        if command is None:
            continue
        observed.append(
            {
                "seq": event["seq"],
                "tool": event["tool"],
                "command": _normalize_command(str(command)),
            }
        )
    return observed


def _first_expected_command(
    observed_commands: list[dict[str, Any]], expected_norm: set[str]
) -> dict[str, Any] | None:
    if not expected_norm:
        return None
    for command in observed_commands:
        if _normalize_command(command["command"]) in expected_norm:
            return command
    return None


def _rediscovery_before(
    events: list[dict[str, Any]], first_expected_seq: int | None
) -> list[dict[str, Any]]:
    boundary = float("inf") if first_expected_seq is None else first_expected_seq
    rediscovery: list[dict[str, Any]] = []
    for event in events:
        if int(event["seq"]) >= boundary:
            continue
        rediscovery.extend(_rediscovery_for_event(event))
    return rediscovery


def _rediscovery_for_event(event: dict[str, Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    strings = list(_nested_strings(event["meta"]))
    command = _nested_command(event["meta"])

    for filename in REDISCOVERY_FILES:
        if _contains_path(strings, filename):
            found.append(_rediscovery_event(event, filename, _detail_for(event, filename)))

    broad_detail = _broad_scan_detail(event, command, strings)
    if broad_detail is not None:
        found.append(_rediscovery_event(event, "broad_scan", broad_detail))

    return found


def _rediscovery_event(event: dict[str, Any], kind: str, detail: str) -> dict[str, Any]:
    return {
        "seq": event["seq"],
        "kind": kind,
        "tool": event["tool"],
        "detail": detail,
    }


def _mentions_path(event: dict[str, Any], target: str) -> bool:
    command = _nested_command(event["meta"])
    if command is not None and _path_in_text(str(command), target):
        return True
    return _contains_path(_nested_strings(event["meta"]), target)


def _contains_path(values: Any, target: str) -> bool:
    return any(_path_in_text(value, target) for value in values)


def _path_in_text(value: str, target: str) -> bool:
    normalized_value = value.replace("\\", "/").lower()
    normalized_target = target.replace("\\", "/").lower()
    return normalized_target in normalized_value


def _broad_scan_detail(
    event: dict[str, Any], command: Any | None, strings: list[str]
) -> str | None:
    tool = str(event["tool"] or "").lower()
    if tool == "glob":
        return _first_with_glob(strings) or "Glob"
    if tool == "ls":
        return _detail_for(event, "LS")

    if command is None:
        return None
    normalized = _normalize_command(str(command))
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


def _detail_for(event: dict[str, Any], target: str) -> str:
    command = _nested_command(event["meta"])
    if command is not None:
        return _normalize_command(str(command))
    for value in _nested_strings(event["meta"]):
        if target == "LS" or _path_in_text(value, target):
            return value
    return str(event["tool"] or event["event_type"] or "")


def _classify(
    result: dict[str, Any], *, has_expected: bool, has_events: bool
) -> tuple[str, str]:
    if not has_expected or not has_events:
        return ("unknown", "insufficient evidence: no active expected facts or no events")
    if result["expected_verification_executed"] and result["rediscovery_count"] == 0:
        return ("helped", "expected command executed before rediscovery")
    if result["expected_verification_executed"]:
        return ("neutral", "expected command executed after rediscovery")
    if (result["claude_md_read"] or result["memory_md_read"]) and result["rediscovery_count"] > 0:
        return (
            "failed_to_help",
            "CLAUDE.md or memory was read, rediscovery occurred, and no expected command executed",
        )
    return ("unknown", "insufficient evidence")


def _decode_meta(meta_json: str | None) -> dict[str, Any]:
    if not meta_json:
        return {}
    try:
        decoded = json.loads(meta_json)
    except (TypeError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _nested_command(value: Any) -> Any:
    if isinstance(value, dict):
        for key in ("command", "cmd"):
            if key in value:
                return value[key]
        for key in ("input", "tool_input", "parameters", "args"):
            found = _nested_command(value.get(key))
            if found is not None:
                return found
        for child in value.values():
            found = _nested_command(child)
            if found is not None:
                return found
    if isinstance(value, list):
        for child in value:
            found = _nested_command(child)
            if found is not None:
                return found
    return None


def _nested_strings(value: Any) -> list[str]:
    strings: list[str] = []
    if isinstance(value, dict):
        for child in value.values():
            strings.extend(_nested_strings(child))
    elif isinstance(value, list):
        for child in value:
            strings.extend(_nested_strings(child))
    elif isinstance(value, str):
        strings.append(value)
    return strings


def _normalize_command(command: str) -> str:
    return " ".join(command.strip().split())


def _unknown_result(run_id: str, reason: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "claude_md_read": False,
        "memory_md_read": False,
        "active_expected_commands": {predicate: [] for predicate in EXPECTED_PREDICATES},
        "observed_commands": [],
        "first_expected_command_position": None,
        "first_expected_command": None,
        "rediscovery_events_before_first_expected_command": [],
        "rediscovery_count": 0,
        "expected_verification_executed": False,
        "memory_effect": "unknown",
        "reason": reason,
    }
