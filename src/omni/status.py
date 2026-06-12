"""Read-only project status reporting."""

from __future__ import annotations

import json
import math
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
    body.update(_hook_elapsed_summary(base))
    return json.dumps(body, sort_keys=True) + "\n"


def _hook_elapsed_summary(root: Path) -> dict[str, int]:
    elapsed: list[int] = []
    spool = root / ".omni" / "spool"
    if not spool.exists():
        return {}

    hook_paths = [*spool.glob("hook-*.jsonl"), *(spool / "processed").glob("hook-*.jsonl")]
    for path in sorted(hook_paths):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            meta = record.get("meta")
            if not isinstance(meta, dict):
                continue
            value = meta.get("elapsed_ms")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            elapsed.append(max(0, int(value)))

    if not elapsed:
        return {}

    elapsed.sort()
    return {
        "hook_elapsed_ms_p50": _nearest_rank(elapsed, 50),
        "hook_elapsed_ms_p95": _nearest_rank(elapsed, 95),
    }


def _nearest_rank(values: list[int], percentile: int) -> int:
    index = max(0, math.ceil((percentile / 100) * len(values)) - 1)
    return values[min(index, len(values) - 1)]
