from __future__ import annotations

import json
from pathlib import Path

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

    result = parse.parse_transcript(transcript)

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

    result = parse.parse_transcript(transcript)

    assert len(result.events) == 1
    assert result.archive is not None
    assert result.archive.kind == "transcript_archive"
    assert result.archive.line_count == 2
    assert result.archive.redaction_status == "redacted"
    assert "env" in result.archive.detectors
    assert not (tmp_path / ".omni").exists()
    archive_text = result.archive.payload.decode("utf-8")
    assert "parse-secret-value-123" not in archive_text
    records = [json.loads(line) for line in archive_text.splitlines()]
    assert [record["line"] for record in records] == [2, 3]
    assert records[0]["reason"] == "invalid_json"
    assert records[1]["reason"] == "unknown_transcript_shape"


def test_parse_transcript_redacts_known_event_meta_in_return_value(tmp_path: Path) -> None:
    secret = "sk-parsemetasecretvalue1234567890"
    transcript = tmp_path / "transcript.jsonl"
    write_jsonl(
        transcript,
        [
            {
                "type": "tool_use",
                "timestamp": "2026-06-11T00:00:00Z",
                "name": "Bash",
                "api_key": secret,
            }
        ],
    )

    result = parse.parse_transcript(transcript)
    meta_text = json.dumps(result.events[0].meta, sort_keys=True)
    rendered = parse.events_as_jsonl(result.events)

    assert secret not in meta_text
    assert "REDACTED:" in meta_text
    assert secret not in rendered
    assert not (tmp_path / ".omni").exists()
    assert not (tmp_path / ".omni" / "omni.sqlite3").exists()


def test_parse_transcript_redacts_secret_like_known_event_fields(tmp_path: Path) -> None:
    secret = "ghp_" + "abcdefghijklmnopqrstuvwxyz1234567890"
    transcript = tmp_path / "transcript.jsonl"
    write_jsonl(
        transcript,
        [
            {
                "type": "tool_use",
                "timestamp": "2026-06-11T00:00:00Z",
                "id": secret,
                "name": f"token={secret}",
            }
        ],
    )

    result = parse.parse_transcript(transcript)
    rendered = parse.events_as_jsonl(result.events)
    event = result.events[0]

    assert secret not in event.tool
    assert secret not in event.tool_use_id
    assert secret not in rendered
    assert "REDACTED:" in rendered


def test_parse_transcript_streams_without_reading_entire_file(
    tmp_path: Path, monkeypatch
) -> None:
    transcript = tmp_path / "large.jsonl"
    with transcript.open("w", encoding="utf-8") as handle:
        for index in range(50_000):
            handle.write(
                json.dumps(
                    {
                        "type": "tool_use",
                        "timestamp": f"2026-06-11T00:00:{index % 60:02d}Z",
                        "id": f"toolu_{index}",
                    }
                )
                + "\n"
            )

    def fail_read_bytes(_path: Path) -> bytes:
        raise AssertionError("parse_transcript must stream transcript lines")

    monkeypatch.setattr(Path, "read_bytes", fail_read_bytes)

    result = parse.parse_transcript(transcript)

    assert len(result.events) == 50_000
    assert result.archive is None


def test_events_as_jsonl_redacts_each_line_for_large_output() -> None:
    secret = "sk-" + "largeparseoutputsecretvalue1234567890"
    events = [
        parse.NormalizedEvent(
            seq=index + 1,
            ts="2026-06-11T00:00:00Z",
            event_type="tool_use",
            tool="Bash",
            tool_use_id=f"toolu_{index}",
            exit_code=0,
            duration_ms=None,
            source="transcript",
            meta={"api_key": secret, "padding": "x" * 200},
        )
        for index in range(6_000)
    ]

    rendered = parse.events_as_jsonl(events)
    lines = rendered.splitlines()

    assert len(lines) == len(events)
    assert "payload_truncated" not in rendered
    assert secret not in rendered
    assert all(json.loads(line)["event_type"] == "tool_use" for line in lines)


def test_events_as_jsonl_is_stable(tmp_path: Path) -> None:
    transcript = tmp_path / "transcript.jsonl"
    write_jsonl(transcript, [{"hook_event_name": "SessionEnd", "session_id": "s1"}])

    result = parse.parse_transcript(transcript)
    rendered = parse.events_as_jsonl(result.events)

    assert rendered == (
        '{"duration_ms":null,"event_type":"SessionEnd","exit_code":null,'
        '"meta":{"session_id":"s1"},"seq":1,"source":"transcript","tool":null,'
        '"tool_use_id":null,"ts":""}\n'
    )
