from __future__ import annotations

import json
from pathlib import Path

from omni import db
from omni import parse


def write_jsonl(path: Path, rows: list[object]) -> None:
    lines = [json.dumps(row) if isinstance(row, dict) else str(row) for row in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_parse_transcript_normalizes_known_jsonl_events(tmp_path: Path) -> None:
    transcript = tmp_path / "transcript.jsonl"
    write_jsonl(
        transcript,
        [
            {
                "type": "tool_use",
                "timestamp": "2026-06-11T00:00:00Z",
                "id": "toolu_1",
                "name": "Bash",
                "exit_code": 0,
                "duration_ms": 42,
                "surprise": {"kept": True},
            },
            {
                "event_type": "assistant_message",
                "ts": "2026-06-11T00:00:01Z",
                "tool_use_id": "toolu_1",
                "tool": "Bash",
            },
        ],
    )

    result = parse.parse_transcript(transcript, root=tmp_path)

    assert result.archive is None
    assert [event.seq for event in result.events] == [1, 2]
    assert result.events[0].event_type == "tool_use"
    assert result.events[0].ts == "2026-06-11T00:00:00Z"
    assert result.events[0].tool == "Bash"
    assert result.events[0].tool_use_id == "toolu_1"
    assert result.events[0].exit_code == 0
    assert result.events[0].duration_ms == 42
    assert result.events[0].source == "transcript"
    assert result.events[0].meta == {"surprise": {"kept": True}}
    assert result.events[1].event_type == "assistant_message"


def test_parse_transcript_archives_unknown_lines_with_redaction(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OMNI_PARSE_SECRET", "parse-secret-value-123")
    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")
    db.migrate(conn)
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        "\n".join(
            [
                json.dumps({"type": "tool_result", "timestamp": "2026-06-11T00:00:02Z"}),
                "not-json parse-secret-value-123",
                json.dumps(
                    {
                        "timestamp": "2026-06-11T00:00:03Z",
                        "api_key": "parse-secret-value-123",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = parse.parse_transcript(transcript, root=tmp_path, conn=conn)
    conn.commit()

    assert len(result.events) == 1
    assert result.archive is not None
    assert result.archive.kind == "transcript_archive"
    assert result.archive.artifact_hash
    assert result.archive.line_count == 2
    assert result.archive.redaction_status == "redacted"
    assert "env" in result.archive.detectors
    assert not (tmp_path / ".omni" / "artifacts" / "transcript_archive.jsonl").exists()
    stored = conn.execute(
        "SELECT kind, line_count FROM artifacts WHERE hash = ?",
        (result.archive.artifact_hash,),
    ).fetchone()
    assert dict(stored) == {"kind": "transcript_archive", "line_count": 2}
    archive_text = result.archive.path.read_text(encoding="utf-8")
    assert "parse-secret-value-123" not in archive_text
    records = [json.loads(line) for line in archive_text.splitlines()]
    assert [record["line"] for record in records] == [2, 3]
    assert records[0]["reason"] == "invalid_json"
    assert records[1]["reason"] == "unknown_transcript_shape"


def test_events_as_jsonl_is_stable(tmp_path: Path) -> None:
    transcript = tmp_path / "transcript.jsonl"
    write_jsonl(transcript, [{"hook_event_name": "SessionEnd", "session_id": "s1"}])

    result = parse.parse_transcript(transcript, root=tmp_path)
    rendered = parse.events_as_jsonl(result.events)

    assert rendered == (
        '{"duration_ms":null,"event_type":"SessionEnd","exit_code":null,'
        '"meta":{"session_id":"s1"},"seq":1,"source":"transcript","tool":null,'
        '"tool_use_id":null,"ts":""}\n'
    )
