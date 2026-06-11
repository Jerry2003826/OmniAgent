from __future__ import annotations

import json
from pathlib import Path

import pytest

from omni import hook
from omni import spool


def test_capture_hook_writes_stub_when_redactor_raises(tmp_path: Path, monkeypatch) -> None:
    payload = b"raw secret must not be written"

    def fail(_payload: bytes):
        raise RuntimeError("boom")

    monkeypatch.setattr(hook, "redact_minimal", fail)

    result = hook.capture_hook(payload, root=tmp_path)

    assert result.ok is True
    assert result.spool_path is not None
    written = result.spool_path.read_text(encoding="utf-8")
    assert "raw secret must not be written" not in written
    record = json.loads(written)
    stub = json.loads(record["payload"])
    assert record["meta"]["redaction_status"] == "withheld"
    assert stub["error"] == "redaction_failed"
    assert stub["byte_len"] == len(payload)


def test_session_end_writes_per_request_ingest_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OMNI_QUEUE_SECRET", "queue-secret-value-123")
    result = hook.capture_hook(
        b'{"hook_event_name":"SessionEnd","session_id":"queue-secret-value-123",'
        b'"transcript_path":"t.jsonl"}',
        root=tmp_path,
    )

    request_files = sorted((tmp_path / ".omni" / "spool").glob("ingest-*.json"))
    request_text = request_files[0].read_text(encoding="utf-8")

    assert result.ok is True
    assert len(request_files) == 1
    assert not (tmp_path / ".omni" / "spool" / "ingest_queue.jsonl").exists()
    assert "SessionEnd" in request_text
    assert "queue-secret-value-123" not in request_text
    assert "REDACTED:env:" in request_text


def test_capture_hook_skips_raw_event_parse_for_oversized_payload(
    tmp_path: Path, monkeypatch
) -> None:
    def fail_raw_parse(_payload: bytes) -> dict[str, object]:
        raise AssertionError("oversized payload should not be parsed for enqueue detection")

    monkeypatch.setattr(hook, "_event_from_payload", fail_raw_parse)
    payload = b'{"hook_event_name":"PostToolUse","padding":"' + b"x" * (2 * 1024 * 1024) + b'"}'

    result = hook.capture_hook(payload, root=tmp_path)

    assert result.ok is True
    assert result.spool_path is not None
    assert not list((tmp_path / ".omni" / "spool").glob("ingest-*.json"))


def test_capture_hook_discovers_project_root_from_subdirectory(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "repo"
    subdir = project / "src" / "pkg"
    subdir.mkdir(parents=True)
    (project / ".git").mkdir()
    monkeypatch.chdir(subdir)

    result = hook.capture_hook(b'{"hook_event_name":"PostToolUse"}')

    assert result.ok is True
    assert result.spool_path is not None
    assert result.spool_path.parent == project / ".omni" / "spool"
    assert not (subdir / ".omni").exists()


def test_capture_hook_withholds_payload_when_skiplisted_path_is_referenced(
    tmp_path: Path,
) -> None:
    raw_secret = "DB_PASS=correcthorsebattery"
    result = hook.capture_hook(
        json.dumps(
            {
                "hook_event_name": "PostToolUse",
                "tool": "Read",
                "tool_input": {"file_path": ".env"},
                "tool_response": {"content": raw_secret},
            }
        ).encode("utf-8"),
        root=tmp_path,
    )

    assert result.ok is True
    assert result.spool_path is not None
    written = result.spool_path.read_text(encoding="utf-8")
    assert raw_secret not in written
    record = json.loads(written)
    payload = json.loads(record["payload"])
    assert record["meta"]["redaction_status"] == "withheld"
    assert record["meta"]["detectors"] == ["skiplist"]
    assert payload["hook_event_name"] == "PostToolUse"
    assert payload["tool"] == "Read"
    assert payload["tool_input"] == {"file_path": ".env"}
    assert payload["tool_response"]["content"]["error"] == "skiplisted_path_withheld"


def test_capture_hook_withholds_skiplisted_write_input_content(
    tmp_path: Path,
) -> None:
    raw_secret = "DB_PASS=lowercaseplainword"
    replacement_secret = "NEW_PASS=anotherlowercaseplainword"
    data_secret = "DATA_PASS=thirdlowercaseplainword"
    result = hook.capture_hook(
        json.dumps(
            {
                "hook_event_name": "PostToolUse",
                "tool": "Write",
                "tool_input": {
                    "file_path": ".env",
                    "content": raw_secret,
                    "new_string": replacement_secret,
                    "data": {"raw": data_secret},
                },
                "tool_response": {"stdout": "wrote .env\n"},
            }
        ).encode("utf-8"),
        root=tmp_path,
    )

    assert result.ok is True
    assert result.spool_path is not None
    written = result.spool_path.read_text(encoding="utf-8")
    assert raw_secret not in written
    assert replacement_secret not in written
    assert data_secret not in written
    record = json.loads(written)
    payload = json.loads(record["payload"])
    assert record["meta"]["redaction_status"] == "withheld"
    assert record["meta"]["detectors"] == ["skiplist"]
    assert payload["tool"] == "Write"
    assert payload["tool_input"]["file_path"] == ".env"
    assert payload["tool_input"]["content"]["error"] == "skiplisted_path_withheld"
    assert payload["tool_input"]["new_string"]["error"] == "skiplisted_path_withheld"
    assert payload["tool_input"]["data"]["error"] == "skiplisted_path_withheld"


@pytest.mark.parametrize(
    "command",
    [
        'echo "DB_PASS=lowercaseplainword" > .env',
        'echo "DB_PASS=lowercaseplainword" >> .env',
        'printf "DB_PASS=lowercaseplainword" | tee .env',
    ],
)
def test_capture_hook_withholds_bash_write_command_for_skiplisted_path(
    tmp_path: Path,
    command: str,
) -> None:
    raw_secret = "DB_PASS=lowercaseplainword"
    result = hook.capture_hook(
        json.dumps(
            {
                "hook_event_name": "PostToolUse",
                "tool": "Bash",
                "tool_input": {"command": command},
                "tool_response": {"stdout": ""},
            }
        ).encode("utf-8"),
        root=tmp_path,
    )

    assert result.ok is True
    assert result.spool_path is not None
    written = result.spool_path.read_text(encoding="utf-8")
    assert raw_secret not in written
    record = json.loads(written)
    payload = json.loads(record["payload"])
    assert record["meta"]["redaction_status"] == "withheld"
    assert record["meta"]["detectors"] == ["skiplist"]
    assert payload["tool_input"]["command"]["error"] == "skiplisted_path_withheld"


def test_capture_hook_preserves_bash_read_command_for_skiplisted_path(
    tmp_path: Path,
) -> None:
    raw_secret = "DB_PASS=lowercaseplainword"
    command = "cat .env"
    result = hook.capture_hook(
        json.dumps(
            {
                "hook_event_name": "PostToolUse",
                "tool": "Bash",
                "tool_input": {"command": command},
                "tool_response": {"stdout": raw_secret},
            }
        ).encode("utf-8"),
        root=tmp_path,
    )

    assert result.ok is True
    assert result.spool_path is not None
    written = result.spool_path.read_text(encoding="utf-8")
    assert raw_secret not in written
    record = json.loads(written)
    payload = json.loads(record["payload"])
    assert record["meta"]["redaction_status"] == "withheld"
    assert payload["tool_input"]["command"] == command
    assert payload["tool_response"]["stdout"]["error"] == "skiplisted_path_withheld"


def test_capture_hook_does_not_withhold_directory_listing_that_mentions_env(
    tmp_path: Path,
) -> None:
    result = hook.capture_hook(
        json.dumps(
            {
                "hook_event_name": "PostToolUse",
                "tool": "Bash",
                "tool_input": {"command": "ls -la"},
                "tool_response": {"stdout": ".env\npackage.json\n"},
            }
        ).encode("utf-8"),
        root=tmp_path,
    )

    assert result.spool_path is not None
    record = json.loads(result.spool_path.read_text(encoding="utf-8"))
    payload = json.loads(record["payload"])
    assert record["meta"]["redaction_status"] == "clean"
    assert payload["tool_input"]["command"] == "ls -la"
    assert payload["tool_response"]["stdout"] == ".env\npackage.json\n"


def test_capture_hook_does_not_withhold_prompt_mentioning_env_example(
    tmp_path: Path,
) -> None:
    result = hook.capture_hook(
        json.dumps(
            {
                "hook_event_name": "UserPromptSubmit",
                "prompt": "Please compare .env.example with README instructions.",
            }
        ).encode("utf-8"),
        root=tmp_path,
    )

    assert result.spool_path is not None
    record = json.loads(result.spool_path.read_text(encoding="utf-8"))
    payload = json.loads(record["payload"])
    assert record["meta"]["redaction_status"] == "clean"
    assert ".env.example" in payload["prompt"]


def test_capture_hook_does_not_withhold_plain_credentials_word_in_output(
    tmp_path: Path,
) -> None:
    result = hook.capture_hook(
        json.dumps(
            {
                "hook_event_name": "PostToolUse",
                "tool": "Bash",
                "tool_response": {"stdout": "credentials were not configured\n"},
            }
        ).encode("utf-8"),
        root=tmp_path,
    )

    assert result.spool_path is not None
    record = json.loads(result.spool_path.read_text(encoding="utf-8"))
    payload = json.loads(record["payload"])
    assert record["meta"]["redaction_status"] == "clean"
    assert payload["tool_response"]["stdout"] == "credentials were not configured\n"


def test_drain_ingest_queue_reads_request_files_and_quarantines_malformed(
    tmp_path: Path,
) -> None:
    spool_dir = tmp_path / ".omni" / "spool"
    spool_dir.mkdir(parents=True)
    (spool_dir / "ingest-1.json").write_text(
        '{"event":"SessionEnd","session_id":"s1","transcript_path":"a.jsonl"}\n',
        encoding="utf-8",
    )
    (spool_dir / "ingest-2.json").write_text(
        '{"event":"SessionEnd","session_id":"s2","transcript_path":"b.jsonl"}\n',
        encoding="utf-8",
    )
    malformed = spool_dir / "ingest-bad.json"
    malformed.write_text("not-json\n", encoding="utf-8")

    requests = spool.drain_ingest_queue(tmp_path)
    second = spool.drain_ingest_queue(tmp_path)

    assert [request["session_id"] for request in requests] == ["s1", "s2"]
    assert [request["session_id"] for request in second] == ["s1", "s2"]
    assert (spool_dir / "ingest-1.json").exists()
    assert (spool_dir / "ingest-2.json").exists()
    assert not malformed.exists()
    assert (spool_dir / "bad" / "ingest-bad.json").exists()


def test_ack_ingest_queue_removes_only_successful_request_files(tmp_path: Path) -> None:
    spool_dir = tmp_path / ".omni" / "spool"
    spool_dir.mkdir(parents=True)
    first = spool_dir / "ingest-1.json"
    second = spool_dir / "ingest-2.json"
    first.write_text('{"session_id":"s1"}\n', encoding="utf-8")
    second.write_text('{"session_id":"s2"}\n', encoding="utf-8")
    requests = spool.drain_ingest_queue(tmp_path)

    spool.ack_ingest_queue(requests[:1])

    assert not first.exists()
    assert second.exists()


def test_iter_hook_records_quarantines_malformed_hook_file(tmp_path: Path) -> None:
    spool_dir = tmp_path / ".omni" / "spool"
    spool_dir.mkdir(parents=True)
    malformed = spool_dir / "hook-bad.jsonl"
    malformed.write_text("not-json\n", encoding="utf-8")

    records = spool.iter_hook_records(tmp_path)

    assert records == []
    assert not malformed.exists()
    assert (spool_dir / "bad" / "hook-bad.jsonl").exists()


def test_quarantine_preserves_existing_bad_file_with_same_name(tmp_path: Path) -> None:
    spool_dir = tmp_path / ".omni" / "spool"
    bad_dir = spool_dir / "bad"
    bad_dir.mkdir(parents=True)
    existing = bad_dir / "hook-bad.jsonl"
    existing.write_text("first bad file\n", encoding="utf-8")
    malformed = spool_dir / "hook-bad.jsonl"
    malformed.write_text("not-json\n", encoding="utf-8")

    records = spool.iter_hook_records(tmp_path)
    bad_files = sorted(bad_dir.glob("hook-bad.jsonl*"))

    assert records == []
    assert existing.read_text(encoding="utf-8") == "first bad file\n"
    assert len(bad_files) == 2
    assert any(path.name != "hook-bad.jsonl" for path in bad_files)


def test_spool_readers_quarantine_invalid_utf8_files(tmp_path: Path) -> None:
    spool_dir = tmp_path / ".omni" / "spool"
    spool_dir.mkdir(parents=True)
    hook_file = spool_dir / "hook-binary.jsonl"
    request_file = spool_dir / "ingest-binary.json"
    legacy_file = spool_dir / "ingest_queue.jsonl"
    hook_file.write_bytes(b"\xff\xfe\x00")
    request_file.write_bytes(b"\xff\xfe\x00")
    legacy_file.write_bytes(b"\xff\xfe\x00")

    records = spool.iter_hook_records(tmp_path)
    requests = spool.drain_ingest_queue(tmp_path)

    assert records == []
    assert requests == []
    assert not hook_file.exists()
    assert not request_file.exists()
    assert not legacy_file.exists()
    assert (spool_dir / "bad" / "hook-binary.jsonl").exists()
    assert (spool_dir / "bad" / "ingest-binary.json").exists()
    assert (spool_dir / "bad" / "ingest_queue.jsonl").exists()


def test_drain_ingest_queue_quarantines_malformed_legacy_jsonl(tmp_path: Path) -> None:
    spool_dir = tmp_path / ".omni" / "spool"
    spool_dir.mkdir(parents=True)
    legacy = spool_dir / "ingest_queue.jsonl"
    legacy.write_text('{"session_id":"s1"}\nnot-json\n', encoding="utf-8")

    requests = spool.drain_ingest_queue(tmp_path)

    assert requests == []
    assert not legacy.exists()
    assert (spool_dir / "bad" / "ingest_queue.jsonl").exists()


def test_legacy_ingest_queue_malformed_line_quarantines_whole_file(
    tmp_path: Path,
) -> None:
    spool_dir = tmp_path / ".omni" / "spool"
    spool_dir.mkdir(parents=True)
    legacy = spool_dir / "ingest_queue.jsonl"
    legacy.write_text(
        '{"session_id":"before"}\nnot-json\n{"session_id":"after"}\n',
        encoding="utf-8",
    )

    requests = spool.drain_ingest_queue(tmp_path)
    quarantined = spool_dir / "bad" / "ingest_queue.jsonl"

    assert requests == []
    assert not legacy.exists()
    assert quarantined.exists()
    assert '"session_id":"before"' in quarantined.read_text(encoding="utf-8")
    assert '"session_id":"after"' in quarantined.read_text(encoding="utf-8")
