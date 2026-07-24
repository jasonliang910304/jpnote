from __future__ import annotations

import argparse
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from jpnote_app import cli
from jpnote_app.optional_features import load_quiz_tui
from jpnote_app.preferences import (
    DEFAULT_CONFIG,
    load_preferences,
    quiz_defaults,
    validate_preferences,
    write_preferences,
)
from jpnote_app.quiz import tui
from jpnote_app.quiz.tui_controller import QuizTuiController


class _SetupService:
    def __init__(self) -> None:
        self.start_calls: list[dict[str, object]] = []

    def list_resumable_sessions(self, *, limit: int = 20):
        return ()

    def start_session(self, **kwargs):
        self.start_calls.append(kwargs)
        return SimpleNamespace(status="no_safe_questions")


class QuizCliConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.config_path = Path(self.temp.name) / "config.json"
        os.environ["JPNOTE_CONFIG_FILE"] = str(self.config_path)

    def tearDown(self) -> None:
        os.environ.pop("JPNOTE_CONFIG_FILE", None)
        self.temp.cleanup()

    def test_legacy_browse_only_config_backfills_quiz_defaults(self) -> None:
        self.config_path.write_text(
            json.dumps({"browse": {"types": ["vocab"], "levels": [], "results": []}}),
            encoding="utf-8",
        )
        loaded = load_preferences()
        self.assertEqual(loaded["quiz"], DEFAULT_CONFIG["quiz"])

    def test_quiz_preferences_round_trip_and_deduplicate_filters(self) -> None:
        config = validate_preferences(
            {
                "browse": DEFAULT_CONFIG["browse"],
                "quiz": {
                    "mode": "mistake",
                    "count": 25,
                    "levels": ["N3", "N3", "N4"],
                    "sources": ["TRY! N3", "TRY! N3", "今日練習"],
                    "transparent_background": False,
                    "history_detail_cap_mib": 64,
                    "prune_after_session": False,
                },
            }
        )
        write_preferences(config)
        loaded = quiz_defaults()
        self.assertEqual(loaded["mode"], "mistake")
        self.assertEqual(loaded["count"], 25)
        self.assertEqual(loaded["levels"], ["N3", "N4"])
        self.assertEqual(loaded["sources"], ["TRY! N3", "今日練習"])
        self.assertFalse(loaded["transparent_background"])
        self.assertEqual(loaded["history_detail_cap_mib"], 64)
        self.assertFalse(loaded["prune_after_session"])

    def test_invalid_quiz_preferences_fail_closed(self) -> None:
        for field, value in (
            ("mode", "unknown"),
            ("count", 0),
            ("count", True),
            ("transparent_background", "yes"),
            ("history_detail_cap_mib", 0),
            ("prune_after_session", 1),
        ):
            with self.subTest(field=field, value=value):
                raw = {"browse": DEFAULT_CONFIG["browse"], "quiz": dict(DEFAULT_CONFIG["quiz"])}
                raw["quiz"][field] = value
                with self.assertRaises(ValueError):
                    validate_preferences(raw)

    def test_parser_recognizes_quiz_overrides(self) -> None:
        args = cli.build_parser().parse_args(
            [
                "quiz",
                "--mode",
                "vocabulary",
                "--count",
                "12",
                "--level",
                "N3",
                "--source",
                "TRY! N3",
                "--opaque-background",
            ]
        )
        self.assertIs(args.func, cli.command_quiz)
        self.assertEqual(args.mode, "vocabulary")
        self.assertEqual(args.count, 12)
        self.assertEqual(args.levels, ["N3"])
        self.assertEqual(args.sources, ["TRY! N3"])
        self.assertFalse(args.transparent_background)

    def test_command_quiz_passes_config_and_session_overrides(self) -> None:
        write_preferences(
            {
                "browse": DEFAULT_CONFIG["browse"],
                "quiz": {
                    **DEFAULT_CONFIG["quiz"],
                    "mode": "mistake",
                    "count": 20,
                    "levels": ["N4"],
                    "sources": ["book"],
                    "history_detail_cap_mib": 32,
                    "prune_after_session": False,
                },
            }
        )
        runner = Mock(return_value=0)
        feature = SimpleNamespace(available=True, value=runner, error="")
        args = argparse.Namespace(
            mode="vocabulary",
            count=7,
            levels=["N3", "N3"],
            sources=["today", "today"],
            transparent_background=False,
        )
        with patch("jpnote_app.optional_features.load_quiz_tui", return_value=feature):
            self.assertEqual(cli.command_quiz(args), 0)
        runner.assert_called_once_with(
            default_mode="vocabulary",
            default_count=7,
            default_levels=["N3"],
            default_sources=["today"],
            transparent_background=False,
            history_detail_cap_bytes=32 * 1024 * 1024,
            prune_after_session=False,
        )

    def test_quiz_import_failure_is_contained(self) -> None:
        with patch(
            "jpnote_app.optional_features.import_module",
            side_effect=ImportError("broken optional package"),
        ):
            result = load_quiz_tui()
        self.assertFalse(result.available)
        self.assertIn("broken optional package", result.error)
        # The core parser remains usable because it never imports Quiz at build time.
        self.assertEqual(cli.build_parser().parse_args(["stats"]).command, "stats")

    def test_command_quiz_reports_unavailable_without_traceback(self) -> None:
        args = argparse.Namespace(
            mode=None,
            count=None,
            levels=None,
            sources=None,
            transparent_background=None,
        )
        feature = SimpleNamespace(available=False, value=None, error="Quiz TUI 壞掉")
        stderr = StringIO()
        with patch("jpnote_app.optional_features.load_quiz_tui", return_value=feature):
            with redirect_stderr(stderr):
                self.assertEqual(cli.command_quiz(args), 2)
        self.assertIn("Quiz TUI 壞掉", stderr.getvalue())

    def test_controller_uses_configured_filters_when_starting(self) -> None:
        service = _SetupService()
        controller = QuizTuiController(
            service,
            default_mode="mistake",
            default_count=15,
            default_levels=("N3", "N4"),
            default_sources=("TRY! N3",),
            seed_factory=lambda: "fixed",
        )
        self.assertEqual(controller.state.mode, "mistake")
        self.assertEqual(controller.state.requested_count, 15)
        rendered = "\n".join(controller.render(100, 30).lines)
        self.assertIn("JLPT：N3、N4", rendered)
        self.assertIn("來源：TRY! N3", rendered)
        controller.handle_key("ENTER")
        controller.handle_key("ENTER")
        controller.handle_key("ENTER")
        self.assertEqual(len(service.start_calls), 1)
        call = service.start_calls[0]
        self.assertEqual(call["mode"], "mistake")
        self.assertEqual(call["requested_count"], 15)
        self.assertEqual(call["levels"], ("N3", "N4"))
        self.assertEqual(call["sources"], ("TRY! N3",))

    def test_tui_run_prunes_with_configured_cap_even_after_wrapper_returns(self) -> None:
        store = SimpleNamespace(prune_details=Mock())
        service = SimpleNamespace(session_store=store)
        controller = SimpleNamespace()
        with patch("jpnote_app.quiz.tui.QuizTuiController", return_value=controller) as factory:
            with patch("jpnote_app.quiz.tui.curses.wrapper", return_value=0):
                result = tui.run(
                    service=service,
                    default_mode="vocabulary",
                    default_count=8,
                    default_levels=("N3",),
                    default_sources=("book",),
                    transparent_background=False,
                    history_detail_cap_bytes=1234,
                    prune_after_session=True,
                )
        self.assertEqual(result, 0)
        factory.assert_called_once_with(
            service,
            default_mode="vocabulary",
            default_count=8,
            default_levels=("N3",),
            default_sources=("book",),
        )
        store.prune_details.assert_called_once_with(cap_bytes=1234)


if __name__ == "__main__":
    unittest.main()
