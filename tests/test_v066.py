from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from jpnote_app.api import JpnoteCore
from jpnote_app.audit import apply_safe_repairs, run_audit
from jpnote_app.db import connect, connect_preflight, db_path
from jpnote_app.import_preflight import build_preflight_report
from jpnote_app.repository import get_attempt, get_entry
from jpnote_app.services import apply_import, prepare_import
from jpnote_app.validation import parse_payload, normalize_payload, validate_attempt


class V066Tests(unittest.TestCase):
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

    def test_relation_only_change_is_update_in_preflight_and_apply(self) -> None:
        self._import({"items": [
            {"key": "grammar:A", "type": "grammar", "display": "A"},
            {"key": "grammar:B", "type": "grammar", "display": "B"},
        ]})
        payload = {"items": [{
            "key": "grammar:A", "type": "grammar", "display": "A",
            "related_grammar": [{"key": "grammar:B", "relation": "對比", "note": "old"}],
        }]}
        with connect_preflight() as conn:
            report = build_preflight_report(conn, prepare_import(conn, payload))
        self.assertEqual(report["items"][0]["status"], "update")
        self.assertEqual(report["summary"]["new_relations"], 1)
        result = self._import(payload)
        self.assertEqual(result.updated_entries, 1)
        self.assertEqual(result.unchanged_entries, 0)
        self.assertEqual(result.added_relations, 2)

    def test_relation_note_correction_replaces_logical_relation_instead_of_accumulating(self) -> None:
        base = {"items": [
            {"key": "grammar:A", "type": "grammar", "display": "A",
             "related_grammar": [{"key": "grammar:B", "relation": "意思相近", "note": "old"}]},
            {"key": "grammar:B", "type": "grammar", "display": "B"},
        ]}
        self._import(base)
        incoming = {"items": [{
            "key": "grammar:A", "type": "grammar", "display": "A",
            "related_grammar": [{"key": "grammar:B", "relation": "意思相近", "note": "new"}],
        }]}
        with connect_preflight() as conn:
            report = build_preflight_report(conn, prepare_import(conn, incoming))
        self.assertEqual(report["summary"]["updated_relations"], 1)
        result = self._import(incoming)
        self.assertGreaterEqual(result.updated_relations, 1)
        with connect() as conn:
            rows = conn.execute(
                "SELECT source_key,target_key,relation_type,note FROM grammar_relations ORDER BY source_key,target_key"
            ).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["note"] for row in rows}, {"new"})

    def test_attempt_identity_includes_prompt_even_with_source_question_locator(self) -> None:
        common = {
            "date": "2026-07-20", "source": "TRY! N4", "question": "問題1",
            "question_type": "multiple_choice", "user_answer": "1", "result": "wrong",
        }
        a = validate_attempt({**common, "prompt": "猫は（　）です。"})
        b = validate_attempt({**common, "prompt": "犬は（　）です。"})
        self.assertNotEqual(a["event_key"], b["event_key"])
        result = self._import({"attempts": [{**common, "prompt": "猫は（　）です。"}, {**common, "prompt": "犬は（　）です。"}]})
        self.assertEqual(result.added_attempts, 2)

    def test_unknown_public_fields_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "readng"):
            normalize_payload({"items": [{
                "key": "vocab:猫", "type": "vocabulary", "display": "猫", "readng": "ねこ"
            }]})
        with self.assertRaisesRegex(ValueError, "reslut"):
            normalize_payload({"attempts": [{"result": "wrong", "reslut": "partial"}]})
        with self.assertRaisesRegex(ValueError, "extra"):
            normalize_payload({"attempts": [{"options": [{"id": 1, "text": "A", "extra": 1}]}]})

    def test_multiple_distinct_payloads_are_rejected_as_ambiguous(self) -> None:
        text = '''```json\n{"items":[{"key":"vocab:A","type":"vocabulary","display":"A"}]}\n```\n```json\n{"items":[{"key":"vocab:B","type":"vocabulary","display":"B"}]}\n```'''
        with self.assertRaisesRegex(ValueError, "多份不同"):
            parse_payload(text)

    def test_explicit_event_key_is_nfkc_normalized(self) -> None:
        attempt = validate_attempt({"event_key": "attempt:Ａ", "result": "wrong"})
        self.assertEqual(attempt["event_key"], "attempt:A")

    def test_audit_and_repair_fix_safe_legacy_relations_and_list_conflicts(self) -> None:
        self._import({"items": [
            {"key": "grammar:A", "type": "grammar", "display": "A"},
            {"key": "grammar:B", "type": "grammar", "display": "B"},
            {"key": "grammar:C", "type": "grammar", "display": "C"},
        ]})
        with connect() as conn:
            # Safe duplicate: one note empty, one informative; reciprocal missing.
            conn.execute("INSERT INTO grammar_relations(source_key,target_key,relation_type,note,source,created_at) VALUES(?,?,?,?,?,?)",
                         ("grammar:A", "grammar:B", "對比", "", "old", "2025-01-01T00:00:00+08:00"))
            conn.execute("INSERT INTO grammar_relations(source_key,target_key,relation_type,note,source,created_at) VALUES(?,?,?,?,?,?)",
                         ("grammar:A", "grammar:B", "對比", "keep", "old", "2025-01-02T00:00:00+08:00"))
            # Unsafe conflict: two different non-empty notes.
            conn.execute("INSERT INTO grammar_relations(source_key,target_key,relation_type,note,source,created_at) VALUES(?,?,?,?,?,?)",
                         ("grammar:A", "grammar:C", "意思相近", "left", "old", "2025-01-01T00:00:00+08:00"))
            conn.execute("INSERT INTO grammar_relations(source_key,target_key,relation_type,note,source,created_at) VALUES(?,?,?,?,?,?)",
                         ("grammar:A", "grammar:C", "意思相近", "right", "old", "2025-01-02T00:00:00+08:00"))
            codes_before = {issue.code for issue in run_audit(conn)}
            self.assertIn("duplicate_relation_rows", codes_before)
            self.assertIn("conflicting_relation_notes", codes_before)
            apply_safe_repairs(conn)
            issues_after = run_audit(conn)
            codes_after = {issue.code for issue in issues_after}
            self.assertNotIn("duplicate_relation_rows", codes_after)
            self.assertIn("conflicting_relation_notes", codes_after)
            reciprocal = conn.execute(
                "SELECT note FROM grammar_relations WHERE source_key='grammar:B' AND target_key='grammar:A' AND relation_type='對比'"
            ).fetchone()
        self.assertIsNotNone(reciprocal)
        self.assertEqual(reciprocal["note"], "keep")

    def test_audit_repairs_nfkc_event_key_only_when_no_conflict(self) -> None:
        self._import({"attempts": [{"event_key": "attempt:x", "result": "wrong"}]})
        with connect() as conn:
            conn.execute("UPDATE attempts SET event_key='attempt:Ａ' WHERE event_key='attempt:x'")
            codes = {issue.code for issue in run_audit(conn)}
            self.assertIn("noncanonical_event_key", codes)
            apply_safe_repairs(conn)
            value = conn.execute("SELECT event_key FROM attempts").fetchone()[0]
        self.assertEqual(value, "attempt:A")

    def test_core_preflight_does_not_create_real_database(self) -> None:
        self.assertFalse(db_path().exists())
        report = JpnoteCore().preflight_import({"items": [{
            "key": "vocab:猫", "type": "vocabulary", "display": "猫"
        }]})
        self.assertFalse(db_path().exists())
        self.assertFalse(report["database_modified"])

    def test_read_only_connect_no_longer_silently_normalizes_legacy_relation_labels(self) -> None:
        self._import({"items": [
            {"key": "grammar:A", "type": "grammar", "display": "A"},
            {"key": "grammar:B", "type": "grammar", "display": "B"},
        ]})
        with connect() as conn:
            conn.execute("INSERT INTO grammar_relations(source_key,target_key,relation_type,note,source,created_at) VALUES(?,?,?,?,?,?)",
                         ("grammar:A", "grammar:B", "相反／對比", "", "old", "2025-01-01T00:00:00+08:00"))
        # Reopening a normal connection must leave the data value alone so audit can see it.
        with connect() as conn:
            value = conn.execute("SELECT relation_type FROM grammar_relations WHERE source_key='grammar:A'").fetchone()[0]
            codes = {issue.code for issue in run_audit(conn)}
        self.assertEqual(value, "相反／對比")
        self.assertIn("noncanonical_relation_type", codes)


if __name__ == "__main__":
    unittest.main()
