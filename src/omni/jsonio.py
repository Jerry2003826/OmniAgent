"""Shared JSON output and text redaction helpers."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from omni.redact import redact

DEFAULT_JSON_DETAIL_CHARS = 200


def redact_text(value: str | None) -> str | None:
    if value is None:
        return None
    return redact(value.encode("utf-8")).data.decode("utf-8", errors="replace")


def redact_mapping_str(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return redact(encoded).data.decode("utf-8", errors="replace")


def is_redaction_wrapper(value: str) -> bool:
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return True
    return isinstance(decoded, dict) and decoded.get("error") in {
        "payload_truncated",
        "redaction_failed",
    }


def safe_json_string(value: str, max_chars: int = DEFAULT_JSON_DETAIL_CHARS) -> str:
    redacted = redact(value.encode("utf-8")).data.decode("utf-8", errors="replace")
    if len(redacted) <= max_chars:
        return redacted
    return redacted[: max_chars - 14].rstrip() + "...[truncated]"


def as_json(
    value: Any,
    *,
    max_detail_chars: int = DEFAULT_JSON_DETAIL_CHARS,
) -> str:
    return dump_json(
        value,
        string_sanitizer=lambda s: safe_json_string(s, max_detail_chars),
    )


def dump_json(
    value: Any,
    *,
    string_sanitizer: Callable[[str], str] | None = None,
) -> str:
    sanitized = _sanitize_for_json(value, string_sanitizer=string_sanitizer)
    encoded = json.dumps(sanitized, indent=2, sort_keys=True).encode("utf-8")
    defended = redact(encoded).data.decode("utf-8", errors="replace")
    if is_redaction_wrapper(defended):
        return encoded.decode("utf-8", errors="replace") + "\n"
    return defended + "\n"


def _sanitize_for_json(
    value: Any,
    *,
    string_sanitizer: Callable[[str], str] | None,
) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _sanitize_for_json(child, string_sanitizer=string_sanitizer)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [
            _sanitize_for_json(child, string_sanitizer=string_sanitizer) for child in value
        ]
    if isinstance(value, str) and string_sanitizer is not None:
        return string_sanitizer(value)
    return value
