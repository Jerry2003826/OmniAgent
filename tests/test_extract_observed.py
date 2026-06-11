from __future__ import annotations

import json
from pathlib import Path

from omni import db
from omni import hook
from omni import ingest


def test_single_observed_command_never_auto_commits(tmp_path: Path) -> None:
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
