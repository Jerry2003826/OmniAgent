"""Command line interface for OmniMemory."""

from __future__ import annotations

import argparse
import sys

from omni import __version__
from omni.audit import run_audit_cli
from omni.config import ensure_project_layout
from omni.hook import install_claude_hooks, run_from_stdin
from omni.ingest import ingest as ingest_project
from omni.ingest import run_show
from omni.parse import events_as_jsonl, parse_transcript
from omni import inject
from omni import render
from omni import review
from omni import gate
from omni.redact import redact
from omni.status import status_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="omni")
    parser.add_argument("--version", action="version", version=f"omni {__version__}")

    subcommands = parser.add_subparsers(
        dest="command",
        required=True,
        metavar="{init,status,render,inject}",
    )
    init_parser = subcommands.add_parser("init", help="Create a project-local .omni layout")
    init_parser.add_argument("--install-claude-hooks", action="store_true")
    init_parser.add_argument("--yes", action="store_true")

    subcommands.add_parser("status")
    subcommands.add_parser("doctor", help=argparse.SUPPRESS)
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
    audit_parser = subcommands.add_parser("audit", help=argparse.SUPPRESS)
    audit_subcommands = audit_parser.add_subparsers(dest="audit_command", required=True)
    audit_subcommands.add_parser("secrets")
    review_parser = subcommands.add_parser("review", help=argparse.SUPPRESS)
    review_subcommands = review_parser.add_subparsers(
        dest="review_command",
        required=True,
        metavar="{approve,reject}",
    )
    for command in ("approve", "reject"):
        review_command = review_subcommands.add_parser(command)
        review_command.add_argument("cand_id")
    review_subcommands.add_parser("interactive", help=argparse.SUPPRESS)
    render_parser = subcommands.add_parser("render")
    render_parser.add_argument("--diff", action="store_true")
    render_parser.add_argument("--force", action="store_true")
    inject_parser = subcommands.add_parser("inject")
    inject_subcommands = inject_parser.add_subparsers(dest="inject_command", required=True)
    inject_claude_parser = inject_subcommands.add_parser("claude")
    inject_claude_parser.add_argument("--mode", choices=("preview", "link"), required=True)

    _hide_subcommands(
        subcommands,
        {"doctor", "hook", "parse", "ingest", "run", "audit", "review"},
    )
    _hide_subcommands(review_subcommands, {"interactive"})

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
            safe_diff = redact(installed.diff.encode("utf-8")).data.decode(
                "utf-8", errors="replace"
            )
            _print_diff(safe_diff)
        return 0

    if args.command == "hook":
        run_from_stdin()
        return 0

    if args.command == "status":
        _print_diff(status_json("."))
        return 0

    if args.command == "doctor":
        return _experimental_disabled()

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

    if args.command == "audit" and args.audit_command == "secrets":
        code, body = run_audit_cli(".")
        _print_diff(body)
        return code

    if args.command == "review":
        if args.review_command == "interactive":
            return _experimental_disabled()
        conn = review.connect_project(".")
        try:
            if args.review_command == "approve":
                try:
                    result = review.approve(conn, args.cand_id)
                except gate.ConflictRequiresSupersede as exc:
                    print(str(exc), file=sys.stderr)
                    return 2
            elif args.review_command == "reject":
                result = review.reject(conn, args.cand_id)
            else:
                result = review.interactive(conn)
        finally:
            conn.close()
        _print_diff(result.as_json())
        return 0

    if args.command == "render":
        conn = render.connect_project(".")
        try:
            try:
                result = render.render_project(conn, ".", diff=args.diff, force=args.force)
            except render.ManualEditError as exc:
                _print_diff(exc.diff)
                print(str(exc), file=sys.stderr)
                return 2
        finally:
            conn.close()
        if args.diff:
            _print_diff(result.diff)
        else:
            _print_diff(f"rendered {result.path}\n")
        return 0

    if args.command == "inject" and args.inject_command == "claude":
        try:
            result = inject.inject_claude(".", mode=args.mode)
        except inject.ManagedRegionEditedError as exc:
            _print_diff(exc.diff)
            print(str(exc), file=sys.stderr)
            return 2
        _print_diff(result.body if args.mode == "preview" else result.diff)
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


def _print_diff(diff: str) -> None:
    encoding = sys.stdout.encoding or "utf-8"
    safe_diff = diff.encode(encoding, errors="replace").decode(encoding, errors="replace")
    print(safe_diff, end="")


def _hide_subcommands(subparsers: argparse._SubParsersAction, names: set[str]) -> None:
    subparsers._choices_actions = [
        action for action in subparsers._choices_actions if action.dest not in names
    ]


def _experimental_disabled() -> int:
    print("experimental disabled in Week-1", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
