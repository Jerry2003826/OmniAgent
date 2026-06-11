"""Tolerant transcript JSONL parser."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from omni.redact import redact

KNOWN_EVENT_KEYS = {
    "created_at",
    "duration_ms",
    "event_type",
    "exit_code",
    "hook_event_name",
    "id",
    "name",
    "timestamp",
    "tool",
    "tool_name",
    "tool_use_id",
    "ts",
    "type",
}

@dataclass(frozen=True)
class NormalizedEvent:
    seq: int
    ts: str
    event_type: str
    tool: str | None
    tool_use_id: str | None
    exit_code: int | None
    duration_ms: int | None
    source: str
    meta: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "duration_ms": self.duration_ms,
            "event_type": self.event_type,
            "exit_code": self.exit_code,
            "meta": self.meta,
            "seq": self.seq,
            "source": self.source,
            "tool": self.tool,
            "tool_use_id": self.tool_use_id,
            "ts": self.ts,
        }


@dataclass(frozen=True)
class TranscriptArchive:
    kind: str
    payload: bytes
    line_count: int
    redaction_status: str
    detectors: tuple[str, ...]


@dataclass(frozen=True)
class ParseResult:
    events: list[NormalizedEvent]
    archive: TranscriptArchive | None


def parse_transcript(
    path: Path | str,
) -> ParseResult:
    transcript_path = Path(path)
    events: list[NormalizedEvent] = []
    archive_lines: list[bytes] = []
    archive_detectors: list[str] = []
    archive_status = "clean"

    for line_no, raw_line in enumerate(transcript_path.read_bytes().splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            parsed = json.loads(raw_line.decode("utf-8"))
        except Exception:
            record, status, detectors = _archive_record(line_no, "invalid_json", raw_line)
            archive_lines.append(record)
            archive_status = _merge_status(archive_status, status)
            archive_detectors.extend(detectors)
            continue

        if not isinstance(parsed, dict) or not _event_type(parsed):
            record, status, detectors = _archive_record(
                line_no, "unknown_transcript_shape", raw_line
            )
            archive_lines.append(record)
            archive_status = _merge_status(archive_status, status)
            archive_detectors.extend(detectors)
            continue

        events.append(_normalize_event(len(events) + 1, parsed))

    archive = None
    if archive_lines:
        archive_payload = b"\n".join(archive_lines) + b"\n"
        archive = TranscriptArchive(
            kind="transcript_archive",
            payload=archive_payload,
            line_count=len(archive_lines),
            redaction_status=archive_status,
            detectors=tuple(dict.fromkeys(archive_detectors)),
        )

    return ParseResult(events=events, archive=archive)


def events_as_jsonl(events: list[NormalizedEvent]) -> str:
    payload = "".join(
        json.dumps(event.as_dict(), sort_keys=True, separators=(",", ":")) + "\n"
        for event in events
    )
    return redact(payload.encode("utf-8")).data.decode("utf-8", errors="replace")


def _normalize_event(seq: int, row: dict[str, Any]) -> NormalizedEvent:
    return NormalizedEvent(
        seq=seq,
        ts=str(row.get("timestamp") or row.get("ts") or row.get("created_at") or ""),
        event_type=str(_event_type(row)),
        tool=_optional_str(row.get("tool") or row.get("tool_name") or row.get("name")),
        tool_use_id=_optional_str(row.get("tool_use_id") or row.get("id")),
        exit_code=_optional_int(row.get("exit_code")),
        duration_ms=_optional_int(row.get("duration_ms")),
        source="transcript",
        meta={key: value for key, value in row.items() if key not in KNOWN_EVENT_KEYS},
    )


def _event_type(row: dict[str, Any]) -> Any:
    return row.get("type") or row.get("event_type") or row.get("hook_event_name")


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _archive_record(
    line_no: int, reason: str, raw_line: bytes
) -> tuple[bytes, str, tuple[str, ...]]:
    redaction = redact(raw_line)
    record = {
        "detectors": list(redaction.detectors),
        "line": line_no,
        "payload": redaction.data.decode("utf-8", errors="replace"),
        "reason": reason,
        "redaction_status": redaction.status,
    }
    encoded = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return redact(encoded).data, redaction.status, redaction.detectors


def _merge_status(left: str, right: str) -> str:
    if "withheld" in (left, right):
        return "withheld"
    if "redacted" in (left, right):
        return "redacted"
    return "clean"
