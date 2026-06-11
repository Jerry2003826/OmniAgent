"""Command line interface for OmniMemory."""

from __future__ import annotations

import argparse
import sys

from omni import __version__
from omni.config import ensure_project_layout
from omni.hook import install_claude_hooks, run_from_stdin
from omni.ingest import ingest as ingest_project
from omni.ingest import run_show
from omni.parse import events_as_jsonl, parse_transcript


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="omni")
    parser.add_argument("--version", action="version", version=f"omni {__version__}")

    subcommands = parser.add_subparsers(dest="command", required=True)
    init_parser = subcommands.add_parser("init", help="Create a project-local .omni layout")
    init_parser.add_argument("--install-claude-hooks", action="store_true")
    init_parser.add_argument("--yes", action="store_true")

    subcommands.add_parser("hook", help=argparse.SUPPRESS)
    parse_parser = subcommands.add_parser("parse", help=argparse.SUPPRESS)
    parse_parser.add_argument("transcript")
    ingest_parser = subcommands.add_parser("ingest", help=argparse.SUPPRESS)
    ingest_parser.add_argument("run_id", nargs="?")
    ingest_parser.add_argument("--transcript")
    run_parser = subcommands.add_parser("run", help=argparse.SUPPRESS)
    run_subcommands = run_parser.add_subparsers(dest="run_command", required=True)
    run_show_parser = run_subcommands.add_parser("show")
    run_show_parser.add_argument("run_id")
    run_show_parser.add_argument("--seq", type=int)

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

    if args.command == "parse":
        result = parse_transcript(args.transcript)
        _print_diff(events_as_jsonl(result.events))
        return 0

    if args.command == "ingest":
        result = ingest_project(run_id=args.run_id, transcript=args.transcript)
        _print_diff(
            f"run_ids={','.join(result.run_ids)} events_inserted={result.events_inserted} "
            f"queue_drained={result.queue_drained}\n"
        )
        return 0

    if args.command == "run" and args.run_command == "show":
        _print_diff(run_show(None, args.run_id, seq=args.seq))
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


def _print_diff(diff: str) -> None:
    encoding = sys.stdout.encoding or "utf-8"
    safe_diff = diff.encode(encoding, errors="replace").decode(encoding, errors="replace")
    print(safe_diff, end="")


if __name__ == "__main__":
    sys.exit(main())
