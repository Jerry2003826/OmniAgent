"""Interactive and non-interactive review operations for fact candidates."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from pathlib import Path

from omni import db
from omni import gate


@dataclass(frozen=True)
class ReviewResult:
    cand_id: str
    state: str

    def as_json(self) -> str:
        return json.dumps({"cand_id": self.cand_id, "state": self.state}, sort_keys=True) + "\n"


@dataclass(frozen=True)
class ReviewSummary:
    approved: int = 0
    rejected: int = 0
    skipped: int = 0
    remaining: int = 0

    def as_json(self) -> str:
        return json.dumps(
            {
                "approved": self.approved,
                "rejected": self.rejected,
                "skipped": self.skipped,
                "remaining": self.remaining,
            },
            sort_keys=True,
        ) + "\n"


def connect_project(root: Path | str | None = None) -> sqlite3.Connection:
    base = Path(root or Path.cwd()).resolve()
    conn = db.connect(base / ".omni" / "omni.sqlite3")
    db.migrate(conn)
    return conn


def approve(conn: sqlite3.Connection, cand_id: str) -> ReviewResult:
    candidate = _load_candidate(conn, cand_id)
    try:
        gate.insert_fact(conn, candidate)
    except gate.ConflictRequiresSupersede as exc:
        conn.execute(
            """
            UPDATE fact_candidates
            SET state = ?, review_note = ?
            WHERE cand_id = ?
            """,
            ("pending", f"conflict requires supersede: {exc}", cand_id),
        )
        conn.commit()
        raise
    conn.execute(
        "UPDATE fact_candidates SET state = ?, reviewed_at = ?, review_note = NULL WHERE cand_id = ?",
        ("approved", _now(), cand_id),
    )
    conn.commit()
    return ReviewResult(cand_id=cand_id, state="approved")


def reject(conn: sqlite3.Connection, cand_id: str) -> ReviewResult:
    candidate = _load_candidate(conn, cand_id)
    conn.execute(
        """
        INSERT OR IGNORE INTO suppressions(scope, subject, predicate, qualifier, object_norm, created_at)
        VALUES(?,?,?,?,?,?)
        """,
        (
            candidate.scope,
            candidate.subject,
            candidate.predicate,
            candidate.qualifier,
            candidate.object_norm,
            _now(),
        ),
    )
    conn.execute(
        "UPDATE fact_candidates SET state = ?, reviewed_at = ? WHERE cand_id = ?",
        ("rejected", _now(), cand_id),
    )
    conn.commit()
    return ReviewResult(cand_id=cand_id, state="rejected")


def interactive(
    conn: sqlite3.Connection,
    *,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> ReviewSummary:
    approved = 0
    rejected = 0
    skipped = 0
    for candidate in _pending_candidates(conn):
        output_fn(
            f"{candidate.cand_id} | {candidate.predicate}({candidate.qualifier}) | "
            f"{candidate.object_norm}"
        )
        output_fn("[a]pprove/[r]eject/[s]kip/[q]uit:")
        try:
            decision = input_fn("").strip().lower()
        except EOFError:
            break
        if decision in {"a", "approve"}:
            approve(conn, str(candidate.cand_id))
            approved += 1
        elif decision in {"r", "reject"}:
            reject(conn, str(candidate.cand_id))
            rejected += 1
        elif decision in {"q", "quit"}:
            break
        else:
            skipped += 1
    remaining = conn.execute(
        "SELECT COUNT(*) FROM fact_candidates WHERE state = 'pending'"
    ).fetchone()[0]
    return ReviewSummary(
        approved=approved,
        rejected=rejected,
        skipped=skipped,
        remaining=remaining,
    )


def _pending_candidates(conn: sqlite3.Connection) -> list[gate.FactCandidate]:
    rows = conn.execute(
        """
        SELECT * FROM fact_candidates
        WHERE state = 'pending'
        ORDER BY created_at, cand_id
        """
    ).fetchall()
    return [_candidate_from_row(row) for row in rows]


def _load_candidate(conn: sqlite3.Connection, cand_id: str) -> gate.FactCandidate:
    row = conn.execute("SELECT * FROM fact_candidates WHERE cand_id = ?", (cand_id,)).fetchone()
    if row is None:
        raise KeyError(cand_id)
    if row["state"] != "pending":
        raise ValueError(f"candidate {cand_id} is not pending")
    return _candidate_from_row(row)


def _candidate_from_row(row: sqlite3.Row) -> gate.FactCandidate:
    return gate.FactCandidate(
        cand_id=row["cand_id"],
        run_id=row["run_id"],
        scope=row["scope"],
        subject=row["subject"],
        predicate=row["predicate"],
        qualifier=row["qualifier"],
        object_norm=row["object_norm"],
        value_type=row["value_type"],
        claim=row["claim"],
        trust=row["trust"],
        sensitivity="low",
        origin=row["extractor_version"],
        evidence=json.loads(row["evidence"]),
        conflict_with=row["conflict_with"],
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
