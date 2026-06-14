import json
import subprocess
import sys


def test_cli_only_smoke_script_passes() -> None:
    proc = subprocess.run(
        [sys.executable, "scripts/cli_only_smoke.py"],
        text=True,
        capture_output=True,
        timeout=90,
    )

    assert proc.returncode == 0, proc.stderr + proc.stdout
    result = json.loads(proc.stdout)
    assert result["ok"] is True
    assert [item["returncode"] for item in result["results"]] == [0, 0, 0, 0, 0]
    assert all(
        item["command"][:3] == [sys.executable, "-m", "omni.cli"]
        for item in result["results"]
    )
    assert result["memory_path"].endswith(
        (".omni\\generated\\memory.md", ".omni/generated/memory.md")
    )
