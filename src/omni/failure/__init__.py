"""Reviewable failure candidates derived from redacted event evidence."""

from __future__ import annotations

import argparse
import sqlite3
from typing import Any

from omni._common import memory_cli_readonly
from omni.jsonio import as_json

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
    "extract_candidates",
    "list_candidates",
    "list_patterns",
    "normalize_command",
    "reject_candidate",
    "retire_pattern",
    "show_candidate",
    "show_pattern",
]


def cli_command_readonly(args: argparse.Namespace) -> bool:
    return memory_cli_readonly(
        args.failure_command,
        getattr(args, "failure_pattern_command", None),
        nested_parent="pattern",
    )


def handle_cli_action(
    conn: sqlite3.Connection,
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
) -> Any:
    if args.failure_command == "extract":
        candidates = extract_candidates(conn, args.run_id)
        return {"created": len(candidates), "candidates": candidates}
    if args.failure_command == "ls":
        return {"candidates": list_candidates(conn, args.state)}
    if args.failure_command == "show":
        return show_candidate(conn, args.failure_cand_id)
    if args.failure_command == "approve":
        return approve_candidate(
            conn,
            args.failure_cand_id,
            summary=args.summary,
            suggested_action=args.suggested_action,
        )
    if args.failure_command == "reject":
        return reject_candidate(conn, args.failure_cand_id)
    if args.failure_command == "pattern":
        if args.failure_pattern_command == "ls":
            return {"patterns": list_patterns(conn, status=args.status)}
        if args.failure_pattern_command == "show":
            return show_pattern(conn, args.pattern_id)
        if args.failure_pattern_command == "retire":
            return retire_pattern(conn, args.pattern_id)
        parser.error(f"unknown failure pattern command: {args.failure_pattern_command}")
    parser.error(f"unknown failure command: {args.failure_command}")
