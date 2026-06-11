from __future__ import annotations

import json
from pathlib import Path

from omni import hook


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
