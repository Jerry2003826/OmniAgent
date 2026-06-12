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
