"""Reviewable failure candidates derived from redacted event evidence."""

from __future__ import annotations

from omni.dbaccess import connect_project, connect_project_readonly

from omni.failure._text import (
    MAX_COMMAND_CHARS,
    MAX_ERROR_CHARS,
    MAX_EXCERPT_CHARS,
    MAX_REVIEW_TEXT_CHARS,
)
from omni.failure.command_norm import normalize_command
from omni.failure.error_lines import ANSI_RE, WINDOWS_ABS_PATH_RE
from omni.failure.exit_code import COMMAND_NOT_FOUND_EXIT_CODE
from omni.failure.meta import INPUT_CONTAINER_KEYS, OUTPUT_CONTAINER_KEYS
from omni.failure.repo import (
    LIST_PATTERN_STATUS_VALUES,
    LIST_STATE_VALUES,
    PATTERN_STATUS_VALUES,
    STATE_VALUES,
    approve_candidate,
    as_json,
    extract_candidates,
    list_candidates,
    list_patterns,
    reject_candidate,
    retire_pattern,
    show_candidate,
    show_pattern,
)

__all__ = [
    "ANSI_RE",
    "COMMAND_NOT_FOUND_EXIT_CODE",
    "INPUT_CONTAINER_KEYS",
    "LIST_PATTERN_STATUS_VALUES",
    "LIST_STATE_VALUES",
    "MAX_COMMAND_CHARS",
    "MAX_ERROR_CHARS",
    "MAX_EXCERPT_CHARS",
    "MAX_REVIEW_TEXT_CHARS",
    "OUTPUT_CONTAINER_KEYS",
    "PATTERN_STATUS_VALUES",
    "STATE_VALUES",
    "WINDOWS_ABS_PATH_RE",
    "approve_candidate",
    "as_json",
    "connect_project",
    "connect_project_readonly",
    "extract_candidates",
    "list_candidates",
    "list_patterns",
    "normalize_command",
    "reject_candidate",
    "retire_pattern",
    "show_candidate",
    "show_pattern",
]
