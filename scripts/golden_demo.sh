#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
target="${1:-${TMPDIR:-/tmp}/omni-golden-demo}"
python_bin="${PYTHON_BIN:-python}"
claude_bin="${CLAUDE_BIN:-claude}"

export PYTHON_BIN="$python_bin"
export PYTHONPATH="$repo_root/src${PYTHONPATH:+:$PYTHONPATH}"

run_omni() {
  "$python_bin" -m omni.cli "$@"
}

new_uuid() {
  "$python_bin" - <<'PY'
import uuid
print(uuid.uuid4())
PY
}

sandbox="$("$repo_root/scripts/create_sandbox.sh" "$target")"
cd "$sandbox"

run_omni init --install-claude-hooks --yes >/dev/null

cold_id="$(new_uuid)"
"$claude_bin" \
  --print \
  --no-session-persistence \
  --session-id "$cold_id" \
  --permission-mode bypassPermissions \
  --output-format text \
  "Run the project tests once. Use the appropriate shell command, then briefly report the command and whether it passed." \
  >/dev/null

run_omni ingest >/dev/null
run_omni render --diff >/dev/null
run_omni render >/dev/null
run_omni inject claude --mode link >/dev/null # omni inject claude --mode link

warm_ids=()
for _ in 1 2 3; do
  sid="$(new_uuid)"
  warm_ids+=("$sid")
  "$claude_bin" \
    --print \
    --no-session-persistence \
    --session-id "$sid" \
    --permission-mode bypassPermissions \
    --output-format text \
    "Run the project tests once. Briefly report the command and whether it passed." \
    >/dev/null
  run_omni ingest >/dev/null
done

run_omni audit secrets >/dev/null

expected="$(sed -n 's/^- default test command: //p' .omni/generated/memory.md | head -n 1)"
if [ -z "$expected" ]; then
  echo "missing default test command in .omni/generated/memory.md" >&2
  exit 1
fi

warm_csv="$(
  IFS=,
  echo "${warm_ids[*]}"
)"
export OMNI_GOLDEN_SANDBOX="$sandbox"
export OMNI_GOLDEN_WARM_IDS="$warm_csv"
export OMNI_GOLDEN_EXPECTED="$expected"

"$python_bin" - <<'PY'
import json
import os
import sqlite3
import sys
from pathlib import Path

root = Path(os.environ["OMNI_GOLDEN_SANDBOX"])
warm_ids = [item for item in os.environ["OMNI_GOLDEN_WARM_IDS"].split(",") if item]
expected = os.environ["OMNI_GOLDEN_EXPECTED"]
conn = sqlite3.connect(root / ".omni" / "omni.sqlite3")
conn.row_factory = sqlite3.Row
forbidden_reads = {"package.json", "pnpm-lock.yaml", "package-lock.json", "pyproject.toml"}
passed = 0
details = []
for run_id in warm_ids:
    rows = conn.execute(
        "SELECT seq, tool, meta FROM events WHERE run_id = ? ORDER BY seq", (run_id,)
    ).fetchall()
    first_command = None
    stdout_ok = False
    forbidden_before = []
    for row in rows:
        meta = json.loads(row["meta"]) if row["meta"] else {}
        tool_input = meta.get("tool_input") or {}
        file_path = tool_input.get("file_path")
        command = tool_input.get("command")
        if first_command is None and file_path:
            name = Path(str(file_path)).name
            if name in forbidden_reads:
                forbidden_before.append(f"read:{name}")
        if command:
            normalized = " ".join(str(command).strip().split())
            if first_command is None:
                first_command = normalized
                stdout_ok = "sandbox test ok" in json.dumps(meta.get("tool_response") or {})
            break
    ok = first_command == expected and stdout_ok and not forbidden_before
    passed += 1 if ok else 0
    details.append(
        {
            "run_id": run_id,
            "passed": ok,
            "first_command": first_command,
            "forbidden_before": forbidden_before,
        }
    )
print(json.dumps({"expected": expected, "passed": passed, "total": len(warm_ids), "details": details}, sort_keys=True))
print(f"G6 robust: {passed}/{len(warm_ids)}")
if passed != len(warm_ids):
    sys.exit(1)
PY

printf 'sandbox: %s\n' "$sandbox"
