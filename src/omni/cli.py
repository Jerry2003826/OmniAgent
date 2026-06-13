"""Command line interface for OmniMemory."""

from __future__ import annotations

import argparse
import sys

from omni import __version__
from omni.config import (
    CLAUDE_HOOK_GITIGNORE_ENTRIES,
    OMNI_GITIGNORE_ENTRIES,
    ensure_gitignore_entry,
    ensure_project_layout,
    project_root,
)


def run_from_stdin():
    from omni.hook import run_from_stdin as hook_run_from_stdin

    return hook_run_from_stdin()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="omni")
    parser.add_argument("--version", action="version", version=f"omni {__version__}")

    subcommands = parser.add_subparsers(
        dest="command",
        required=True,
        metavar="{init,status,render,inject,eval,outcome,experience,failure}",
    )
    init_parser = subcommands.add_parser("init", help="Create a project-local .omni layout")
    init_parser.add_argument("--install-claude-hooks", action="store_true")
    init_parser.add_argument(
        "--claude-hooks-scope",
        choices=("local", "project"),
        default="local",
        help=argparse.SUPPRESS,
    )
    init_parser.add_argument("--yes", action="store_true")

    subcommands.add_parser("status")
    subcommands.add_parser("doctor", help=argparse.SUPPRESS)
    subcommands.add_parser("hook", help=argparse.SUPPRESS)
    parse_parser = subcommands.add_parser("parse", help=argparse.SUPPRESS)
    parse_parser.add_argument("transcript")
    ingest_parser = subcommands.add_parser("ingest", help=argparse.SUPPRESS)
    ingest_parser.add_argument("run_id", nargs="?")
    ingest_parser.add_argument("--run-id", dest="run_id_option")
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
    eval_parser = subcommands.add_parser("eval")
    eval_subcommands = eval_parser.add_subparsers(dest="eval_command", required=True)
    eval_run_parser = eval_subcommands.add_parser("run")
    eval_run_parser.add_argument("run_id")
    eval_dogfood_parser = eval_subcommands.add_parser("dogfood")
    eval_dogfood_parser.add_argument("--cold", required=True)
    eval_dogfood_parser.add_argument("--warm", required=True)
    outcome_parser = subcommands.add_parser("outcome")
    outcome_subcommands = outcome_parser.add_subparsers(
        dest="outcome_command",
        required=True,
        metavar="{mark,show}",
    )
    outcome_mark_parser = outcome_subcommands.add_parser("mark")
    outcome_mark_parser.add_argument("run_id")
    status_group = outcome_mark_parser.add_mutually_exclusive_group()
    status_group.add_argument("--success", dest="outcome_status", action="store_const", const="success")
    status_group.add_argument("--failed", dest="outcome_status", action="store_const", const="failed")
    status_group.add_argument("--unknown", dest="outcome_status", action="store_const", const="unknown")
    tests_group = outcome_mark_parser.add_mutually_exclusive_group()
    tests_group.add_argument(
        "--tests-passed",
        dest="tests_status",
        action="store_const",
        const="passed",
    )
    tests_group.add_argument(
        "--tests-failed",
        dest="tests_status",
        action="store_const",
        const="failed",
    )
    tests_group.add_argument(
        "--tests-not-run",
        dest="tests_status",
        action="store_const",
        const="not_run",
    )
    tests_group.add_argument(
        "--tests-unknown",
        dest="tests_status",
        action="store_const",
        const="unknown",
    )
    outcome_mark_parser.add_argument(
        "--memory-effect",
        choices=("helped", "neutral", "failed_to_help", "unknown"),
    )
    outcome_mark_parser.add_argument(
        "--task-type",
        choices=("validation", "bugfix", "docs", "refactor", "exploration", "unknown"),
        default="unknown",
    )
    outcome_mark_parser.add_argument("--summary", dest="task_summary")
    outcome_mark_parser.add_argument("--final-command")
    outcome_mark_parser.add_argument("--note")
    outcome_show_parser = outcome_subcommands.add_parser("show")
    outcome_show_parser.add_argument("run_id")
    experience_parser = subcommands.add_parser("experience")
    experience_subcommands = experience_parser.add_subparsers(
        dest="experience_command",
        required=True,
        metavar="{extract,ls,show,approve,reject}",
    )
    experience_extract_parser = experience_subcommands.add_parser("extract")
    experience_extract_parser.add_argument("run_id")
    experience_ls_parser = experience_subcommands.add_parser("ls")
    experience_ls_parser.add_argument(
        "--state",
        choices=("pending", "approved", "rejected", "all"),
        default="pending",
    )
    experience_show_parser = experience_subcommands.add_parser("show")
    experience_show_parser.add_argument("exp_cand_id")
    for command in ("approve", "reject"):
        experience_review_parser = experience_subcommands.add_parser(command)
        experience_review_parser.add_argument("exp_cand_id")
    failure_parser = subcommands.add_parser("failure")
    failure_subcommands = failure_parser.add_subparsers(
        dest="failure_command",
        required=True,
        metavar="{extract,ls,show,reject}",
    )
    failure_extract_parser = failure_subcommands.add_parser("extract")
    failure_extract_parser.add_argument("run_id")
    failure_ls_parser = failure_subcommands.add_parser("ls")
    failure_ls_parser.add_argument(
        "--state",
        choices=("pending", "rejected", "all"),
        default="pending",
    )
    failure_show_parser = failure_subcommands.add_parser("show")
    failure_show_parser.add_argument("failure_cand_id")
    failure_reject_parser = failure_subcommands.add_parser("reject")
    failure_reject_parser.add_argument("failure_cand_id")

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
        gitignore_updated = ensure_gitignore_entry(result.root, OMNI_GITIGNORE_ENTRIES)
        if args.install_claude_hooks:
            gitignore_updated = (
                ensure_gitignore_entry(result.root, CLAUDE_HOOK_GITIGNORE_ENTRIES)
                or gitignore_updated
            )
        print(f"Initialized OmniMemory at {result.omni_dir}")
        if gitignore_updated:
            print(f"Updated {result.root / '.gitignore'}")
        if args.install_claude_hooks:
            from omni.hook import install_claude_hooks
            from omni.redact import redact

            installed = install_claude_hooks(
                result.root,
                yes=args.yes,
                scope=args.claude_hooks_scope,
            )
            if not installed.ok:
                print(installed.message, file=sys.stderr)
                return 2
            safe_diff = redact(installed.diff.encode("utf-8")).data.decode(
                "utf-8", errors="replace"
            )
            _print_diff(safe_diff)
        return 0

    if args.command == "hook":
        try:
            run_from_stdin()
        except Exception:
            pass
        return 0

    if args.command == "status":
        from omni.status import status_json

        _print_diff(status_json(project_root()))
        return 0

    if args.command == "doctor":
        return _experimental_disabled()

    if args.command == "parse":
        from omni.parse import events_as_jsonl, parse_transcript

        result = parse_transcript(args.transcript)
        _print_diff(events_as_jsonl(result.events))
        return 0

    if args.command == "ingest":
        from omni.ingest import ingest as ingest_project

        run_id = args.run_id_option or args.run_id
        result = ingest_project(project_root(), run_id=run_id, transcript=args.transcript)
        _print_diff(
            f"run_ids={','.join(result.run_ids)} events_inserted={result.events_inserted} "
            f"queue_drained={result.queue_drained}\n"
        )
        return 0

    if args.command == "run" and args.run_command == "show":
        from omni.ingest import run_show

        _print_diff(run_show(project_root(), args.run_id, seq=args.seq))
        return 0

    if args.command == "audit" and args.audit_command == "secrets":
        from omni.audit import run_audit_cli

        code, body = run_audit_cli(project_root())
        _print_diff(body)
        return code

    if args.command == "review":
        from omni import gate
        from omni import review

        if args.review_command == "interactive":
            return _experimental_disabled()
        conn = review.connect_project(project_root())
        try:
            if args.review_command == "approve":
                try:
                    result = review.approve(conn, args.cand_id)
                except gate.ConflictRequiresSupersede as exc:
                    print(str(exc), file=sys.stderr)
                    return 2
                except (KeyError, ValueError) as exc:
                    print(_review_error_message(exc), file=sys.stderr)
                    return 2
            elif args.review_command == "reject":
                try:
                    result = review.reject(conn, args.cand_id)
                except (KeyError, ValueError) as exc:
                    print(_review_error_message(exc), file=sys.stderr)
                    return 2
            else:
                result = review.interactive(conn)
        finally:
            conn.close()
        _print_diff(result.as_json())
        return 0

    if args.command == "render":
        from omni import render

        root = project_root()
        conn = render.connect_project(root)
        try:
            try:
                result = render.render_project(conn, root, diff=args.diff, force=args.force)
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
        from omni import inject

        try:
            result = inject.inject_claude(project_root(), mode=args.mode)
        except inject.ManagedRegionEditedError as exc:
            _print_diff(exc.diff)
            print(str(exc), file=sys.stderr)
            return 2
        _print_diff(result.body if args.mode == "preview" else result.diff)
        return 0

    if args.command == "eval":
        from omni import eval as behavior_eval

        if args.eval_command == "run":
            result = behavior_eval.evaluate_run(project_root(), args.run_id)
        elif args.eval_command == "dogfood":
            result = behavior_eval.evaluate_dogfood(
                project_root(),
                cold_run_id=args.cold,
                warm_run_id=args.warm,
            )
        else:
            parser.error(f"unknown eval command: {args.eval_command}")
            return 2
        _print_diff(behavior_eval.as_json(result))
        return 0

    if args.command == "outcome":
        from omni import outcome

        try:
            if args.outcome_command == "show":
                conn = outcome.connect_project_readonly(project_root())
            else:
                conn = outcome.connect_project(project_root())
        except (FileNotFoundError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        try:
            try:
                if args.outcome_command == "mark":
                    result = outcome.mark_outcome(
                        conn,
                        args.run_id,
                        status=args.outcome_status or "unknown",
                        tests_status=args.tests_status or "unknown",
                        memory_effect=args.memory_effect,
                        task_type=args.task_type,
                        task_summary=args.task_summary,
                        final_command=args.final_command,
                        note=args.note,
                    )
                elif args.outcome_command == "show":
                    result = outcome.show_outcome(conn, args.run_id)
                else:
                    parser.error(f"unknown outcome command: {args.outcome_command}")
                    return 2
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 2
        finally:
            conn.close()
        _print_diff(outcome.as_json(result))
        return 0

    if args.command == "experience":
        from omni import experience

        try:
            if args.experience_command in ("ls", "show"):
                conn = experience.connect_project_readonly(project_root())
            else:
                conn = experience.connect_project(project_root())
        except (FileNotFoundError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        try:
            try:
                if args.experience_command == "extract":
                    candidates = experience.extract_candidates(conn, args.run_id)
                    result = {"created": len(candidates), "candidates": candidates}
                elif args.experience_command == "ls":
                    result = {"candidates": experience.list_candidates(conn, args.state)}
                elif args.experience_command == "show":
                    result = experience.show_candidate(conn, args.exp_cand_id)
                elif args.experience_command == "approve":
                    result = experience.approve_candidate(conn, args.exp_cand_id)
                elif args.experience_command == "reject":
                    result = experience.reject_candidate(conn, args.exp_cand_id)
                else:
                    parser.error(f"unknown experience command: {args.experience_command}")
                    return 2
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 2
        finally:
            conn.close()
        _print_diff(experience.as_json(result))
        return 0

    if args.command == "failure":
        from omni import failure

        try:
            if args.failure_command in ("ls", "show"):
                conn = failure.connect_project_readonly(project_root())
            else:
                conn = failure.connect_project(project_root())
        except (FileNotFoundError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        try:
            try:
                if args.failure_command == "extract":
                    candidates = failure.extract_candidates(conn, args.run_id)
                    result = {"created": len(candidates), "candidates": candidates}
                elif args.failure_command == "ls":
                    result = {"candidates": failure.list_candidates(conn, args.state)}
                elif args.failure_command == "show":
                    result = failure.show_candidate(conn, args.failure_cand_id)
                elif args.failure_command == "reject":
                    result = failure.reject_candidate(conn, args.failure_cand_id)
                else:
                    parser.error(f"unknown failure command: {args.failure_command}")
                    return 2
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 2
        finally:
            conn.close()
        _print_diff(failure.as_json(result))
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


def _print_diff(diff: str) -> None:
    encoding = sys.stdout.encoding or "utf-8"
    safe_diff = diff.encode(encoding, errors="replace").decode(encoding, errors="replace")
    print(safe_diff, end="")


def _review_error_message(exc: KeyError | ValueError) -> str:
    if isinstance(exc, KeyError) and exc.args:
        return f"unknown candidate: {exc.args[0]}"
    return str(exc)


def _hide_subcommands(subparsers: argparse._SubParsersAction, names: set[str]) -> None:
    subparsers._choices_actions = [
        action for action in subparsers._choices_actions if action.dest not in names
    ]


def _experimental_disabled() -> int:
    print("experimental disabled in Week-1", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
