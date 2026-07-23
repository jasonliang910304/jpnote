from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jpnote_app.audit import apply_safe_repairs, run_audit
from jpnote_app.browsing import browse_records
from jpnote_app.db import connect
from jpnote_app.import_preflight import build_preflight_report
from jpnote_app.repository import get_entry, replace_entry
from jpnote_app.romaji_maintenance import apply_safe_romaji_normalization
from jpnote_app.services import apply_import, prepare_import
from jpnote_app.validation import validate_attempt


class V063Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        os.environ["JPNOTE_DATA_DIR"] = str(self.root / "data")

    def tearDown(self) -> None:
        os.environ.pop("JPNOTE_DATA_DIR", None)
        self.temp.cleanup()

    def test_auto_event_key_ignores_explanation_and_link_order(self) -> None:
        base = {
            "date": "2026-07-19",
            "source": "TRY! N4",
            "section": "第7課",
            "question": "問題3",
            "question_type": "multiple_choice",
            "prompt": "問題本文",
            "user_answer": "2",
            "reason": "舊解析",
            "linked_entries": ["vocab:猫", "grammar:のに"],
        }
        first = validate_attempt(base)
        second = validate_attempt({
            **base,
            "reason": "重新產生、內容更完整的解析",
            "linked_entries": ["grammar:のに", "vocab:猫"],
        })
        changed_answer = validate_attempt({**base, "user_answer": "3"})
        self.assertEqual(first["event_key"], second["event_key"])
        self.assertNotEqual(first["event_key"], changed_answer["event_key"])

    def test_new_auto_identity_deduplicates_pre_v063_existing_attempt_key(self) -> None:
        base = {
            "date": "2026-07-19", "source": "TRY! N4", "section": "第1課",
            "question": "問題1", "question_type": "multiple_choice",
            "prompt": "テスト", "user_answer": "2", "result": "wrong",
        }
        with connect() as conn:
            first = prepare_import(conn, {"attempts": [{**base, "event_key": "attempt:legacy-old-hash", "reason": "old"}]})
            result1 = apply_import(conn, first)
            second = prepare_import(conn, {"attempts": [{**base, "reason": "new explanation"}]})
            with self.assertRaisesRegex(ValueError, "identity 相同但內容不同"):
                apply_import(conn, second)
            count = conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
        self.assertEqual(result1.added_attempts, 1)
        self.assertEqual(count, 1)

    def test_attempt_date_requires_iso_calendar_date(self) -> None:
        self.assertEqual(validate_attempt({"date": "2026-07-19"})["date"], "2026-07-19")
        with self.assertRaisesRegex(ValueError, "YYYY-MM-DD"):
            validate_attempt({"date": "banana"})
        with self.assertRaisesRegex(ValueError, "YYYY-MM-DD"):
            validate_attempt({"date": "2026-7-1"})

    def test_noop_reimport_preserves_updated_at_and_reports_unchanged(self) -> None:
        payload = {
            "source": "book",
            "items": [{
                "key": "vocab:猫", "type": "vocabulary", "display": "猫",
                "reading": "ねこ", "romaji": "ne ko", "meanings": ["貓"],
            }],
        }
        with connect() as conn:
            apply_import(conn, prepare_import(conn, payload))
            conn.execute("UPDATE entries SET updated_at='2020-01-01T00:00:00+08:00' WHERE key='vocab:猫'")
            result = apply_import(conn, prepare_import(conn, payload))
            updated_at = conn.execute("SELECT updated_at FROM entries WHERE key='vocab:猫'").fetchone()[0]
        self.assertEqual(result.unchanged_entries, 1)
        self.assertEqual(result.updated_entries, 0)
        self.assertEqual(updated_at, "2020-01-01T00:00:00+08:00")

    def test_replace_entry_preserves_existing_source_added_at(self) -> None:
        payload = {
            "source": "source-A",
            "items": [{
                "key": "vocab:猫", "type": "vocabulary", "display": "猫",
                "reading": "ねこ", "romaji": "ne ko", "meanings": ["貓"],
            }],
        }
        with connect() as conn:
            apply_import(conn, prepare_import(conn, payload))
            conn.execute(
                "UPDATE sources SET added_at='2020-01-01T00:00:00+08:00' WHERE entry_key='vocab:猫' AND source='source-A'"
            )
            entry = get_entry(conn, "vocab:猫", include_attempts=False)
            assert entry is not None
            entry["sources"] = ["source-A", "source-B"]
            replace_entry(conn, "vocab:猫", entry)
            rows = conn.execute(
                "SELECT source, added_at FROM sources WHERE entry_key='vocab:猫' ORDER BY source"
            ).fetchall()
        self.assertEqual(rows[0]["source"], "source-A")
        self.assertEqual(rows[0]["added_at"], "2020-01-01T00:00:00+08:00")
        self.assertEqual(rows[1]["source"], "source-B")
        self.assertNotEqual(rows[1]["added_at"], "2020-01-01T00:00:00+08:00")

    def test_maintenance_romaji_and_repair_do_not_pollute_recent_timestamp(self) -> None:
        payload = {
            "items": [{
                "key": "vocab:運転", "type": "vocabulary", "display": "運転",
                "reading": "うんてん", "romaji": "u n te n", "meanings": ["駕駛"],
            }],
        }
        with connect() as conn:
            apply_import(conn, prepare_import(conn, payload))
            conn.execute(
                "UPDATE entries SET romaji='unten', level='n4', updated_at='2020-01-01T00:00:00+08:00' WHERE key='vocab:運転'"
            )
            apply_safe_romaji_normalization(conn)
            apply_safe_repairs(conn)
            row = conn.execute("SELECT romaji, level, updated_at FROM entries WHERE key='vocab:運転'").fetchone()
        self.assertEqual(row["romaji"], "u n te n")
        self.assertEqual(row["level"], "N4")
        self.assertEqual(row["updated_at"], "2020-01-01T00:00:00+08:00")

    def test_batch_preflight_marks_both_conflicting_items_for_review(self) -> None:
        payload = {
            "items": [
                {"key": "vocab:猫", "type": "vocabulary", "display": "猫", "aliases": ["ねこ"]},
                {"key": "vocab:ねこ", "type": "vocabulary", "display": "ねこ", "aliases": ["猫"]},
            ]
        }
        with connect() as conn:
            report = build_preflight_report(conn, prepare_import(conn, payload))
        self.assertEqual([item["status"] for item in report["items"]], ["review", "review"])
        self.assertEqual(report["summary"]["review_items"], 2)

    def test_audit_reports_invalid_date_relation_and_foreign_key(self) -> None:
        with connect() as conn:
            apply_import(conn, prepare_import(conn, {
                "items": [
                    {"key": "grammar:のに", "type": "grammar", "display": "のに"},
                    {"key": "grammar:ので", "type": "grammar", "display": "ので"},
                ],
                "attempts": [{"event_key": "attempt:test", "date": "2026-07-19"}],
            }))
            conn.execute("UPDATE attempts SET attempt_date='banana' WHERE event_key='attempt:test'")
            conn.execute(
                "INSERT INTO grammar_relations(source_key,target_key,relation_type,note,source,created_at) VALUES(?,?,?,?,?,?)",
                ("grammar:のに", "grammar:ので", "unsupported", "", "", "2026-07-19T00:00:00+08:00"),
            )
            conn.commit()
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute(
                "INSERT INTO attempt_entries(attempt_id,entry_key,role) VALUES(?,?,?)",
                (999999, "grammar:のに", "related"),
            )
            conn.commit()
            conn.execute("PRAGMA foreign_keys=ON")
            issues = run_audit(conn)
        codes = {issue.code for issue in issues}
        self.assertIn("invalid_attempt_date", codes)
        self.assertIn("invalid_relation_type", codes)
        self.assertIn("foreign_key_violation", codes)

    def test_safe_repair_normalizes_legacy_relation_without_unique_collision(self) -> None:
        with connect() as conn:
            apply_import(conn, prepare_import(conn, {
                "items": [
                    {"key": "grammar:のに", "type": "grammar", "display": "のに"},
                    {"key": "grammar:ので", "type": "grammar", "display": "ので"},
                ]
            }))
            conn.execute(
                "INSERT INTO grammar_relations(source_key,target_key,relation_type,note,source,created_at) VALUES(?,?,?,?,?,?)",
                ("grammar:のに", "grammar:ので", "相反／對比", "note", "src", "2020-01-01T00:00:00+08:00"),
            )
            conn.execute(
                "INSERT INTO grammar_relations(source_key,target_key,relation_type,note,source,created_at) VALUES(?,?,?,?,?,?)",
                ("grammar:のに", "grammar:ので", "對比", "note", "src", "2020-01-02T00:00:00+08:00"),
            )
            actions = apply_safe_repairs(conn)
            rows = conn.execute(
                "SELECT relation_type FROM grammar_relations WHERE source_key='grammar:のに' AND target_key='grammar:ので' AND note='note'"
            ).fetchall()
        self.assertEqual([row["relation_type"] for row in rows], ["對比"])
        self.assertTrue(any("normalized_relation_types" in action for action in actions))

    def test_browse_does_not_load_full_attempt_history_for_each_entry(self) -> None:
        with connect() as conn:
            apply_import(conn, prepare_import(conn, {
                "items": [{"key": "vocab:猫", "type": "vocabulary", "display": "猫", "reading": "ねこ"}],
            }))
            from jpnote_app import browsing
            real_get_entry = browsing.get_entry
            calls: list[bool] = []

            def wrapped(connection, key, include_attempts=True):
                calls.append(include_attempts)
                return real_get_entry(connection, key, include_attempts=include_attempts)

            with patch("jpnote_app.browsing.get_entry", side_effect=wrapped):
                browse_records(conn)
        # v0.6.5 batch-hydrates browse entries, so the old per-entry get_entry
        # fallback should no longer be called at all.
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
