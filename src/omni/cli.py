"""Command line interface for OmniMemory."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from typing import Any

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


def _add_init_parser(subcommands: argparse._SubParsersAction) -> None:
    init_parser = subcommands.add_parser("init", help="Create a project-local .omni layout")
    init_parser.add_argument("--install-claude-hooks", action="store_true")
    init_parser.add_argument(
        "--claude-hooks-scope",
        choices=("local", "project"),
        default="local",
        help=argparse.SUPPRESS,
    )
    init_parser.add_argument("--yes", action="store_true")


def _add_status_parser(subcommands: argparse._SubParsersAction) -> None:
    status_parser = subcommands.add_parser("status", help="Show OmniMemory project status")
    status_parser.add_argument(
        "--all",
        action="store_true",
        help="Summarize all registered projects (read-only)",
    )


def _add_doctor_parser(subcommands: argparse._SubParsersAction) -> None:
    subcommands.add_parser("doctor", help="Run read-only project health diagnostics")


def _add_hidden_core_parsers(subcommands: argparse._SubParsersAction) -> None:
    subcommands.add_parser("hook", help=argparse.SUPPRESS)
    parse_parser = subcommands.add_parser("parse", help=argparse.SUPPRESS)
    parse_parser.add_argument("transcript")


def _add_ingest_parser(subcommands: argparse._SubParsersAction) -> None:
    ingest_parser = subcommands.add_parser("ingest", help="Ingest redacted Claude Code traces")
    ingest_parser.add_argument("run_id", nargs="?")
    ingest_parser.add_argument("--run-id", dest="run_id_option")
    ingest_parser.add_argument("--transcript")


def _add_run_parser(subcommands: argparse._SubParsersAction) -> None:
    run_parser = subcommands.add_parser("run", help=argparse.SUPPRESS)
    run_subcommands = run_parser.add_subparsers(dest="run_command", required=True)
    run_show_parser = run_subcommands.add_parser("show")
    run_show_parser.add_argument("run_id")
    run_show_parser.add_argument("--seq", type=int)


def _add_audit_parser(subcommands: argparse._SubParsersAction) -> None:
    audit_parser = subcommands.add_parser("audit", help="Run safety audits")
    audit_subcommands = audit_parser.add_subparsers(dest="audit_command", required=True)
    audit_subcommands.add_parser("secrets")


def _add_review_parser(subcommands: argparse._SubParsersAction) -> None:
    review_parser = subcommands.add_parser("review", help="Review staged fact candidates")
    review_subcommands = review_parser.add_subparsers(
        dest="review_command",
        required=True,
        metavar="{approve,reject,interactive}",
    )
    for command in ("approve", "reject"):
        review_command = review_subcommands.add_parser(command)
        review_command.add_argument("cand_id")
    review_subcommands.add_parser("interactive", help="Interactively review pending fact candidates")


def _add_render_parser(subcommands: argparse._SubParsersAction) -> None:
    render_parser = subcommands.add_parser("render", help="Render generated memory")
    render_parser.add_argument("--diff", action="store_true")
    render_parser.add_argument("--force", action="store_true")


def _add_inject_parser(subcommands: argparse._SubParsersAction) -> None:
    inject_parser = subcommands.add_parser("inject", help="Manage agent memory injection")
    inject_subcommands = inject_parser.add_subparsers(dest="inject_command", required=True)
    inject_claude_parser = inject_subcommands.add_parser("claude")
    inject_claude_parser.add_argument("--mode", choices=("preview", "link"), required=True)


def _add_verify_parser(subcommands: argparse._SubParsersAction) -> None:
    verify_parser = subcommands.add_parser("verify", help="Run the known verification command")
    verify_parser.add_argument("--timeout-seconds", type=int, default=120)
    verify_parser.add_argument("--qualifier")
    verify_parser.add_argument(
        "--task",
        choices=("validation", "bugfix", "docs", "refactor", "exploration", "unknown"),
        help="Map task type to a preferred verification qualifier when --qualifier is omitted",
    )
    verify_parser.add_argument(
        "--profile",
        choices=("default", "release", "test"),
        help="Select verification predicate profile (default=test command, release=build command)",
    )


def _add_dogfood_parser(subcommands: argparse._SubParsersAction) -> None:
    dogfood_parser = subcommands.add_parser(
        "dogfood",
        help=(
            "Read-only consolidated dogfood summary "
            "(eval run + outcome + optional cold/warm compare)"
        ),
    )
    dogfood_parser.add_argument("--warm", required=True, help="warm run id to review")
    dogfood_parser.add_argument(
        "--cold",
        help="optional cold baseline run id for pairwise compare",
    )


def _add_eval_parser(subcommands: argparse._SubParsersAction) -> None:
    eval_parser = subcommands.add_parser("eval", help="Evaluate run behavior")
    eval_subcommands = eval_parser.add_subparsers(dest="eval_command", required=True)
    eval_run_parser = eval_subcommands.add_parser("run")
    eval_run_parser.add_argument("run_id")
    eval_dogfood_parser = eval_subcommands.add_parser("dogfood")
    eval_dogfood_parser.add_argument("--cold", required=True)
    eval_dogfood_parser.add_argument("--warm", required=True)


def _add_outcome_parser(subcommands: argparse._SubParsersAction) -> None:
    outcome_parser = subcommands.add_parser("outcome", help="Record or show run outcomes")
    outcome_subcommands = outcome_parser.add_subparsers(
        dest="outcome_command",
        required=True,
        metavar="{mark,mark-from-verify,show,ls}",
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
    outcome_mark_from_verify_parser = outcome_subcommands.add_parser("mark-from-verify")
    outcome_mark_from_verify_parser.add_argument("run_id")
    verify_status_group = outcome_mark_from_verify_parser.add_mutually_exclusive_group()
    verify_status_group.add_argument(
        "--success",
        dest="outcome_status",
        action="store_const",
        const="success",
    )
    verify_status_group.add_argument(
        "--failed",
        dest="outcome_status",
        action="store_const",
        const="failed",
    )
    verify_status_group.add_argument(
        "--unknown",
        dest="outcome_status",
        action="store_const",
        const="unknown",
    )
    outcome_mark_from_verify_parser.add_argument(
        "--memory-effect",
        choices=("helped", "neutral", "failed_to_help", "unknown"),
    )
    outcome_mark_from_verify_parser.add_argument(
        "--task-type",
        choices=("validation", "bugfix", "docs", "refactor", "exploration", "unknown"),
        default="unknown",
    )
    outcome_mark_from_verify_parser.add_argument("--summary", dest="task_summary")
    outcome_mark_from_verify_parser.add_argument("--note")
    outcome_mark_from_verify_parser.add_argument("--timeout-seconds", type=int, default=120)
    outcome_mark_from_verify_parser.add_argument("--qualifier")
    outcome_mark_from_verify_parser.add_argument(
        "--profile",
        choices=("default", "release", "test"),
    )
    outcome_show_parser = outcome_subcommands.add_parser("show")
    outcome_show_parser.add_argument("run_id")
    outcome_ls_parser = outcome_subcommands.add_parser("ls")
    outcome_ls_parser.add_argument(
        "--task-type",
        choices=("validation", "bugfix", "docs", "refactor", "exploration", "unknown"),
    )
    outcome_ls_parser.add_argument(
        "--status",
        choices=("success", "failed", "unknown"),
    )
    outcome_ls_parser.add_argument(
        "--tests-status",
        choices=("passed", "failed", "not_run", "unknown"),
    )
    outcome_ls_parser.add_argument(
        "--memory-effect",
        choices=("helped", "neutral", "failed_to_help", "unknown"),
    )


def _add_experience_parser(subcommands: argparse._SubParsersAction) -> None:
    experience_parser = subcommands.add_parser("experience", help="Review experience memory")
    experience_subcommands = experience_parser.add_subparsers(
        dest="experience_command",
        required=True,
        metavar="{extract,ls,show,approve,reject,note}",
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
    experience_note_parser = experience_subcommands.add_parser("note")
    experience_note_subcommands = experience_note_parser.add_subparsers(
        dest="experience_note_command",
        required=True,
        metavar="{ls,show,retire}",
    )
    experience_note_ls_parser = experience_note_subcommands.add_parser("ls")
    experience_note_ls_parser.add_argument(
        "--status",
        choices=("active", "retired", "all"),
        default="active",
    )
    experience_note_show_parser = experience_note_subcommands.add_parser("show")
    experience_note_show_parser.add_argument("note_id")
    experience_note_retire_parser = experience_note_subcommands.add_parser("retire")
    experience_note_retire_parser.add_argument("note_id")


def _add_failure_parser(subcommands: argparse._SubParsersAction) -> None:
    failure_parser = subcommands.add_parser("failure", help="Review known failure memory")
    failure_subcommands = failure_parser.add_subparsers(
        dest="failure_command",
        required=True,
        metavar="{extract,ls,show,approve,reject,pattern}",
    )
    failure_extract_parser = failure_subcommands.add_parser("extract")
    failure_extract_parser.add_argument("run_id")
    failure_ls_parser = failure_subcommands.add_parser("ls")
    failure_ls_parser.add_argument(
        "--state",
        choices=("pending", "approved", "rejected", "all"),
        default="pending",
    )
    failure_show_parser = failure_subcommands.add_parser("show")
    failure_show_parser.add_argument("failure_cand_id")
    failure_approve_parser = failure_subcommands.add_parser("approve")
    failure_approve_parser.add_argument("failure_cand_id")
    failure_approve_parser.add_argument("--summary", required=True)
    failure_approve_parser.add_argument("--suggested-action", required=True)
    failure_reject_parser = failure_subcommands.add_parser("reject")
    failure_reject_parser.add_argument("failure_cand_id")
    failure_pattern_parser = failure_subcommands.add_parser("pattern")
    failure_pattern_subcommands = failure_pattern_parser.add_subparsers(
        dest="failure_pattern_command",
        required=True,
        metavar="{ls,show,retire}",
    )
    failure_pattern_ls_parser = failure_pattern_subcommands.add_parser("ls")
    failure_pattern_ls_parser.add_argument(
        "--status",
        choices=("active", "retired", "all"),
        default="active",
    )
    failure_pattern_show_parser = failure_pattern_subcommands.add_parser("show")
    failure_pattern_show_parser.add_argument("pattern_id")
    failure_pattern_retire_parser = failure_pattern_subcommands.add_parser("retire")
    failure_pattern_retire_parser.add_argument("pattern_id")


def _add_preference_parser(subcommands: argparse._SubParsersAction) -> None:
    preference_parser = subcommands.add_parser("preference", help="Review preference memory")
    preference_subcommands = preference_parser.add_subparsers(
        dest="preference_command",
        required=True,
        metavar="{extract,ls,show,approve,reject,note}",
    )
    preference_subcommands.add_parser("extract")
    preference_ls_parser = preference_subcommands.add_parser("ls")
    preference_ls_parser.add_argument(
        "--state",
        choices=("pending", "approved", "rejected", "all"),
        default="pending",
    )
    preference_show_parser = preference_subcommands.add_parser("show")
    preference_show_parser.add_argument("pref_cand_id")
    preference_approve_parser = preference_subcommands.add_parser("approve")
    preference_approve_parser.add_argument("pref_cand_id")
    preference_approve_parser.add_argument("--suggested-action")
    preference_reject_parser = preference_subcommands.add_parser("reject")
    preference_reject_parser.add_argument("pref_cand_id")
    preference_note_parser = preference_subcommands.add_parser("note")
    preference_note_subcommands = preference_note_parser.add_subparsers(
        dest="preference_note_command",
        required=True,
        metavar="{ls,show,retire}",
    )
    preference_note_ls_parser = preference_note_subcommands.add_parser("ls")
    preference_note_ls_parser.add_argument(
        "--status",
        choices=("active", "retired", "all"),
        default="active",
    )
    preference_note_show_parser = preference_note_subcommands.add_parser("show")
    preference_note_show_parser.add_argument("note_id")
    preference_note_retire_parser = preference_note_subcommands.add_parser("retire")
    preference_note_retire_parser.add_argument("note_id")


def _add_project_parser(subcommands: argparse._SubParsersAction) -> None:
    project_parser = subcommands.add_parser("project", help="Manage the multi-project registry")
    project_subcommands = project_parser.add_subparsers(
        dest="project_command",
        required=True,
        metavar="{register,ls}",
    )
    project_register_parser = project_subcommands.add_parser("register")
    project_register_parser.add_argument(
        "path",
        nargs="?",
        help="Project root to register (defaults to discovered project root)",
    )
    project_subcommands.add_parser("ls")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="omni")
    parser.add_argument("--version", action="version", version=f"omni {__version__}")

    subcommands = parser.add_subparsers(
        dest="command",
        required=True,
        metavar=(
            "{init,audit,ingest,status,doctor,render,inject,dogfood,eval,outcome,"
            "experience,failure,preference,project,verify,review}"
        ),
    )
    _add_init_parser(subcommands)
    _add_status_parser(subcommands)
    _add_doctor_parser(subcommands)
    _add_hidden_core_parsers(subcommands)
    _add_ingest_parser(subcommands)
    _add_run_parser(subcommands)
    _add_audit_parser(subcommands)
    _add_review_parser(subcommands)
    _add_render_parser(subcommands)
    _add_inject_parser(subcommands)
    _add_verify_parser(subcommands)
    _add_dogfood_parser(subcommands)
    _add_eval_parser(subcommands)
    _add_outcome_parser(subcommands)
    _add_experience_parser(subcommands)
    _add_failure_parser(subcommands)
    _add_preference_parser(subcommands)
    _add_project_parser(subcommands)

    _hide_subcommands(
        subcommands,
        {"hook", "parse", "run"},
    )

    return parser


def _run_db_command(
    *,
    readonly: bool,
    action: Callable[[Any], Any],
    render: Callable[[Any], str],
) -> int:
    from omni.dbaccess import connect_project, connect_project_readonly

    root = project_root()
    try:
        conn = connect_project_readonly(root) if readonly else connect_project(root)
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    try:
        try:
            result = action(conn)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
    finally:
        conn.close()
    _print_diff(render(result))
    return 0


def _cmd_init(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
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


def _cmd_hook(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    try:
        run_from_stdin()
    except Exception:
        pass
    return 0


def _cmd_status(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from omni import projects
    from omni.status import status_json

    if args.all:
        _print_diff(projects.as_json(projects.status_all()))
    else:
        _print_diff(status_json(project_root()))
    return 0


def _cmd_doctor(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from omni import doctor

    result = doctor.run(project_root())
    _print_diff(result.as_json())
    return 0 if result.ok else 1


def _cmd_parse(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from omni.parse import events_as_jsonl, parse_transcript

    result = parse_transcript(args.transcript)
    _print_diff(events_as_jsonl(result.events))
    return 0


def _cmd_ingest(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from omni.ingest import ingest as ingest_project

    run_id = args.run_id_option or args.run_id
    result = ingest_project(project_root(), run_id=run_id, transcript=args.transcript)
    _print_diff(
        f"run_ids={','.join(result.run_ids)} events_inserted={result.events_inserted} "
        f"queue_drained={result.queue_drained}\n"
    )
    return 0


def _cmd_run(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from omni.ingest import run_show

    if args.run_command == "show":
        try:
            result = run_show(project_root(), args.run_id, seq=args.seq)
        except FileNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        _print_diff(result)
        return 0
    parser.error(f"unknown run command: {args.run_command}")
    return 2


def _cmd_audit(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from omni.audit import run_audit_cli

    if args.audit_command == "secrets":
        code, body = run_audit_cli(project_root())
        _print_diff(body)
        return code
    parser.error(f"unknown audit command: {args.audit_command}")
    return 2


def _cmd_review(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from omni import gate
    from omni import review
    from omni.dbaccess import connect_project_migrate

    conn = connect_project_migrate(project_root())
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
        elif args.review_command == "interactive":
            result = review.interactive(conn)
        else:
            parser.error(f"unknown review command: {args.review_command}")
            return 2
    finally:
        conn.close()
    _print_diff(result.as_json())
    return 0


def _cmd_render(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from omni import render
    from omni.dbaccess import connect_project_migrate

    root = project_root()
    conn = connect_project_migrate(root)
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


def _cmd_inject(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from omni import inject

    if args.inject_command == "claude":
        try:
            result = inject.inject_claude(project_root(), mode=args.mode)
        except inject.ManagedRegionEditedError as exc:
            _print_diff(exc.diff)
            print(str(exc), file=sys.stderr)
            return 2
        _print_diff(result.body if args.mode == "preview" else result.diff)
        return 0
    parser.error(f"unknown inject command: {args.inject_command}")
    return 2


def _cmd_verify(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from omni import verify
    from omni.dbaccess import connect_project_readonly_verify

    root = project_root()
    try:
        conn = connect_project_readonly_verify(root)
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    try:
        try:
            result = verify.run_preflight(
                conn,
                root,
                timeout_seconds=args.timeout_seconds,
                qualifier=args.qualifier,
                task_type=args.task,
                profile=args.profile,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
    finally:
        conn.close()
    _print_diff(verify.as_json(result))
    if result["status"] == "passed":
        return 0
    if result["status"] == "failed":
        return 1
    return 2


def _cmd_dogfood(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from omni import eval as behavior_eval

    result = behavior_eval.review_dogfood(
        project_root(),
        warm_run_id=args.warm,
        cold_run_id=args.cold,
    )
    _print_diff(behavior_eval.as_json(result))
    return 0


def _cmd_eval(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
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


def _cmd_outcome(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from omni import outcome

    return _run_db_command(
        readonly=outcome.cli_command_readonly(args),
        action=lambda conn: outcome.handle_cli_action(
            conn, args, parser, root=project_root()
        ),
        render=outcome.as_json,
    )


def _cmd_experience(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from omni import experience

    return _run_db_command(
        readonly=experience.cli_command_readonly(args),
        action=lambda conn: experience.handle_cli_action(conn, args, parser),
        render=experience.as_json,
    )


def _cmd_failure(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from omni import failure

    return _run_db_command(
        readonly=failure.cli_command_readonly(args),
        action=lambda conn: failure.handle_cli_action(conn, args, parser),
        render=failure.as_json,
    )


def _cmd_preference(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from omni import preference

    return _run_db_command(
        readonly=preference.cli_command_readonly(args),
        action=lambda conn: preference.handle_cli_action(conn, args, parser),
        render=preference.as_json,
    )


def _cmd_project(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from omni import projects

    if args.project_command == "register":
        target = args.path or str(project_root())
        result = projects.register(target)
    elif args.project_command == "ls":
        result = projects.list_registered()
    else:
        parser.error(f"unknown project command: {args.project_command}")
        return 2
    _print_diff(projects.as_json(result))
    return 0


_HANDLERS: dict[str, Callable[[argparse.Namespace, argparse.ArgumentParser], int]] = {
    "init": _cmd_init,
    "hook": _cmd_hook,
    "status": _cmd_status,
    "doctor": _cmd_doctor,
    "parse": _cmd_parse,
    "ingest": _cmd_ingest,
    "run": _cmd_run,
    "audit": _cmd_audit,
    "review": _cmd_review,
    "render": _cmd_render,
    "inject": _cmd_inject,
    "verify": _cmd_verify,
    "dogfood": _cmd_dogfood,
    "eval": _cmd_eval,
    "outcome": _cmd_outcome,
    "experience": _cmd_experience,
    "failure": _cmd_failure,
    "preference": _cmd_preference,
    "project": _cmd_project,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = _HANDLERS.get(args.command)
    if handler is None:
        parser.error(f"unknown command: {args.command}")
        return 2
    return handler(args, parser)


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


if __name__ == "__main__":
    sys.exit(main())
