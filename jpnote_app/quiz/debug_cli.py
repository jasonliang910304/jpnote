"""JSON debug CLI for the optional headless Quiz service.

This module is intentionally separate from the core ``jpnote`` CLI.  It can be
invoked during development with ``python -m jpnote_app.quiz.debug_cli`` and is
not the final user-facing TUI.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from collections.abc import Sequence
from typing import Any

from jpnote_app.study_sources import StudySourceService

from .service import QuizService
from .session_store import QuizSessionStore


def _jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return {field.name: _jsonable(getattr(value, field.name)) for field in dataclasses.fields(value)}
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _emit(value: Any, *, stream: Any | None = None) -> None:
    output = sys.stdout if stream is None else stream
    json.dump(_jsonable(value), output, ensure_ascii=False, indent=2, sort_keys=True)
    output.write("\n")


def _service() -> QuizService:
    return QuizService(
        StudySourceService.from_default_core(),
        QuizSessionStore(),
    )


def _add_plan_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--mode", choices=("mixed", "vocabulary", "mistake"), default="mixed")
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--level", action="append", dest="levels")
    parser.add_argument("--source", action="append", dest="sources")
    parser.add_argument("--seed")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m jpnote_app.quiz.debug_cli",
        description="jpnote Quiz headless development/debug adapter",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan", help="build a safe pool without saving")
    _add_plan_arguments(plan)

    start = subparsers.add_parser("start", help="build and persist a session")
    _add_plan_arguments(start)
    start.add_argument("--allow-shortage", action="store_true")

    subparsers.add_parser("recent", help="list recent Quiz session summaries").add_argument(
        "--limit", type=int, default=20
    )

    show = subparsers.add_parser("show", help="show one saved session")
    show.add_argument("session_id")

    next_parser = subparsers.add_parser("next", help="show the current unanswered question")
    next_parser.add_argument("session_id")

    answer = subparsers.add_parser("answer", help="answer the current single-choice question")
    answer.add_argument("session_id")
    answer.add_argument("question_event_id")
    answer.add_argument("choice_id")

    reorder = subparsers.add_parser("reorder", help="answer the current reorder_4 question")
    reorder.add_argument("session_id")
    reorder.add_argument("question_event_id")
    reorder.add_argument("choice_ids", nargs="+")

    for name in ("skip", "pause", "resume", "interrupt", "abandon"):
        command = subparsers.add_parser(name)
        command.add_argument("session_id")
        if name == "skip":
            command.add_argument("question_event_id")

    return parser


def run(argv: Sequence[str] | None = None, *, service: QuizService | None = None) -> int:
    args = build_parser().parse_args(argv)
    quiz = service or _service()

    if args.command == "plan":
        _emit(
            quiz.plan_session(
                mode=args.mode,
                requested_count=args.count,
                levels=args.levels,
                sources=args.sources,
                seed=args.seed,
            )
        )
        return 0
    if args.command == "start":
        result = quiz.start_session(
            mode=args.mode,
            requested_count=args.count,
            levels=args.levels,
            sources=args.sources,
            seed=args.seed,
            allow_shortage=args.allow_shortage,
        )
        _emit(result)
        return 0 if result.started else 3
    if args.command == "recent":
        _emit(quiz.session_store.list_recent_sessions(limit=args.limit))
        return 0
    if args.command == "show":
        _emit(quiz.get_session(args.session_id))
        return 0
    if args.command == "next":
        _emit(quiz.current_question(args.session_id))
        return 0
    if args.command == "answer":
        _emit(
            quiz.submit_choice(
                args.session_id,
                args.question_event_id,
                choice_id=args.choice_id,
            )
        )
        return 0
    if args.command == "reorder":
        _emit(
            quiz.submit_reorder(
                args.session_id,
                args.question_event_id,
                ordered_choice_ids=args.choice_ids,
            )
        )
        return 0
    if args.command == "skip":
        _emit(quiz.skip_question(args.session_id, args.question_event_id))
        return 0
    if args.command == "pause":
        _emit(quiz.pause_session(args.session_id))
        return 0
    if args.command == "resume":
        _emit(quiz.resume_session(args.session_id))
        return 0
    if args.command == "interrupt":
        _emit(quiz.mark_interrupted(args.session_id))
        return 0
    if args.command == "abandon":
        _emit(quiz.abandon_session(args.session_id))
        return 0
    raise AssertionError(f"unhandled command: {args.command}")


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return run(argv)
    except Exception as exc:  # development adapter must return structured failure
        _emit({"error": type(exc).__name__, "message": str(exc)}, stream=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
