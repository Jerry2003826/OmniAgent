"""Spool readers for hook and ingest queue records."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REQUEST_PATH_KEY = "__omni_spool_path"
_LEGACY_QUEUE_KEY = "__omni_legacy_queue"


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


def _quarantine(path: Path) -> None:
    bad_dir = path.parent / "bad"
    bad_dir.mkdir(parents=True, exist_ok=True)
    path.replace(bad_dir / path.name)
