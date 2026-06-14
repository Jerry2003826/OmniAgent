from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

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


def candidate(
    object_norm: str = "custom",
    *,
    qualifier: str = "default",
) -> gate.FactCandidate:
    return gate.FactCandidate(
        scope="project",
        subject=".",
        predicate="uses_test_command",
        qualifier=qualifier,
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


def test_stage_candidate_does_not_commit_open_transaction(tmp_path: Path) -> None:
    conn = connect(tmp_path)

    conn.execute("BEGIN")
    pending = gate.stage_candidate(conn, candidate("transactional-pending"))
    conn.rollback()

    row = conn.execute(
        "SELECT cand_id FROM fact_candidates WHERE cand_id = ?",
        (pending.cand_id,),
    ).fetchone()
    assert row is None


def test_apply_candidates_counts_only_newly_staged_candidates(tmp_path: Path) -> None:
    conn = connect(tmp_path)

    first = gate.apply_candidates(conn, [candidate("duplicate-pending")])
    second = gate.apply_candidates(conn, [candidate("duplicate-pending")])

    rows = conn.execute(
        "SELECT cand_id FROM fact_candidates WHERE object_norm = 'duplicate-pending'"
    ).fetchall()
    assert first.pending == 1
    assert second.pending == 0
    assert len(rows) == 1


def test_apply_candidates_does_not_commit_open_transaction_by_default(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path)

    conn.execute("BEGIN")
    result = gate.apply_candidates(conn, [candidate("transactional-apply")])
    conn.rollback()

    row = conn.execute(
        "SELECT cand_id FROM fact_candidates WHERE object_norm = 'transactional-apply'"
    ).fetchone()
    assert result.pending == 1
    assert row is None


def test_review_reject_writes_suppression_and_blocks_auto_commit(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    pending = gate.stage_candidate(conn, candidate("blocked"))

    review.reject(conn, pending.cand_id)
    auto_result = gate.apply_candidates(conn, [candidate("blocked")])

    assert auto_result.auto_committed == 0
    assert auto_result.pending == 0
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


def test_review_approve_rejects_conflicting_single_valued_fact(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    gate.insert_fact(conn, candidate("pnpm run test", qualifier="node"))
    pending = gate.stage_candidate(conn, candidate("npm test", qualifier="node"))
    conflict = conn.execute(
        """
        SELECT fact_id FROM facts
        WHERE predicate = 'uses_test_command' AND qualifier = 'node'
        """
    ).fetchone()["fact_id"]

    with pytest.raises(gate.ConflictRequiresSupersede) as exc:
        review.approve(conn, pending.cand_id)

    facts = conn.execute(
        """
        SELECT object_norm FROM facts
        WHERE predicate = 'uses_test_command' AND qualifier = 'node'
        """
    ).fetchall()
    candidate_row = conn.execute(
        "SELECT state, review_note FROM fact_candidates WHERE cand_id = ?",
        (pending.cand_id,),
    ).fetchone()
    message = str(exc.value)

    assert [row["object_norm"] for row in facts] == ["pnpm run test"]
    assert candidate_row["state"] == "pending"
    assert "conflict requires supersede" in candidate_row["review_note"]
    assert "pnpm run test" in candidate_row["review_note"]
    assert conflict in message
    assert "pnpm run test" in message


def test_review_approve_exact_duplicate_is_harmless(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    gate.insert_fact(conn, candidate("pnpm run test", qualifier="node"))
    pending = gate.stage_candidate(conn, candidate("pnpm run test", qualifier="node"))

    result = review.approve(conn, pending.cand_id)

    facts = conn.execute(
        """
        SELECT object_norm FROM facts
        WHERE predicate = 'uses_test_command' AND qualifier = 'node'
        """
    ).fetchall()
    assert result.state == "approved"
    assert [row["object_norm"] for row in facts] == ["pnpm run test"]


def test_review_approve_clears_stale_review_note(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    pending = gate.stage_candidate(conn, candidate("stale-note"))
    conn.execute(
        "UPDATE fact_candidates SET review_note = ? WHERE cand_id = ?",
        ("previous conflict requires supersede", pending.cand_id),
    )

    review.approve(conn, pending.cand_id)

    row = conn.execute(
        "SELECT state, review_note FROM fact_candidates WHERE cand_id = ?",
        (pending.cand_id,),
    ).fetchone()
    assert dict(row) == {"state": "approved", "review_note": None}


def test_review_cli_approve_and_reject(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    approve_candidate = gate.stage_candidate(conn, candidate("cli-approve"))
    reject_candidate = gate.stage_candidate(conn, candidate("cli-reject"))
    conn.commit()
    conn.close()

    approve = run_omni(tmp_path, "review", "approve", approve_candidate.cand_id)
    reject = run_omni(tmp_path, "review", "reject", reject_candidate.cand_id)

    assert approve.returncode == 0, approve.stderr
    assert reject.returncode == 0, reject.stderr
    assert json.loads(approve.stdout)["state"] == "approved"
    assert json.loads(reject.stdout)["state"] == "rejected"


def test_review_cli_approve_conflict_exits_nonzero_and_keeps_candidate_pending(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path)
    gate.insert_fact(conn, candidate("pnpm run test", qualifier="node"))
    pending = gate.stage_candidate(conn, candidate("npm test", qualifier="node"))
    conn.commit()
    conn.close()

    result = run_omni(tmp_path, "review", "approve", pending.cand_id)
    conn = connect(tmp_path)
    candidate_row = conn.execute(
        "SELECT state, review_note FROM fact_candidates WHERE cand_id = ?",
        (pending.cand_id,),
    ).fetchone()
    facts = conn.execute(
        """
        SELECT object_norm FROM facts
        WHERE predicate = 'uses_test_command' AND qualifier = 'node'
        """
    ).fetchall()

    assert result.returncode != 0
    assert "conflict" in result.stderr.lower()
    assert "pnpm run test" in result.stderr
    assert candidate_row["state"] == "pending"
    assert "conflict requires supersede" in candidate_row["review_note"]
    assert [row["object_norm"] for row in facts] == ["pnpm run test"]


def test_review_refuses_to_reprocess_already_reviewed_candidate(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    pending = gate.stage_candidate(conn, candidate("already-reviewed"))

    review.approve(conn, pending.cand_id)

    with pytest.raises(ValueError, match="not pending"):
        review.reject(conn, pending.cand_id)


def test_review_interactive_approves_rejects_and_summarizes(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    approve_candidate = gate.stage_candidate(conn, candidate("interactive-approve"))
    reject_candidate = gate.stage_candidate(conn, candidate("interactive-reject"))
    decisions = iter(["a", "r"])
    output: list[str] = []

    result = review.interactive(
        conn,
        input_fn=lambda _prompt: next(decisions),
        output_fn=output.append,
    )
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

    assert str(approve_candidate.cand_id) in "\n".join(output)
    assert str(reject_candidate.cand_id) in "\n".join(output)
    assert result == review.ReviewSummary(
        approved=1,
        rejected=1,
        skipped=0,
        remaining=0,
    )
    assert states == {
        "interactive-approve": "approved",
        "interactive-reject": "rejected",
    }
    assert fact["object_norm"] == "interactive-approve"
    assert suppression["object_norm"] == "interactive-reject"


def test_review_interactive_skips_conflict_requires_supersede(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    gate.insert_fact(conn, candidate("pnpm run test", qualifier="node"))
    pending = gate.stage_candidate(conn, candidate("npm test", qualifier="node"))
    output: list[str] = []

    result = review.interactive(
        conn,
        input_fn=lambda _prompt: "a",
        output_fn=output.append,
    )
    candidate_row = conn.execute(
        "SELECT state, review_note FROM fact_candidates WHERE cand_id = ?",
        (pending.cand_id,),
    ).fetchone()
    facts = conn.execute(
        """
        SELECT object_norm FROM facts
        WHERE predicate = 'uses_test_command' AND qualifier = 'node'
        """
    ).fetchall()
    joined = "\n".join(output)

    assert result == review.ReviewSummary(
        approved=0,
        rejected=0,
        skipped=1,
        remaining=1,
    )
    assert "conflict requires supersede" in joined
    assert "pnpm run test" in joined
    assert candidate_row["state"] == "pending"
    assert "conflict requires supersede" in candidate_row["review_note"]
    assert [row["object_norm"] for row in facts] == ["pnpm run test"]


def test_review_interactive_no_pending_candidates(tmp_path: Path) -> None:
    conn = connect(tmp_path)

    result = review.interactive(conn, input_fn=lambda _prompt: "", output_fn=lambda _line: None)

    assert result == review.ReviewSummary(
        approved=0,
        rejected=0,
        skipped=0,
        remaining=0,
    )
