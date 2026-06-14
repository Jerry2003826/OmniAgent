"""Error line extraction, normalization, and signature hashing."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from omni.failure._text import MAX_ERROR_CHARS, _collapse_whitespace, _safe_text
from omni.failure.meta import _nested_error_strings, _nested_get

ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
WINDOWS_ABS_PATH_RE = re.compile(r"(?i)\b[A-Z]:[\\/][^\s\"']+")


def _first_error_line(meta: dict[str, Any]) -> str | None:
    for value in (
        meta.get("error"),
        meta.get("stderr"),
        _nested_get(meta.get("tool_response"), "stderr"),
        _nested_get(meta.get("toolUseResult"), "stderr"),
    ):
        line = _first_meaningful_line(value)
        if line is not None:
            return line
    for value in _nested_error_strings(meta):
        line = _first_meaningful_line(value)
        if line is not None:
            return line
    return None


def _first_meaningful_line(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    for line in value.splitlines():
        normalized = _collapse_whitespace(ANSI_RE.sub("", line))
        if normalized:
            return normalized
    return None


def _normalize_error_line(value: str) -> str:
    normalized = _collapse_whitespace(ANSI_RE.sub("", value))
    normalized = WINDOWS_ABS_PATH_RE.sub("<path>", normalized)
    normalized = _mask_unix_abs_paths(normalized)
    return _safe_text(normalized, MAX_ERROR_CHARS) or "unknown failure"


def _mask_unix_abs_paths(value: str) -> str:
    masked: list[str] = []
    index = 0
    while index < len(value):
        if _starts_unix_abs_path(value, index):
            end = _path_end(value, index)
            path = value[index:end]
            if path.count("/") >= 2:
                masked.append("<path>")
                index = end
                continue
        masked.append(value[index])
        index += 1
    return "".join(masked)


def _starts_unix_abs_path(value: str, index: int) -> bool:
    if value[index] != "/":
        return False
    return index == 0 or not value[index - 1].isalnum()


def _path_end(value: str, start: int) -> int:
    end = start
    while end < len(value) and not _is_path_boundary(value[end]):
        end += 1
    return end


def _is_path_boundary(char: str) -> bool:
    return char.isspace() or char in {"'", '"'}


def _signature_hash(
    command_norm: str | None, exit_code: int | None, error_signature: str
) -> str:
    payload = f"{command_norm or ''}|{'' if exit_code is None else exit_code}|{error_signature}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
