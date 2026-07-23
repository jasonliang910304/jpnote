from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from jpnote_app.attempt_services import delete_attempt_data, replace_attempt_data
from jpnote_app.browsing import browse_records
from jpnote_app.audit import apply_safe_repairs, run_audit
from jpnote_app.db import connect
from jpnote_app.import_resolution import resolve_import_plan
from jpnote_app.repository import (
    entry_attempt_stats,
    get_attempt,
    get_entry,
    list_attempts,
    list_entries,
    list_recent_entries,
    search_entries,
)
from jpnote_app.services import apply_import, duplicate_candidates, merge_entries, prepare_import
from jpnote_app.validation import normalize_payload, validate_attempt, validate_item


class JpnoteCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        os.environ["JPNOTE_DATA_DIR"] = str(Path(self.temp.name) / "data")

    def tearDown(self) -> None:
        os.environ.pop("JPNOTE_DATA_DIR", None)
        self.temp.cleanup()


    def test_relation_labels_use_canonical_enum_and_accept_old_aliases(self) -> None:
        canonical = validate_item({
            "key": "grammar:のに",
            "type": "grammar",
            "display": "のに",
            "meanings": ["明明卻"],
            "related_grammar": [{
                "key": "grammar:ので",
                "relation": "對比",
                "note": "逆接與原因",
            }],
        })
        self.assertEqual(canonical["related_grammar"][0]["relation"], "對比")

        legacy = validate_item({
            "key": "grammar:ので",
            "type": "grammar",
            "display": "ので",
            "meanings": ["因為"],
            "related_grammar": [{
                "key": "grammar:のに",
                "relation": "相反／對比",
                "note": "舊格式",
            }],
        })
        self.assertEqual(legacy["related_grammar"][0]["relation"], "對比")

        with self.assertRaises(ValueError):
            validate_item({
                "key": "grammar:ながら",
                "type": "grammar",
                "display": "ながら",
                "meanings": ["一邊"],
                "related_grammar": [{
                    "key": "grammar:つつ",
                    "relation": "搭配使用",
                }],
            })

    def test_recent_entries_use_local_calendar_date(self) -> None:
        previous_tz = os.environ.get("TZ")
        os.environ["TZ"] = "Asia/Taipei"
        if hasattr(time, "tzset"):
            time.tzset()
        try:
            with connect() as conn:
                apply_import(conn, prepare_import(conn, {
                    "source": "2026-07-17 今日練習",
                    "items": [{
                        "key": "grammar:のに",
                        "type": "grammar",
                        "display": "のに",
                        "meanings": ["明明卻"],
                    }],
                }))
                conn.execute(
                    "UPDATE entries SET created_at=?, updated_at=? WHERE key=?",
                    ("2026-07-17T00:30:00+08:00", "2026-07-17T04:20:00+08:00", "grammar:のに"),
                )
                conn.execute(
                    "UPDATE sources SET added_at=? WHERE entry_key=?",
                    ("2026-07-17T04:20:00+08:00", "grammar:のに"),
                )
                rows = list_recent_entries(conn, target_date="2026-07-17", entry_type="grammar")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["key"], "grammar:のに")
            self.assertEqual(rows[0]["action"], "updated")
            self.assertEqual(rows[0]["recent_sources"], ["2026-07-17 今日練習"])
        finally:
            if previous_tz is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = previous_tz
            if hasattr(time, "tzset"):
                time.tzset()

    def test_reorder_requires_full_permutation(self) -> None:
        with self.assertRaises(ValueError):
            validate_attempt({
                "question_type": "reorder_4",
                "parts": [
                    {"id": 1, "text": "a"}, {"id": 2, "text": "b"},
                    {"id": 3, "text": "c"}, {"id": 4, "text": "d"},
                ],
                "user_order": [1, 2, 3],
                "correct_order": [1, 2, 3, 4],
            })

    def test_reorder_historical_wrong_allows_missing_user_order(self) -> None:
        attempt = validate_attempt({
            "question_type": "reorder_4",
            "result": "wrong",
            "parts": [
                {"id": 1, "text": "a"}, {"id": 2, "text": "b"},
                {"id": 3, "text": "c"}, {"id": 4, "text": "d"},
            ],
            "user_order": [],
            "correct_order": [1, 2, 3, 4],
        })
        self.assertEqual(attempt["result"], "wrong")
        self.assertEqual(attempt["user_order"], [])

    def test_reorder_missing_user_order_cannot_claim_correct(self) -> None:
        with self.assertRaises(ValueError):
            validate_attempt({
                "question_type": "reorder_4",
                "result": "correct",
                "parts": [
                    {"id": 1, "text": "a"}, {"id": 2, "text": "b"},
                    {"id": 3, "text": "c"}, {"id": 4, "text": "d"},
                ],
                "user_order": [],
                "correct_order": [1, 2, 3, 4],
            })

    def test_same_batch_canonical_key_is_coalesced(self) -> None:
        payload = {
            "items": [
                {"key": "grammar:〜のに", "type": "grammar", "display": "のに", "meanings": ["A"]},
                {"key": "grammar:のに", "type": "grammar", "display": "のに", "meanings": ["B"]},
            ]
        }
        _, items, _, notes = normalize_payload(payload)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["key"], "grammar:のに")
        self.assertEqual({sense["meaning"] for sense in items[0]["senses"]}, {"A", "B"})
        self.assertTrue(notes)

    def test_relation_attempt_and_repair_flow(self) -> None:
        payload = {
            "source": "test",
            "items": [
                {
                    "key": "grammar:のに", "type": "grammar", "display": "のに",
                    "related_grammar": [{"key": "grammar:ので", "relation": "容易混淆", "note": "原因 vs 逆接"}],
                    "meanings": ["明明卻"],
                },
                {"key": "grammar:ので", "type": "grammar", "display": "ので", "meanings": ["因為"]},
                {"key": "vocab:教室", "type": "vocabulary", "display": "教室", "reading": "きょうしつ", "meanings": ["教室"]},
            ],
            "attempts": [{
                "question_type": "reorder_4",
                "parts": [
                    {"id": 1, "text": "a"}, {"id": 2, "text": "b"},
                    {"id": 3, "text": "c"}, {"id": 4, "text": "d"},
                ],
                "user_order": [1, 3, 2, 4],
                "correct_order": [1, 2, 3, 4],
                "linked_entries": ["grammar:のに"],
            }],
        }
        with connect() as conn:
            plan = prepare_import(conn, payload)
            result = apply_import(conn, plan)
            self.assertEqual(result.added_entries, 3)
            self.assertEqual(result.added_attempts, 1)
            entry = get_entry(conn, "grammar:のに")
            self.assertEqual(entry["related_grammar"][0]["key"], "grammar:ので")
            self.assertEqual(entry["attempt_stats"]["mistake_count"], 1)
            vocab = get_entry(conn, "vocab:教室")
            self.assertEqual(vocab["romaji"], "kyō shi tsu")
            # v0.6 normalizes safe romaji at the import boundary, so repair
            # no longer needs to fill this record later.
            apply_safe_repairs(conn)
            mistakes = list_attempts(conn, ["wrong"])
            self.assertEqual(mistakes[0]["result"], "wrong")


    def test_partial_attempt_has_half_weight(self) -> None:
        payload = {
            "items": [{
                "key": "grammar:のに", "type": "grammar",
                "display": "のに", "meanings": ["明明卻"],
            }],
            "attempts": [
                {
                    "result": "partial", "question_type": "multiple_choice",
                    "question": "1", "prompt": "二選一答對",
                    "linked_entries": ["grammar:のに"],
                },
                {
                    "result": "wrong", "question_type": "multiple_choice",
                    "question": "2", "prompt": "答錯",
                    "linked_entries": ["grammar:のに"],
                },
            ],
        }
        with connect() as conn:
            apply_import(conn, prepare_import(conn, payload))
            stats = entry_attempt_stats(conn, "grammar:のに")
            self.assertEqual(stats["partial_count"], 1)
            self.assertEqual(stats["mistake_count"], 1)
            self.assertAlmostEqual(stats["strict_accuracy"], 0.0)
            self.assertAlmostEqual(stats["weighted_accuracy"], 25.0)

    def test_pending_relation_resolves_on_later_import(self) -> None:
        with connect() as conn:
            first = prepare_import(conn, {
                "items": [{
                    "key": "grammar:のに", "type": "grammar", "display": "のに",
                    "meanings": ["明明卻"],
                    "related_grammar": [{"key": "grammar:くせに", "relation": "語氣比較", "note": "較強"}],
                }]
            })
            apply_import(conn, first)
            self.assertEqual(len(get_entry(conn, "grammar:のに")["pending_related_grammar"]), 1)
            second = prepare_import(conn, {
                "items": [{"key": "grammar:くせに", "type": "grammar", "display": "くせに", "meanings": ["明明卻"]}]
            })
            result = apply_import(conn, second)
            self.assertEqual(result.resolved_relations, 1)
            self.assertEqual(get_entry(conn, "grammar:のに")["related_grammar"][0]["key"], "grammar:くせに")

    def test_duplicate_and_merge(self) -> None:
        with connect() as conn:
            plan = prepare_import(conn, {
                "items": [
                    {"key": "vocab:食べる", "type": "vocabulary", "display": "食べる", "reading": "たべる", "aliases": ["食べます"], "meanings": ["吃"]},
                    {"key": "vocab:食べます", "type": "vocabulary", "display": "食べます", "reading": "たべます", "meanings": ["吃（敬體）"]},
                ]
            })
            apply_import(conn, plan)
            candidates = duplicate_candidates(conn)
            self.assertTrue(candidates)
            merged = merge_entries(conn, "vocab:食べます", "vocab:食べる")
            self.assertIn("食べます", merged["aliases"])
            self.assertEqual(len(list_entries(conn, "vocabulary")), 1)

    def test_import_duplicate_can_remap_to_existing_key(self) -> None:
        with connect() as conn:
            apply_import(conn, prepare_import(conn, {
                "items": [{
                    "key": "vocab:かむ", "type": "vocabulary", "display": "かむ",
                    "reading": "かむ", "aliases": ["噛む"], "meanings": ["咬"],
                }]
            }))
            plan = prepare_import(conn, {
                "items": [{
                    "key": "vocab:噛む", "type": "vocabulary", "display": "噛む",
                    "reading": "かむ", "meanings": ["咬、咀嚼"],
                }],
                "attempts": [{
                    "result": "wrong", "question_type": "vocabulary",
                    "question": "1", "linked_entries": ["vocab:噛む"],
                }],
            })
            self.assertTrue(plan.warnings)
            resolved = resolve_import_plan(conn, plan, {"vocab:噛む": "vocab:かむ"})
            self.assertFalse(resolved.warnings)
            self.assertEqual(resolved.items[0]["key"], "vocab:かむ")
            self.assertEqual(resolved.attempts[0]["linked_entries"], ["vocab:かむ"])
            apply_import(conn, resolved)
            entries = list_entries(conn, "vocabulary")
            self.assertEqual(len(entries), 1)
            entry = get_entry(conn, "vocab:かむ")
            self.assertEqual(entry["display"], "噛む")
            self.assertIn("かむ", entry["aliases"])
            self.assertEqual(entry["attempt_stats"]["mistake_count"], 1)

    def test_attempt_can_be_edited_and_deleted(self) -> None:
        with connect() as conn:
            result = apply_import(conn, prepare_import(conn, {
                "items": [{
                    "key": "grammar:のに", "type": "grammar",
                    "display": "のに", "meanings": ["明明卻"],
                }],
                "attempts": [{
                    "event_key": "attempt:test-edit",
                    "result": "wrong", "question_type": "grammar",
                    "question": "1", "reason": "最初的原因",
                    "linked_entries": ["grammar:のに"],
                }],
            }))
            self.assertEqual(result.added_attempts, 1)
            original = get_attempt(conn, "attempt:test-edit")
            self.assertIsNotNone(original)
            edited = dict(original)
            edited["result"] = "partial"
            edited["reason"] = "刪去到二選一後答對"
            updated = replace_attempt_data(conn, "attempt:test-edit", edited)
            self.assertEqual(updated["result"], "partial")
            self.assertEqual(updated["reason"], "刪去到二選一後答對")
            self.assertTrue(delete_attempt_data(conn, "attempt:test-edit"))
            self.assertIsNone(get_attempt(conn, "attempt:test-edit"))

    def test_vocabulary_sort_level_then_gojuon(self) -> None:
        with connect() as conn:
            plan = prepare_import(conn, {
                "items": [
                    {"key": "vocab:駅", "type": "vocabulary", "display": "駅", "reading": "えき", "level": "N5", "meanings": ["車站"]},
                    {"key": "vocab:会う", "type": "vocabulary", "display": "会う", "reading": "あう", "level": "N5", "meanings": ["見面"]},
                    {"key": "vocab:アルバイト", "type": "vocabulary", "display": "アルバイト", "reading": "アルバイト", "level": "N4", "meanings": ["打工"]},
                ]
            })
            apply_import(conn, plan)
            entries = list_entries(conn, "vocabulary")
            self.assertEqual([entry["display"] for entry in entries], ["会う", "駅", "アルバイト"])

    def test_search_accepts_relaxed_romaji_variants(self) -> None:
        with connect() as conn:
            apply_import(conn, prepare_import(conn, {
                "items": [
                    {
                        "key": "vocab:教室", "type": "vocabulary",
                        "display": "教室", "reading": "きょうしつ",
                        "romaji": "kyō shi tsu", "level": "N5",
                        "meanings": ["教室"],
                    },
                    {
                        "key": "vocab:コンピューター", "type": "vocabulary",
                        "display": "コンピューター", "reading": "コンピューター",
                        "romaji": "ko n pyū tā", "level": "N4",
                        "meanings": ["電腦"],
                    },
                    {
                        "key": "vocab:新聞", "type": "vocabulary",
                        "display": "新聞", "reading": "しんぶん",
                        "romaji": "shi n bu n", "level": "N5",
                        "meanings": ["報紙"],
                    },
                ]
            }))
            self.assertEqual(search_entries(conn, "kyoshitsu")[0]["key"], "vocab:教室")
            self.assertEqual(search_entries(conn, "kyoushitsu")[0]["key"], "vocab:教室")
            self.assertEqual(search_entries(conn, "kyooshitsu")[0]["key"], "vocab:教室")
            self.assertEqual(search_entries(conn, "konpyuutaa")[0]["key"], "vocab:コンピューター")
            self.assertEqual(search_entries(conn, "shimbun")[0]["key"], "vocab:新聞")

    def test_browse_filters_n4_vocabulary_and_mistakes(self) -> None:
        with connect() as conn:
            apply_import(conn, prepare_import(conn, {
                "items": [
                    {
                        "key": "vocab:予定", "type": "vocabulary",
                        "display": "予定", "reading": "よてい",
                        "level": "N4", "meanings": ["預定"],
                    },
                    {
                        "key": "grammar:のに", "type": "grammar",
                        "display": "のに", "level": "N4",
                        "meanings": ["明明卻"],
                    },
                ],
                "attempts": [{
                    "event_key": "attempt:browse",
                    "result": "wrong",
                    "question_type": "grammar",
                    "question": "第1題",
                    "prompt": "問題",
                    "linked_entries": ["grammar:のに"],
                }],
            }))
            vocab = browse_records(conn, types=["vocab"], levels=["N4"])
            self.assertEqual([record["data"]["display"] for record in vocab], ["予定"])
            mistakes = browse_records(
                conn, types=["mistake"], levels=["N4"], results=["wrong"]
            )
            self.assertEqual(len(mistakes), 1)
            self.assertEqual(mistakes[0]["event_key"], "attempt:browse")
            self.assertEqual(mistakes[0]["levels"], ["N4"])
            # Empty result filters mean all mistake results, not zero rows.
            all_mistakes = browse_records(
                conn, types=["mistake"], levels=["N4"], results=[]
            )
            self.assertEqual(len(all_mistakes), 1)
            self.assertEqual(all_mistakes[0]["event_key"], "attempt:browse")

            # Empty type filters mean all types.  A level-only filter therefore
            # returns matching grammar, vocabulary, and linked mistakes.
            n4_all_types = browse_records(conn, types=[], levels=["N4"], results=[])
            self.assertEqual(
                {record["kind"] for record in n4_all_types},
                {"grammar", "vocab", "mistake"},
            )

            # Hidden/stale result filters are ignored unless mistake is an
            # explicitly selected type.
            n4_with_hidden_wrong = browse_records(
                conn, types=[], levels=["N4"], results=["wrong"]
            )
            self.assertEqual(len(n4_with_hidden_wrong), len(n4_all_types))

    def test_connection_closes_after_outer_context_but_not_nested_transaction(self) -> None:
        conn = connect()
        with conn:
            with conn:
                conn.execute("SELECT 1").fetchone()
            # The inner transaction must not close the connection while the
            # outer owner still needs it.
            self.assertEqual(conn.execute("SELECT 1").fetchone()[0], 1)
        with self.assertRaises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")


if __name__ == "__main__":
    unittest.main()
