"""Spool readers for hook and ingest queue records."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REQUEST_PATH_KEY = "__omni_spool_path"
_LEGACY_QUEUE_KEY = "__omni_legacy_queue"
DEFAULT_PROCESSED_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
DEFAULT_PROCESSED_MAX_BYTES = 128 * 1024 * 1024


@dataclass(frozen=True)
class HookRecord:
    path: Path
    line_no: int
    record: dict[str, Any]
    payload: dict[str, Any]


def spool_dir(root: Path | str) -> Path:
    return Path(root).resolve() / ".omni" / "spool"


def iter_hook_records(root: Path | str) -> list[HookRecord]:
    records: list[HookRecord] = []
    for path in sorted(spool_dir(root).glob("hook-*.jsonl")):
        file_records: list[HookRecord] = []
        malformed = False
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception:
            _quarantine(path)
            continue
        for line_no, line in enumerate(lines, start=1):
            try:
                record = json.loads(line)
                payload = json.loads(record.get("payload", "{}"))
            except Exception:
                malformed = True
                break
            if isinstance(record, dict) and isinstance(payload, dict):
                file_records.append(
                    HookRecord(path=path, line_no=line_no, record=record, payload=payload)
                )
            else:
                malformed = True
                break
        if malformed:
            _quarantine(path)
        else:
            records.extend(file_records)
    return records


def drain_ingest_queue(root: Path | str) -> list[dict[str, Any]]:
    directory = spool_dir(root)
    requests: list[dict[str, Any]] = []
    for path in sorted(directory.glob("ingest-*.json")):
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            _quarantine(path)
            continue
        if isinstance(parsed, dict):
            parsed = dict(parsed)
            parsed[_REQUEST_PATH_KEY] = str(path)
            requests.append(parsed)
        else:
            _quarantine(path)

    legacy_path = directory / "ingest_queue.jsonl"
    if legacy_path.exists():
        legacy_requests: list[dict[str, Any]] = []
        malformed = False
        try:
            legacy_lines = legacy_path.read_text(encoding="utf-8").splitlines()
        except Exception:
            _quarantine(legacy_path)
            return requests
        for line in legacy_lines:
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                malformed = True
                break
            if isinstance(parsed, dict):
                parsed = dict(parsed)
                parsed[_LEGACY_QUEUE_KEY] = str(legacy_path)
                legacy_requests.append(parsed)
            else:
                malformed = True
                break
        if malformed:
            _quarantine(legacy_path)
        else:
            requests.extend(legacy_requests)
    return requests


def ack_ingest_queue(requests: list[dict[str, Any]]) -> None:
    legacy_paths: set[Path] = set()
    for request in requests:
        source = request.get(_REQUEST_PATH_KEY)
        if isinstance(source, str):
            Path(source).unlink(missing_ok=True)
        legacy = request.get(_LEGACY_QUEUE_KEY)
        if isinstance(legacy, str):
            legacy_paths.add(Path(legacy))
    for path in legacy_paths:
        path.write_text("", encoding="utf-8")


def ack_hook_records(root: Path | str, paths: set[Path]) -> None:
    if not paths:
        return
    processed_dir = spool_dir(root) / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted(paths, key=lambda item: str(item)):
        if not path.exists():
            continue
        target = processed_dir / path.name
        if target.exists():
            target = processed_dir / f"{path.name}.{time.time_ns()}.processed"
        path.replace(target)


def prune_processed_hook_records(
    root: Path | str,
    *,
    max_age_seconds: int = DEFAULT_PROCESSED_MAX_AGE_SECONDS,
    max_bytes: int = DEFAULT_PROCESSED_MAX_BYTES,
    now_ts: float | None = None,
) -> int:
    processed_dir = spool_dir(root) / "processed"
    if not processed_dir.exists():
        return 0

    now = time.time() if now_ts is None else now_ts
    entries: list[tuple[Path, float, int]] = []
    for path in sorted(processed_dir.glob("hook-*.jsonl*")):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        entries.append((path, stat.st_mtime, stat.st_size))

    deleted: set[Path] = set()
    for path, mtime, _size in entries:
        if max_age_seconds >= 0 and now - mtime >= max_age_seconds:
            if _unlink_best_effort(path):
                deleted.add(path)

    remaining = [entry for entry in entries if entry[0] not in deleted]
    if max_bytes >= 0:
        total_bytes = sum(size for _path, _mtime, size in remaining)
        for path, _mtime, size in sorted(
            remaining,
            key=lambda entry: (entry[1], str(entry[0])),
        ):
            if total_bytes <= max_bytes:
                break
            if _unlink_best_effort(path):
                deleted.add(path)
                total_bytes -= size

    return len(deleted)


def _quarantine(path: Path) -> None:
    bad_dir = path.parent / "bad"
    bad_dir.mkdir(parents=True, exist_ok=True)
    target = bad_dir / path.name
    if target.exists():
        target = bad_dir / f"{path.name}.{time.time_ns()}.bad"
    path.replace(target)


def _unlink_best_effort(path: Path) -> bool:
    try:
        path.unlink()
    except OSError:
        return False
    return True
