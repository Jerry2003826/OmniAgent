from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_demo_doc_covers_manual_cold_warm_g6_and_definition_of_done() -> None:
    demo = REPO_ROOT / "docs" / "demo.md"

    text = demo.read_text(encoding="utf-8")

    assert "# OmniMemory Manual Demo" in text
    for command in (
        "omni audit secrets",
        "omni ingest",
        "omni render --diff",
        "omni render",
        "omni inject claude --mode preview",
        "omni inject claude --mode link",
        "omni run show <run_id>",
    ):
        assert command in text

    for phrase in (
        "Cold Run",
        "Warm Run",
        "G6 Robust Criterion",
        "Allowed before first correct test command",
        "Forbidden before first correct test command",
        "first matching test command equals injected command",
        "no forbidden rediscovery event occurred before it",
        "Final Definition Of Done",
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
    ):
        assert checklist_item in text
