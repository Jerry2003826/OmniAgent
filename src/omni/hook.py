"""Claude Code hook capture entrypoints."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from omni.redact import RedactionResult, redact, redact_minimal

LEGACY_HOOK_COMMAND = "omni hook"
HOOK_COMMAND_ENV = "OMNI_HOOK_COMMAND"
INGEST_EVENTS = {"Stop", "SessionEnd"}
AUDIT_PASSED_MARKER = Path(".omni") / "audit" / "secrets.passed"
MAX_HOOK_EVENT_PARSE_BYTES = 256 * 1024

CLAUDE_HOOK_EVENTS = (
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "PermissionRequest",
    "Notification",
    "PreCompact",
    "SubagentStart",
    "SubagentStop",
    "Stop",
    "SessionEnd",
)

MATCHER_EVENTS = {
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "PermissionRequest",
    "SubagentStart",
    "SubagentStop",
    "SessionStart",
    "SessionEnd",
    "Notification",
    "PreCompact",
}


@dataclass(frozen=True)
class HookCaptureResult:
    ok: bool
    spool_path: Path | None = None


@dataclass(frozen=True)
class InstallResult:
    ok: bool
    message: str = ""
    diff: str = ""


def capture_hook(payload: bytes, root: Path | str | None = None) -> HookCaptureResult:
    started = time.perf_counter()
    base = Path(root or Path.cwd()).resolve()
    spool_dir = base / ".omni" / "spool"

    try:
        spool_dir.mkdir(parents=True, exist_ok=True)
        redaction = _redact_payload(payload)
        event = _event_for_enqueue(payload)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        record = {
            "meta": {
                "elapsed_ms": elapsed_ms,
                "redaction_status": redaction.status,
                "detectors": list(redaction.detectors),
            },
            "payload": redaction.data.decode("utf-8", errors="replace"),
        }
        line = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
        spool_path = spool_dir / f"hook-{time.time_ns()}-{uuid.uuid4().hex}.jsonl"
        temp_path = spool_path.with_suffix(".jsonl.tmp")
        temp_path.write_bytes(line + b"\n")
        temp_path.replace(spool_path)

        if event.get("hook_event_name") in INGEST_EVENTS:
            _enqueue_ingest_request(spool_dir, event)

        return HookCaptureResult(ok=True, spool_path=spool_path)
    except Exception as exc:
        _write_error(spool_dir, exc)
        return HookCaptureResult(ok=True)


def run_from_stdin() -> HookCaptureResult:
    try:
        payload = sys.stdin.buffer.read()
    except Exception:
        payload = b""
    return capture_hook(payload)


def install_claude_hooks(root: Path | str | None = None, *, yes: bool = False) -> InstallResult:
    base = Path(root or Path.cwd()).resolve()
    if not yes and not (base / AUDIT_PASSED_MARKER).exists():
        return InstallResult(
            ok=False,
            message=(
                "omni audit secrets has not passed in this checkout; rerun with --yes "
                "to install project Claude hooks anyway."
            ),
        )

    claude_dir = base / ".claude"
    settings_path = claude_dir / "settings.json"
    original = settings_path.read_text(encoding="utf-8-sig") if settings_path.exists() else "{}\n"
    try:
        settings = _parse_settings(original)
    except ValueError as exc:
        return InstallResult(ok=False, message=str(exc))
    hook_command = _hook_command()
    updated = _settings_with_omni_hooks(settings, command=hook_command)
    rendered = json.dumps(updated, indent=2, sort_keys=True) + "\n"
    diff = "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            rendered.splitlines(keepends=True),
            fromfile=".claude/settings.json",
            tofile=".claude/settings.json (omni)",
        )
    )

    claude_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(settings_path, rendered)
    return InstallResult(ok=True, diff=_redacted_text(diff))


def main() -> int:
    run_from_stdin()
    return 0


def _redact_payload(payload: bytes) -> RedactionResult:
    try:
        return redact_minimal(payload)
    except Exception:
        return RedactionResult(
            data=_redaction_failed_stub(payload),
            status="withheld",
            detectors=("withheld",),
        )


def _redaction_failed_stub(payload: bytes) -> bytes:
    stub = {
        "error": "redaction_failed",
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "byte_len": len(payload),
    }
    return json.dumps(stub, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _event_from_payload(payload: bytes) -> dict[str, object]:
    try:
        parsed = json.loads(payload.decode("utf-8"))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _event_for_enqueue(payload: bytes) -> dict[str, object]:
    if len(payload) > MAX_HOOK_EVENT_PARSE_BYTES:
        return {}
    return _event_from_payload(payload)


def _redact_line(record: dict[str, object]) -> bytes:
    encoded = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return redact(encoded).data


def _enqueue_ingest_request(spool_dir: Path, event: dict[str, object]) -> None:
    request = {
        "event": event.get("hook_event_name"),
        "session_id": event.get("session_id"),
        "transcript_path": event.get("transcript_path"),
    }
    line = _redact_line(request)
    target = spool_dir / f"ingest-{time.time_ns()}-{uuid.uuid4().hex}.json"
    temp = target.with_suffix(".json.tmp")
    temp.write_bytes(line + b"\n")
    temp.replace(target)


def _write_error(spool_dir: Path, exc: Exception) -> None:
    try:
        spool_dir.mkdir(parents=True, exist_ok=True)
        error = {
            "error": type(exc).__name__,
            "message": str(exc),
        }
        line = _redact_line(error)
        with (spool_dir / "_errors.log").open("ab") as handle:
            handle.write(line + b"\n")
    except Exception:
        pass


def _atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    temp_path = path.with_name(f"{path.name}.omni-tmp")
    try:
        temp_path.write_text(content, encoding=encoding)
        if path.exists():
            try:
                shutil.copymode(path, temp_path)
            except OSError:
                pass
        temp_path.replace(path)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def _redacted_text(value: str) -> str:
    return redact(value.encode("utf-8")).data.decode("utf-8", errors="replace")


def _parse_settings(original: str) -> dict[str, object]:
    try:
        parsed = json.loads(original) if original.strip() else {}
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid .claude/settings.json: {exc.msg}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("invalid .claude/settings.json: root must be a JSON object")
    return parsed


def _settings_with_omni_hooks(settings: dict[str, object], *, command: str) -> dict[str, object]:
    updated = dict(settings)
    hooks = updated.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
    else:
        hooks = dict(hooks)

    for event_name in CLAUDE_HOOK_EVENTS:
        groups = hooks.get(event_name)
        if not isinstance(groups, list):
            groups = []
        groups = list(groups)
        groups, found = _upgrade_omni_hooks(groups, command)
        if not found:
            groups.append(_hook_group(event_name, command))
        hooks[event_name] = groups

    updated["hooks"] = hooks
    return updated


def _hook_command() -> str:
    override = os.environ.get(HOOK_COMMAND_ENV)
    if override:
        return override
    parts = [sys.executable, "-m", "omni.cli", "hook"]
    if os.name == "nt":
        return subprocess.list2cmdline(parts)
    return shlex.join(parts)


def _hook_group(event_name: str, command: str) -> dict[str, object]:
    group: dict[str, object] = {
        "hooks": [
            {
                "type": "command",
                "command": command,
                "timeout": 5,
            }
        ]
    }
    if event_name in MATCHER_EVENTS:
        group["matcher"] = "*"
    return group


def _upgrade_omni_hooks(groups: list[object], command: str) -> tuple[list[object], bool]:
    upgraded: list[object] = []
    found = False
    for group in groups:
        if not isinstance(group, dict):
            upgraded.append(group)
            continue
        handlers = group.get("hooks")
        if not isinstance(handlers, list):
            upgraded.append(group)
            continue

        new_handlers: list[object] = []
        group_has_omni = False
        for handler in handlers:
            if not isinstance(handler, dict):
                new_handlers.append(handler)
                continue
            handler_command = handler.get("command")
            if handler_command == LEGACY_HOOK_COMMAND:
                if not found:
                    replacement = dict(handler)
                    replacement["command"] = command
                    new_handlers.append(replacement)
                    found = True
                    group_has_omni = True
                continue
            if handler_command == command:
                if not found:
                    new_handlers.append(handler)
                    found = True
                    group_has_omni = True
                continue
            new_handlers.append(handler)

        new_group = dict(group)
        new_group["hooks"] = new_handlers
        if group_has_omni or new_handlers:
            upgraded.append(new_group)
    return upgraded, found
