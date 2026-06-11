"""Managed prompt-file injection helpers."""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path

BEGIN = "<!-- omni:begin -->"
END = "<!-- omni:end -->"
MANAGED_REGION = f"{BEGIN}\n@.omni/generated/memory.md\n{END}\n"


@dataclass(frozen=True)
class InjectResult:
    path: Path
    body: str
    diff: str
    wrote: bool


class ManagedRegionEditedError(RuntimeError):
    def __init__(self, diff: str) -> None:
        super().__init__("CLAUDE.md managed region was edited; refusing overwrite")
        self.diff = diff


def inject_claude(root: Path | str, *, mode: str) -> InjectResult:
    base = Path(root).resolve()
    path = base / "CLAUDE.md"

    if mode == "preview":
        return InjectResult(path=path, body=MANAGED_REGION, diff="", wrote=False)
    if mode != "link":
        raise ValueError(f"unsupported inject mode: {mode}")

    current = path.read_text(encoding="utf-8") if path.exists() else ""
    next_text = _linked_text(current)
    if next_text == current:
        return InjectResult(path=path, body=MANAGED_REGION, diff="", wrote=False)

    rendered_diff = _diff(current, next_text)
    path.write_text(next_text, encoding="utf-8")
    return InjectResult(path=path, body=MANAGED_REGION, diff=rendered_diff, wrote=True)


def _linked_text(current: str) -> str:
    begin = current.find(BEGIN)
    end = current.find(END)

    if begin == -1 and end == -1:
        if not current:
            return MANAGED_REGION
        separator = "" if current.endswith("\n") else "\n"
        return f"{current}{separator}{MANAGED_REGION}"

    if begin == -1 or end == -1 or end < begin:
        raise ManagedRegionEditedError(_diff(current, current))

    region_end = end + len(END)
    if region_end < len(current) and current[region_end : region_end + 1] in ("\r", "\n"):
        if current[region_end : region_end + 2] == "\r\n":
            region_end += 2
        else:
            region_end += 1

    current_region = current[begin:region_end]
    if current_region != MANAGED_REGION and not (
        region_end == len(current) and f"{current_region}\n" == MANAGED_REGION
    ):
        raise ManagedRegionEditedError(_diff(current_region, MANAGED_REGION))
    return current


def _diff(current: str, rendered: str) -> str:
    return "".join(
        difflib.unified_diff(
            current.splitlines(keepends=True),
            rendered.splitlines(keepends=True),
            fromfile="CLAUDE.md",
            tofile="CLAUDE.md (omni)",
        )
    )
