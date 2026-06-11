"""Secret audit gate."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from omni.config import ensure_project_layout
from omni.redact import redact, redact_path


@dataclass(frozen=True)
class AuditResult:
    ok: bool
    positive_failures: list[Path]
    negative_failures: list[Path]
    omni_leaks: list[Path]

    def as_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "positive_failures": [str(path) for path in self.positive_failures],
            "negative_failures": [str(path) for path in self.negative_failures],
            "omni_leaks": [str(path) for path in self.omni_leaks],
        }


def audit_secrets(root: Path | str, fixtures_root: Path | str | None = None) -> AuditResult:
    base = Path(root).resolve()
    fixture_base = Path(fixtures_root) if fixtures_root else _default_fixtures_root()
    allow_values = _load_allow_values(base)

    positive_failures = _positive_failures(fixture_base, allow_values)
    negative_failures = _negative_failures(fixture_base, allow_values)
    omni_leaks = _omni_leaks(base, allow_values)
    ok = not positive_failures and not negative_failures and not omni_leaks
    result = AuditResult(
        ok=ok,
        positive_failures=positive_failures,
        negative_failures=negative_failures,
        omni_leaks=omni_leaks,
    )
    if ok:
        marker = base / ".omni" / "audit" / "secrets.passed"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("ok\n", encoding="utf-8")
    return result


def run_audit_cli(root: Path | str, fixtures_root: Path | str | None = None) -> tuple[int, str]:
    ensure_project_layout(root)
    result = audit_secrets(root, fixtures_root=fixtures_root)
    body = json.dumps(result.as_dict(), sort_keys=True, indent=2) + "\n"
    return (0 if result.ok else 1), body


def _default_fixtures_root() -> Path:
    return Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "redaction"


def _positive_failures(fixtures_root: Path, allow_values: set[str]) -> list[Path]:
    failures: list[Path] = []
    for path in sorted((fixtures_root / "positives").glob("*")):
        if not path.is_file():
            continue
        result = redact(path.read_bytes(), allow_values=allow_values)
        if result.status == "clean":
            failures.append(path)
    return failures


def _negative_failures(fixtures_root: Path, allow_values: set[str]) -> list[Path]:
    failures: list[Path] = []
    for path in sorted((fixtures_root / "negatives").glob("*")):
        if not path.is_file():
            continue
        result = redact(path.read_bytes(), allow_values=allow_values)
        if result.status != "clean":
            failures.append(path)
    return failures


def _omni_leaks(root: Path, allow_values: set[str]) -> list[Path]:
    omni_dir = root / ".omni"
    if not omni_dir.exists():
        return []

    leaks: list[Path] = []
    for path in sorted(omni_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.relative_to(omni_dir) == Path("audit") / "secrets.passed":
            continue
        result = redact_path(path, allow_values=allow_values)
        if result.status != "clean":
            leaks.append(path)
    return leaks


def _load_allow_values(root: Path) -> set[str]:
    path = root / ".omni" / "redaction-allow.txt"
    if not path.exists():
        return set()
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
