import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "dogfood_ritual.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("dogfood_ritual", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dogfood_ritual_parser_contract() -> None:
    module = _load_module()
    parser = module.build_parser()

    args = parser.parse_args(["--warm", "w1", "--cold", "c1"])
    assert args.warm == "w1"
    assert args.cold == "c1"
    assert args.task_type == "validation"
    assert args.skip_ingest is False

    with pytest.raises(SystemExit):
        parser.parse_args(["--cold", "c1"])


def test_dogfood_ritual_handles_missing_run(tmp_path: Path) -> None:
    init = subprocess.run(
        [sys.executable, "-m", "omni.cli", "init"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert init.returncode == 0, init.stderr + init.stdout

    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), "--warm", "missing-run", "--skip-ingest"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=90,
    )

    report = json.loads(proc.stdout)
    assert report["summary"]["warm_run_id"] == "missing-run"
    assert report["summary"]["cold_run_id"] is None
    assert report["summary"]["audit_ok"] is True
    assert {"audit", "eval", "verify", "outcome"}.issubset(report["steps"])
    # A missing run cannot be evaluated or outcome-marked, so the ritual is not
    # clean and the helper exits non-zero even though audit secrets is ok.
    assert report["ran_cleanly"] is False
    assert proc.returncode == 1
