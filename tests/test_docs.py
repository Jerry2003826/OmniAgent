from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_demo_doc_covers_manual_cold_warm_g6_and_definition_of_done() -> None:
    demo = REPO_ROOT / "docs" / "demo.md"

    text = demo.read_text(encoding="utf-8")

    assert "# OmniMemory Manual Demo" in text
    for command in (
        "omni audit secrets",
        "omni init",
        "omni init --install-claude-hooks --yes",
        "omni ingest",
        "omni render --diff",
        "omni render",
        "omni inject claude --mode preview",
        "omni inject claude --mode link",
        "omni run show <run_id>",
        "omni verify",
        "omni outcome mark-from-verify <run_id> --task-type validation",
        "scripts/create_sandbox.ps1",
    ):
        assert command in text

    for phrase in (
        "Cold Run",
        "Warm Run",
        "G6 Robust Criterion",
        "Verify Bridge",
        "reason_code=start_failed",
        "SQLite read-only",
        "S12 Planted Secret Check",
        "raw planted secrets",
        "working-tree-only redaction fixtures",
        "Allowed before first correct test command",
        "Forbidden before first correct test command",
        "first matching test command equals injected command",
        "no forbidden rediscovery event occurred before it",
        "Final Definition Of Done",
        "Windows PowerShell",
    ):
        assert phrase in text

    for checklist_item in (
        "- [ ] G1",
        "- [ ] G2",
        "- [ ] G3",
        "- [ ] G4",
        "- [ ] G5",
        "- [ ] G6",
        "- [ ] G7",
        "- [ ] S12",
    ):
        assert checklist_item in text


def test_week2_sandbox_runbook_covers_required_scenarios() -> None:
    runbook = REPO_ROOT / "docs" / "week2-sandbox-runbook.md"

    text = runbook.read_text(encoding="utf-8")

    for command in (
        "pytest -q",
        "omni audit secrets",
        "git rev-parse HEAD",
        "claude --version",
        "bash scripts/create_sandbox.sh /tmp/omni-demo-sandbox",
        "omni init --install-claude-hooks --yes",
        "omni status",
        "command -v omni",
        "where omni",
        "omni ingest",
        "omni run show <run_id>",
    ):
        assert command in text

    for scenario in (
        "S1 Bash success",
        "S2 Bash failure",
        "S3 Edit / Write / Read",
        "S4 permission deny",
        "S5 PreToolUse deny if feasible",
        "S6 subagent if feasible",
        "S7 manual /compact",
        "S8 auto compact if feasible",
        "S9 resume",
        "S10 interrupt Bash",
        "S11 crash / missing SessionEnd",
        "S12 read .env",
    ):
        assert scenario in text

    for phrase in (
        "run it TWICE",
        "events_inserted=0",
        "hook events actually captured",
        "no leftover hook-*.jsonl",
        ".omni/spool/bad/ is empty",
        ".omni/spool/_errors.log is empty",
        "ingest-*.json appeared",
        "byte-identical across two renders",
        "CLAUDE_PROJECT_DIR",
        "not feasible",
        "only *.tmp orphan files are acceptable",
        "omni ingest <session_id>",
        "withheld stub",
    ):
        assert phrase in text


def test_week2_spike_report_contains_required_pending_sections() -> None:
    report = REPO_ROOT / "docs" / "week2-spike-report.md"

    text = report.read_text(encoding="utf-8")

    for heading in (
        "## 1. Environment",
        "## 2. Hook capture matrix",
        "## 3. Transcript parser matrix",
        "## 4. Bash evidence",
        "## 5. File operation evidence",
        "## 6. Permission / denial behavior",
        "## 7. Subagent behavior",
        "## 8. Compact behavior",
        "## 9. Resume behavior",
        "## 10. Crash / missing SessionEnd behavior",
        "## 11. S12 planted secret result",
        "## 12. Hook latency",
        "## 13. Cold / warm demo",
        "## 14. Go / No-Go decision",
    ):
        assert heading in text

    for phrase in (
        "PENDING HUMAN EVIDENCE",
        "KEYS ONLY",
        "unknown line ratio",
        "tool_use",
        "raw FAKE_AWS value absent",
        "raw OMNI_FAKE_SECRET absent",
        "raw fake GitHub token absent",
        "withheld stub envelope present",
        "in-process capture p50 / p95 / sample count",
        "process-level latency",
        "G6 strict pass/fail",
        "G6 robust pass/fail",
    ):
        assert phrase in text


def test_week2_go_no_go_doc_defines_gates_and_dogfood_entry() -> None:
    doc = REPO_ROOT / "docs" / "week2-go-no-go.md"

    text = doc.read_text(encoding="utf-8")

    for gate in ("G1", "G2", "G3", "G4", "G5", "G6", "G7"):
        assert f"## {gate}:" in text

    for phrase in (
        "session_id / cwd / timestamp",
        "command + exit_code + stdout/stderr",
        "safely archived with redaction",
        "omni audit secrets",
        "package manager and test/build commands",
        "first matching test command equals injected command",
        "no forbidden rediscovery event occurred before it",
        "in-process hook capture p95 < 250 ms",
        "process-level latency is sampled separately",
        "Dogfood Entry",
        "G1-G7 pass",
        "no PENDING HUMAN EVIDENCE cells in sections 2, 3, 11",
        "no raw secrets in .omni/**",
        "no uncontrolled modification outside the CLAUDE.md managed region",
    ):
        assert phrase in text


def test_experience_memory_v0_doc_covers_behavior_eval_v0() -> None:
    doc = REPO_ROOT / "docs" / "experience-memory-v0.md"

    text = doc.read_text(encoding="utf-8")

    for phrase in (
        "Behavior Eval v0",
        "omni eval run <run_id>",
        "omni eval dogfood --cold <run_id> --warm <run_id>",
        "read-only",
        "no DB writes",
        "no new tables",
        "failed_to_help",
        "unihack negative sample",
        "CLAUDE.md",
        "README.md",
        "package.json",
        "DEPLOY.md",
        "pnpm verification command",
        "heuristic",
        "not causal proof",
        "cold/warm comparison",
        "project-level facts",
        "Outcome Log v0",
        "omni outcome mark <run_id>",
        "omni outcome mark-from-verify <run_id>",
        "omni outcome show <run_id>",
        "user-marked",
        "does not infer task",
        "Verify-to-Outcome helper v0",
        "Verify Hardening v0.3",
        "omni verify --qualifier <qualifier>",
        "omni outcome mark-from-verify <run_id> --qualifier <qualifier>",
        "reason_code",
        "selection_mode",
        "selection_reason",
        "Verify Polish v0.4",
        "start_failed",
        "does not store stdout or stderr excerpts",
        "anchor for future experience and failure memory",
        "Experience Candidate v0",
        "omni experience extract <run_id>",
        "omni experience ls",
        "omni experience show <exp_cand_id>",
        "omni experience approve <exp_cand_id>",
        "omni experience reject <exp_cand_id>",
        "reviewable only",
        "Experience Notes + Renderer v0",
        "approved candidates into active experience",
        "active notes can affect future agent behavior",
        "Failure Memory v0 Pointer",
        "omni failure extract",
        "omni failure approve",
        "omni failure pattern retire",
        "Known Failures Renderer v0",
        "renders only active failure patterns",
        "Pattern Lifecycle v0",
        "pending and rejected",
        "not Soul runtime",
        "review-gated",
        "bridge from eval/outcome evidence to future memory rendering",
    ):
        assert phrase in text


def test_experience_memory_v0_doc_covers_verify_v05_hardening() -> None:
    doc = REPO_ROOT / "docs" / "experience-memory-v0.md"

    text = doc.read_text(encoding="utf-8")

    for phrase in (
        "Verify v0.5 / Outcome-from-Verify Hardening",
        "stays SQLite read-only",
        "only write bridge",
        "requires an existing `run_id`",
        "raw stdout and stderr excerpts",
        "derives `tests_status` from the stable verify `reason_code`",
        "`reason_code=passed` → `tests_status=passed`",
        "`reason_code=start_failed`",
        "automatically infer task success",
        "idempotent",
        "preserving `created_at`",
    ):
        assert phrase in text


def test_verify_v05_closeout_records_audit_and_dogfood_bridge() -> None:
    doc = REPO_ROOT / "docs" / "v05-closeout-audit-2026-06-14.md"

    text = doc.read_text(encoding="utf-8")

    for phrase in (
        "Verify v0.5 Closeout Audit - 2026-06-14",
        "outcome-from-verify hardening",
        "`omni verify` remains SQLite read-only",
        "`omni outcome mark-from-verify` remains the explicit write bridge",
        "No new tables",
        "reason_code=passed",
        "tests_status=passed",
        "reason_code=start_failed",
        "tests_status=unknown",
        "Outcome `status` is not inferred from verify",
        "Stored verify evidence excludes stdout and stderr excerpts",
        "pytest -q: 457 passed, 3 skipped",
        "5bba6758-75e8-4643-bfae-8818bb84f982",
        "status: success",
        "evidence.verify.reason_code: passed",
        "does not include stdout or stderr excerpts",
        "READY_TO_CLOSE",
    ):
        assert phrase in text

    assert "C:\\Users" not in text
    assert "Jiarui" not in text


def test_failure_memory_v0_doc_covers_candidate_only_scope() -> None:
    doc = REPO_ROOT / "docs" / "failure-memory-v0.md"

    text = doc.read_text(encoding="utf-8")

    for phrase in (
        "Failure Memory v0",
        "Failure Candidate v0",
        "omni failure extract <run_id>",
        "omni failure ls",
        "omni failure show <failure_cand_id>",
        "omni failure approve <failure_cand_id>",
        "omni failure reject <failure_cand_id>",
        "omni failure pattern ls",
        "omni failure pattern show <pattern_id>",
        "omni failure pattern retire <pattern_id>",
        "Failure Pattern v0",
        "Pattern Lifecycle v0",
        "Known Failures Renderer v0",
        "human approval step",
        "human-provided",
        "does not use an LLM",
        "does not run verification",
        "does not infer task success",
        "does not read or",
        "pending or rejected",
        "excludes pattern ids",
        "raw stderr",
        "omni render --diff",
        "Retiring an already-retired pattern is idempotent",
        "`lifecycle` summary",
        "`renders=true`",
        "`can_reactivate=false`",
        "`supersede_supported=false`",
        "v0 does not silently",
        "does not implement supersede",
        "does not use an LLM",
        "does not parse raw artifacts",
        "redacted event metadata",
        "PostToolUseFailure",
        "non-zero exit codes",
        "interrupted",
        "error_signature_hash",
        "Rejected candidates are not recreated",
        "Behavior Eval v0",
        "Outcome Log v0",
        "Experience Notes Renderer v0",
    ):
        assert phrase in text


def test_known_failure_ab_dogfood_template_covers_control_treatment_verdicts() -> None:
    doc = REPO_ROOT / "docs" / "dogfood-known-failure-ab-template.md"

    text = doc.read_text(encoding="utf-8")

    for phrase in (
        "# Known Failure A/B Dogfood Template",
        "## Context",
        "OmniMemory commit:",
        "project:",
        "failure pattern id:",
        "old failed run id:",
        "known failure memory line:",
        "## Control / cold run",
        "memory disabled or Known Failure absent:",
        "did it use old failed command:",
        "failure extract created:",
        "audit result:",
        "## Treatment / warm run",
        "Known Failure present:",
        "did it avoid old failed command:",
        "## Verdict",
        "PASS",
        "PARTIAL",
        "FAIL",
        "INCONCLUSIVE",
        "cold/control reproduces or attempts the old failed path",
        "warm/treatment avoids the old failed path",
        "warm uses the safer command family",
        "audit secrets passes",
        "created=0 is necessary but not sufficient by itself",
        "Do not claim causal proof without controlled cold/warm evidence",
    ):
        assert phrase in text


def test_dogfood_acceptance_pack_covers_real_project_loop_and_record_template() -> None:
    pack = REPO_ROOT / "docs" / "dogfood-acceptance-pack-v0.md"
    template = REPO_ROOT / "docs" / "dogfood-acceptance-record-template.md"
    stage_record = REPO_ROOT / "docs" / "dogfood-stage-acceptance-2026-06-14.md"

    pack_text = pack.read_text(encoding="utf-8")
    template_text = template.read_text(encoding="utf-8")
    stage_text = stage_record.read_text(encoding="utf-8")

    for phrase in (
        "Dogfood Acceptance Pack v0",
        "rendered memory -> Claude Code warm run -> ingest -> eval -> verify -> outcome",
        "Single runs are not causal proof",
        "omni audit secrets",
        "omni render --diff",
        "omni render",
        "omni inject claude --mode preview",
        "omni inject claude --mode link",
        "Please validate this project and tell me whether the current setup works",
        "omni ingest",
        "omni eval run <warm_run_id>",
        "omni verify",
        "omni outcome mark-from-verify <warm_run_id> --task-type validation",
        "omni eval dogfood --cold <cold_run_id> --warm <warm_run_id>",
        "PASS",
        "PARTIAL",
        "FAIL",
        "INCONCLUSIVE",
        "Do not claim universal causal proof",
        "omni failure extract <warm_run_id>",
        "omni experience extract <warm_run_id>",
        "docs/dogfood-stage-acceptance-2026-06-14.md",
    ):
        assert phrase in pack_text

    for phrase in (
        "Dogfood Acceptance Record",
        "OmniMemory commit:",
        "Target project commit:",
        "Cold or old negative run id:",
        "Warm run id:",
        "memory_effect:",
        "expected_verification_executed:",
        "first_expected_command:",
        "rediscovery_count:",
        "dogfood improvement:",
        "verify reason_code:",
        "outcome tests_status:",
        "Verdict: PASS | PARTIAL | FAIL | INCONCLUSIVE",
    ):
        assert phrase in template_text

    for phrase in (
        "Stage Dogfood Acceptance - 2026-06-14",
        "does not add a new Claude Code run",
        "<DOGFOOD_PROJECT>",
        "<PYTHON_SCRIPTS>\\omni.exe",
        "fcdefb4a-2d39-46ed-ab1e-a1cae466e861",
        "87722242-c373-4713-abe9-4288edc71982",
        "memory_effect: failed_to_help",
        "first_expected_command: pnpm run test",
        "rediscovery_count: 0",
        "improvement: true",
        "reason_code: passed",
        "tests_status: passed",
        "lifecycle.renders: true",
        "lifecycle.can_reactivate: false",
        "Verdict: PASS",
        "Fresh Follow-up Warm Run",
        "6ecbde84-e13f-4d75-97bd-3e3a7d4c2b3b",
        "4a0ab86d-d25c-4b61-9aac-a27fde35868f",
        "permission mode: bypassPermissions",
        "first_expected_command: pnpm run build",
        "observed commands: pnpm run build, pnpm run test, pnpm run lint",
        "warm_rediscovery_count: 0",
        "command_adopted: true",
        "omni verify: status=passed, reason_code=passed, command=pnpm run test",
        "Fresh follow-up verdict: PARTIAL",
        "test-first ordering is not stable",
        "Test-first Renderer Retune",
        "do not start with build or lint; first run `pnpm run test`",
        "post-test checks only",
        "After validation tests pass, use pnpm run build to build Node.",
        "7a4cfff4-ce0d-410b-997e-e0bd9485296a",
        "still chose",
        "Post-test Wording Fresh Warm Run",
        "2d6294a5d39a7ba86de6c1c622507904d3b2b67d",
        "5bba6758-75e8-4643-bfae-8818bb84f982",
        "Final fresh follow-up verdict: PASS",
        "observed commands: pnpm run test, pnpm run build, pnpm run lint",
        "failure extract: created=0",
        "experience extract: created=0",
        "not a universal proof",
    ):
        assert phrase in stage_text
    assert "C:\\Users" not in stage_text
    assert "Jiarui" not in stage_text


def test_acceptance_pack_v0_doc_covers_readonly_writer_and_semantics() -> None:
    doc = REPO_ROOT / "docs" / "acceptance-pack-v0.md"

    text = doc.read_text(encoding="utf-8")

    # Documented commands for an already-ingested run.
    for command in (
        "omni audit secrets",
        "omni status",
        "omni eval run <run_id>",
        "omni eval dogfood --cold <cold_run_id> --warm <warm_run_id>",
        "omni verify",
        "omni outcome mark-from-verify <run_id> --task-type validation",
        "omni outcome show <run_id>",
        "omni experience extract <run_id>",
        "omni failure extract <run_id>",
    ):
        assert command in text

    for phrase in (
        # read-only vs writer classification
        "Read-only vs writer commands",
        "approved writer",
        "read-only for OmniMemory state but executes",
        # dogfood comparison fields
        "cold_comparable",
        "command_adopted",
        "improvement",
        "memory_effect_summary",
        "stronger behavior metric",
        # verify/outcome bridge
        "verify->outcome write bridge",
        "`reason_code=passed` -> `tests_status=passed`",
        "`start_failed` and every selection/parse failure -> `tests_status=unknown`",
        # experience/failure extract explicit write status
        "approved writers",
        "must be run explicitly by a human",
        "reviewable candidate rows",
        # neutral memory_effect caveat
        "can remain `neutral`",
        # no causal overclaim
        "evidence packaging, not causal proof",
        # safety / redaction boundaries
        "no raw stdout/stderr or artifact payloads",
        # no new tables / features
        "No new tables, no new memory types",
    ):
        assert phrase in text

    # The runbook itself must not leak local paths or identities.
    assert "C:\\Users" not in text
    assert "Jiarui" not in text


def test_acceptance_pack_v0_closeout_records_scope_and_validation() -> None:
    doc = REPO_ROOT / "docs" / "acceptance-pack-v0-closeout-2026-06-15.md"

    text = doc.read_text(encoding="utf-8")

    for phrase in (
        "Acceptance Pack v0 Closeout",
        "Date: 2026-06-15 local",
        "Scope A (docs-only)",
        "adds no runtime code",
        "evidence packaging, not causal proof",
        "Read-only vs writer confirmation",
        "Approved writers, run explicitly by a human",
        "no automatic task success inference",
        "still 001-006",
        "No new memory types",
        "No Behavior Eval classification change",
        "pytest -q",
        "omni audit secrets",
        "git diff --check",
        "ready to close",
    ):
        assert phrase in text

    assert "C:\\Users" not in text
    assert "Jiarui" not in text


def test_minimal_linux_ci_workflow_runs_pytest_on_311_and_312() -> None:
    workflow = REPO_ROOT / ".github" / "workflows" / "ci.yml"

    text = workflow.read_text(encoding="utf-8")

    for phrase in (
        "ubuntu-latest",
        "3.11",
        "3.12",
        'pip install -e ".[dev]"',
        "pytest -q",
    ):
        assert phrase in text
