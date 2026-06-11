"""Commit gate for deterministic fact candidates."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

AUTO_ORIGINS = {"pm_detector@1", "script_extractor@1"}
SINGLE_VALUED_PREDICATES = {
    "uses_package_manager",
    "uses_test_command",
    "uses_build_command",
    "uses_dev_command",
    "uses_lint_command",
    "uses_typecheck_command",
}


class ConflictRequiresSupersede(RuntimeError):
    def __init__(self, *, fact_id: str, object_norm: str) -> None:
        self.fact_id = fact_id
        self.object_norm = object_norm
        super().__init__(
            "conflict requires supersede: "
            f"active fact {fact_id} already has object_norm={object_norm!r}"
        )


@dataclass(frozen=True)
class FactCandidate:
    scope: str
    subject: str
    predicate: str
    qualifier: str
    object_norm: str
    value_type: str
    claim: str
    trust: int
    sensitivity: str
    origin: str
    evidence: dict[str, Any]
    cand_id: str | None = None
    run_id: str | None = None
    conflict_with: str | None = None


@dataclass(frozen=True)
class GateResult:
    auto_committed: int
    pending: int


def extract_static_facts(
    repo: Path | str, conn: sqlite3.Connection, *, commit: bool = True
) -> GateResult:
    from omni.extract import pm, scripts

    root = Path(repo).resolve()
    candidates = [*pm.detect(root), *scripts.detect(root)]
    return apply_candidates(conn, candidates, commit=commit)


def extract_observed_facts(conn: sqlite3.Connection, *, commit: bool = True) -> GateResult:
    from omni.extract import observed

    return apply_candidates(conn, observed.detect(conn), commit=commit)


def apply_candidates(
    conn: sqlite3.Connection,
    candidates: Iterable[FactCandidate],
    *,
    commit: bool = True,
) -> GateResult:
    auto_committed = 0
    pending = 0
    for candidate in candidates:
        with_id = ensure_candidate_id(candidate)
        if _active_fact_exists(conn, with_id):
            continue
        if _can_auto_commit(conn, with_id):
            auto_committed += insert_fact(conn, with_id)
        else:
            before = conn.total_changes
            stage_candidate(conn, with_id)
            if conn.total_changes > before:
                pending += 1
    if commit:
        conn.commit()
    return GateResult(auto_committed=auto_committed, pending=pending)


def stage_candidate(conn: sqlite3.Connection, candidate: FactCandidate) -> FactCandidate:
    with_id = ensure_candidate_id(candidate)
    conn.execute(
        """
        INSERT OR IGNORE INTO fact_candidates(
          cand_id, run_id, scope, subject, predicate, qualifier, object_norm,
          value_type, claim, trust, evidence, extractor_version, state,
          conflict_with, created_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            with_id.cand_id,
            with_id.run_id,
            with_id.scope,
            with_id.subject,
            with_id.predicate,
            with_id.qualifier,
            with_id.object_norm,
            with_id.value_type,
            with_id.claim,
            with_id.trust,
            json.dumps(with_id.evidence, sort_keys=True, separators=(",", ":")),
            with_id.origin,
            "pending",
            with_id.conflict_with,
            _now(),
        ),
    )
    return with_id


def insert_fact(conn: sqlite3.Connection, candidate: FactCandidate) -> int:
    with_id = ensure_candidate_id(candidate)
    if _active_fact_exists(conn, with_id):
        return 0
    conflict = _single_valued_conflict(conn, with_id)
    if conflict is not None:
        raise ConflictRequiresSupersede(
            fact_id=conflict["fact_id"],
            object_norm=conflict["object_norm"],
        )

    before = conn.total_changes
    conn.execute(
        """
        INSERT OR IGNORE INTO facts(
          fact_id, scope, subject, predicate, qualifier, object_norm, value_type,
          claim, trust, confidence, sensitivity, origin, pinned, created_seq,
          retired_seq, superseded_by, last_confirmed_at, created_at, evidence
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            _fact_id(with_id),
            with_id.scope,
            with_id.subject,
            with_id.predicate,
            with_id.qualifier,
            with_id.object_norm,
            with_id.value_type,
            with_id.claim,
            with_id.trust,
            None,
            with_id.sensitivity,
            with_id.origin,
            0,
            _next_commit_seq(conn),
            None,
            None,
            None,
            _now(),
            json.dumps(with_id.evidence, sort_keys=True, separators=(",", ":")),
        ),
    )
    return 1 if conn.total_changes > before else 0


def ensure_candidate_id(candidate: FactCandidate) -> FactCandidate:
    if candidate.cand_id:
        return candidate
    return replace(candidate, cand_id=_candidate_id(candidate))


def _can_auto_commit(conn: sqlite3.Connection, candidate: FactCandidate) -> bool:
    return (
        candidate.origin in AUTO_ORIGINS
        and candidate.trust == 2
        and candidate.sensitivity == "low"
        and not candidate.conflict_with
        and not _active_key_exists(conn, candidate)
        and not _is_suppressed(conn, candidate)
    )


def _active_fact_exists(conn: sqlite3.Connection, candidate: FactCandidate) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM facts
        WHERE scope = ? AND subject = ? AND predicate = ? AND qualifier = ?
          AND object_norm = ? AND retired_seq IS NULL
        """,
        (
            candidate.scope,
            candidate.subject,
            candidate.predicate,
            candidate.qualifier,
            candidate.object_norm,
        ),
    ).fetchone()
    return row is not None


def _active_key_exists(conn: sqlite3.Connection, candidate: FactCandidate) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM facts
        WHERE scope = ? AND subject = ? AND predicate = ? AND qualifier = ?
          AND retired_seq IS NULL
        """,
        (
            candidate.scope,
            candidate.subject,
            candidate.predicate,
            candidate.qualifier,
        ),
    ).fetchone()
    return row is not None


def _single_valued_conflict(
    conn: sqlite3.Connection, candidate: FactCandidate
) -> sqlite3.Row | None:
    if candidate.predicate not in SINGLE_VALUED_PREDICATES:
        return None
    return conn.execute(
        """
        SELECT fact_id, object_norm FROM facts
        WHERE scope = ? AND subject = ? AND predicate = ? AND qualifier = ?
          AND object_norm <> ? AND retired_seq IS NULL
        ORDER BY created_seq, fact_id
        LIMIT 1
        """,
        (
            candidate.scope,
            candidate.subject,
            candidate.predicate,
            candidate.qualifier,
            candidate.object_norm,
        ),
    ).fetchone()


def _is_suppressed(conn: sqlite3.Connection, candidate: FactCandidate) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM suppressions
        WHERE scope = ? AND subject = ? AND predicate = ? AND qualifier = ? AND object_norm = ?
        """,
        (
            candidate.scope,
            candidate.subject,
            candidate.predicate,
            candidate.qualifier,
            candidate.object_norm,
        ),
    ).fetchone()
    return row is not None


def _candidate_id(candidate: FactCandidate) -> str:
    payload = {
        "scope": candidate.scope,
        "subject": candidate.subject,
        "predicate": candidate.predicate,
        "qualifier": candidate.qualifier,
        "object_norm": candidate.object_norm,
        "origin": candidate.origin,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return f"cand_{digest[:24]}"


def _fact_id(candidate: FactCandidate) -> str:
    digest = hashlib.sha256(
        f"{candidate.scope}:{candidate.subject}:{candidate.predicate}:"
        f"{candidate.qualifier}:{candidate.object_norm}".encode("utf-8")
    ).hexdigest()
    return f"fact_{digest[:24]}"


def _next_commit_seq(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM meta WHERE key = 'commit_seq'").fetchone()
    current = int(row["value"]) if row else 0
    next_value = current + 1
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES('commit_seq', ?)",
        (str(next_value),),
    )
    return next_value


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
