"""Ingest spool and transcript events into SQLite."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from omni import db
from omni import gate
from omni.config import ensure_project_layout
from omni.ids import project_id_for_path
from omni.parse import NormalizedEvent, parse_transcript
from omni.redact import redact
from omni.spool import (
    HookRecord,
    ack_hook_records,
    ack_ingest_queue,
    drain_ingest_queue,
    iter_hook_records,
    prune_processed_hook_records,
)
from omni.store import REDACTION_VER, put_artifact


@dataclass(frozen=True)
class IngestResult:
    run_ids: tuple[str, ...]
    events_inserted: int
    queue_drained: int


@dataclass(frozen=True)
class EventCandidate:
    event_type: str
    ts: str
    tool: str | None
    tool_use_id: str | None
    exit_code: int | None
    duration_ms: int | None
    source: str
    meta: dict[str, Any]
    artifact_hash: str | None
    unique_key: str
    redaction_status: str = "clean"
    sort_index: int = 0


def ingest(
    root: Path | str | None = None,
    *,
    run_id: str | None = None,
    transcript: Path | str | None = None,
) -> IngestResult:
    base = Path(root or Path.cwd()).resolve()
    ensure_project_layout(base)
    conn = _connect_project_db(base)
    try:
        total_inserted = 0
        run_ids: list[str] = []
        drained = 0
        consumed_hook_paths: set[Path] = set()

        if transcript is not None:
            rid = run_id or _run_id_for_transcript(Path(transcript))
            manual_session_id = run_id
            inserted, hook_paths = _ingest_one(
                conn,
                base,
                rid,
                Path(transcript),
                include_hooks=manual_session_id is not None,
                session_id=manual_session_id,
            )
            total_inserted += inserted
            consumed_hook_paths.update(hook_paths)
            run_ids.append(rid)
        else:
            requests = drain_ingest_queue(base)
            drained = len(requests)
            if requests:
                for request in requests:
                    transcript_path = request.get("transcript_path")
                    request_session_id = _optional_str(request.get("session_id"))
                    rid = request_session_id or run_id or "queued_run"
                    path = Path(str(transcript_path)) if transcript_path else None
                    if path is not None and not path.is_absolute():
                        path = base / path
                    inserted, hook_paths = _ingest_one(
                        conn,
                        base,
                        rid,
                        path,
                        include_hooks=True,
                        session_id=request_session_id,
                    )
                    total_inserted += inserted
                    consumed_hook_paths.update(hook_paths)
                    run_ids.append(rid)
            else:
                if run_id is not None:
                    inserted, hook_paths = _ingest_one(
                        conn,
                        base,
                        run_id,
                        None,
                        include_hooks=True,
                        session_id=run_id,
                    )
                    total_inserted += inserted
                    consumed_hook_paths.update(hook_paths)
                    run_ids.append(run_id)

        gate.extract_static_facts(base, conn, commit=False)
        close_stale_runs(conn, commit=False)
        conn.commit()
        if transcript is None and requests:
            ack_ingest_queue(requests)
        ack_hook_records(base, consumed_hook_paths)
        prune_processed_hook_records(base)
        return IngestResult(
            run_ids=tuple(dict.fromkeys(run_ids)),
            events_inserted=total_inserted,
            queue_drained=drained,
        )
    finally:
        conn.close()


def close_stale_runs(
    conn: sqlite3.Connection,
    *,
    older_than_seconds: int = 600,
    now_ts: float | None = None,
    commit: bool = True,
) -> int:
    now = datetime.now(timezone.utc).timestamp() if now_ts is None else now_ts
    rows = conn.execute(
        "SELECT run_id, transcript_path FROM runs WHERE status = 'open' AND transcript_path IS NOT NULL"
    ).fetchall()
    closed = 0
    for row in rows:
        path = Path(row["transcript_path"])
        try:
            stale = not path.exists() or now - path.stat().st_mtime >= older_than_seconds
        except OSError:
            stale = True
        if not stale:
            continue
        conn.execute(
            "UPDATE runs SET status = 'closed', end_reason = ?, ended_at = ? WHERE run_id = ?",
            ("watchdog", _iso_from_timestamp(now), row["run_id"]),
        )
        closed += 1
    if commit:
        conn.commit()
    return closed


def run_show(root: Path | str | None, run_id: str, seq: int | None = None) -> str:
    base = Path(root or Path.cwd()).resolve()
    conn = _connect_project_db_readonly(base)
    try:
        if seq is not None:
            row = conn.execute(
                "SELECT * FROM events WHERE run_id = ? AND seq = ?", (run_id, seq)
            ).fetchone()
            return "{}\n" if row is None else json.dumps(dict(row), indent=2, sort_keys=True) + "\n"

        rows = conn.execute(
            "SELECT seq, ts, event_type, tool, exit_code, input_ref, output_ref, meta FROM events "
            "WHERE run_id = ? ORDER BY seq",
            (run_id,),
        ).fetchall()
        lines = ["seq | ts | type | tool | exit | artifact | command"]
        for row in rows:
            artifact = (row["output_ref"] or row["input_ref"] or "")[:12]
            lines.append(
                " | ".join(
                    [
                        str(row["seq"]),
                        row["ts"] or "",
                        row["event_type"] or "",
                        row["tool"] or "",
                        "" if row["exit_code"] is None else str(row["exit_code"]),
                        artifact,
                        _command_preview(row["meta"]),
                    ]
                )
            )
        return "\n".join(lines) + "\n"
    finally:
        conn.close()


def _ingest_one(
    conn: sqlite3.Connection,
    root: Path,
    run_id: str,
    transcript: Path | None,
    *,
    include_hooks: bool,
    session_id: str | None = None,
) -> tuple[int, set[Path]]:
    transcript_events: list[EventCandidate] = []
    if transcript is not None and transcript.exists():
        transcript_events = _transcript_candidates(conn, root, transcript)

    if include_hooks:
        hook_events, hook_paths = _hook_candidates(conn, root, session_id=session_id)
    else:
        hook_events, hook_paths = [], set()
    candidates = _reconcile_candidates(transcript_events, hook_events)
    _ensure_run(conn, root, run_id, transcript)

    inserted = 0
    for seq, candidate in enumerate(candidates, start=1):
        inserted += _insert_event(conn, run_id, seq, candidate)
    _renumber_run_events(conn, run_id)
    _update_run_bounds(conn, run_id)
    return inserted, hook_paths


def _connect_project_db(root: Path) -> sqlite3.Connection:
    conn = db.connect(root / ".omni" / "omni.sqlite3")
    db.migrate(conn)
    return conn


def _connect_project_db_readonly(root: Path) -> sqlite3.Connection:
    db_path = root / ".omni" / "omni.sqlite3"
    if not db_path.exists():
        raise FileNotFoundError(f"OmniMemory database is missing: {db_path}")
    return db.connect_readonly(db_path)


def _ensure_run(conn: sqlite3.Connection, root: Path, run_id: str, transcript: Path | None) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO runs(run_id, project_id, cwd, transcript_path, snapshot_seq, status)
        VALUES(?,?,?,?,?,?)
        """,
        (
            run_id,
            project_id_for_path(root),
            str(root),
            str(transcript) if transcript is not None else None,
            0,
            "open",
        ),
    )


def _transcript_candidates(conn: sqlite3.Connection, root: Path, path: Path) -> list[EventCandidate]:
    parsed = parse_transcript(path)
    if parsed.archive is not None:
        put_artifact(
            root,
            conn,
            kind=parsed.archive.kind,
            data=parsed.archive.payload,
        )
    return [_candidate_from_transcript_event(conn, root, event) for event in parsed.events]


def _candidate_from_transcript_event(
    conn: sqlite3.Connection, root: Path, event: NormalizedEvent
) -> EventCandidate:
    unique_key = _transcript_unique_key(event)
    artifact = put_artifact(
        root,
        conn,
        kind="transcript_event",
        data=json.dumps(
            event.as_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8"),
    )
    return EventCandidate(
        event_type=event.event_type,
        ts=event.ts,
        tool=event.tool,
        tool_use_id=event.tool_use_id,
        exit_code=event.exit_code,
        duration_ms=event.duration_ms,
        source="transcript",
        meta=event.meta,
        artifact_hash=artifact.hash,
        unique_key=unique_key,
        redaction_status=event.redaction_status,
        sort_index=event.seq,
    )


def _transcript_unique_key(event: NormalizedEvent) -> str:
    uuid = event.meta.get("uuid")
    if isinstance(uuid, str) and uuid:
        return f"transcript:{uuid}"
    # TODO: Do not infer nested Claude tool ids from message.content/toolUseResult
    # until recorded evidence requires changing transcript/hook reconciliation.
    return f"transcript:{event.tool_use_id or event.seq}:{event.event_type}:{event.ts}"


def _hook_candidates(
    conn: sqlite3.Connection, root: Path, *, session_id: str | None = None
) -> tuple[list[EventCandidate], set[Path]]:
    records = iter_hook_records(root)
    if session_id is not None:
        records = [
            record
            for record in records
            if _optional_str(record.payload.get("session_id")) == session_id
        ]
    by_tool: dict[str, list[HookRecord]] = {}
    without_tool: list[HookRecord] = []
    for record in records:
        tool_use_id, _status = _redacted_optional_str(
            record.payload.get("tool_use_id") or record.payload.get("id")
        )
        if tool_use_id:
            by_tool.setdefault(tool_use_id, []).append(record)
        else:
            without_tool.append(record)

    candidates: list[EventCandidate] = []
    for tool_use_id, grouped in by_tool.items():
        candidates.append(_candidate_from_hook_group(conn, root, tool_use_id, grouped))
    for record in without_tool:
        candidates.append(_candidate_from_hook_record(conn, root, record, None))
    return candidates, {record.path for record in records}


def _candidate_from_hook_group(
    conn: sqlite3.Connection, root: Path, tool_use_id: str, records: list[HookRecord]
) -> EventCandidate:
    records = sorted(records, key=lambda item: _timestamp(item.payload) or "")
    preferred = _preferred_hook_record(records)
    duration = _hook_duration_ms(records)
    candidate = _candidate_from_hook_record(conn, root, preferred, duration)
    return replace(
        candidate,
        tool_use_id=tool_use_id,
        unique_key=f"hook:{tool_use_id}:{candidate.event_type}:{candidate.ts}",
    )


def _candidate_from_hook_record(
    conn: sqlite3.Connection, root: Path, record: HookRecord, duration_ms: int | None
) -> EventCandidate:
    payload = record.payload
    event_type, event_status = _redacted_str(
        payload.get("hook_event_name") or payload.get("type") or "hook"
    )
    tool, tool_status = _redacted_optional_str(
        payload.get("tool") or payload.get("tool_name") or payload.get("name")
    )
    tool_use_id, tool_id_status = _redacted_optional_str(payload.get("tool_use_id") or payload.get("id"))
    record_status = _record_redaction_status(record)
    artifact = put_artifact(
        root,
        conn,
        kind="hook_event",
        data=json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8"),
    )
    return EventCandidate(
        event_type=event_type,
        ts=_timestamp(payload),
        tool=tool,
        tool_use_id=tool_use_id,
        exit_code=_optional_int(payload.get("exit_code")),
        duration_ms=_optional_int(payload.get("duration_ms")) or duration_ms,
        source="hook",
        meta={
            "spool_path": str(record.path),
            "spool_line": record.line_no,
            **{
                key: value
                for key, value in payload.items()
                if key
                not in {
                    "duration_ms",
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
            },
        },
        artifact_hash=artifact.hash,
        unique_key=f"hook:{record.path.name}:{record.line_no}",
        redaction_status=_merge_redaction_status(record_status, event_status, tool_status, tool_id_status),
        sort_index=record.line_no,
    )


def _preferred_hook_record(records: list[HookRecord]) -> HookRecord:
    for name in ("PostToolUse", "PostToolUseFailure", "PreToolUse"):
        for record in reversed(records):
            if record.payload.get("hook_event_name") == name:
                return record
    return records[-1]


def _hook_duration_ms(records: list[HookRecord]) -> int | None:
    pre = next(
        (record for record in records if record.payload.get("hook_event_name") == "PreToolUse"),
        None,
    )
    post = next(
        (
            record
            for record in records
            if record.payload.get("hook_event_name") in {"PostToolUse", "PostToolUseFailure"}
        ),
        None,
    )
    if pre is None or post is None:
        return None
    start = _parse_ts(_timestamp(pre.payload))
    end = _parse_ts(_timestamp(post.payload))
    if start is None or end is None:
        return None
    return max(0, int((end - start) * 1000))


def _reconcile_candidates(
    transcript_events: list[EventCandidate], hook_events: list[EventCandidate]
) -> list[EventCandidate]:
    hooks_by_tool = {event.tool_use_id: event for event in hook_events if event.tool_use_id}
    transcript_tool_ids = {event.tool_use_id for event in transcript_events if event.tool_use_id}
    reconciled: list[EventCandidate] = []
    for event in transcript_events:
        hook_event = hooks_by_tool.get(event.tool_use_id)
        if hook_event is None:
            reconciled.append(event)
            continue
        reconciled.append(
            EventCandidate(
                event_type=event.event_type,
                ts=event.ts or hook_event.ts,
                tool=event.tool or hook_event.tool,
                tool_use_id=event.tool_use_id,
                exit_code=event.exit_code if event.exit_code is not None else hook_event.exit_code,
                duration_ms=event.duration_ms if event.duration_ms is not None else hook_event.duration_ms,
                source="reconciled",
                meta={"transcript": event.meta, "hook": hook_event.meta},
                artifact_hash=event.artifact_hash or hook_event.artifact_hash,
                unique_key=f"reconciled:{event.tool_use_id}:{event.event_type}:{event.ts}",
                redaction_status=_merge_redaction_status(
                    event.redaction_status,
                    hook_event.redaction_status,
                ),
                sort_index=event.sort_index,
            )
        )
    reconciled.extend(
        event for event in hook_events if not event.tool_use_id or event.tool_use_id not in transcript_tool_ids
    )
    return sorted(
        reconciled,
        key=lambda item: (
            item.ts if item.ts else "\uffff",
            item.sort_index,
            item.event_type,
            item.unique_key,
        ),
    )


def _insert_event(conn: sqlite3.Connection, run_id: str, seq: int, candidate: EventCandidate) -> int:
    event_id = _event_id(run_id, candidate)
    meta_json, meta_status = _redacted_json(candidate.meta)
    redaction_status = _merge_redaction_status(candidate.redaction_status, meta_status)
    existing = _existing_canonical_event(conn, run_id, candidate)
    if existing is not None:
        conn.execute(
            """
            UPDATE events
            SET ts = ?, event_type = ?, tool = ?, tool_use_id = ?, input_ref = ?,
                output_ref = NULL, exit_code = ?, duration_ms = ?,
                redaction_status = ?, redaction_ver = ?, source = ?, meta = ?
            WHERE event_id = ?
            """,
            (
                candidate.ts,
                candidate.event_type,
                candidate.tool,
                candidate.tool_use_id,
                candidate.artifact_hash,
                candidate.exit_code,
                candidate.duration_ms,
                redaction_status,
                REDACTION_VER,
                candidate.source,
                meta_json,
                existing["event_id"],
            ),
        )
        return 0
    before = conn.total_changes
    next_seq = _next_event_seq(conn, run_id)
    conn.execute(
        """
        INSERT OR IGNORE INTO events(
          event_id, run_id, seq, ts, event_type, tool, tool_use_id, input_ref,
          output_ref, exit_code, duration_ms, redaction_status, redaction_ver, source, meta
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            event_id,
            run_id,
            next_seq,
            candidate.ts,
            candidate.event_type,
            candidate.tool,
            candidate.tool_use_id,
            candidate.artifact_hash,
            None,
            candidate.exit_code,
            candidate.duration_ms,
            redaction_status,
            REDACTION_VER,
            candidate.source,
            meta_json,
        ),
    )
    return 1 if conn.total_changes > before else 0


def _existing_canonical_event(
    conn: sqlite3.Connection, run_id: str, candidate: EventCandidate
) -> sqlite3.Row | None:
    if not candidate.tool_use_id or candidate.source not in {"reconciled", "transcript"}:
        return None
    # Canonicalization is intentionally narrow: transcript-backed events may upgrade
    # a prior hook-only placeholder for the same tool_use_id, but once an event is
    # transcript/reconciled, later re-ingest only updates the same semantic event_type.
    # Distinct Pre/Post/tool_result shapes under one tool_use_id remain separate rows.
    return conn.execute(
        """
        SELECT event_id, source FROM events
        WHERE run_id = ?
          AND tool_use_id = ?
          AND (
            source = 'hook'
            OR (source IN ('reconciled', 'transcript') AND event_type = ?)
          )
        ORDER BY CASE WHEN source IN ('reconciled', 'transcript') THEN 0 ELSE 1 END, seq
        LIMIT 1
        """,
        (run_id, candidate.tool_use_id, candidate.event_type),
    ).fetchone()


def _next_event_seq(conn: sqlite3.Connection, run_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(seq), 0) + 1 FROM events WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    return int(row[0])


def _renumber_run_events(conn: sqlite3.Connection, run_id: str) -> None:
    rows = conn.execute(
        """
        SELECT event_id FROM events
        WHERE run_id = ?
        ORDER BY
          CASE WHEN NULLIF(ts, '') IS NULL THEN 1 ELSE 0 END,
          NULLIF(ts, ''),
          seq,
          event_type,
          COALESCE(tool_use_id, ''),
          event_id
        """,
        (run_id,),
    ).fetchall()
    for index, row in enumerate(rows, start=1):
        conn.execute(
            "UPDATE events SET seq = ? WHERE event_id = ?",
            (-index, row["event_id"]),
        )
    for index, row in enumerate(rows, start=1):
        conn.execute(
            "UPDATE events SET seq = ? WHERE event_id = ?",
            (index, row["event_id"]),
        )


def _update_run_bounds(conn: sqlite3.Connection, run_id: str) -> None:
    row = conn.execute(
        """
        SELECT MIN(NULLIF(ts,'')) AS started_at, MAX(NULLIF(ts,'')) AS ended_at
        FROM events
        WHERE run_id = ?
        """,
        (run_id,),
    ).fetchone()
    if row:
        conn.execute(
            """
            UPDATE runs
            SET started_at = COALESCE(?, started_at),
                ended_at = COALESCE(?, ended_at)
            WHERE run_id = ?
            """,
            (row["started_at"], row["ended_at"], run_id),
        )


def _redacted_json(value: Any) -> tuple[str, str]:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    redaction = redact(encoded)
    return redaction.data.decode("utf-8", errors="replace"), redaction.status


def _redacted_str(value: Any) -> tuple[str, str]:
    text = str(value)
    if _is_redaction_placeholder(text):
        return text, "redacted"
    redaction = redact(text.encode("utf-8"))
    return redaction.data.decode("utf-8", errors="replace"), redaction.status


def _redacted_optional_str(value: Any) -> tuple[str | None, str]:
    if value is None:
        return None, "clean"
    return _redacted_str(value)


def _record_redaction_status(record: HookRecord) -> str:
    meta = record.record.get("meta")
    if not isinstance(meta, dict):
        return "clean"
    status = meta.get("redaction_status")
    return str(status) if isinstance(status, str) else "clean"


def _merge_redaction_status(*statuses: str) -> str:
    for status in ("withheld", "truncated", "redacted"):
        if status in statuses:
            return status
    return "clean"


def _is_redaction_placeholder(value: str) -> bool:
    return value.startswith("\u27e8REDACTED:") and value.endswith("\u27e9")


def _command_preview(meta_json: str | None) -> str:
    if not meta_json:
        return ""
    try:
        meta = json.loads(meta_json)
    except json.JSONDecodeError:
        return ""
    command = _nested_command(meta)
    if command is None:
        return ""
    return str(command).replace("\r", " ").replace("\n", " ")[:160]


def _nested_command(value: Any) -> Any:
    if isinstance(value, dict):
        for key in ("command", "cmd"):
            if key in value:
                return value[key]
        for key in ("input", "tool_input", "parameters", "args"):
            found = _nested_command(value.get(key))
            if found is not None:
                return found
    return None


def _event_id(run_id: str, candidate: EventCandidate) -> str:
    digest = hashlib.sha256(f"{run_id}:{candidate.unique_key}".encode("utf-8")).hexdigest()
    return f"evt_{digest[:24]}"


def _run_id_for_transcript(path: Path) -> str:
    digest = hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()
    return f"run_{digest[:16]}"


def _timestamp(payload: dict[str, Any]) -> str:
    return str(payload.get("timestamp") or payload.get("ts") or payload.get("created_at") or "")


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_ts(value: str) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _iso_from_timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, timezone.utc).isoformat()
