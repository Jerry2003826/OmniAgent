"""Content-addressed artifact storage."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from omni.redact import redact

REDACTION_VER = 1


@dataclass(frozen=True)
class StoredArtifact:
    hash: str
    path: Path
    kind: str
    byte_len: int
    line_count: int
    redaction_status: str
    redaction_ver: int


def put_artifact(
    root: Path | str,
    conn: sqlite3.Connection,
    *,
    kind: str,
    data: bytes,
) -> StoredArtifact:
    base = Path(root).resolve()
    redaction = redact(data)
    content = redaction.data
    digest = hashlib.sha256(content).hexdigest()
    path = base / ".omni" / "artifacts" / digest[7:9] / digest[9:11] / digest
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(content)

    artifact = StoredArtifact(
        hash=digest,
        path=path,
        kind=kind,
        byte_len=len(content),
        line_count=_line_count(content),
        redaction_status=redaction.status,
        redaction_ver=REDACTION_VER,
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO artifacts(
          hash, kind, byte_len, line_count, redaction_status, redaction_ver, created_at
        ) VALUES(?,?,?,?,?,?,?)
        """,
        (
            artifact.hash,
            artifact.kind,
            artifact.byte_len,
            artifact.line_count,
            artifact.redaction_status,
            artifact.redaction_ver,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
    return artifact


def _line_count(content: bytes) -> int:
    if not content:
        return 0
    return len(content.splitlines())
