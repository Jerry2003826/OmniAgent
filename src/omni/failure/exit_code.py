"""Exit code extraction from event metadata."""

from __future__ import annotations

import sqlite3
from typing import Any

from omni.failure.meta import _nested_error_strings, _nested_get

# Exit 127 means "command not found". On hosts without a given shell (for example
# Windows without bash), an agent's failed shell or command probe reports 127.
# That is environment noise, not a project failure, so those candidates are skipped.
COMMAND_NOT_FOUND_EXIT_CODE = 127


def _event_exit_code(event: sqlite3.Row, meta: dict[str, Any]) -> int | None:
    if event["exit_code"] is not None:
        return int(event["exit_code"])
    for value in _exit_code_text_candidates(meta):
        exit_code = _parse_exit_code_text(value)
        if exit_code is not None:
            return exit_code
    return None


def _exit_code_text_candidates(meta: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for value in (
        meta.get("error"),
        meta.get("stderr"),
        _nested_get(meta.get("tool_response"), "error"),
        _nested_get(meta.get("tool_response"), "stderr"),
        _nested_get(meta.get("toolUseResult"), "error"),
        _nested_get(meta.get("toolUseResult"), "stderr"),
    ):
        if isinstance(value, str):
            values.append(value)
    values.extend(_nested_error_strings(meta))
    return values


def _parse_exit_code_text(value: str) -> int | None:
    lowered = value.lower()
    for marker in (
        "exit_code",
        "exit code",
        "exit status",
        "exited with status",
        "exited with code",
        "exited with",
    ):
        start = lowered.find(marker)
        if start == -1:
            continue
        exit_code = _integer_after_marker(value, start + len(marker))
        if exit_code is not None:
            return exit_code
    return None


def _integer_after_marker(value: str, start: int) -> int | None:
    index = _skip_exit_code_separator(value, start)
    sign = 1
    if index < len(value) and value[index] == "-":
        sign = -1
        index += 1
    end = index
    while end < len(value) and value[end].isdigit():
        end += 1
    if end == index:
        return None
    return sign * int(value[index:end])


def _skip_exit_code_separator(value: str, index: int) -> int:
    while index < len(value) and value[index].isspace():
        index += 1
    if index < len(value) and value[index] in {":", "="}:
        index += 1
    while index < len(value) and value[index].isspace():
        index += 1
    return index
