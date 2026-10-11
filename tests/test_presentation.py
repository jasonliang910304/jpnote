from __future__ import annotations

import unittest
from unittest.mock import patch

from jpnote_app import ui_fzf
from jpnote_app.terminal_style import configure
from jpnote_app.presentation import (
    _wrap_hanging_line,
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


    def test_hanging_wrapper_aligns_numbered_continuations_by_cell_width(self) -> None:
        lines = _wrap_hanging_line(
            "12. 這是一段需要換行而且續行必須對齊正文起點的很長說明文字。",
            24,
        )
        self.assertGreater(len(lines), 1)
        self.assertTrue(lines[0].startswith("12. "))
        self.assertTrue(all(line.startswith("    ") for line in lines[1:]))
        self.assertTrue(all(not line.startswith("12. ") for line in lines[1:]))

    def test_hanging_wrapper_preserves_existing_indent_on_every_line(self) -> None:
        lines = _wrap_hanging_line(
            "   這是一段縮排後仍然很長、需要跨越多行顯示的翻譯內容。",
            22,
        )
        self.assertGreater(len(lines), 1)
        self.assertTrue(all(line.startswith("   ") for line in lines))

    def test_entry_numbered_meanings_and_examples_share_hanging_renderer(self) -> None:
        text = render_entry(
            {
                "key": "grammar:test-hanging",
                "type": "grammar",
                "display": "～テスト",
                "level": "N3",
                "aliases": [],
                "senses": [
                    {
                        "meaning": (
                            "第一個意思非常長，用來確認編號後的正文換行時，"
                            "續行不會跑回區塊最左側。"
                        ),
                        "example_ja": (
                            "この例文はとても長いので、狭い端末では必ず複数行に"
                            "折り返されます。"
                        ),
                        "example_zh": (
                            "這個中文翻譯也故意寫得很長，用來確認原有縮排會在"
                            "後續換行持續保留。"
                        ),
                    },
                    {
                        "meaning": (
                            "第二個意思同樣夠長，用來確認下一個編號項目也採用"
                            "相同的懸掛縮排規則。"
                        ),
                        "example_ja": "二つ目の例文も十分に長くして折り返しを確認します。",
                        "example_zh": "第二個例句翻譯同樣用來確認一致的排版。",
                    },
                ],
                "related_grammar": [],
                "sources": [],
                "attempt_stats": {},
            },
            width=32,
        )
        lines = text.splitlines()

        first_meaning = next(i for i, line in enumerate(lines) if line.startswith("  1. "))
        second_meaning = next(i for i, line in enumerate(lines) if line.startswith("  2. "))
        self.assertGreater(second_meaning, first_meaning + 1)
        self.assertTrue(
            all(
                line.startswith("     ")
                for line in lines[first_meaning + 1 : second_meaning]
                if line
            )
        )

        example_title = lines.index("例句")
        first_example = next(
            i for i in range(example_title + 1, len(lines))
            if lines[i].startswith("  1. ")
        )
        self.assertTrue(lines[first_example + 1].startswith("     "))
        self.assertTrue(
            any(
                line.startswith("     這個中文翻譯")
                for line in lines[first_example + 1 :]
            )
        )

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
        self.assertIn("未分類：游標＋Space", run.call_args.kwargs["input"])


    def test_unclassified_filter_summary_uses_human_label(self) -> None:
        summary = ui_fzf.browse_filter_summary({
            "types": {"grammar", "vocab"},
            "levels": {"unclassified"},
            "results": set(),
        })
        self.assertIn("等級＝未分類", summary)
        self.assertNotIn("unclassified", summary)

    def test_browse_entry_with_empty_level_displays_unclassified(self) -> None:
        visible = ui_fzf._browse_visible({
            "record_type": "entry",
            "kind": "vocab",
            "data": {
                "type": "vocabulary",
                "display": "語彙",
                "reading": "ごい",
                "level": "",
            },
        })
        self.assertIn("未分類", visible)

    def test_mistake_mixed_levels_never_renders_blank_tail(self) -> None:
        visible = ui_fzf._browse_visible({
            "record_type": "attempt",
            "kind": "mistake",
            "levels": ["N4", ""],
            "data": {
                "event_key": "attempt:mixed-levels",
                "result": "wrong",
                "date": "2026-10-12",
                "source": "test",
                "question": "q1",
            },
        })
        self.assertIn("N4、未分類", visible)
        self.assertFalse(visible.rstrip().endswith("N4、"))

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
