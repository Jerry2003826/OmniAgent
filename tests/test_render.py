from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from omni import db
from omni import experience
from omni import gate
from omni import render


REPO_ROOT = Path(__file__).resolve().parents[1]


def run_omni(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", "omni.cli", *args],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def connect(tmp_path: Path):
    conn = db.connect(tmp_path / ".omni" / "omni.sqlite3")
    db.migrate(conn)
    return conn


def add_fact(conn, *, predicate: str, qualifier: str, object_norm: str) -> None:
    gate.insert_fact(
        conn,
        gate.FactCandidate(
            scope="project",
            subject=".",
            predicate=predicate,
            qualifier=qualifier,
            object_norm=object_norm,
            value_type="string",
            claim=f"{predicate}: {object_norm}",
            trust=2,
            sensitivity="low",
            origin="test@1",
            evidence={"files": [{"path": "package.json", "hash": "abc"}]},
        ),
    )
    conn.commit()


def add_experience_candidate(
    conn,
    *,
    exp_cand_id: str,
    run_id: str,
    kind: str,
    state: str = "pending",
    claim: str = "For validation tasks, the known verification command worked before rediscovery.",
    suggested_action: str = "Prefer the known verification command early in future validation tasks.",
) -> None:
    conn.execute(
        "INSERT INTO runs(run_id, project_id, snapshot_seq, status) VALUES(?,?,?,?)",
        (run_id, "project", 0, "closed"),
    )
    conn.execute(
        """
        INSERT INTO experience_candidates(
          exp_cand_id, run_id, outcome_id, task_type, kind, trigger, claim,
          suggested_action, evidence, state, created_at, reviewed_at, review_note
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            exp_cand_id,
            run_id,
            "outcome_render",
            "validation",
            kind,
            "validation_render",
            claim,
            suggested_action,
            json.dumps({"run_id": run_id, "candidate": exp_cand_id}, sort_keys=True),
            state,
            "2026-06-13T00:00:00+00:00",
            None,
            None,
        ),
    )
    conn.commit()


def seed_project_facts(conn) -> None:
    add_fact(conn, predicate="uses_package_manager", qualifier="node", object_norm="pnpm")
    add_fact(conn, predicate="uses_test_command", qualifier="node", object_norm="pnpm run test")
    add_fact(conn, predicate="uses_build_command", qualifier="node", object_norm="pnpm run build")


def test_render_generates_byte_stable_memory_without_internal_metadata(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    seed_project_facts(conn)

    first = render.render_project(conn, tmp_path)
    first_text = first.path.read_text(encoding="utf-8")
    second = render.render_project(conn, tmp_path)
    second_text = second.path.read_text(encoding="utf-8")

    assert first.path == tmp_path / ".omni" / "generated" / "memory.md"
    assert first_text == second_text
    assert first_text.startswith("<!-- omni:generated render_ver=1 sha256=")
    assert "# Project memory" in first_text
    assert "## Commands" in first_text
    assert "## Boundaries" in first_text
    assert "## Project" in first_text
    assert "Use pnpm run test for Node tests." in first_text
    assert "Use pnpm run build to build Node." in first_text
    assert first_text.index("Use pnpm run test") < first_text.index("Use pnpm run build")
    assert first_text.index("Use pnpm run test") < first_text.index("node package manager: pnpm")
    assert "fact_" not in first_text
    assert "confidence" not in first_text.lower()
    assert "created_at" not in first_text.lower()


def test_render_dirty_changes_only_when_visible_line_hash_changes(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    add_fact(conn, predicate="uses_test_command", qualifier="node", object_norm="pnpm run test")

    render.render_project(conn, tmp_path)
    first_hashes = [
        row["dep_line_hash"]
        for row in conn.execute("SELECT dep_line_hash FROM block_deps ORDER BY dep_line_hash")
    ]
    assert conn.execute("SELECT dirty FROM blocks WHERE block_id = 'project_memory'").fetchone()["dirty"] == 1

    conn.execute("UPDATE facts SET confidence = 0.9, evidence = ? WHERE predicate = 'uses_test_command'", ('{"files":[]}',))
    render.render_project(conn, tmp_path)
    evidence_only_hashes = [
        row["dep_line_hash"]
        for row in conn.execute("SELECT dep_line_hash FROM block_deps ORDER BY dep_line_hash")
    ]
    assert evidence_only_hashes == first_hashes
    assert conn.execute("SELECT dirty FROM blocks WHERE block_id = 'project_memory'").fetchone()["dirty"] == 0

    conn.execute("UPDATE facts SET object_norm = 'npm test' WHERE predicate = 'uses_test_command'")
    render.render_project(conn, tmp_path)
    visible_change_hashes = [
        row["dep_line_hash"]
        for row in conn.execute("SELECT dep_line_hash FROM block_deps ORDER BY dep_line_hash")
    ]
    assert visible_change_hashes != first_hashes
    assert conn.execute("SELECT dirty FROM blocks WHERE block_id = 'project_memory'").fetchone()["dirty"] == 1


def test_render_refuses_manual_edit_without_force(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    seed_project_facts(conn)
    result = render.render_project(conn, tmp_path)
    result.path.write_text(result.path.read_text(encoding="utf-8") + "\nmanual edit\n", encoding="utf-8")

    with pytest.raises(render.ManualEditError):
        render.render_project(conn, tmp_path)

    forced = render.render_project(conn, tmp_path, force=True)
    assert "manual edit" not in forced.path.read_text(encoding="utf-8")


def test_render_cli_diff_previews_without_writing_and_render_writes_file(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    seed_project_facts(conn)
    conn.close()

    diff = run_omni(tmp_path, "render", "--diff")
    assert diff.returncode == 0, diff.stderr
    assert "pnpm run test" in diff.stdout
    assert not (tmp_path / ".omni" / "generated" / "memory.md").exists()

    written = run_omni(tmp_path, "render")
    assert written.returncode == 0, written.stderr
    assert (tmp_path / ".omni" / "generated" / "memory.md").exists()


def test_render_orders_commands_by_explicit_predicate_priority(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    add_fact(conn, predicate="uses_dev_command", qualifier="node", object_norm="pnpm run dev")
    add_fact(conn, predicate="uses_typecheck_command", qualifier="node", object_norm="pnpm run typecheck")
    add_fact(conn, predicate="uses_lint_command", qualifier="node", object_norm="pnpm run lint")
    add_fact(conn, predicate="uses_build_command", qualifier="node", object_norm="pnpm run build")
    add_fact(conn, predicate="uses_test_command", qualifier="node", object_norm="pnpm run test")

    result = render.render_project(conn, tmp_path)
    text = result.path.read_text(encoding="utf-8")

    assert [
        text.index("pnpm run test"),
        text.index("pnpm run build"),
        text.index("pnpm run lint"),
        text.index("pnpm run typecheck"),
        text.index("pnpm run dev"),
    ] == sorted(
        [
            text.index("pnpm run test"),
            text.index("pnpm run build"),
            text.index("pnpm run lint"),
            text.index("pnpm run typecheck"),
            text.index("pnpm run dev"),
        ]
    )


def test_render_marks_omitted_facts_when_body_limit_is_reached(
    tmp_path: Path, monkeypatch
) -> None:
    conn = connect(tmp_path)
    monkeypatch.setattr(render, "MAX_BODY_CHARS", 220)
    for index in range(20):
        add_fact(
            conn,
            predicate=f"boundary_rule_{index:02d}",
            qualifier="default",
            object_norm=f"keep generated memory concise rule {index:02d}",
        )

    result = render.render_project(conn, tmp_path)
    text = result.path.read_text(encoding="utf-8")

    assert result.body == text
    assert "Additional facts omitted due to size limit." in text
    assert len(result.body.split("\n", 1)[1]) <= render.MAX_BODY_CHARS


def test_render_redacts_fact_values_before_writing_generated_memory(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    raw_secret = "ghp_abcdefghijklmnopqrstuvwxyz1234567890"
    add_fact(
        conn,
        predicate="boundary_rule",
        qualifier="default",
        object_norm=f"never print {raw_secret}",
    )

    result = render.render_project(conn, tmp_path)
    text = result.path.read_text(encoding="utf-8")

    assert raw_secret not in text
    assert "REDACTED:github_token:" in text
    assert "REDACTED:secret_assignment:" not in text
    assert result.body == text


def test_pending_experience_candidate_does_not_render(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    add_experience_candidate(
        conn,
        exp_cand_id="exp_cand_pending_render",
        run_id="run_pending_render",
        kind="fast_path",
        state="pending",
    )

    result = render.render_project(conn, tmp_path)
    text = result.path.read_text(encoding="utf-8")

    assert "prefer the known verification command early" not in text
    assert "run_pending_render" not in text
    assert "exp_cand_pending_render" not in text


def test_rejected_experience_candidate_does_not_render(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    add_experience_candidate(
        conn,
        exp_cand_id="exp_cand_rejected_render",
        run_id="run_rejected_render",
        kind="rediscovery_waste",
        state="rejected",
        claim="Memory context was available, but rediscovery happened.",
        suggested_action=(
            "For validation tasks, execute the known verification command before broad "
            "README/package/deployment rediscovery."
        ),
    )

    result = render.render_project(conn, tmp_path)
    text = result.path.read_text(encoding="utf-8")

    assert "before broad README/package/deployment rediscovery" not in text
    assert "run_rejected_render" not in text
    assert "exp_cand_rejected_render" not in text


def test_approved_experience_note_renders_without_internal_metadata(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    add_experience_candidate(
        conn,
        exp_cand_id="exp_cand_approved_render",
        run_id="run_approved_render",
        kind="fast_path",
    )
    approved = experience.approve_candidate(conn, "exp_cand_approved_render")

    result = render.render_project(conn, tmp_path)
    text = result.path.read_text(encoding="utf-8")

    assert "## Fast Path" in text
    assert "For validation tasks, prefer the known verification command early." in text
    assert "run_approved_render" not in text
    assert "exp_cand_approved_render" not in text
    assert approved["note_id"] not in text
    assert "evidence" not in text.lower()
    assert "created_at" not in text.lower()
    assert "updated_at" not in text.lower()
    assert "confidence" not in text.lower()


def test_approved_experience_note_render_is_byte_stable(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    add_experience_candidate(
        conn,
        exp_cand_id="exp_cand_stable_render",
        run_id="run_stable_render",
        kind="fast_path",
    )
    experience.approve_candidate(conn, "exp_cand_stable_render")

    first = render.render_project(conn, tmp_path).path.read_text(encoding="utf-8")
    second = render.render_project(conn, tmp_path).path.read_text(encoding="utf-8")

    assert first == second


def test_approved_note_still_renders_after_reject_attempt(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    add_experience_candidate(
        conn,
        exp_cand_id="exp_cand_reject_attempt_render",
        run_id="run_reject_attempt_render",
        kind="fast_path",
    )
    approved = experience.approve_candidate(conn, "exp_cand_reject_attempt_render")

    with pytest.raises(ValueError, match="approved candidate cannot be rejected in v0"):
        experience.reject_candidate(conn, "exp_cand_reject_attempt_render")

    note = conn.execute(
        """
        SELECT status
        FROM experience_notes
        WHERE note_id = ?
        """,
        (approved["note_id"],),
    ).fetchone()
    result = render.render_project(conn, tmp_path)
    text = result.path.read_text(encoding="utf-8")

    assert note["status"] == "active"
    assert experience.show_candidate(conn, "exp_cand_reject_attempt_render")["state"] == "approved"
    assert "For validation tasks, prefer the known verification command early." in text


def test_fast_path_uses_test_command_when_fact_exists(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    add_fact(conn, predicate="uses_test_command", qualifier="node", object_norm="pnpm run test")
    add_experience_candidate(
        conn,
        exp_cand_id="exp_cand_command_render",
        run_id="run_command_render",
        kind="rediscovery_waste",
        claim="Memory context was available, but rediscovery happened.",
        suggested_action=(
            "For validation tasks, execute the known verification command before broad "
            "README/package/deployment rediscovery."
        ),
    )
    experience.approve_candidate(conn, "exp_cand_command_render")

    result = render.render_project(conn, tmp_path)
    text = result.path.read_text(encoding="utf-8")

    assert (
        "For validation tasks, run `pnpm run test` before broad "
        "README/package/deployment rediscovery."
    ) in text


def test_fast_path_uses_generic_known_verification_command_without_fact(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path)
    add_experience_candidate(
        conn,
        exp_cand_id="exp_cand_generic_render",
        run_id="run_generic_render",
        kind="rediscovery_waste",
        claim="Memory context was available, but rediscovery happened.",
        suggested_action=(
            "For validation tasks, execute the known verification command before broad "
            "README/package/deployment rediscovery."
        ),
    )
    experience.approve_candidate(conn, "exp_cand_generic_render")

    result = render.render_project(conn, tmp_path)
    text = result.path.read_text(encoding="utf-8")

    assert (
        "For validation tasks, run the known verification command before broad "
        "README/package/deployment rediscovery."
    ) in text
