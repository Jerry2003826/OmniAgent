"""Command line interface for OmniMemory."""

from __future__ import annotations

import argparse
import sys

from omni import __version__
from omni.config import ensure_project_layout
from omni.hook import install_claude_hooks, run_from_stdin


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="omni")
    parser.add_argument("--version", action="version", version=f"omni {__version__}")

    subcommands = parser.add_subparsers(dest="command", required=True)
    init_parser = subcommands.add_parser("init", help="Create a project-local .omni layout")
    init_parser.add_argument("--install-claude-hooks", action="store_true")
    init_parser.add_argument("--yes", action="store_true")

    subcommands.add_parser("hook", help=argparse.SUPPRESS)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "init":
        result = ensure_project_layout()
        print(f"Initialized OmniMemory at {result.omni_dir}")
        if result.gitignore_updated:
            print(f"Updated {result.root / '.gitignore'}")
        if args.install_claude_hooks:
            installed = install_claude_hooks(result.root, yes=args.yes)
            if not installed.ok:
                print(installed.message, file=sys.stderr)
                return 2
            _print_diff(installed.diff)
        return 0

    if args.command == "hook":
        run_from_stdin()
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


def _print_diff(diff: str) -> None:
    encoding = sys.stdout.encoding or "utf-8"
    safe_diff = diff.encode(encoding, errors="replace").decode(encoding, errors="replace")
    print(safe_diff, end="")


if __name__ == "__main__":
    sys.exit(main())
