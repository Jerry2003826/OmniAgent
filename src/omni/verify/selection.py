"""Verification command selection from active project facts."""

from __future__ import annotations

import sqlite3
from typing import Any

from omni.verify.text import MAX_COMMAND_CHARS, _safe_text

VERIFY_PREDICATE = "uses_test_command"
PROFILE_VALUES = frozenset({"default", "release", "test"})
PROFILE_PREDICATES = {
    "default": "uses_test_command",
    "test": "uses_test_command",
    "release": "uses_build_command",
}
TASK_TYPE_VALUES = frozenset(
    {"validation", "bugfix", "docs", "refactor", "exploration", "unknown"}
)
TASK_QUALIFIER_HINTS: dict[str, str | None] = {
    "validation": None,
    "bugfix": "node:unit",
    "docs": None,
    "refactor": None,
    "exploration": None,
    "unknown": None,
}
MAX_CANDIDATE_COMMANDS = 10
SELECTION_REASON_SELECTED = "selected active uses_test_command fact"
REASON_CODE_NO_ACTIVE_TEST_COMMAND = "no_active_test_command"
REASON_CODE_AMBIGUOUS_ACTIVE_TEST_COMMAND = "ambiguous_active_test_command"
REASON_CODE_QUALIFIER_NOT_FOUND = "qualifier_not_found"
REASON_CODE_AMBIGUOUS_QUALIFIER = "ambiguous_qualifier"
REASON_CODE_SELECTED = "selected"
REASON_CODE_UNKNOWN = "unknown"
DISAMBIGUATION_HINT = (
    "Pass --qualifier <name> to select one active uses_test_command fact."
)


def _resolve_predicate(profile: str | None) -> str:
    if profile is None:
        return VERIFY_PREDICATE
    return PROFILE_PREDICATES[profile]


def _resolve_qualifier(
    qualifier: str | None,
    task_type: str | None,
) -> str | None:
    if qualifier is not None:
        return qualifier
    if task_type is None:
        return None
    return TASK_QUALIFIER_HINTS.get(task_type)


def _select_verification_command(
    conn: sqlite3.Connection,
    *,
    predicate: str = VERIFY_PREDICATE,
    qualifier: str | None = None,
    task_type: str | None = None,
    profile: str | None = None,
    explicit_qualifier: bool = False,
) -> dict[str, Any]:
    rows = _active_command_rows(conn, predicate)
    candidates = _command_candidates(rows)
    limited, omitted = _limit_candidates(candidates)
    selection_mode = _selection_mode(
        explicit_qualifier=explicit_qualifier,
        task_type=task_type,
        profile=profile,
    )
    if not candidates:
        return {
            "status": "missing",
            "reason_code": REASON_CODE_NO_ACTIVE_TEST_COMMAND,
            "reason": f"no active {predicate} facts",
            "selection_mode": selection_mode,
            "selection_reason": f"no active {predicate} facts",
            "candidate_commands": [],
            "candidate_commands_omitted": 0,
        }

    if qualifier is not None:
        normalized_qualifier = _normalize_qualifier(qualifier)
        display_qualifier = _safe_text(normalized_qualifier, MAX_COMMAND_CHARS)
        qualified_candidates = [
            candidate
            for candidate in candidates
            if candidate["_qualifier_raw"] == normalized_qualifier
        ]
        if not qualified_candidates:
            return {
                "status": "missing",
                "reason_code": REASON_CODE_QUALIFIER_NOT_FOUND,
                "reason": (
                    f"no active {predicate} fact for qualifier "
                    f"{display_qualifier}"
                ),
                "selection_mode": selection_mode,
                "selection_reason": (
                    f"no active {predicate} fact for qualifier "
                    f"{display_qualifier}"
                ),
                "candidate_commands": limited,
                "candidate_commands_omitted": omitted,
                "available_qualifiers": _available_qualifiers(candidates),
            }
        qualified_commands = _unique_commands(qualified_candidates)
        if len(qualified_commands) == 1:
            selection_reason = (
                f"selected active {predicate} fact for qualifier "
                f"{display_qualifier}"
            )
            return _selected(
                qualified_candidates,
                qualified_commands[0],
                candidates,
                selection_mode=selection_mode,
                selection_reason=selection_reason,
            )
        qualified_limited, qualified_omitted = _limit_candidates(qualified_candidates)
        return {
            "status": "ambiguous",
            "reason_code": REASON_CODE_AMBIGUOUS_QUALIFIER,
            "reason": (
                f"ambiguous active {predicate} facts for qualifier "
                f"{display_qualifier}"
            ),
            "selection_mode": selection_mode,
            "selection_reason": (
                f"ambiguous active {predicate} facts for qualifier "
                f"{display_qualifier}"
            ),
            "candidate_commands": qualified_limited,
            "candidate_commands_omitted": qualified_omitted,
            "disambiguation_hint": DISAMBIGUATION_HINT,
        }

    base_candidates = [
        candidate for candidate in candidates if ":" not in candidate["_qualifier_raw"]
    ]
    base_commands = _unique_commands(base_candidates)
    if len(base_commands) == 1:
        return _selected(
            base_candidates,
            base_commands[0],
            candidates,
            selection_mode=selection_mode,
            selection_reason=SELECTION_REASON_SELECTED,
        )

    all_commands = _unique_commands(candidates)
    if len(all_commands) == 1:
        return _selected(
            candidates,
            all_commands[0],
            candidates,
            selection_mode=selection_mode,
            selection_reason=SELECTION_REASON_SELECTED,
        )

    return {
        "status": "ambiguous",
        "reason_code": REASON_CODE_AMBIGUOUS_ACTIVE_TEST_COMMAND,
        "reason": f"ambiguous active {predicate} facts",
        "selection_mode": selection_mode,
        "selection_reason": f"ambiguous active {predicate} facts",
        "candidate_commands": limited,
        "candidate_commands_omitted": omitted,
        "disambiguation_hint": DISAMBIGUATION_HINT,
    }


PLAN_VIEW_SCHEMA_VERSION = 1


def plan_view(
    conn: sqlite3.Connection,
    *,
    qualifier: str | None = None,
    task_type: str | None = None,
    profile: str | None = None,
) -> dict[str, Any]:
    """Return verify selection without executing the chosen command."""

    if task_type is not None and task_type not in TASK_TYPE_VALUES:
        allowed = ", ".join(sorted(TASK_TYPE_VALUES))
        raise ValueError(f"invalid task_type: {task_type!r}; expected one of: {allowed}")
    if profile is not None and profile not in PROFILE_VALUES:
        allowed = ", ".join(sorted(PROFILE_VALUES))
        raise ValueError(f"invalid profile: {profile!r}; expected one of: {allowed}")

    predicate = _resolve_predicate(profile)
    effective_qualifier = _resolve_qualifier(qualifier, task_type)
    selection = _select_verification_command(
        conn,
        predicate=predicate,
        qualifier=effective_qualifier,
        task_type=task_type,
        profile=profile,
        explicit_qualifier=qualifier is not None,
    )
    return {
        "schema_version": PLAN_VIEW_SCHEMA_VERSION,
        "predicate": predicate,
        "qualifier": effective_qualifier,
        "profile": profile,
        "candidate_commands": selection.get("candidate_commands", []),
        "selection_mode": selection.get("selection_mode"),
    }


def _selection_mode(
    *,
    explicit_qualifier: bool,
    task_type: str | None,
    profile: str | None,
) -> str:
    if explicit_qualifier:
        return "qualifier"
    if profile is not None:
        return "profile"
    if task_type is not None:
        return "task"
    return "auto"


def _active_command_rows(conn: sqlite3.Connection, predicate: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT qualifier, object_norm
        FROM facts
        WHERE retired_seq IS NULL
          AND scope = 'project'
          AND subject = '.'
          AND predicate = ?
        ORDER BY qualifier, created_seq, object_norm
        """,
        (predicate,),
    ).fetchall()


def _active_test_command_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return _active_command_rows(conn, VERIFY_PREDICATE)


def _command_candidates(rows: list[sqlite3.Row]) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        command = _normalize_command(str(row["object_norm"]))
        qualifier = _normalize_qualifier(str(row["qualifier"] or "default"))
        key = (qualifier, command)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(
            {
                "qualifier": _safe_text(qualifier, MAX_COMMAND_CHARS),
                "_qualifier_raw": qualifier,
                "command": _safe_text(command, MAX_COMMAND_CHARS),
                "_command_raw": command,
            }
        )
    return candidates


def _selected(
    candidates_to_pick_from: list[dict[str, str]],
    command: str,
    all_candidates: list[dict[str, str]],
    *,
    selection_mode: str,
    selection_reason: str,
) -> dict[str, Any]:
    selected = next(
        candidate for candidate in candidates_to_pick_from if candidate["_command_raw"] == command
    )
    limited, omitted = _limit_candidates(all_candidates)
    return {
        "status": "selected",
        "reason_code": REASON_CODE_SELECTED,
        "reason": SELECTION_REASON_SELECTED,
        "selection_mode": selection_mode,
        "selection_reason": selection_reason,
        "qualifier": selected["qualifier"],
        "command": selected["command"],
        "_command_raw": selected["_command_raw"],
        "candidate_commands": limited,
        "candidate_commands_omitted": omitted,
    }


def _unique_commands(candidates: list[dict[str, str]]) -> list[str]:
    commands: list[str] = []
    for candidate in candidates:
        command = candidate["_command_raw"]
        if command not in commands:
            commands.append(command)
    return commands


def _available_qualifiers(candidates: list[dict[str, str]]) -> list[str]:
    qualifiers: list[str] = []
    for candidate in candidates:
        qualifier = candidate["_qualifier_raw"]
        if qualifier not in qualifiers:
            qualifiers.append(qualifier)
    return sorted(qualifiers)


def _limit_candidates(candidates: list[dict[str, str]]) -> tuple[list[dict[str, str]], int]:
    limited = [
        {
            "qualifier": candidate["qualifier"],
            "command": candidate["command"],
        }
        for candidate in candidates[:MAX_CANDIDATE_COMMANDS]
    ]
    return limited, max(0, len(candidates) - MAX_CANDIDATE_COMMANDS)


def _normalize_command(command: str) -> str:
    return " ".join(command.strip().split())


def _normalize_qualifier(qualifier: str) -> str:
    return qualifier.strip()
