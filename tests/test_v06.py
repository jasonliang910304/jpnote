from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from jpnote_app.db import connect
from jpnote_app.import_preflight import build_preflight_report
from jpnote_app.repository import get_entry
from jpnote_app.romaji import spaced_hepburn
from jpnote_app.romaji_maintenance import (
    apply_safe_romaji_normalization,
    romaji_audit_records,
)
from jpnote_app.services import apply_import, prepare_import
from jpnote_app.validation import validate_item


class V06Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        os.environ["JPNOTE_DATA_DIR"] = str(Path(self.temp.name) / "data")

    def tearDown(self) -> None:
        os.environ.pop("JPNOTE_DATA_DIR", None)
        self.temp.cleanup()

    def test_preflight_reports_conflicts_updates_attempts_and_does_not_mutate(self) -> None:
        with connect() as conn:
            apply_import(conn, prepare_import(conn, {
                "items": [{
                    "key": "vocab:運転", "type": "vocabulary", "display": "運転",
                    "reading": "うんてん", "romaji": "u n te n", "meanings": ["駕駛"],
                }, {
                    "key": "vocab:かむ", "type": "vocabulary", "display": "かむ",
                    "aliases": ["噛む"], "reading": "かむ", "meanings": ["咬"],
                }],
                "attempts": [{
                    "event_key": "attempt:existing", "result": "wrong",
                    "linked_entries": ["vocab:運転"],
                }],
            }))
            before = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
            plan = prepare_import(conn, {
                "items": [{
                    "key": "vocab:運転", "type": "vocabulary", "display": "運転",
                    "reading": "うんてん", "romaji": "unten", "meanings": ["駕駛；操縱"],
                }, {
                    "key": "vocab:噛む", "type": "vocabulary", "display": "噛む",
                    "reading": "かむ", "meanings": ["咬"],
                }],
                "attempts": [{
                    "event_key": "attempt:existing", "result": "wrong",
                    "linked_entries": ["vocab:運転"],
                }, {
                    "event_key": "attempt:missing", "result": "wrong",
                    "linked_entries": ["vocab:不存在"],
                }],
            })
            report = build_preflight_report(conn, plan)
            after = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]

        self.assertEqual(before, after)
        self.assertFalse(report["database_modified"])
        self.assertEqual(report["summary"]["update_items"], 1)
        self.assertGreaterEqual(report["summary"]["conflicts"], 1)
        self.assertEqual(report["summary"]["duplicate_attempts"], 1)
        self.assertEqual(report["summary"]["attempts_with_missing_links"], 1)

    def test_import_normalizes_equivalent_unspaced_romaji(self) -> None:
        item = validate_item({
            "key": "vocab:運転", "type": "vocabulary", "display": "運転",
            "reading": "うんてん", "romaji": "unten", "meanings": ["駕駛"],
        })
        self.assertEqual(item["romaji"], "u n te n")

    def test_romaji_audit_and_safe_apply(self) -> None:
        with connect() as conn:
            apply_import(conn, prepare_import(conn, {
                "items": [{
                    "key": "vocab:運転", "type": "vocabulary", "display": "運転",
                    "reading": "うんてん", "romaji": "u n te n", "meanings": ["駕駛"],
                }, {
                    "key": "vocab:合格", "type": "vocabulary", "display": "合格",
                    "reading": "ごうかく", "romaji": "gōkaku suru", "meanings": ["合格"],
                }],
            }))
            # Simulate one legacy formatting-only value that predates v0.6 import normalization.
            conn.execute("UPDATE entries SET romaji='unten' WHERE key='vocab:運転'")
            records = {record["key"]: record for record in romaji_audit_records(conn)}
            self.assertEqual(records["vocab:運転"]["status"], "format_only")
            self.assertEqual(records["vocab:合格"]["status"], "mismatch")
            applied = apply_safe_romaji_normalization(conn)
            self.assertEqual([item["key"] for item in applied], ["vocab:運転"])
            self.assertEqual(get_entry(conn, "vocab:運転")["romaji"], "u n te n")
            self.assertEqual(get_entry(conn, "vocab:合格")["romaji"], "gōkaku suru")

    def test_extended_katakana_combinations_are_supported(self) -> None:
        self.assertEqual(spaced_hepburn("デュアル"), "dyu a ru")
        self.assertEqual(spaced_hepburn("クォーツ"), "kwō tsu")


if __name__ == "__main__":
    unittest.main()
