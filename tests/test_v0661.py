from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from jpnote_app.db import connect, connect_preflight
from jpnote_app.import_preflight import build_preflight_report
from jpnote_app.repository import get_entry
from jpnote_app.services import apply_import, merge_entries, prepare_import
from jpnote_app.validation import normalize_payload


class V0661Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        os.environ["JPNOTE_DATA_DIR"] = str(self.root / "data")

    def tearDown(self) -> None:
        os.environ.pop("JPNOTE_DATA_DIR", None)
        self.temp.cleanup()

    def _import(self, payload: dict):
        with connect() as conn:
            return apply_import(conn, prepare_import(conn, payload))

    def test_merge_relation_bearing_entry_recreates_relations(self) -> None:
        self._import({"items": [
            {
                "key": "grammar:A", "type": "grammar", "display": "A",
                "related_grammar": [
                    {"key": "grammar:C", "relation": "意思相近", "note": "same"}
                ],
            },
            {"key": "grammar:B", "type": "grammar", "display": "B"},
            {"key": "grammar:C", "type": "grammar", "display": "C"},
        ]})
        with connect() as conn:
            result = merge_entries(conn, "grammar:A", "grammar:B")
            rows = conn.execute(
                "SELECT source_key,target_key,relation_type,note FROM grammar_relations ORDER BY source_key,target_key"
            ).fetchall()
            source_missing = get_entry(conn, "grammar:A") is None
        self.assertEqual(result["key"], "grammar:B")
        self.assertTrue(source_missing)
        self.assertEqual(
            {(r["source_key"], r["target_key"], r["relation_type"], r["note"]) for r in rows},
            {
                ("grammar:B", "grammar:C", "意思相近", "same"),
                ("grammar:C", "grammar:B", "意思相近", "same"),
            },
        )

    def test_merge_pending_relation_note_conflict_is_rejected_without_mutation(self) -> None:
        self._import({"items": [
            {
                "key": "grammar:A", "type": "grammar", "display": "A",
                "related_grammar": [
                    {"key": "grammar:X", "relation": "意思相近", "note": "from-A"}
                ],
            },
            {
                "key": "grammar:B", "type": "grammar", "display": "B",
                "related_grammar": [
                    {"key": "grammar:X", "relation": "意思相近", "note": "from-B"}
                ],
            },
        ]})
        with connect() as conn:
            before = [tuple(row) for row in conn.execute(
                "SELECT source_key,target_key,relation_type,note FROM pending_grammar_relations ORDER BY id"
            ).fetchall()]
            with self.assertRaisesRegex(ValueError, "note.*衝突"):
                merge_entries(conn, "grammar:A", "grammar:B")
            after = [tuple(row) for row in conn.execute(
                "SELECT source_key,target_key,relation_type,note FROM pending_grammar_relations ORDER BY id"
            ).fetchall()]
            self.assertIsNotNone(get_entry(conn, "grammar:A"))
            self.assertIsNotNone(get_entry(conn, "grammar:B"))
        self.assertEqual(before, after)

    def test_same_batch_same_logical_relation_conflicting_note_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "邏輯關聯相同但 note 衝突"):
            normalize_payload({"items": [{
                "key": "grammar:A", "type": "grammar", "display": "A",
                "related_grammar": [
                    {"key": "grammar:B", "relation": "意思相近", "note": "old"},
                    {"key": "grammar:B", "relation": "意思相近", "note": "new"},
                ],
            }]})

    def test_same_batch_reciprocal_conflicting_note_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "reciprocal／inverse"):
            normalize_payload({"items": [
                {
                    "key": "grammar:A", "type": "grammar", "display": "A",
                    "related_grammar": [
                        {"key": "grammar:B", "relation": "意思相近", "note": "left"}
                    ],
                },
                {
                    "key": "grammar:B", "type": "grammar", "display": "B",
                    "related_grammar": [
                        {"key": "grammar:A", "relation": "意思相近", "note": "right"}
                    ],
                },
            ]})

    def test_preflight_simulates_same_batch_reciprocal_relation_state(self) -> None:
        payload = {"items": [
            {
                "key": "grammar:A", "type": "grammar", "display": "A",
                "related_grammar": [
                    {"key": "grammar:B", "relation": "意思相近", "note": "same"}
                ],
            },
            {
                "key": "grammar:B", "type": "grammar", "display": "B",
                "related_grammar": [
                    {"key": "grammar:A", "relation": "意思相近", "note": "same"}
                ],
            },
        ]}
        with connect_preflight() as conn:
            report = build_preflight_report(conn, prepare_import(conn, payload))
        statuses = [
            relation["status"]
            for item in report["items"]
            for relation in item["relation_outcomes"]
        ]
        self.assertEqual(statuses, ["new", "unchanged"])
        self.assertEqual(report["summary"]["new_relations"], 1)
        self.assertEqual(report["summary"]["unchanged_relations"], 1)

    def test_date_and_attempt_date_conflict_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "date.*attempt_date"):
            normalize_payload({"attempts": [{
                "date": "2026-07-20", "attempt_date": "2026-07-19", "result": "wrong"
            }]})
        _, _, attempts, _ = normalize_payload({"attempts": [{
            "date": "2026-07-20", "attempt_date": "2026-07-20", "result": "wrong"
        }]})
        self.assertEqual(attempts[0]["date"], "2026-07-20")

    def test_internal_event_key_generated_field_is_not_public_input(self) -> None:
        with self.assertRaisesRegex(ValueError, "_event_key_generated"):
            normalize_payload({"attempts": [{
                "event_key": "attempt:x", "result": "wrong", "_event_key_generated": True
            }]})


if __name__ == "__main__":
    unittest.main()
