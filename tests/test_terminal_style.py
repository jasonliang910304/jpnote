from __future__ import annotations

import io
import os
import unittest
from unittest.mock import patch

from jpnote_app.presentation import render_attempt, render_entry, render_recent_list
from jpnote_app.terminal_style import configure, enabled, strip_ansi


class _TTY(io.StringIO):
    def isatty(self) -> bool:
        return True


ENTRY = {
    "key": "grammar:～わけではない",
    "type": "grammar",
    "display": "～わけではない",
    "level": "N3",
    "senses": [{
        "meaning": "並不是……",
        "example_ja": "嫌いなわけではない。",
        "example_zh": "並不是討厭。",
    }],
    "sources": ["2026-07-18 TRY! N3"],
    "attempt_stats": {},
}


class TerminalStyleTests(unittest.TestCase):
    def tearDown(self) -> None:
        configure("never")

    def test_always_adds_ansi_without_changing_plain_content(self) -> None:
        configure("never")
        plain = render_entry(ENTRY, width=48)
        configure("always")
        colored = render_entry(ENTRY, width=48)
        self.assertIn("\x1b[", colored)
        self.assertEqual(strip_ansi(colored), plain)

    def test_auto_requires_tty_and_respects_no_color(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            configure("auto", stream=io.StringIO())
            self.assertFalse(enabled())
            configure("auto", stream=_TTY())
            self.assertTrue(enabled())

        with patch.dict(os.environ, {"NO_COLOR": "1"}, clear=True):
            configure("auto", stream=_TTY())
            self.assertFalse(enabled())

    def test_json_is_plain_even_when_always_requested(self) -> None:
        configure("always", output_format="json", stream=_TTY())
        self.assertFalse(enabled())
        self.assertNotIn("\x1b[", render_entry(ENTRY, width=48))

    def test_attempt_uses_result_tone(self) -> None:
        configure("always")
        text = render_attempt({
            "event_key": "attempt:test",
            "result": "wrong",
            "date": "2026-07-18",
            "question": "第1題",
            "question_type": "multiple_choice",
            "prompt": "問題",
            "user_answer": "A",
            "correct_answer": "B",
        }, width=48)
        self.assertIn("\x1b[1;31m", text)
        self.assertIn("\x1b[32mB\x1b[0m", text)

    def test_recent_colors_do_not_change_wrapping(self) -> None:
        entries = [
            {"action": "added", "type": "grammar", "display": "～わけではない", "level": "N3"},
            {"action": "updated", "type": "vocabulary", "display": "確信", "reading": "かくしん", "level": "N3"},
        ]
        configure("never")
        plain = render_recent_list(entries, "2026-07-18", width=48)
        configure("always")
        colored = render_recent_list(entries, "2026-07-18", width=48)
        self.assertEqual(strip_ansi(colored), plain)


if __name__ == "__main__":
    unittest.main()
