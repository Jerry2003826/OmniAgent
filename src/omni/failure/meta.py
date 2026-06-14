"""Event metadata decoding and nested field traversal."""

from __future__ import annotations

import json
from typing import Any, Callable, Iterable

INPUT_CONTAINER_KEYS = ("tool_input", "input", "parameters", "args")
OUTPUT_CONTAINER_KEYS = ("tool_response", "toolUseResult")


def _input_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        collected = []
        for key in INPUT_CONTAINER_KEYS:
            if key in value:
                collected.append(value[key])
        return collected
    return {}


def _nested_command(value: Any) -> str | None:
    return _nested_find(value, _command_from_dict)


def _command_from_dict(value: dict[str, Any]) -> str | None:
    for key in ("command", "cmd"):
        child = value.get(key)
        if isinstance(child, str):
            return child
    return None


def _interrupted(value: Any) -> bool:
    return _nested_match(value, _dict_has_interrupted)


def _dict_has_interrupted(value: dict[str, Any]) -> bool:
    return any(key.lower() == "interrupted" and child is True for key, child in value.items())


def _nested_find(value: Any, reader: Callable[[dict[str, Any]], str | None]) -> str | None:
    if isinstance(value, dict):
        found = reader(value)
        if found is not None:
            return found
        return _nested_find_in_children(value.values(), reader)
    if isinstance(value, list):
        return _nested_find_in_children(value, reader)
    return None


def _nested_find_in_children(
    values: Iterable[Any], reader: Callable[[dict[str, Any]], str | None]
) -> str | None:
    for child in values:
        found = _nested_find(child, reader)
        if found is not None:
            return found
    return None


def _nested_match(value: Any, predicate: Callable[[dict[str, Any]], bool]) -> bool:
    if isinstance(value, dict):
        return predicate(value) or any(
            _nested_match(child, predicate) for child in value.values()
        )
    if isinstance(value, list):
        return any(_nested_match(child, predicate) for child in value)
    return False


def _nested_get(value: Any, target_key: str) -> Any:
    if isinstance(value, dict):
        if target_key in value:
            return value[target_key]
        for child in value.values():
            found = _nested_get(child, target_key)
            if found is not None:
                return found
    if isinstance(value, list):
        for child in value:
            found = _nested_get(child, target_key)
            if found is not None:
                return found
    return None


def _nested_error_strings(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if "error" in key.lower() and isinstance(child, str):
                found.append(child)
            found.extend(_nested_error_strings(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_nested_error_strings(child))
    return found


def _is_shell_tool(tool: Any) -> bool:
    return str(tool or "").lower() in {"bash", "shell", "powershell", "pwsh", "cmd"}


def _decode_meta(meta_json: str | None) -> dict[str, Any]:
    if not meta_json:
        return {}
    try:
        decoded = json.loads(meta_json)
    except (TypeError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _decode_json_object(value: str) -> dict[str, Any]:
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return {"decode_error": "invalid_json"}
    return decoded if isinstance(decoded, dict) else {"decode_error": "non_object"}
