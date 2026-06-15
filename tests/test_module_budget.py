"""Guard against re-growing monolithic cli/failure/verify/eval modules."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
OMNI_SRC = REPO_ROOT / "src" / "omni"

# Current sizes (688136e) plus ~10–15% headroom. Tighten when splitting further.
MODULE_LINE_BUDGETS: dict[str, int] = {
    "cli.py": 1050,
    "failure/repo.py": 550,
    "failure/command_norm.py": 150,
    "failure/meta.py": 140,
    "failure/exit_code.py": 100,
    "failure/error_lines.py": 100,
    "verify/process.py": 330,
    "verify/selection.py": 350,
    "verify/command_safety.py": 300,
    "eval/classify.py": 600,
    "eval/meta.py": 140,
    "eval/command_match.py": 150,
    "capture/claude.py": 350,
    "task.py": 550,
}

PACKAGE_SUBMODULE_MAX = 600


def _line_count(relative_path: str) -> int:
    return len((OMNI_SRC / relative_path).read_text(encoding="utf-8").splitlines())


@pytest.mark.parametrize("relative_path,max_lines", MODULE_LINE_BUDGETS.items())
def test_module_line_budget(relative_path: str, max_lines: int) -> None:
    actual = _line_count(relative_path)
    assert actual <= max_lines, (
        f"{relative_path} has {actual} lines (budget {max_lines}); "
        "split the module instead of growing it in place"
    )


@pytest.mark.parametrize(
    "package",
    ["failure", "verify", "eval"],
)
def test_package_submodules_stay_under_ceiling(package: str) -> None:
    package_dir = OMNI_SRC / package
    for path in sorted(package_dir.glob("*.py")):
        if path.name == "__init__.py":
            continue
        actual = len(path.read_text(encoding="utf-8").splitlines())
        assert actual <= PACKAGE_SUBMODULE_MAX, (
            f"{path.relative_to(OMNI_SRC)} has {actual} lines "
            f"(ceiling {PACKAGE_SUBMODULE_MAX}); add a submodule split"
        )
