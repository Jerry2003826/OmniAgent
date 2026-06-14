"""Shared helpers with no domain dependencies."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_choice(name: str, value: str, allowed: set[str]) -> None:
    if value not in allowed:
        allowed_text = ", ".join(sorted(allowed))
        raise ValueError(f"invalid {name}: {value}; expected one of: {allowed_text}")


def optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def is_redaction_placeholder(value: str) -> bool:
    return value.startswith("\u27e8REDACTED:") and value.endswith("\u27e9")


def merge_redaction_status(*statuses: str) -> str:
    for status in ("withheld", "truncated", "redacted"):
        if status in statuses:
            return status
    return "clean"


def memory_cli_readonly(
    command: str,
    nested_command: str | None,
    *,
    nested_parent: str,
) -> bool:
    if command in ("ls", "show"):
        return True
    return command == nested_parent and nested_command in ("ls", "show")
