"""User-level project registry for multi-project read-only overview."""

from __future__ import annotations

import json
from pathlib import Path

from omni.status import status_json

REGISTRY_DIRNAME = ".omni"
REGISTRY_FILENAME = "projects.json"


def registry_path() -> Path:
    return Path.home() / REGISTRY_DIRNAME / REGISTRY_FILENAME


def load_paths() -> list[Path]:
    path = registry_path()
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict):
        return []
    raw = payload.get("projects")
    if not isinstance(raw, list):
        return []
    paths: list[Path] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            continue
        resolved = str(Path(item).expanduser().resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        paths.append(Path(resolved))
    return paths


def save_paths(paths: list[Path]) -> None:
    registry = registry_path()
    registry.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "projects": [str(path.resolve()) for path in paths],
    }
    registry.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def register(path: Path | str) -> dict[str, object]:
    resolved = Path(path).expanduser().resolve()
    paths = load_paths()
    if resolved not in paths:
        paths.append(resolved)
        save_paths(paths)
    return {"registered": str(resolved), "count": len(paths)}


def list_registered() -> dict[str, object]:
    paths = load_paths()
    return {
        "count": len(paths),
        "projects": [str(path) for path in paths],
    }


def status_all() -> dict[str, object]:
    projects: list[dict[str, object]] = []
    for path in load_paths():
        entry = json.loads(status_json(path))
        entry["root"] = str(path)
        projects.append(entry)
    return {"count": len(projects), "projects": projects}


def as_json(value: dict[str, object]) -> str:
    return json.dumps(value, sort_keys=True) + "\n"
