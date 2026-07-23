from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jpnote_app.audit import apply_safe_repairs, run_audit
from jpnote_app.db import active_backups, connect, connect_preflight, db_path, mutation_backup
from jpnote_app.export_markdown import export_all
from jpnote_app.import_preflight import build_preflight_report
from jpnote_app.presentation import render_attempt
from jpnote_app.repository import get_attempt, get_entry, list_attempts
from jpnote_app.services import apply_import, prepare_import
from jpnote_app.validation import (
    normalize_payload,
    validate_attempt_edit_fields,
    validate_entry_edit_fields,
)


class V0662Tests(unittest.TestCase):
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

    def test_pending_relation_conflict_is_reported_and_apply_rolls_back(self) -> None:
        self._import({"items": [{
            "key": "grammar:A", "type": "grammar", "display": "A",
            "related_grammar": [{"key": "grammar:B", "relation": "意思相近", "note": "OLD"}],
        }]})
        payload = {"items": [{
            "key": "grammar:B", "type": "grammar", "display": "B",
            "related_grammar": [{"key": "grammar:A", "relation": "意思相近", "note": "NEW"}],
        }]}
        with connect_preflight() as conn:
            report = build_preflight_report(conn, prepare_import(conn, payload))
        self.assertEqual(report["summary"]["pending_relation_conflicts"], 1)
        self.assertEqual(report["items"][0]["status"], "review")

        with connect() as conn:
            with self.assertRaisesRegex(ValueError, "待補文法關聯.*衝突"):
                apply_import(conn, prepare_import(conn, payload))
        with connect() as conn:
            self.assertIsNone(get_entry(conn, "grammar:B"))
            row = conn.execute(
                "SELECT note FROM pending_grammar_relations WHERE source_key='grammar:A'"
            ).fetchone()
            self.assertEqual(row["note"], "OLD")

    def test_repair_never_overwrites_resolved_note_with_stale_pending_note(self) -> None:
        self._import({"items": [
            {"key": "grammar:A", "type": "grammar", "display": "A"},
            {"key": "grammar:B", "type": "grammar", "display": "B"},
        ]})
        with connect() as conn:
            conn.execute(
                "INSERT INTO grammar_relations(source_key,target_key,relation_type,note,source,created_at) VALUES(?,?,?,?,?,?)",
                ("grammar:A", "grammar:B", "意思相近", "NEW", "new", "2026-01-01T00:00:00+08:00"),
            )
            conn.execute(
                "INSERT INTO grammar_relations(source_key,target_key,relation_type,note,source,created_at) VALUES(?,?,?,?,?,?)",
                ("grammar:B", "grammar:A", "意思相近", "NEW", "new", "2026-01-01T00:00:00+08:00"),
            )
            conn.execute(
                "INSERT INTO pending_grammar_relations(source_key,target_key,relation_type,note,source,created_at) VALUES(?,?,?,?,?,?)",
                ("grammar:A", "grammar:B", "意思相近", "OLD", "old", "2025-01-01T00:00:00+08:00"),
            )
            issues = run_audit(conn)
            self.assertTrue(any(i.code == "pending_relation_note_conflict" and not i.fixable for i in issues))
            apply_safe_repairs(conn)
            notes = {
                row["note"] for row in conn.execute(
                    "SELECT note FROM grammar_relations WHERE (source_key='grammar:A' AND target_key='grammar:B') OR (source_key='grammar:B' AND target_key='grammar:A')"
                )
            }
            pending = conn.execute(
                "SELECT note FROM pending_grammar_relations WHERE source_key='grammar:A' AND target_key='grammar:B'"
            ).fetchone()
        self.assertEqual(notes, {"NEW"})
        self.assertEqual(pending["note"], "OLD")


    def test_safe_pending_relation_resolves_and_preflight_reports_side_effect(self) -> None:
        self._import({"items": [{
            "key": "grammar:A", "type": "grammar", "display": "A",
            "related_grammar": [{"key": "grammar:B", "relation": "意思相近", "note": "SAME"}],
        }]})
        payload = {"items": [{"key": "grammar:B", "type": "grammar", "display": "B"}]}
        with connect_preflight() as conn:
            report = build_preflight_report(conn, prepare_import(conn, payload))
        self.assertEqual(report["summary"]["resolved_pending_relations"], 1)
        self.assertEqual(report["summary"]["pending_relation_conflicts"], 0)
        self._import(payload)
        with connect() as conn:
            rows = conn.execute(
                "SELECT source_key, target_key, note FROM grammar_relations ORDER BY source_key"
            ).fetchall()
            pending = conn.execute("SELECT COUNT(*) FROM pending_grammar_relations").fetchone()[0]
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["note"] for row in rows}, {"SAME"})
        self.assertEqual(pending, 0)

    def test_post_commit_failure_keeps_pre_mutation_backup(self) -> None:
        self._import({"items": [{"key": "vocab:A", "type": "vocabulary", "display": "A"}]})
        before = set(active_backups())
        with self.assertRaisesRegex(RuntimeError, "simulated export failure"):
            with mutation_backup("post-commit-failure") as backup:
                with connect() as conn:
                    conn.execute(
                        "INSERT INTO entries(key,type,display,created_at,updated_at) VALUES(?,?,?,?,?)",
                        ("vocab:B", "vocabulary", "B", "2026-07-22T00:00:00+08:00", "2026-07-22T00:00:00+08:00"),
                    )
                    conn.commit()
                backup.mark_changed()
                raise RuntimeError("simulated export failure")
        after = set(active_backups())
        self.assertEqual(len(after - before), 1)
        with connect() as conn:
            self.assertIsNotNone(get_entry(conn, "vocab:B"))

    def test_attempt_locator_format_variation_is_duplicate_not_conflict(self) -> None:
        base = {
            "event_key": "attempt:locator", "result": "wrong", "date": "2026-07-20",
            "source": "TRY! N4", "section": "第１課", "question": "問題 1",
            "question_type": "multiple_choice", "prompt": "猫は（　）です。",
            "user_answer": "1", "correct_answer": "2",
        }
        self._import({"attempts": [base]})
        incoming = {**base, "section": "第1課", "question": "問題1"}
        with connect_preflight() as conn:
            report = build_preflight_report(conn, prepare_import(conn, {"attempts": [incoming]}))
        self.assertEqual(report["attempts"][0]["status"], "duplicate")

    def test_manual_edit_field_validation_rejects_typos(self) -> None:
        with self.assertRaisesRegex(ValueError, "readng"):
            validate_entry_edit_fields({
                "key": "vocab:猫", "type": "vocabulary", "display": "猫", "readng": "ねこ"
            })
        with self.assertRaisesRegex(ValueError, "correct_answr"):
            validate_attempt_edit_fields({"event_key": "attempt:x", "correct_answr": "A"})

    def test_malformed_nested_public_values_return_value_errors(self) -> None:
        cases = [
            ({"items": [{"key": "vocab:X", "type": "vocabulary", "display": "X", "senses": 1.2}]}, "senses 必須是陣列"),
            ({"items": [{"key": "grammar:X", "type": "grammar", "display": "X", "related_grammar": 1}]}, "related_grammar 必須是陣列"),
            ({"attempts": [{"question_type": "reorder_4", "parts": 1, "correct_order": [1,2,3,4]}]}, "parts 必須是陣列"),
            ({"attempts": [{"options": True}]}, "options 必須是陣列"),
        ]
        for payload, message in cases:
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(ValueError, message):
                    normalize_payload(payload)

    def test_corrupt_attempt_structures_are_fail_soft_for_show_export_and_repair(self) -> None:
        self._import({"attempts": [{
            "event_key": "attempt:bad", "result": "wrong", "question_type": "reorder_4",
            "parts": [{"id": 1, "text": "A"}, {"id": 2, "text": "B"}, {"id": 3, "text": "C"}, {"id": 4, "text": "D"}],
            "correct_order": [1,2,3,4], "user_order": [2,1,3,4],
        }]})
        with connect() as conn:
            conn.execute("UPDATE attempts SET parts_json='[\"oops\"]' WHERE event_key='attempt:bad'")
            attempt = get_attempt(conn, "attempt:bad")
            self.assertTrue(attempt["_data_warnings"])
            rendered = render_attempt(attempt)
            self.assertIn("資料警告", rendered)
            export_all(conn)
            apply_safe_repairs(conn)
            export_all(conn)
        self.assertTrue((self.root / "data" / "exports" / "錯題.md").exists())

    def test_identical_cli_reimport_does_not_publish_another_backup(self) -> None:
        payload_path = self.root / "payload.json"
        payload_path.write_text(json.dumps({"items": [{
            "key": "vocab:猫", "type": "vocabulary", "display": "猫",
            "reading": "ねこ", "meanings": ["貓"],
        }]}, ensure_ascii=False), encoding="utf-8")
        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        command = [sys.executable, "-m", "jpnote_app", "import", str(payload_path), "--all", "--yes"]
        first = subprocess.run(command, env=env, text=True, capture_output=True, check=False)
        self.assertEqual(first.returncode, 0, first.stderr)
        before = list(active_backups())
        second = subprocess.run(command, env=env, text=True, capture_output=True, check=False)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(list(active_backups()), before)

    def test_legacy_relation_preflight_matches_apply_and_self_relation_is_rejected(self) -> None:
        self._import({"items": [
            {"key": "grammar:A", "type": "grammar", "display": "A"},
            {"key": "grammar:B", "type": "grammar", "display": "B"},
        ]})
        with sqlite3.connect(db_path()) as raw:
            raw.execute(
                "INSERT INTO grammar_relations(source_key,target_key,relation_type,note,source,created_at) VALUES(?,?,?,?,?,?)",
                ("grammar:A", "grammar:B", "相反／對比", "", "legacy", "2025-01-01T00:00:00+08:00"),
            )
        payload = {"items": [{
            "key": "grammar:A", "type": "grammar", "display": "A",
            "related_grammar": [{"key": "grammar:B", "relation": "對比", "note": ""}],
        }]}
        with connect_preflight() as conn:
            report = build_preflight_report(conn, prepare_import(conn, payload))
        self.assertEqual(report["summary"]["new_relations"], 1)
        with self.assertRaisesRegex(ValueError, "指向自己的 relation"):
            normalize_payload({"items": [{
                "key": "grammar:A", "type": "grammar", "display": "A",
                "related_grammar": [{"key": "grammar:A", "relation": "意思相近"}],
            }]})


if __name__ == "__main__":
    unittest.main()
