"""Managed prompt-file injection helpers."""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class InjectTarget:
    name: str
    filename: str
    begin: str
    end: str
    import_line: str

    @property
    def managed_region(self) -> str:
        return f"{self.begin}\n{self.import_line}\n{self.end}\n"


TARGETS: dict[str, InjectTarget] = {
    "claude": InjectTarget(
        "claude",
        "CLAUDE.md",
        "<!-- omni:begin -->",
        "<!-- omni:end -->",
        "@.omni/generated/memory.md",
    ),
}
MANAGED_REGION = TARGETS["claude"].managed_region


@dataclass(frozen=True)
class InjectResult:
    path: Path
    body: str
    diff: str
    wrote: bool


class ManagedRegionEditedError(RuntimeError):
    def __init__(self, target: InjectTarget, diff: str) -> None:
        if target.name == "claude":
            message = "CLAUDE.md managed region was edited; refusing overwrite"
        else:
            message = f"{target.filename} managed region was edited; refusing overwrite"
        super().__init__(message)
        self.diff = diff
        self.target = target


def inject(root: Path | str, *, target: str, mode: str) -> InjectResult:
    try:
        inject_target = TARGETS[target]
    except KeyError as exc:
        raise ValueError(f"unknown inject target: {target}") from exc

    base = Path(root).resolve()
    path = base / inject_target.filename
    managed_region = inject_target.managed_region

    if mode == "preview":
        return InjectResult(path=path, body=managed_region, diff="", wrote=False)
    if mode != "link":
        raise ValueError(f"unsupported inject mode: {mode}")

    current = path.read_text(encoding="utf-8") if path.exists() else ""
    next_text = _linked_text(current, inject_target)
    if next_text == current:
        return InjectResult(path=path, body=managed_region, diff="", wrote=False)

    rendered_diff = _diff(current, next_text, inject_target)
    path.write_text(next_text, encoding="utf-8")
    return InjectResult(path=path, body=managed_region, diff=rendered_diff, wrote=True)


def inject_claude(root: Path | str, *, mode: str) -> InjectResult:
    return inject(root, target="claude", mode=mode)


def _linked_text(current: str, target: InjectTarget) -> str:
    begin = current.find(target.begin)
    end = current.find(target.end)
    managed_region = target.managed_region

    if begin == -1 and end == -1:
        if not current:
            return managed_region
        separator = "" if current.endswith("\n") else "\n"
        return f"{current}{separator}{managed_region}"

    if begin == -1 or end == -1 or end < begin:
        raise ManagedRegionEditedError(target, _diff(current, current, target))

    region_end = end + len(target.end)
    if region_end < len(current) and current[region_end : region_end + 1] in ("\r", "\n"):
        if current[region_end : region_end + 2] == "\r\n":
            region_end += 2
        else:
            region_end += 1

    current_region = current[begin:region_end]
    if current_region != managed_region and not (
        region_end == len(current) and f"{current_region}\n" == managed_region
    ):
        raise ManagedRegionEditedError(target, _diff(current_region, managed_region, target))
    return current


def _diff(current: str, rendered: str, target: InjectTarget) -> str:
    return "".join(
        difflib.unified_diff(
            current.splitlines(keepends=True),
            rendered.splitlines(keepends=True),
            fromfile=target.filename,
            tofile=f"{target.filename} (omni)",
        )
    )
