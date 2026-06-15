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


def add_failure_pattern(
    conn,
    *,
    pattern_id: str = "failure_pattern_render",
    source_failure_cand_id: str | None = "failure_cand_render",
    command_norm: str | None = "pnpm run build",
    failure_kind: str = "command_failed",
    error_signature: str = "exit 1: dependency resolution failed",
    error_signature_hash: str = "hash_failure_render",
    summary: str = "Build failed because dependency resolution failed.",
    suggested_action: str = "Inspect the existing lockfile before changing package managers.",
    status: str = "active",
    evidence: dict[str, object] | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO failure_patterns(
          pattern_id, source_failure_cand_id, scope, command_norm, failure_kind,
          error_signature, error_signature_hash, summary, suggested_action, trust,
          status, evidence, created_seq, retired_seq, superseded_by, created_at,
          updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            pattern_id,
            source_failure_cand_id,
            "project",
            command_norm,
            failure_kind,
            error_signature,
            error_signature_hash,
            summary,
            suggested_action,
            2,
            status,
            json.dumps(evidence or {"run_id": "run_hidden"}, sort_keys=True),
            1,
            None,
            None,
            "2026-06-13T00:00:00+00:00",
            "2026-06-13T00:00:00+00:00",
        ),
    )
    conn.commit()


def add_failure_candidate(
    conn,
    *,
    failure_cand_id: str,
    run_id: str,
    state: str,
    command_norm: str = "pnpm run build",
    error_signature: str = "exit 1: candidate should not render",
) -> None:
    conn.execute(
        "INSERT INTO runs(run_id, project_id, snapshot_seq, status) VALUES(?,?,?,?)",
        (run_id, "project", 0, "closed"),
    )
    conn.execute(
        """
        INSERT INTO failure_candidates(
          failure_cand_id, run_id, event_id, tool_use_id, tool, command_norm,
          exit_code, failure_kind, error_signature, error_signature_hash,
          stderr_excerpt, artifact_ref, evidence, state, created_at, reviewed_at,
          review_note, pattern_id
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            failure_cand_id,
            run_id,
            "event_should_not_render",
            "tool_should_not_render",
            "Bash",
            command_norm,
            1,
            "command_failed",
            error_signature,
            "hash_candidate_should_not_render",
            "stderr candidate should not render",
            "artifact_candidate_should_not_render",
            json.dumps({"run_id": run_id, "event_id": "event_should_not_render"}, sort_keys=True),
            state,
            "2026-06-13T00:00:00+00:00",
            None,
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
    assert "## Project" in first_text
    assert "## Boundaries" not in first_text
    assert "## Fast Path" not in first_text
    assert "## Experience Notes" not in first_text
    assert "Use pnpm run test for Node tests." in first_text
    assert "Use pnpm run build to build Node." in first_text
    assert first_text.index("Use pnpm run test") < first_text.index("Use pnpm run build")
    assert first_text.index("Use pnpm run test") < first_text.index("node package manager: pnpm")
    assert "fact_" not in first_text
    assert "confidence" not in first_text.lower()
    assert "created_at" not in first_text.lower()


def test_render_omits_empty_sections(tmp_path: Path) -> None:
    conn = connect(tmp_path)

    result = render.render_project(conn, tmp_path)
    text = result.path.read_text(encoding="utf-8")

    assert text.startswith("<!-- omni:generated render_ver=1 sha256=")
    assert "# Project memory" in text
    for section in (
        "## Fast Path",
        "## Commands",
        "## Known Failures",
        "## Experience Notes",
        "## Boundaries",
        "## Project",
    ):
        assert section not in text


def test_active_failure_patterns_render_known_failures_section(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    seed_project_facts(conn)
    add_experience_candidate(
        conn,
        exp_cand_id="exp_cand_section_order",
        run_id="run_section_order",
        kind="fast_path",
    )
    experience.approve_candidate(conn, "exp_cand_section_order")
    add_failure_pattern(
        conn,
        pattern_id="failure_pattern_hidden",
        source_failure_cand_id="failure_cand_hidden",
        command_norm="pnpm run build",
        error_signature="exit 1: dependency resolution failed",
        error_signature_hash="hash_hidden",
        summary="Tests failed because dependency resolution failed.",
        suggested_action="Inspect the lockfile before changing package managers.",
        evidence={
            "source_failure_cand_id": "failure_cand_hidden",
            "run_id": "run_hidden",
            "stderr_excerpt": "raw stderr should not render",
            "confidence": 0.99,
        },
    )

    result = render.render_project(conn, tmp_path)
    text = result.path.read_text(encoding="utf-8")

    assert "## Known Failures" in text
    assert text.index("## Fast Path") < text.index("## Commands")
    assert text.index("## Commands") < text.index("## Known Failures")
    assert "## Experience Notes" not in text
    assert (
        "- If `pnpm run build` fails with `exit 1: dependency resolution failed`: "
        "Inspect the lockfile before changing package managers."
    ) in text
    assert "Tests failed because dependency resolution failed." not in text
    assert "failure_pattern_hidden" not in text
    assert "failure_cand_hidden" not in text
    assert "run_hidden" not in text
    assert "evidence" not in text.lower()
    assert "confidence" not in text.lower()
    assert "created_at" not in text.lower()
    assert "updated_at" not in text.lower()
    assert "raw stderr should not render" not in text
    assert "hash_hidden" not in text


def test_failure_pattern_without_command_renders_generic_known_failure(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    add_failure_pattern(
        conn,
        pattern_id="failure_pattern_generic",
        source_failure_cand_id=None,
        command_norm=None,
        error_signature="exit 1: dependency resolution failed",
        error_signature_hash="hash_failure_generic",
        suggested_action="Inspect the existing lockfile before changing package managers.",
    )

    result = render.render_project(conn, tmp_path)
    text = result.path.read_text(encoding="utf-8")

    assert (
        "- If this failure recurs with `exit 1: dependency resolution failed`: "
        "Inspect the existing lockfile before changing package managers."
    ) in text


def test_failure_pattern_wording_uses_colon_and_strips_backticks(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    add_failure_pattern(
        conn,
        command_norm="`pnpm run build`",
        error_signature="`exit 1` dependency resolution failed",
        suggested_action="When Claude Code uses Bash, inspect the `lockfile` first.",
    )

    result = render.render_project(conn, tmp_path)
    text = result.path.read_text(encoding="utf-8")

    assert (
        "- If `pnpm run build` fails with `exit 1 dependency resolution failed`: "
        "When Claude Code uses Bash, inspect the lockfile first."
    ) in text
    assert ", When Claude Code" not in text


def test_failure_candidates_do_not_render_until_active_pattern_exists(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    add_failure_candidate(
        conn,
        failure_cand_id="failure_cand_pending_render",
        run_id="run_failure_pending_render",
        state="pending",
        error_signature="exit 1: pending candidate should not render",
    )
    add_failure_candidate(
        conn,
        failure_cand_id="failure_cand_rejected_render",
        run_id="run_failure_rejected_render",
        state="rejected",
        error_signature="exit 1: rejected candidate should not render",
    )

    result = render.render_project(conn, tmp_path)
    text = result.path.read_text(encoding="utf-8")

    assert "Known Failures" not in text
    assert "pending candidate should not render" not in text
    assert "rejected candidate should not render" not in text
    assert "failure_cand_pending_render" not in text
    assert "failure_cand_rejected_render" not in text


def test_non_active_failure_patterns_do_not_render(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    add_failure_pattern(
        conn,
        pattern_id="failure_pattern_retired",
        source_failure_cand_id=None,
        command_norm="pnpm run build",
        error_signature="exit 1: retired pattern should not render",
        error_signature_hash="hash_failure_retired",
        status="retired",
    )

    result = render.render_project(conn, tmp_path)
    text = result.path.read_text(encoding="utf-8")

    assert "Known Failures" not in text
    assert "retired pattern should not render" not in text


def test_active_failure_pattern_with_secret_text_renders_redacted(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    raw_secret = "ghp_abcdefghijklmnopqrstuvwxyz1234567890"
    add_failure_pattern(
        conn,
        command_norm="pnpm run build",
        error_signature=f"exit 1 {raw_secret}",
        error_signature_hash="hash_failure_secret",
        summary=f"Build failed with {raw_secret}",
        suggested_action=f"Do not print {raw_secret}",
    )

    result = render.render_project(conn, tmp_path)
    text = result.path.read_text(encoding="utf-8")

    assert raw_secret not in text
    assert "REDACTED:github_token:" in text
    assert result.body == text


def test_failure_pattern_deps_track_visible_line_hashes(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    add_failure_pattern(
        conn,
        pattern_id="failure_pattern_dep",
        source_failure_cand_id=None,
        command_norm="pnpm run build",
        error_signature="exit 1: dependency resolution failed",
        error_signature_hash="hash_failure_dep",
        suggested_action="Inspect the lockfile before changing package managers.",
        evidence={"run_id": "run_original"},
    )

    render.render_project(conn, tmp_path)
    first_dep = conn.execute(
        """
        SELECT dep_line_hash
        FROM block_deps
        WHERE dep_kind = 'failure_pattern' AND dep_id = ?
        """,
        ("failure_pattern_dep",),
    ).fetchone()
    assert first_dep is not None
    assert conn.execute("SELECT dirty FROM blocks WHERE block_id = 'project_memory'").fetchone()["dirty"] == 1

    conn.execute(
        "UPDATE failure_patterns SET evidence = ? WHERE pattern_id = ?",
        (json.dumps({"run_id": "run_changed", "raw": "different evidence"}), "failure_pattern_dep"),
    )
    render.render_project(conn, tmp_path)
    evidence_dep = conn.execute(
        """
        SELECT dep_line_hash
        FROM block_deps
        WHERE dep_kind = 'failure_pattern' AND dep_id = ?
        """,
        ("failure_pattern_dep",),
    ).fetchone()
    assert evidence_dep["dep_line_hash"] == first_dep["dep_line_hash"]
    assert conn.execute("SELECT dirty FROM blocks WHERE block_id = 'project_memory'").fetchone()["dirty"] == 0

    conn.execute(
        "UPDATE failure_patterns SET suggested_action = ? WHERE pattern_id = ?",
        ("Use the existing package manager before changing dependencies.", "failure_pattern_dep"),
    )
    render.render_project(conn, tmp_path)
    changed_dep = conn.execute(
        """
        SELECT dep_line_hash
        FROM block_deps
        WHERE dep_kind = 'failure_pattern' AND dep_id = ?
        """,
        ("failure_pattern_dep",),
    ).fetchone()
    assert changed_dep["dep_line_hash"] != first_dep["dep_line_hash"]
    assert conn.execute("SELECT dirty FROM blocks WHERE block_id = 'project_memory'").fetchone()["dirty"] == 1


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
    assert "Additional entries omitted due to size limit." in text
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
    note = conn.execute(
        "SELECT created_at, updated_at FROM experience_notes WHERE note_id = ?",
        (approved["note_id"],),
    ).fetchone()

    assert "## Fast Path" in text
    assert "For validation tasks, prefer the known verification command early." in text
    assert "run_approved_render" not in text
    assert "exp_cand_approved_render" not in text
    assert approved["note_id"] not in text
    assert "outcome_render" not in text
    assert "evidence" not in text.lower()
    assert "created_at" not in text.lower()
    assert "updated_at" not in text.lower()
    assert "confidence" not in text.lower()
    assert "2026-06-13T00:00:00+00:00" not in text
    assert note["created_at"] not in text
    assert note["updated_at"] not in text


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


def test_retired_experience_note_no_longer_renders_but_active_still_does(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path)
    add_experience_candidate(
        conn,
        exp_cand_id="exp_cand_retire_render",
        run_id="run_retire_render",
        kind="fast_path",
    )
    note_id = experience.approve_candidate(conn, "exp_cand_retire_render")["note_id"]

    active = render.render_project(conn, tmp_path).path.read_text(encoding="utf-8")
    assert "## Fast Path" in active
    assert "For validation tasks, prefer the known verification command early." in active

    retired = experience.retire_note(conn, note_id)
    assert retired["status"] == "retired"
    after = render.render_project(conn, tmp_path).path.read_text(encoding="utf-8")

    # A retired note must stop rendering, and memory.md still leaks no internals.
    assert "## Fast Path" not in after
    assert "For validation tasks, prefer the known verification command early." not in after
    assert note_id not in after
    assert "run_retire_render" not in after
    assert "exp_cand_retire_render" not in after
    assert "evidence" not in after.lower()
    assert "created_at" not in after.lower()
    assert "confidence" not in after.lower()


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

    assert text.index("## Fast Path") < text.index("## Commands")
    assert (
        "For validation tasks, the first shell command must be `pnpm run test`. "
        "Do not run build or lint before this command. Do not run broad file scans "
        "such as `Glob **`, `ls`, `find`, `tree`, or `rg --files` before this "
        "command. Do not inspect package scripts, README, deployment docs, or "
        "environment files first unless the command fails or the user explicitly "
        "asks for configuration-first exploration. After tests pass, run build and "
        "lint if broader validation is needed."
    ) in text
    assert (
        "- For validation tasks, do not start with build or lint; first run "
        "`pnpm run test`."
    ) in text
    assert text.index("first run `pnpm run test`.") < text.index("Use pnpm run test")


def test_rediscovery_waste_fast_path_blocks_broad_scans_before_command(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path)
    add_fact(conn, predicate="uses_test_command", qualifier="node", object_norm="pnpm run test")
    add_experience_candidate(
        conn,
        exp_cand_id="exp_cand_broad_scan_block",
        run_id="run_broad_scan_block",
        kind="rediscovery_waste",
        claim="Memory context was available, but rediscovery happened.",
        suggested_action=(
            "For validation tasks, execute the known verification command before broad "
            "README/package/deployment rediscovery."
        ),
    )
    experience.approve_candidate(conn, "exp_cand_broad_scan_block")

    result = render.render_project(conn, tmp_path)
    text = result.path.read_text(encoding="utf-8")

    assert "For validation tasks, the first shell command must be `pnpm run test`." in text
    assert (
        "Do not run broad file scans such as `Glob **`, `ls`, `find`, `tree`, "
        "or `rg --files` before this command."
    ) in text


def test_rediscovery_waste_fast_path_requires_test_before_build_or_lint(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path)
    add_fact(conn, predicate="uses_test_command", qualifier="node", object_norm="pnpm run test")
    add_fact(conn, predicate="uses_build_command", qualifier="node", object_norm="pnpm run build")
    add_fact(conn, predicate="uses_lint_command", qualifier="node", object_norm="pnpm run lint")
    add_experience_candidate(
        conn,
        exp_cand_id="exp_cand_test_before_build_lint",
        run_id="run_test_before_build_lint",
        kind="rediscovery_waste",
        claim="Memory context was available, but rediscovery happened.",
        suggested_action=(
            "For validation tasks, execute the known verification command before broad "
            "README/package/deployment rediscovery."
        ),
    )
    experience.approve_candidate(conn, "exp_cand_test_before_build_lint")

    result = render.render_project(conn, tmp_path)
    text = result.path.read_text(encoding="utf-8")

    assert "For validation tasks, the first shell command must be `pnpm run test`." in text
    assert "Do not run `pnpm run build` or `pnpm run lint` before `pnpm run test`." in text
    assert (
        "- For validation tasks, do not start with build or lint; first run "
        "`pnpm run test`. Treat `pnpm run build` and `pnpm run lint` as "
        "post-test checks only."
    ) in text
    assert text.index("do not start with build or lint") < text.index("Use pnpm run test")
    assert (
        "- After validation tests pass, use pnpm run build to build Node."
    ) in text
    assert "- After validation tests pass, use pnpm run lint to lint Node." in text
    assert text.index("Use pnpm run test") < text.index(
        "After validation tests pass, use pnpm run build"
    )
    assert text.index("Use pnpm run test") < text.index(
        "After validation tests pass, use pnpm run lint"
    )
    assert (
        "After tests pass, run `pnpm run build` and `pnpm run lint` "
        "if broader validation is needed."
    ) in text


def test_rediscovery_waste_fast_path_uses_active_build_lint_facts(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path)
    add_fact(conn, predicate="uses_test_command", qualifier="node", object_norm="pnpm test")
    add_fact(conn, predicate="uses_build_command", qualifier="node", object_norm="pnpm run build:ci")
    add_fact(conn, predicate="uses_lint_command", qualifier="node", object_norm="pnpm run lint:ci")
    add_experience_candidate(
        conn,
        exp_cand_id="exp_cand_custom_build_lint",
        run_id="run_custom_build_lint",
        kind="rediscovery_waste",
        claim="Memory context was available, but rediscovery happened.",
        suggested_action=(
            "For validation tasks, execute the known verification command before broad "
            "README/package/deployment rediscovery."
        ),
    )
    experience.approve_candidate(conn, "exp_cand_custom_build_lint")

    result = render.render_project(conn, tmp_path)
    text = result.path.read_text(encoding="utf-8")

    assert "Do not run `pnpm run build:ci` or `pnpm run lint:ci` before `pnpm test`." in text
    assert (
        "- For validation tasks, do not start with build or lint; first run "
        "`pnpm test`. Treat `pnpm run build:ci` and `pnpm run lint:ci` as "
        "post-test checks only."
    ) in text
    assert (
        "- After validation tests pass, use pnpm run build:ci to build Node."
    ) in text
    assert "- After validation tests pass, use pnpm run lint:ci to lint Node." in text
    assert (
        "After tests pass, run `pnpm run build:ci` and `pnpm run lint:ci` "
        "if broader validation is needed."
    ) in text
    assert "Do not run `pnpm run build` or `pnpm run lint` before `pnpm test`." not in text


def test_rediscovery_waste_fast_path_uses_single_post_test_fact_in_followup(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path)
    add_fact(conn, predicate="uses_test_command", qualifier="node", object_norm="pnpm test")
    add_fact(conn, predicate="uses_build_command", qualifier="node", object_norm="pnpm run build:ci")
    add_experience_candidate(
        conn,
        exp_cand_id="exp_cand_single_post_test",
        run_id="run_single_post_test",
        kind="rediscovery_waste",
        claim="Memory context was available, but rediscovery happened.",
        suggested_action=(
            "For validation tasks, execute the known verification command before broad "
            "README/package/deployment rediscovery."
        ),
    )
    experience.approve_candidate(conn, "exp_cand_single_post_test")

    result = render.render_project(conn, tmp_path)
    text = result.path.read_text(encoding="utf-8")

    assert (
        "Do not run `pnpm run build:ci` or any other build/lint command "
        "before `pnpm test`."
    ) in text
    assert "- After validation tests pass, use pnpm run build:ci to build Node." in text
    assert "After tests pass, run `pnpm run build:ci` if broader validation is needed." in text
    assert "After tests pass, run build and lint if broader validation is needed." not in text


def test_rediscovery_waste_fast_path_blocks_build_when_only_lint_fact_exists(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path)
    add_fact(conn, predicate="uses_test_command", qualifier="node", object_norm="pnpm test")
    add_fact(conn, predicate="uses_lint_command", qualifier="node", object_norm="pnpm run lint:ci")
    add_experience_candidate(
        conn,
        exp_cand_id="exp_cand_single_lint_post_test",
        run_id="run_single_lint_post_test",
        kind="rediscovery_waste",
        claim="Memory context was available, but rediscovery happened.",
        suggested_action=(
            "For validation tasks, execute the known verification command before broad "
            "README/package/deployment rediscovery."
        ),
    )
    experience.approve_candidate(conn, "exp_cand_single_lint_post_test")

    result = render.render_project(conn, tmp_path)
    text = result.path.read_text(encoding="utf-8")

    assert (
        "Do not run `pnpm run lint:ci` or any other build/lint command "
        "before `pnpm test`."
    ) in text
    assert "- After validation tests pass, use pnpm run lint:ci to lint Node." in text
    assert "After tests pass, run `pnpm run lint:ci` if broader validation is needed." in text


def test_rediscovery_waste_fast_path_uses_generic_build_lint_for_non_pnpm_command(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path)
    add_fact(conn, predicate="uses_test_command", qualifier="python", object_norm="pytest -q")
    add_experience_candidate(
        conn,
        exp_cand_id="exp_cand_python_test_first",
        run_id="run_python_test_first",
        kind="rediscovery_waste",
        claim="Memory context was available, but rediscovery happened.",
        suggested_action=(
            "For validation tasks, execute the known verification command before broad "
            "README/package/deployment rediscovery."
        ),
    )
    experience.approve_candidate(conn, "exp_cand_python_test_first")

    result = render.render_project(conn, tmp_path)
    text = result.path.read_text(encoding="utf-8")

    assert "For validation tasks, the first shell command must be `pytest -q`." in text
    assert "Do not run build or lint before this command." in text
    assert "`pnpm run build`" not in text
    assert "`pnpm run lint`" not in text


def test_same_kind_notes_from_multiple_runs_render_one_guidance_line(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path)
    for suffix in ("a", "b"):
        add_experience_candidate(
            conn,
            exp_cand_id=f"exp_cand_dup_{suffix}",
            run_id=f"run_dup_{suffix}",
            kind="rediscovery_waste",
            claim="Memory context was available, but rediscovery happened.",
            suggested_action=(
                "For validation tasks, execute the known verification command before broad "
                "README/package/deployment rediscovery."
            ),
        )
        experience.approve_candidate(conn, f"exp_cand_dup_{suffix}")

    result = render.render_project(conn, tmp_path)
    text = result.path.read_text(encoding="utf-8")
    bullet_lines = [line for line in text.splitlines() if line.startswith("- ")]

    assert (
        text.count(
            "- For validation tasks, the first shell command must be the known "
            "verification command. Do not run build, lint, broad file scans such as "
            "`Glob **`, `ls`, `find`, `tree`, or `rg --files` before trying it. Do "
            "not inspect package scripts, README, deployment docs, or environment "
            "files first unless it fails or the user explicitly asks for "
            "configuration-first exploration. After tests pass, run build and lint "
            "if broader validation is needed."
        )
        == 1
    )
    assert len(bullet_lines) == len(set(bullet_lines))


def test_fast_path_and_rediscovery_waste_notes_render_distinct_lines(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path)
    add_experience_candidate(
        conn,
        exp_cand_id="exp_cand_mix_waste",
        run_id="run_mix_waste",
        kind="rediscovery_waste",
        claim="Memory context was available, but rediscovery happened.",
        suggested_action=(
            "For validation tasks, execute the known verification command before broad "
            "README/package/deployment rediscovery."
        ),
    )
    add_experience_candidate(
        conn,
        exp_cand_id="exp_cand_mix_fast",
        run_id="run_mix_fast",
        kind="fast_path",
    )
    experience.approve_candidate(conn, "exp_cand_mix_waste")
    experience.approve_candidate(conn, "exp_cand_mix_fast")

    result = render.render_project(conn, tmp_path)
    text = result.path.read_text(encoding="utf-8")

    assert (
        text.count("- For validation tasks, prefer the known verification command early.")
        == 1
    )
    assert (
        text.count(
            "- For validation tasks, the first shell command must be the known "
            "verification command. Do not run build, lint, broad file scans such as "
            "`Glob **`, `ls`, `find`, `tree`, or `rg --files` before trying it. Do "
            "not inspect package scripts, README, deployment docs, or environment "
            "files first unless it fails or the user explicitly asks for "
            "configuration-first exploration. After tests pass, run build and lint "
            "if broader validation is needed."
        )
        == 1
    )


def test_fast_path_uses_generic_wording_with_multiple_distinct_test_commands(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path)
    add_fact(conn, predicate="uses_test_command", qualifier="node", object_norm="pnpm run test")
    add_fact(conn, predicate="uses_test_command", qualifier="python", object_norm="pytest -q")
    add_experience_candidate(
        conn,
        exp_cand_id="exp_cand_multi_test",
        run_id="run_multi_test",
        kind="rediscovery_waste",
        claim="Memory context was available, but rediscovery happened.",
        suggested_action=(
            "For validation tasks, execute the known verification command before broad "
            "README/package/deployment rediscovery."
        ),
    )
    experience.approve_candidate(conn, "exp_cand_multi_test")

    result = render.render_project(conn, tmp_path)
    text = result.path.read_text(encoding="utf-8")

    assert (
        "For validation tasks, the first shell command must be the known verification "
        "command. Do not run build, lint, broad file scans such as `Glob **`, `ls`, "
        "`find`, `tree`, or `rg --files` before trying it. Do not inspect package "
        "scripts, README, deployment docs, or environment files first unless it fails "
        "or the user explicitly asks for configuration-first exploration. After tests "
        "pass, run build and lint if broader validation is needed."
    ) in text
    assert "- For validation tasks, the first shell command must be `pnpm run test`." not in text
    assert "- For validation tasks, the first shell command must be `pytest -q`." not in text


def test_fast_path_prefers_base_qualifier_when_node_test_commands_are_scoped(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path)
    add_fact(conn, predicate="uses_test_command", qualifier="node", object_norm="pnpm run test")
    add_fact(
        conn,
        predicate="uses_test_command",
        qualifier="node:e2e",
        object_norm="pnpm run test:e2e",
    )
    add_fact(
        conn,
        predicate="uses_test_command",
        qualifier="node:unit",
        object_norm="pnpm run test:unit",
    )
    add_experience_candidate(
        conn,
        exp_cand_id="exp_cand_scoped_node_test",
        run_id="run_scoped_node_test",
        kind="rediscovery_waste",
        claim="Memory context was available, but rediscovery happened.",
        suggested_action=(
            "For validation tasks, execute the known verification command before broad "
            "README/package/deployment rediscovery."
        ),
    )
    experience.approve_candidate(conn, "exp_cand_scoped_node_test")

    result = render.render_project(conn, tmp_path)
    text = result.path.read_text(encoding="utf-8")

    assert (
        "For validation tasks, the first shell command must be `pnpm run test`. "
        "Do not run build or lint before this command. Do not run broad file scans "
        "such as `Glob **`, `ls`, `find`, `tree`, or `rg --files` before this "
        "command. Do not inspect package scripts, README, deployment docs, or "
        "environment files first unless the command fails or the user explicitly "
        "asks for configuration-first exploration. After tests pass, run build and "
        "lint if broader validation is needed."
    ) in text


def test_fast_path_substitutes_when_duplicate_test_command_facts_agree(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path)
    add_fact(conn, predicate="uses_test_command", qualifier="node", object_norm="pnpm run test")
    add_fact(
        conn, predicate="uses_test_command", qualifier="node:web", object_norm="pnpm run test"
    )
    add_experience_candidate(
        conn,
        exp_cand_id="exp_cand_agree_test",
        run_id="run_agree_test",
        kind="fast_path",
    )
    experience.approve_candidate(conn, "exp_cand_agree_test")

    result = render.render_project(conn, tmp_path)
    text = result.path.read_text(encoding="utf-8")

    assert "- For validation tasks, prefer running `pnpm run test` early." in text


def test_active_note_with_secret_text_renders_redacted(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    raw_secret = "ghp_abcdefghijklmnopqrstuvwxyz1234567890"
    conn.execute(
        """
        INSERT INTO experience_notes(
          note_id, source_cand_id, scope, task_type, kind, trigger,
          body, suggested_action, trust, status, evidence, created_seq,
          retired_seq, superseded_by, created_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "note_secret_render",
            None,
            "project",
            "docs",
            "project_workflow",
            None,
            f"never print {raw_secret}",
            f"never print {raw_secret}",
            2,
            "active",
            "{}",
            1,
            None,
            None,
            "2026-06-13T00:00:00+00:00",
            "2026-06-13T00:00:00+00:00",
        ),
    )
    conn.commit()

    result = render.render_project(conn, tmp_path)
    text = result.path.read_text(encoding="utf-8")

    assert raw_secret not in text
    assert "REDACTED:github_token:" in text
    assert result.body == text


def test_note_fallback_collapses_embedded_newlines(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    conn.execute(
        """
        INSERT INTO experience_notes(
          note_id, source_cand_id, scope, task_type, kind, trigger,
          body, suggested_action, trust, status, evidence, created_seq,
          retired_seq, superseded_by, created_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "note_multiline",
            None,
            "project",
            "docs",
            "project_workflow",
            None,
            "body text",
            "line one\n## Injected\nline two",
            2,
            "active",
            "{}",
            1,
            None,
            None,
            "2026-06-13T00:00:00+00:00",
            "2026-06-13T00:00:00+00:00",
        ),
    )
    conn.commit()

    result = render.render_project(conn, tmp_path)
    text = result.path.read_text(encoding="utf-8")

    assert "- line one ## Injected line two" in text
    assert "\n## Injected" not in text


def test_render_writes_memory_through_temp_file_replace(
    tmp_path: Path, monkeypatch
) -> None:
    conn = connect(tmp_path)
    seed_project_facts(conn)
    original_write_text = Path.write_text

    def fail_direct_memory_write(self: Path, data, *args, **kwargs):
        if self.name == "memory.md" and "generated" in self.parts:
            raise AssertionError("memory.md content must be replaced from a temp file")
        return original_write_text(self, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_direct_memory_write)

    result = render.render_project(conn, tmp_path)
    text = result.path.read_text(encoding="utf-8")

    assert result.wrote
    assert text.startswith("<!-- omni:generated render_ver=1 sha256=")
    assert not list(result.path.parent.glob("*.omni-tmp"))


def test_render_corrupt_generated_memory_raises_manual_edit_error(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    seed_project_facts(conn)
    result = render.render_project(conn, tmp_path)
    result.path.write_bytes(b"\xff\xfe broken \x00 bytes")

    with pytest.raises(render.ManualEditError):
        render.render_project(conn, tmp_path)

    forced = render.render_project(conn, tmp_path, force=True)
    text = forced.path.read_text(encoding="utf-8")
    assert text.startswith("<!-- omni:generated render_ver=1 sha256=")
    assert "Use pnpm run test for Node tests." in text


def test_render_truncation_does_not_promote_lower_priority_lines(
    tmp_path: Path, monkeypatch
) -> None:
    conn = connect(tmp_path)
    monkeypatch.setattr(render, "MAX_BODY_CHARS", 220)
    add_experience_candidate(
        conn,
        exp_cand_id="exp_cand_trunc_priority",
        run_id="run_trunc_priority",
        kind="fast_path",
    )
    experience.approve_candidate(conn, "exp_cand_trunc_priority")
    add_fact(
        conn,
        predicate="boundary_rule",
        qualifier="default",
        object_norm="x" * 160,
    )

    result = render.render_project(conn, tmp_path)
    text = result.path.read_text(encoding="utf-8")

    assert "prefer the known verification command early" in text
    assert "Additional entries omitted due to size limit." in text
    # Fast Path is the highest-priority section; a lower-priority boundary line
    # must not take its place.
    assert "boundary rule: x" not in text


def test_render_cli_includes_approved_experience_note(tmp_path: Path) -> None:
    conn = connect(tmp_path)
    add_experience_candidate(
        conn,
        exp_cand_id="exp_cand_cli_note",
        run_id="run_cli_note",
        kind="fast_path",
    )
    conn.close()

    approve = run_omni(tmp_path, "experience", "approve", "exp_cand_cli_note")
    written = run_omni(tmp_path, "render")
    text = (tmp_path / ".omni" / "generated" / "memory.md").read_text(encoding="utf-8")

    assert approve.returncode == 0, approve.stderr
    assert written.returncode == 0, written.stderr
    assert "For validation tasks, prefer the known verification command early." in text


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
        "For validation tasks, the first shell command must be the known verification "
        "command. Do not run build, lint, broad file scans such as `Glob **`, `ls`, "
        "`find`, `tree`, or `rg --files` before trying it. Do not inspect package "
        "scripts, README, deployment docs, or environment files first unless it fails "
        "or the user explicitly asks for configuration-first exploration. After tests "
        "pass, run build and lint if broader validation is needed."
    ) in text


def _render_body_items(body: str) -> list[str]:
    # Memory lines are bullet-formatted today; adjust if non-bullet lines are added.
    return [
        line
        for line in body.splitlines()
        if line.startswith("- ") and line != render.TRUNCATION_NOTICE
    ]


def _read_view_items(view: dict[str, object]) -> list[str]:
    items: list[str] = []
    for section in view["sections"]:
        for item in section["items"]:
            if item != render.TRUNCATION_NOTICE:
                items.append(str(item))
    return items


def test_render_and_read_view_truncate_at_same_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = connect(tmp_path)
    monkeypatch.setattr(render, "MAX_BODY_CHARS", 220)
    for index in range(15):
        add_fact(
            conn,
            predicate=f"boundary_rule_{index:02d}",
            qualifier="default",
            object_norm=f"keep generated memory concise rule {index:02d}",
        )

    result = render.render_project(conn, tmp_path)
    view = render.read_view(conn)

    render_items = _render_body_items(result.body)
    read_items = _read_view_items(view)
    assert render_items == read_items
    assert (render.TRUNCATION_NOTICE in result.body) == any(
        render.TRUNCATION_NOTICE in section["items"]
        for section in view["sections"]
    )


def test_render_and_read_view_align_across_section_priorities(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = connect(tmp_path)
    monkeypatch.setattr(render, "MAX_BODY_CHARS", 220)
    add_experience_candidate(
        conn,
        exp_cand_id="exp_cand_align_priority",
        run_id="run_align_priority",
        kind="fast_path",
    )
    experience.approve_candidate(conn, "exp_cand_align_priority")
    add_fact(
        conn,
        predicate="boundary_rule",
        qualifier="default",
        object_norm="x" * 160,
    )

    result = render.render_project(conn, tmp_path)
    view = render.read_view(conn)

    assert "prefer the known verification command early" in result.body
    assert "boundary rule: x" not in result.body
    assert _render_body_items(result.body) == _read_view_items(view)
    assert (render.TRUNCATION_NOTICE in result.body) == any(
        render.TRUNCATION_NOTICE in section["items"]
        for section in view["sections"]
    )


def test_render_and_read_view_agree_when_truncation_notice_does_not_fit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = connect(tmp_path)
    monkeypatch.setattr(render, "MAX_BODY_CHARS", 55)
    add_fact(
        conn,
        predicate="boundary_rule",
        qualifier="default",
        object_norm="keep generated memory concise rule 00",
    )

    result = render.render_project(conn, tmp_path)
    view = render.read_view(conn)

    assert render.TRUNCATION_NOTICE not in result.body
    assert not any(
        render.TRUNCATION_NOTICE in section["items"] for section in view["sections"]
    )
    assert _render_body_items(result.body) == _read_view_items(view)


def test_render_and_read_view_agree_when_only_truncation_notice_remains(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = connect(tmp_path)
    monkeypatch.setattr(render, "MAX_BODY_CHARS", 65)
    add_fact(
        conn,
        predicate="boundary_rule",
        qualifier="default",
        object_norm="keep generated memory concise rule 00",
    )

    result = render.render_project(conn, tmp_path)
    view = render.read_view(conn)

    assert render.TRUNCATION_NOTICE in result.body
    assert any(
        render.TRUNCATION_NOTICE in section["items"] for section in view["sections"]
    )
    assert _render_body_items(result.body) == _read_view_items(view)


def test_read_view_truncation_stays_leak_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.leak_helpers import assert_no_metadata_leak

    conn = connect(tmp_path)
    monkeypatch.setattr(render, "MAX_BODY_CHARS", 220)
    for index in range(15):
        add_fact(
            conn,
            predicate=f"boundary_rule_{index:02d}",
            qualifier="default",
            object_norm=f"keep generated memory concise rule {index:02d}",
        )

    view = render.read_view(conn)
    assert view["schema_version"] == render.READ_VIEW_SCHEMA_VERSION
    assert_no_metadata_leak(view)
