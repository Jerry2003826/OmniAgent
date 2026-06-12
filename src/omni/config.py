"""Project-local OmniMemory configuration and layout helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from omni.ids import ensure_project_id

OMNI_DIRNAME = ".omni"
CONFIG_FILENAME = "config.toml"
OMNI_GITIGNORE_ENTRIES = (".omni/",)
CLAUDE_HOOK_GITIGNORE_ENTRIES = (
    ".claude/settings.local.json",
    ".claude/*.omni-tmp",
    ".claude/settings.json.omni-bak",
)
GITIGNORE_ENTRIES = OMNI_GITIGNORE_ENTRIES + CLAUDE_HOOK_GITIGNORE_ENTRIES

OMNI_SUBDIRS = (
    "spool",
    "spike",
    "artifacts",
    "generated",
)

DEFAULT_CONFIG = """# OmniMemory project-local configuration.
version = 1
"""


@dataclass(frozen=True)
class InitResult:
    root: Path
    omni_dir: Path
    created: tuple[Path, ...]
    gitignore_updated: bool


def project_root(cwd: Path | str | None = None) -> Path:
    start = Path(cwd or Path.cwd()).resolve()
    for candidate in (start, *start.parents):
        if (candidate / OMNI_DIRNAME).is_dir() or (candidate / ".git").exists():
            return candidate
    return start


def ensure_project_layout(root: Path | str | None = None) -> InitResult:
    base = project_root(root)
    omni_dir = base / OMNI_DIRNAME
    created: list[Path] = []

    for path in (omni_dir, *(omni_dir / name for name in OMNI_SUBDIRS)):
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            created.append(path)

    config_path = omni_dir / CONFIG_FILENAME
    if not config_path.exists():
        config_path.write_text(DEFAULT_CONFIG, encoding="utf-8")
        created.append(config_path)

    project_id_path = omni_dir / "project_id"
    project_id_exists = project_id_path.exists()
    ensure_project_id(base)
    if not project_id_exists:
        created.append(project_id_path)

    return InitResult(
        root=base,
        omni_dir=omni_dir,
        created=tuple(created),
        gitignore_updated=False,
    )


def ensure_gitignore_entry(root: Path, entries: tuple[str, ...] = GITIGNORE_ENTRIES) -> bool:
    gitignore = root / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    lines = existing.splitlines()
    missing = [entry for entry in entries if not _has_gitignore_entry(lines, entry)]

    if not missing:
        return False

    prefix = "" if not existing or existing.endswith(("\n", "\r\n")) else "\n"
    gitignore.write_text(f"{existing}{prefix}{chr(10).join(missing)}\n", encoding="utf-8")
    return True


def _has_gitignore_entry(lines: list[str], entry: str) -> bool:
    directory = entry.rstrip("/")
    accepted = {entry, directory, f"/{entry}", f"/{directory}"}
    return any(line.strip() in accepted for line in lines)
