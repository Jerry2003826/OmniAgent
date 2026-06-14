"""Run the OmniMemory governance ritual for one real Claude Code run.

Periodic dogfood helper. Given a warm run id (and optionally a cold baseline run
id), it runs the operator ritual through the public CLI and prints a consolidated
JSON report:

    ingest -> audit secrets -> eval run -> verify -> outcome mark-from-verify
    -> eval dogfood

It only calls existing CLI commands. It never passes ``--success`` (task success
stays user-marked), adds no new state or tables, and writes only through the
already-approved ``ingest`` and ``outcome mark-from-verify`` commands. Run it from
the target project root after a Claude Code session.

Examples:

    python scripts/dogfood_ritual.py --warm <warm_run_id>
    python scripts/dogfood_ritual.py --warm <warm_run_id> --cold <cold_run_id>

Exit code is 0 when the ritual ran and ``audit secrets`` is ok (even if tests
failed -- a failing verify is a valid observation surfaced in the report). It is
non-zero when ``audit secrets`` is not ok or when eval/outcome could not resolve
the run.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the OmniMemory governance ritual for one warm run.",
    )
    parser.add_argument(
        "--warm", required=True, help="warm run id (from the `omni ingest` output)"
    )
    parser.add_argument(
        "--cold", default=None, help="optional cold baseline run id for dogfood compare"
    )
    parser.add_argument(
        "--task-type",
        default="validation",
        help="outcome task type recorded by mark-from-verify (default: validation)",
    )
    parser.add_argument(
        "--skip-ingest",
        action="store_true",
        help="do not run `omni ingest` first (use when the run is already ingested)",
    )
    return parser


def _run_cli(args: list[str]) -> dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, "-m", "omni.cli", *args],
        text=True,
        capture_output=True,
    )
    stdout = proc.stdout.strip()
    parsed: Any = None
    if stdout:
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError:
            parsed = None
    return {
        "command": ["omni", *args],
        "returncode": proc.returncode,
        "json": parsed,
        "stdout_tail": stdout[-2000:],
        "stderr_tail": proc.stderr.strip()[-2000:],
    }


def run_ritual(
    warm: str,
    cold: str | None = None,
    task_type: str = "validation",
    skip_ingest: bool = False,
) -> dict[str, Any]:
    steps: dict[str, Any] = {}
    if not skip_ingest:
        steps["ingest"] = _run_cli(["ingest"])
    steps["audit"] = _run_cli(["audit", "secrets"])
    steps["eval"] = _run_cli(["eval", "run", warm])
    steps["verify"] = _run_cli(["verify"])
    steps["outcome"] = _run_cli(
        ["outcome", "mark-from-verify", warm, "--task-type", task_type]
    )
    if cold:
        steps["dogfood"] = _run_cli(["eval", "dogfood", "--cold", cold, "--warm", warm])

    audit = steps["audit"]["json"] or {}
    ev = steps["eval"]["json"] or {}
    vf = steps["verify"]["json"] or {}
    oc = steps["outcome"]["json"] or {}
    df = (steps.get("dogfood") or {}).get("json") or {}

    summary = {
        "warm_run_id": warm,
        "cold_run_id": cold,
        "audit_ok": bool(audit.get("ok")),
        "first_expected_command": ev.get("first_expected_command"),
        "rediscovery_count": ev.get("rediscovery_count"),
        "memory_effect": ev.get("memory_effect"),
        "verify_status": vf.get("status"),
        "verify_reason_code": vf.get("reason_code"),
        "outcome_status": oc.get("status"),
        "outcome_tests_status": oc.get("tests_status"),
        "dogfood_improvement": df.get("improvement") if cold else None,
        "dogfood_command_adopted": df.get("command_adopted") if cold else None,
    }
    ran = bool(summary["audit_ok"]) and bool(ev) and bool(oc)
    return {"summary": summary, "ran_cleanly": ran, "steps": steps}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_ritual(
        warm=args.warm,
        cold=args.cold,
        task_type=args.task_type,
        skip_ingest=args.skip_ingest,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ran_cleanly"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
