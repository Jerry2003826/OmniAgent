"""Tolerant transcript JSONL parser."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from omni._common import (
    is_redaction_placeholder as _is_redaction_placeholder,
    merge_redaction_status as _merge_redaction_status,
    optional_int as _optional_int,
)
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

MAX_TRANSCRIPT_ARCHIVE_BYTES = 768 * 1024


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
    redaction_status: str = "clean"
    detectors: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "detectors": list(self.detectors),
            "duration_ms": self.duration_ms,
            "event_type": self.event_type,
            "exit_code": self.exit_code,
            "meta": self.meta,
            "redaction_status": self.redaction_status,
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
    archive_line_count = 0
    archive_payload_bytes = 0
    archive_omitted_lines = 0
    archive_detectors: list[str] = []
    archive_status = "clean"

    with transcript_path.open("rb") as handle:
        for line_no, raw_line in enumerate(handle, start=1):
            raw_line = raw_line.rstrip(b"\r\n")
            if not raw_line.strip():
                continue
            try:
                parsed = json.loads(raw_line.decode("utf-8"))
            except Exception:
                record, status, detectors = _archive_record(line_no, "invalid_json", raw_line)
                archive_line_count += 1
                archive_payload_bytes, archive_omitted_lines = _append_archive_record(
                    archive_lines, archive_payload_bytes, archive_omitted_lines, record
                )
                archive_status = _merge_status(archive_status, status)
                archive_detectors.extend(detectors)
                continue

            if not isinstance(parsed, dict) or not _event_type(parsed):
                record, status, detectors = _archive_record(
                    line_no, "unknown_transcript_shape", raw_line
                )
                archive_line_count += 1
                archive_payload_bytes, archive_omitted_lines = _append_archive_record(
                    archive_lines, archive_payload_bytes, archive_omitted_lines, record
                )
                archive_status = _merge_status(archive_status, status)
                archive_detectors.extend(detectors)
                continue

            events.append(_normalize_event(len(events) + 1, parsed))

    archive = None
    if archive_line_count:
        if archive_omitted_lines:
            archive_status = _merge_status(archive_status, "truncated")
            _append_archive_truncation_record(
                archive_lines, archive_payload_bytes, archive_omitted_lines
            )
        archive_payload = b"\n".join(archive_lines) + b"\n"
        archive = TranscriptArchive(
            kind="transcript_archive",
            payload=archive_payload,
            line_count=archive_line_count,
            redaction_status=archive_status,
            detectors=tuple(dict.fromkeys(archive_detectors)),
        )

    return ParseResult(events=events, archive=archive)


def events_as_jsonl(events: list[NormalizedEvent]) -> str:
    lines: list[str] = []
    for event in events:
        raw = json.dumps(
            event.as_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        line = redact(raw).data.decode("utf-8", errors="replace")
        lines.append(line if line.endswith("\n") else line + "\n")
    return "".join(lines)


def _normalize_event(seq: int, row: dict[str, Any]) -> NormalizedEvent:
    meta = {key: value for key, value in row.items() if key not in KNOWN_EVENT_KEYS}
    ts, ts_status, ts_detectors = _redacted_str(
        row.get("timestamp") or row.get("ts") or row.get("created_at") or ""
    )
    event_type, event_status, event_detectors = _redacted_str(_event_type(row))
    tool, tool_status, tool_detectors = _redacted_optional_str(
        row.get("tool") or row.get("tool_name") or row.get("name")
    )
    tool_use_id, tool_id_status, tool_id_detectors = _redacted_optional_str(
        row.get("tool_use_id") or row.get("id")
    )
    redacted_meta, meta_status, meta_detectors = _redacted_meta(meta)
    return NormalizedEvent(
        seq=seq,
        ts=ts,
        event_type=event_type,
        tool=tool,
        tool_use_id=tool_use_id,
        exit_code=_optional_int(row.get("exit_code")),
        duration_ms=_optional_int(row.get("duration_ms")),
        source="transcript",
        meta=redacted_meta,
        redaction_status=_merge_redaction_status(
            ts_status,
            event_status,
            tool_status,
            tool_id_status,
            meta_status,
        ),
        detectors=tuple(
            dict.fromkeys(
                ts_detectors
                + event_detectors
                + tool_detectors
                + tool_id_detectors
                + meta_detectors
            )
        ),
    )


def _redacted_meta(meta: dict[str, Any]) -> tuple[dict[str, Any], str, tuple[str, ...]]:
    if not meta:
        return {}, "clean", ()
    encoded = json.dumps(
        meta,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    redaction = redact(encoded)
    redacted = redaction.data.decode("utf-8", errors="replace")
    try:
        parsed = json.loads(redacted)
    except json.JSONDecodeError:
        return {"redacted_meta": redacted}, redaction.status, redaction.detectors
    result = parsed if isinstance(parsed, dict) else {"redacted_meta": redacted}
    return result, redaction.status, redaction.detectors


def _redacted_str(value: Any) -> tuple[str, str, tuple[str, ...]]:
    text = str(value)
    if _is_redaction_placeholder(text):
        return text, "redacted", ()
    redaction = redact(text.encode("utf-8"))
    return redaction.data.decode("utf-8", errors="replace"), redaction.status, redaction.detectors


def _redacted_optional_str(value: Any) -> tuple[str | None, str, tuple[str, ...]]:
    if value is None:
        return None, "clean", ()
    return _redacted_str(value)


def _event_type(row: dict[str, Any]) -> Any:
    return row.get("type") or row.get("event_type") or row.get("hook_event_name")


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


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
    encoded = json.dumps(
        record,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return redact(encoded).data, redaction.status, redaction.detectors


def _append_archive_record(
    archive_lines: list[bytes],
    archive_payload_bytes: int,
    archive_omitted_lines: int,
    record: bytes,
) -> tuple[int, int]:
    if archive_omitted_lines:
        return archive_payload_bytes, archive_omitted_lines + 1
    record_size = len(record) + 1
    if archive_payload_bytes + record_size <= MAX_TRANSCRIPT_ARCHIVE_BYTES:
        archive_lines.append(record)
        return archive_payload_bytes + record_size, archive_omitted_lines
    return archive_payload_bytes, 1


def _append_archive_truncation_record(
    archive_lines: list[bytes],
    archive_payload_bytes: int,
    archive_omitted_lines: int,
) -> None:
    omitted_lines = archive_omitted_lines
    while archive_lines:
        truncated = _archive_truncation_record(omitted_lines)
        if archive_payload_bytes + len(truncated) + 1 <= MAX_TRANSCRIPT_ARCHIVE_BYTES:
            archive_lines.append(truncated)
            return
        removed = archive_lines.pop()
        archive_payload_bytes -= len(removed) + 1
        omitted_lines += 1
    archive_lines.append(_archive_truncation_record(omitted_lines))


def _archive_truncation_record(omitted_lines: int) -> bytes:
    return json.dumps(
        {
            "error": "archive_truncated",
            "omitted_lines": omitted_lines,
            "redaction_status": "truncated",
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _merge_status(left: str, right: str) -> str:
    if "withheld" in (left, right):
        return "withheld"
    if "truncated" in (left, right):
        return "truncated"
    if "redacted" in (left, right):
        return "redacted"
    return "clean"
