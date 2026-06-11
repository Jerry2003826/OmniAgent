from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from omni import inject


REPO_ROOT = Path(__file__).resolve().parents[1]
MANAGED_REGION = """<!-- omni:begin -->
@.omni/generated/memory.md
<!-- omni:end -->
"""


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


def test_preview_mode_prints_managed_region_without_writing(tmp_path: Path) -> None:
    result = inject.inject_claude(tmp_path, mode="preview")

    assert result.body == MANAGED_REGION
    assert result.wrote is False
    assert not (tmp_path / "CLAUDE.md").exists()


def test_link_mode_writes_managed_region_and_preserves_user_content(tmp_path: Path) -> None:
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text("# Project notes\n\nKeep this.\n", encoding="utf-8")

    result = inject.inject_claude(tmp_path, mode="link")
    second = inject.inject_claude(tmp_path, mode="link")
    text = claude_md.read_text(encoding="utf-8")

    assert result.wrote is True
    assert second.wrote is False
    assert text.startswith("# Project notes")
    assert "Keep this." in text
    assert MANAGED_REGION in text
    assert text.count("<!-- omni:begin -->") == 1
    assert text.count("<!-- omni:end -->") == 1


def test_link_refuses_to_overwrite_manually_changed_managed_region(tmp_path: Path) -> None:
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text(
        "# Project notes\n\n<!-- omni:begin -->\nmanual edit\n<!-- omni:end -->\n",
        encoding="utf-8",
    )

    with pytest.raises(inject.ManagedRegionEditedError) as raised:
        inject.inject_claude(tmp_path, mode="link")

    assert "manual edit" in raised.value.diff
    assert claude_md.read_text(encoding="utf-8").count("manual edit") == 1


def test_link_accepts_managed_region_at_eof_without_trailing_newline(
    tmp_path: Path,
) -> None:
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text(MANAGED_REGION.rstrip("\n"), encoding="utf-8")

    result = inject.inject_claude(tmp_path, mode="link")

    assert result.wrote is False
    assert claude_md.read_text(encoding="utf-8") == MANAGED_REGION.rstrip("\n")


def test_inject_cli_preview_and_link_modes(tmp_path: Path) -> None:
    preview = run_omni(tmp_path, "inject", "claude", "--mode", "preview")
    link = run_omni(tmp_path, "inject", "claude", "--mode", "link")

    assert preview.returncode == 0, preview.stderr
    assert preview.stdout == MANAGED_REGION
    assert link.returncode == 0, link.stderr
    assert (tmp_path / "CLAUDE.md").read_text(encoding="utf-8") == MANAGED_REGION
