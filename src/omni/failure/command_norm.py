"""Shell command normalization for failure signatures."""

from __future__ import annotations

import shlex

from omni.failure._text import MAX_COMMAND_CHARS, _collapse_whitespace, _safe_text


def normalize_command(command: str | None) -> str | None:
    collapsed = _normalizable_command(command)
    if collapsed is None:
        return None
    tokens = _shell_tokens(collapsed)
    if not tokens:
        return None
    lowered = [token.lower() for token in tokens]
    known = _known_command_norm(lowered)
    if known is not None:
        return known
    return _safe_text(collapsed, MAX_COMMAND_CHARS)


def _normalizable_command(command: str | None) -> str | None:
    if command is None:
        return None
    collapsed = _primary_command_segment(_collapse_whitespace(command))
    return collapsed or None


def _known_command_norm(lowered: list[str]) -> str | None:
    first = lowered[0]
    if first in {"pnpm", "npm", "yarn"}:
        return _package_command_norm(first, lowered)
    if first == "bun":
        return _single_arg_command_norm("bun", lowered)
    if first == "uv":
        return _uv_command_norm(lowered)
    if first in {"python", "python3", "py"}:
        return _python_module_norm(first, lowered)
    if first == "pytest":
        return "pytest"
    if first in {"bash", "sh", "pwsh", "powershell", "cmd"}:
        return first
    return None


def _package_command_norm(first: str, lowered: list[str]) -> str:
    if len(lowered) >= 3 and lowered[1] == "run":
        return f"{first} run {lowered[2]}"
    if len(lowered) >= 2:
        return f"{first} run {lowered[1]}"
    return first


def _single_arg_command_norm(first: str, lowered: list[str]) -> str:
    if len(lowered) >= 2:
        return f"{first} {lowered[1]}"
    return first


def _uv_command_norm(lowered: list[str]) -> str | None:
    if len(lowered) >= 3 and lowered[1] == "run":
        return f"uv run {lowered[2]}"
    return None


def _python_module_norm(first: str, lowered: list[str]) -> str | None:
    if len(lowered) >= 3 and lowered[1] == "-m":
        return f"{first} -m {lowered[2]}"
    return None


def _primary_command_segment(command: str) -> str:
    segments = _split_shell_segments(command)
    for segment in segments:
        tokens = _shell_tokens(segment)
        if not tokens:
            continue
        command_name = tokens[0].lower()
        if command_name in {"cd", "pushd", "popd"}:
            continue
        if command_name in {"if", "then"}:
            continue
        return segment
    return command


def _split_shell_segments(command: str) -> list[str]:
    segments: list[str] = []
    current: list[str] = []
    quote: str | None = None
    index = 0
    while index < len(command):
        char = command[index]
        if quote is not None:
            current.append(char)
            if char == quote:
                quote = None
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            current.append(char)
            index += 1
            continue
        if char == ";":
            _append_segment(segments, current)
            current = []
            index += 1
            continue
        if command.startswith("&&", index) or command.startswith("||", index):
            _append_segment(segments, current)
            current = []
            index += 2
            continue
        current.append(char)
        index += 1
    _append_segment(segments, current)
    return segments or [command]


def _append_segment(segments: list[str], current: list[str]) -> None:
    segment = _collapse_whitespace("".join(current))
    if segment:
        segments.append(segment)


def _shell_tokens(command: str) -> list[str]:
    try:
        return shlex.split(command, posix=True)
    except ValueError:
        return command.split()
