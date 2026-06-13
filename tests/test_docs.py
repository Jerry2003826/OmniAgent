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
        "scripts/create_sandbox.ps1",
    ):
        assert command in text

    for phrase in (
        "Cold Run",
        "Warm Run",
        "G6 Robust Criterion",
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
        "omni outcome show <run_id>",
        "user-marked",
        "does not infer task",
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
        "approved failure-pattern rendering comes later",
        "not Soul runtime",
        "review-gated",
        "bridge from eval/outcome evidence to future memory rendering",
    ):
        assert phrase in text


def test_failure_memory_v0_doc_covers_candidate_only_scope() -> None:
    doc = REPO_ROOT / "docs" / "failure-memory-v0.md"

    text = doc.read_text(encoding="utf-8")

    for phrase in (
        "Failure Memory v0",
        "Failure Candidate v0",
        "omni failure extract <run_id>",
        "omni failure ls",
        "omni failure show <failure_cand_id>",
        "omni failure reject <failure_cand_id>",
        "no approval flow",
        "does not create approved failure patterns",
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
