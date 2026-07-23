from __future__ import annotations

import unittest
from unittest.mock import patch

from jpnote_app import ui_fzf
from jpnote_app.terminal_style import configure
from jpnote_app.presentation import (
    display_width,
    render_attempt,
    render_attempt_summary,
    render_entry,
    render_recent_list,
)


class PresentationTests(unittest.TestCase):
    def test_entry_uses_compact_box_and_single_blank_lines(self) -> None:
        text = render_entry({
            "key": "grammar:～わけではない",
            "type": "grammar",
            "display": "～わけではない",
            "level": "N3",
            "review_group": "部分否定",
            "aliases": [],
            "senses": [{
                "meaning": "普通形＋わけではない：並不是……",
                "example_ja": "日本料理が嫌いなわけではない。",
                "example_zh": "並不是討厭日本料理。",
            }],
            "related_grammar": [{
                "key": "grammar:～とは限らない",
                "display": "～とは限らない",
                "relation": "容易混淆",
                "note": "前者是否定推論，後者表示不一定。",
            }],
            "sources": ["2026-07-18 TRY! N3"],
            "attempt_stats": {},
        }, width=48)
        self.assertTrue(text.startswith("┌─ 文法 "))
        self.assertIn("│ ～わけではない", text)
        self.assertIn("│ grammar:～わけではない", text)
        self.assertIn("意思／用法", text)
        self.assertIn("相關文法", text)
        self.assertNotIn("\n\n\n", text)

    def test_attempt_shows_missing_answer_without_guessing(self) -> None:
        text = render_attempt({
            "event_key": "attempt:test",
            "result": "wrong",
            "date": "2026-07-18",
            "source": "N3 500題",
            "section": "第2週",
            "question": "第12題",
            "question_type": "multiple_choice",
            "prompt": "雨が降る（　　）。",
            "user_answer": "",
            "correct_answer": "とは限らない",
            "reason": "表示不一定。",
            "linked_entries": ["grammar:～とは限らない"],
        }, include_event_key=True, width=48)
        self.assertIn("┌─ 錯題 ", text)
        self.assertIn("我的答案\n  未記錄", text)
        self.assertIn("event_key: attempt:test", text)
        self.assertNotIn("\n\n\n", text)

    def test_attempt_list_is_compact(self) -> None:
        text = render_attempt_summary({
            "event_key": "attempt:test",
            "result": "wrong",
            "date": "2026-07-18",
            "source": "TRY! N3",
            "question": "第1題",
            "prompt": "問題內容",
        })
        self.assertEqual(text.count("\n"), 2)
        self.assertIn("event_key: attempt:test", text)

    def test_recent_groups_added_and_updated(self) -> None:
        text = render_recent_list([
            {"action": "added", "type": "grammar", "display": "～わけではない", "level": "N3"},
            {"action": "updated", "type": "vocabulary", "display": "確信", "reading": "かくしん", "level": "N3"},
        ], "2026-07-18", width=48)
        self.assertIn("┌─ 近期變更 ", text)
        self.assertIn("新增", text)
        self.assertIn("更新", text)
        self.assertNotIn("\n\n\n", text)

    def test_cjk_width(self) -> None:
        self.assertEqual(display_width("文法"), 4)
        self.assertEqual(display_width("N3"), 2)

    @patch("jpnote_app.ui_fzf.shutil.which", return_value="/usr/bin/fzf")
    @patch("jpnote_app.ui_fzf.subprocess.run")
    def test_fzf_entry_selector_uses_card_preview(self, run, _which) -> None:
        run.return_value.returncode = 0
        run.return_value.stdout = "grammar:のに\tignored\n"
        run.return_value.stderr = ""
        selected = ui_fzf.select_entry([{
            "key": "grammar:のに",
            "type": "grammar",
            "display": "のに",
            "level": "N4",
            "senses": [{"meaning": "明明卻"}],
            "sources": [],
            "attempt_stats": {},
        }], "選擇")
        self.assertEqual(selected, "grammar:のに")
        command = run.call_args.args[0]
        self.assertIn("--preview=cat -- {2}", command)
        fzf_input = run.call_args.kwargs["input"]
        self.assertIn("[文法] のに", fzf_input)
        self.assertEqual(len(fzf_input.split("\t")), 4)
        self.assertIn("grammar:のに", fzf_input.split("\t", 3)[3])

    @patch("jpnote_app.ui_fzf.shutil.which", return_value="/usr/bin/fzf")
    @patch("jpnote_app.ui_fzf.subprocess.run")
    def test_fzf_uses_ansi_flag_when_colors_enabled(self, run, _which) -> None:
        run.return_value.returncode = 0
        run.return_value.stdout = "grammar:のに\tignored\n"
        run.return_value.stderr = ""
        configure("always")
        try:
            ui_fzf.select_entry([{
                "key": "grammar:のに",
                "type": "grammar",
                "display": "のに",
                "level": "N4",
                "senses": [{"meaning": "明明卻"}],
                "sources": [],
                "attempt_stats": {},
            }], "選擇")
        finally:
            configure("never")
        command = run.call_args.args[0]
        self.assertIn("--ansi", command)
        self.assertIn("\x1b[", run.call_args.kwargs["input"])


    @patch("jpnote_app.ui_fzf.read_state")
    @patch("jpnote_app.ui_fzf.shutil.which", return_value="/usr/bin/fzf")
    @patch("jpnote_app.ui_fzf.subprocess.run")
    def test_filter_panel_uses_one_persistent_fzf_session(self, run, _which, read_state) -> None:
        run.return_value.returncode = 0
        run.return_value.stdout = "types:mistake\t[✓] 類型 錯題\t類型 錯題\n"
        run.return_value.stderr = ""
        read_state.return_value = {
            "types": {"grammar", "vocab", "mistake"},
            "levels": set(),
            "results": set(),
        }
        filters = ui_fzf.select_browse_filters(
            {
                "types": {"grammar", "vocab"},
                "levels": set(),
                "results": set(),
            },
            {
                "types": {"grammar", "vocab"},
                "levels": set(),
                "results": set(),
            },
        )
        self.assertIsNotNone(filters)
        self.assertIn("mistake", filters["types"])
        self.assertEqual(run.call_count, 1)
        command = run.call_args.args[0]
        self.assertIn("--header-lines=2", command)
        self.assertTrue(any("space:execute-silent" in arg for arg in command))
        self.assertTrue(any("+reload(" in arg for arg in command))
        self.assertTrue(any(arg.startswith("--bind=1:") for arg in command))
        self.assertTrue(any(arg.startswith("--bind=0:") for arg in command))

    def test_empty_mistake_results_are_summarized_as_all(self) -> None:
        summary = ui_fzf.browse_filter_summary({
            "types": {"mistake"},
            "levels": set(),
            "results": set(),
        })
        self.assertIn("錯題＝全部", summary)

    def test_empty_type_group_is_summarized_as_all(self) -> None:
        summary = ui_fzf.browse_filter_summary({
            "types": set(),
            "levels": {"N4"},
            "results": set(),
        })
        self.assertIn("類型＝全部", summary)
        self.assertIn("等級＝N4", summary)
        self.assertNotIn("錯題＝", summary)



if __name__ == "__main__":
    unittest.main()
