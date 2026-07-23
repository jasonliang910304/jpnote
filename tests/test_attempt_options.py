from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from jpnote_app.attempt_options import (
    apply_safe_option_migrations,
    parse_legacy_prompt_options,
    safe_option_migration_candidates,
)
from jpnote_app.db import connect
from jpnote_app.presentation import render_attempt
from jpnote_app.repository import get_attempt
from jpnote_app.services import apply_import, prepare_import
from jpnote_app.validation import validate_attempt


class AttemptOptionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        os.environ["JPNOTE_DATA_DIR"] = str(Path(self.temp.name) / "data")

    def tearDown(self) -> None:
        os.environ.pop("JPNOTE_DATA_DIR", None)
        self.temp.cleanup()

    def test_explicit_choice_marker_is_split_conservatively(self) -> None:
        prompt = (
            "鈴木くんは、子ねこがけがをしなくてよかったと言っていたけど\n"
            "鈴木くんは（3）から、とてもしんぱいだ。"
            "選択肢：1 やさしすぎる／2 やさしすぎて／3 やさしそうだ／4 やさしいそうだ"
        )
        parsed = parse_legacy_prompt_options(prompt)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertNotIn("選択肢", parsed.prompt)
        self.assertEqual([item["id"] for item in parsed.options], [1, 2, 3, 4])
        self.assertEqual(parsed.options[1]["text"], "やさしすぎて")

    def test_numbered_reading_options_are_split(self) -> None:
        prompt = (
            "花子さんは「顔を洗え」という言葉をどうやって覚えましたか。\n"
            "1 たろうさんの言葉を聞いて覚えました。／"
            "2 たろうさんといっしょに勉強して覚えました。／"
            "3 たろうさんに話し方を教えてもらって覚えました。／"
            "4 日本語学校で勉強して覚えました。"
        )
        parsed = parse_legacy_prompt_options(prompt)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.prompt, "花子さんは「顔を洗え」という言葉をどうやって覚えましたか。")
        self.assertEqual(len(parsed.options), 4)

    def test_ambiguous_plain_numbers_are_not_split(self) -> None:
        self.assertIsNone(parse_legacy_prompt_options("2026年7月18日に3人で4時間勉強した。"))

    def test_import_preserves_structured_options(self) -> None:
        attempt = validate_attempt({
            "event_key": "attempt:options-test",
            "result": "wrong",
            "question_type": "multiple_choice",
            "prompt": "正しいものはどれですか。",
            "options": ["A", "B", "C", "D"],
            "correct_answer": "2 B",
        })
        self.assertEqual(attempt["options"][1], {"id": 2, "text": "B"})
        with connect() as conn:
            apply_import(conn, prepare_import(conn, {"attempts": [{
                "event_key": "attempt:options-test",
                "result": "wrong",
                "question_type": "multiple_choice",
                "prompt": "正しいものはどれですか。",
                "options": ["A", "B", "C", "D"],
                "correct_answer": "2 B",
            }]}))
            saved = get_attempt(conn, "attempt:options-test")
        self.assertEqual(saved["options"][3]["text"], "D")

    def test_safe_migration_splits_old_prompt_without_changing_event_key(self) -> None:
        old_prompt = "問題です。選択肢：1 一／2 二／3 三／4 四"
        with connect() as conn:
            apply_import(conn, prepare_import(conn, {"attempts": [{
                "event_key": "attempt:legacy-options",
                "result": "wrong",
                "question_type": "multiple_choice",
                "prompt": old_prompt,
            }]}))
            candidates = safe_option_migration_candidates(conn)
            self.assertEqual(len(candidates), 1)
            applied = apply_safe_option_migrations(conn)
            self.assertEqual(len(applied), 1)
            saved = get_attempt(conn, "attempt:legacy-options")
        self.assertEqual(saved["event_key"], "attempt:legacy-options")
        self.assertEqual(saved["prompt"], "問題です。")
        self.assertEqual([x["text"] for x in saved["options"]], ["一", "二", "三", "四"])

    def test_render_falls_back_to_legacy_parser_and_separates_options(self) -> None:
        text = render_attempt({
            "event_key": "attempt:legacy",
            "result": "wrong",
            "question_type": "fill_blank",
            "prompt": "文を完成してください。選択肢：1 A／2 B／3 C／4 D",
            "options": [],
            "user_answer": "4 D",
            "correct_answer": "1 A",
            "linked_entries": [],
        }, width=40)
        self.assertIn("題目\n  文を完成してください。", text)
        self.assertIn("選項\n  1. A", text)
        self.assertNotIn("選択肢：", text)


    def test_inline_slash_grammar_choices_are_split(self) -> None:
        prompts = [
            "でも今は難しい曲も弾けて、ピアノの楽しさも分かる [2]。1 ようになる／2 ようになった／3 ようにした／4 ようにする",
            "山田さんは子どもにピアノを [3] と言っていた。私も自分の子どもにピアノを [3]。1 習う／2 習いたい／3 習われたい／4 習わせたい",
            "誕生日に子どもが私の [4] ピアノを弾いてくれたら、とても嬉しいと思う。1 ために／2 ほうが／3 なのに／4 より",
            "旅館の名前は山下旅館 [1]。1 です／2 だ／3 にする／4 でございます",
            "母といっしょなので、部屋は和室 [2] した。1 を／2 が／3 に／4 で",
            "[4] 場所だったら困ると思ったが、旅館の人が駅まで車で迎えに来ると言ってくれた。1 わかりにくい／2 わかった／3 わかりやすい／4 わからなかった",
        ]
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                parsed = parse_legacy_prompt_options(prompt)
                self.assertIsNotNone(parsed)
                assert parsed is not None
                self.assertEqual([x["id"] for x in parsed.options], [1, 2, 3, 4])
                self.assertNotIn("／2", parsed.prompt)

    def test_inline_and_multiline_reading_choices_are_split(self) -> None:
        prompts = [
            (
                "花子さんは「顔を洗え」という言葉をどうやって覚えましたか。\n"
                "1 たろうさんの言葉を聞いて覚えました。／2\n"
                "たろうさんといっしょに勉強して覚えました。／3\n"
                "たろうさんに話し方を教えてもらって覚えました。／4\n"
                "日本語学校で勉強して覚えました。"
            ),
            (
                "たろうさんはこれから花子さんに何をさせたいと思っていますか。"
                "1 たろうさんの言葉を覚えさせたいと思っています。／2 "
                "日本語学校で勉強させたいと思っています。／3 "
                "日本語学校で働かせたいと思っています。／4 "
                "日本語のソフトを作らせたいと思っています。"
            ),
        ]
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                parsed = parse_legacy_prompt_options(prompt)
                self.assertIsNotNone(parsed)
                assert parsed is not None
                self.assertEqual(len(parsed.options), 4)
                self.assertFalse(any("／" in x["text"] for x in parsed.options))

    def test_render_cleans_residual_choices_when_structured_options_already_exist(self) -> None:
        text = render_attempt({
            "event_key": "attempt:residual-options",
            "result": "wrong",
            "question_type": "grammar",
            "prompt": "旅館の名前は山下旅館 [1]。1 です／2 だ／3 にする／4 でございます",
            "options": ["です", "だ", "にする", "でございます"],
            "user_answer": "2 だ",
            "correct_answer": "1 です",
            "linked_entries": [],
        }, width=50)
        self.assertIn("題目\n  旅館の名前は山下旅館 [1]。", text)
        self.assertIn("選項\n  1. です", text)
        self.assertNotIn("[1]。1 です", text)

    def test_render_cleans_reorder_parts_duplicated_in_prompt(self) -> None:
        text = render_attempt({
            "event_key": "attempt:reorder-residual",
            "result": "wrong",
            "question_type": "reorder_4",
            "prompt": "先生、＿＿＿＿ ★＿＿＿ から、アドレスを教えてください。1 撮った／2 京都で／3 しゃしんを／4 お送りします",
            "parts": [
                {"id": 1, "text": "撮った"},
                {"id": 2, "text": "京都で"},
                {"id": 3, "text": "しゃしんを"},
                {"id": 4, "text": "お送りします"},
            ],
            "user_order": [2, 3, 1, 4],
            "correct_order": [2, 1, 3, 4],
            "linked_entries": [],
        }, width=54)
        self.assertIn("題目", text)
        self.assertIn("先生、＿＿＿＿ ★＿＿＿", text)
        self.assertIn("から、アドレスを教えてください。", text)
        self.assertNotIn("ください。1 撮った", text)
        self.assertIn("四格\n  1. 撮った", text)

    def test_placeholder_is_not_split_across_lines(self) -> None:
        text = render_attempt({
            "event_key": "attempt:slot-wrap",
            "result": "wrong",
            "question_type": "fill_blank",
            "prompt": "木からおりられなくなった子ねこをたすけに行って、子ねこに（2）らしい。",
            "options": ["かんだ", "かんで", "かまれた", "かませた"],
            "linked_entries": [],
        }, width=36)
        self.assertIn("（2）", text)
        self.assertNotIn("（\n", text)
        self.assertNotIn("2）\n", text)

    def test_migration_cleans_existing_options_and_reorder_prompt_tails(self) -> None:
        with connect() as conn:
            apply_import(conn, prepare_import(conn, {"attempts": [
                {
                    "event_key": "attempt:existing-options-tail",
                    "result": "wrong",
                    "question_type": "grammar",
                    "prompt": "旅館の名前は山下旅館 [1]。1 です／2 だ／3 にする／4 でございます",
                    "options": ["です", "だ", "にする", "でございます"],
                },
                {
                    "event_key": "attempt:reorder-tail",
                    "result": "wrong",
                    "question_type": "reorder_4",
                    "prompt": "先生、＿＿＿＿ ★＿＿＿ から、アドレスを教えてください。1 撮った／2 京都で／3 しゃしんを／4 お送りします",
                    "parts": [
                        {"id": 1, "text": "撮った"},
                        {"id": 2, "text": "京都で"},
                        {"id": 3, "text": "しゃしんを"},
                        {"id": 4, "text": "お送りします"},
                    ],
                    "correct_order": [2, 1, 3, 4],
                    "user_order": [],
                },
            ]}))
            candidates = safe_option_migration_candidates(conn)
            self.assertEqual({x["event_key"] for x in candidates}, {
                "attempt:existing-options-tail", "attempt:reorder-tail"
            })
            apply_safe_option_migrations(conn)
            first = get_attempt(conn, "attempt:existing-options-tail")
            second = get_attempt(conn, "attempt:reorder-tail")
        self.assertEqual(first["prompt"], "旅館の名前は山下旅館 [1]。")
        self.assertEqual(second["prompt"], "先生、＿＿＿＿ ★＿＿＿ から、アドレスを教えてください。")

    def test_schema_has_options_json(self) -> None:
        with connect() as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(attempts)")}
        self.assertIn("options_json", columns)


if __name__ == "__main__":
    unittest.main()
