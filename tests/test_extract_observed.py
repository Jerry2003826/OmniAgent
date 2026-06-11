from __future__ import annotations

import json
from pathlib import Path

from omni import db
from omni import gate
from omni import hook
from omni import ingest


def test_single_observed_command_never_auto_commits(tmp_path: Path) -> None:
    assert "observed_command@1" not in gate.AUTO_ORIGINS

    hook.capture_hook(
        json.dumps(
            {
                "hook_event_name": "PostToolUse",
                "session_id": "observed-run",
                "timestamp": "2026-06-11T00:00:00Z",
                "tool_use_id": "toolu_test",
                "tool": "Bash",
                "tool_input": {"command": "pnpm run test"},
                "tool_response": {"stdout": "ok", "stderr": ""},
            }
        ).encode("utf-8"),
        root=tmp_path,
    )
    hook.capture_hook(
        json.dumps(
            {
                "hook_event_name": "SessionEnd",
                "session_id": "observed-run",
                "transcript_path": None,
            }
        ).encode("utf-8"),
        root=tmp_path,
    )

    result = ingest.ingest(root=tmp_path)
    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")
    facts = conn.execute("SELECT object_norm FROM facts").fetchall()
    pending = conn.execute(
        """
        SELECT predicate, qualifier, object_norm, trust, extractor_version, state
        FROM fact_candidates
        WHERE extractor_version = 'observed_command@1'
        """
    ).fetchall()

    assert result.events_inserted >= 1
    assert facts == []
    assert [dict(row) for row in pending] == [
        {
            "predicate": "uses_test_command",
            "qualifier": "default",
            "object_norm": "pnpm run test",
            "trust": 1,
            "extractor_version": "observed_command@1",
            "state": "pending",
        }
    ]


def test_observed_command_reads_reconciled_transcript_or_hook_meta(tmp_path: Path) -> None:
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "type": "tool_use",
                "timestamp": "2026-06-11T00:00:00Z",
                "id": "toolu_reconciled",
                "name": "Bash",
                "input": {"command": "pnpm run test"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    hook.capture_hook(
        json.dumps(
            {
                "hook_event_name": "PostToolUse",
                "session_id": "reconciled-run",
                "timestamp": "2026-06-11T00:00:01Z",
                "tool_use_id": "toolu_reconciled",
                "tool": "Bash",
                "tool_input": {"command": "pnpm run test"},
                "tool_response": {"stdout": "sandbox test ok", "stderr": ""},
            }
        ).encode("utf-8"),
        root=tmp_path,
    )

    ingest.ingest(root=tmp_path, run_id="reconciled-run", transcript=transcript)
    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")
    pending = conn.execute(
        """
        SELECT object_norm, extractor_version, state
        FROM fact_candidates
        WHERE extractor_version = 'observed_command@1'
        """
    ).fetchall()

    assert [dict(row) for row in pending] == [
        {
            "object_norm": "pnpm run test",
            "extractor_version": "observed_command@1",
            "state": "pending",
        }
    ]
