"""Identifier helpers for OmniMemory records."""

from __future__ import annotations

import hashlib
import subprocess
import uuid
from pathlib import Path


def new_id(prefix: str) -> str:
    safe_prefix = prefix.strip().replace("-", "_")
    if not safe_prefix or not safe_prefix.replace("_", "").isalnum():
        raise ValueError("prefix must contain only letters, digits, hyphen, or underscore")
    return f"{safe_prefix}_{uuid.uuid4().hex}"


def project_id_for_path(path: Path | str) -> str:
    base = Path(path).resolve()
    remote_id = _project_id_from_git_remote(base)
    if remote_id is not None:
        return remote_id

    project_id_path = base / ".omni" / "project_id"
    if project_id_path.exists():
        existing = project_id_path.read_text(encoding="utf-8").strip()
        if existing:
            return existing

    return ensure_project_id(base)


def ensure_project_id(path: Path | str) -> str:
    base = Path(path).resolve()
    project_id_path = base / ".omni" / "project_id"
    remote_id = _project_id_from_git_remote(base)
    project_id = remote_id
    if project_id is None and project_id_path.exists():
        project_id = project_id_path.read_text(encoding="utf-8").strip() or None
    if project_id is None:
        project_id = f"proj_{uuid.uuid4().hex[:16]}"

    project_id_path.parent.mkdir(parents=True, exist_ok=True)
    current = project_id_path.read_text(encoding="utf-8").strip() if project_id_path.exists() else ""
    if current != project_id:
        project_id_path.write_text(project_id + "\n", encoding="utf-8")
    return project_id


def _project_id_from_git_remote(path: Path) -> str | None:
    remote = _git_origin_url(path)
    if remote is None:
        return None
    digest = hashlib.sha256(remote.encode("utf-8")).hexdigest()
    return f"proj_{digest[:16]}"


def _git_origin_url(path: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "config", "--get", "remote.origin.url"],
            text=True,
            capture_output=True,
            check=False,
        )
    except (OSError, ValueError):
        return None
    if result.returncode != 0:
        return None
    remote = result.stdout.strip()
    return remote or None
