from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from omni import db
from omni import gate
from omni import review


REPO_ROOT = Path(__file__).resolve().parents[1]


def run_omni(
    cwd: Path, *args: str, input_text: str | None = None
) -> subprocess.CompletedProcess[str]:
    env = {"PYTHONPATH": str(REPO_ROOT / "src")}
    return subprocess.run(
        [sys.executable, "-m", "omni.cli", *args],
        cwd=cwd,
        env={**env},
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )


def candidate(object_norm: str = "custom") -> gate.FactCandidate:
    return gate.FactCandidate(
        scope="project",
        subject=".",
        predicate="uses_test_command",
        qualifier="default",
        object_norm=object_norm,
        value_type="string",
        claim=f"Use {object_norm}",
        trust=1,
        sensitivity="low",
        origin="manual@1",
        evidence={"files": []},
    )


def connect(tmp_path: Path) -> sqlite3.Connection:
    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")
    db.migrate(conn)
    return conn


def test_review_approve_promotes_pending_candidate_to_fact(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    pending = gate.stage_candidate(conn, candidate())

    review.approve(conn, pending.cand_id)

    fact = conn.execute(
        "SELECT object_norm, origin FROM facts WHERE predicate = 'uses_test_command'"
    ).fetchone()
    state = conn.execute(
        "SELECT state FROM fact_candidates WHERE cand_id = ?", (pending.cand_id,)
    ).fetchone()["state"]
    assert dict(fact) == {"object_norm": "custom", "origin": "manual@1"}
    assert state == "approved"


def test_review_reject_writes_suppression_and_blocks_auto_commit(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    pending = gate.stage_candidate(conn, candidate("blocked"))

    review.reject(conn, pending.cand_id)
    auto_result = gate.apply_candidates(conn, [candidate("blocked")])

    assert auto_result.auto_committed == 0
    assert auto_result.pending == 1
    suppression = conn.execute(
        "SELECT object_norm FROM suppressions WHERE object_norm = 'blocked'"
    ).fetchone()
    assert suppression["object_norm"] == "blocked"


def test_gate_keeps_new_value_pending_when_active_key_exists(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    gate.insert_fact(conn, candidate("current"))

    result = gate.apply_candidates(
        conn,
        [
            gate.FactCandidate(
                scope="project",
                subject=".",
                predicate="uses_test_command",
                qualifier="default",
                object_norm="replacement",
                value_type="string",
                claim="Use replacement",
                trust=2,
                sensitivity="low",
                origin="script_extractor@1",
                evidence={"files": []},
            )
        ],
    )

    pending = conn.execute(
        """
        SELECT object_norm, state FROM fact_candidates
        WHERE predicate = 'uses_test_command'
        """
    ).fetchone()
    facts = conn.execute(
        """
        SELECT object_norm FROM facts
        WHERE predicate = 'uses_test_command' AND retired_seq IS NULL
        ORDER BY object_norm
        """
    ).fetchall()
    assert result.auto_committed == 0
    assert result.pending == 1
    assert dict(pending) == {"object_norm": "replacement", "state": "pending"}
    assert [row["object_norm"] for row in facts] == ["current"]


def test_review_cli_approve_and_reject(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    approve_candidate = gate.stage_candidate(conn, candidate("cli-approve"))
    reject_candidate = gate.stage_candidate(conn, candidate("cli-reject"))
    conn.close()

    approve = run_omni(tmp_path, "review", "approve", approve_candidate.cand_id)
    reject = run_omni(tmp_path, "review", "reject", reject_candidate.cand_id)

    assert approve.returncode == 0, approve.stderr
    assert reject.returncode == 0, reject.stderr
    assert json.loads(approve.stdout)["state"] == "approved"
    assert json.loads(reject.stdout)["state"] == "rejected"


def test_review_interactive_approves_rejects_and_summarizes(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    approve_candidate = gate.stage_candidate(conn, candidate("interactive-approve"))
    reject_candidate = gate.stage_candidate(conn, candidate("interactive-reject"))
    conn.close()

    result = run_omni(tmp_path, "review", "interactive", input_text="a\nr\n")
    conn = connect(tmp_path)
    states = dict(
        conn.execute(
            "SELECT object_norm, state FROM fact_candidates ORDER BY object_norm"
        ).fetchall()
    )
    fact = conn.execute(
        "SELECT object_norm FROM facts WHERE object_norm = 'interactive-approve'"
    ).fetchone()
    suppression = conn.execute(
        "SELECT object_norm FROM suppressions WHERE object_norm = 'interactive-reject'"
    ).fetchone()

    assert result.returncode == 0, result.stderr
    assert approve_candidate.cand_id in result.stdout
    assert reject_candidate.cand_id in result.stdout
    assert json.loads(result.stdout.splitlines()[-1]) == {
        "approved": 1,
        "rejected": 1,
        "skipped": 0,
        "remaining": 0,
    }
    assert states == {
        "interactive-approve": "approved",
        "interactive-reject": "rejected",
    }
    assert fact["object_norm"] == "interactive-approve"
    assert suppression["object_norm"] == "interactive-reject"


def test_review_interactive_no_pending_candidates(tmp_path: Path) -> None:
    connect(tmp_path).close()

    result = run_omni(tmp_path, "review", "interactive", input_text="")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.splitlines()[-1]) == {
        "approved": 0,
        "rejected": 0,
        "skipped": 0,
        "remaining": 0,
    }
