"""Read-only project status reporting."""

from __future__ import annotations

import json
from pathlib import Path

from omni.inject import MANAGED_REGION


def status_json(root: Path | str | None = None) -> str:
    base = Path(root or Path.cwd()).resolve()
    claude = base / "CLAUDE.md"
    memory = base / ".omni" / "generated" / "memory.md"
    body = {
        "ok": True,
        "omni_dir": (base / ".omni").is_dir(),
        "config": (base / ".omni" / "config.toml").is_file(),
        "database": (base / ".omni" / "omni.sqlite3").is_file(),
        "generated_memory": memory.is_file(),
        "claude_link": claude.is_file()
        and MANAGED_REGION.rstrip("\n") in claude.read_text(encoding="utf-8"),
    }
    return json.dumps(body, sort_keys=True) + "\n"
