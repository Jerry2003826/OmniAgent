"""Run a minimal public-command smoke for CLI-only Claude Code v1."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="omni-cli-v1-smoke-"))
    env = os.environ.copy()
    commands = [
        ["omni", "init"],
        ["omni", "audit", "secrets"],
        ["omni", "status"],
        ["omni", "render", "--diff"],
        ["omni", "render"],
    ]
    results: list[dict[str, Any]] = []
    for command in commands:
        proc = subprocess.run(
            command,
            cwd=root,
            env=env,
            text=True,
            capture_output=True,
            timeout=60,
        )
        results.append(
            {
                "command": command,
                "returncode": proc.returncode,
                "stdout": proc.stdout[-1000:],
                "stderr": proc.stderr[-1000:],
            }
        )
        if proc.returncode != 0:
            print(json.dumps({"ok": False, "root": str(root), "results": results}, indent=2))
            return proc.returncode

    memory_path = root / ".omni" / "generated" / "memory.md"
    ok = memory_path.exists()
    print(
        json.dumps(
            {
                "ok": ok,
                "root": str(root),
                "memory_path": str(memory_path),
                "results": results,
            },
            indent=2,
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
