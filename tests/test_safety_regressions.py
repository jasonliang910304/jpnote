from __future__ import annotations

import os
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

from jpnote_app.audit import apply_safe_repairs, run_audit
from jpnote_app.config import SCHEMA_VERSION, db_path
from jpnote_app.config import VERSION
from jpnote_app.db import connect
from jpnote_app.repository import find_exact_entry, get_attempt, get_entry
from jpnote_app.services import apply_import, filter_import_plan, prepare_import
from jpnote_app.validation import validate_attempt, validate_item


class SafetyRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        os.environ["JPNOTE_DATA_DIR"] = str(Path(self.temp.name) / "data")

    def tearDown(self) -> None:
        os.environ.pop("JPNOTE_DATA_DIR", None)
        self.temp.cleanup()

    def _import(self, payload: dict) -> None:
        with connect() as conn:
            apply_import(conn, prepare_import(conn, payload))

    def test_ambiguous_display_does_not_auto_resolve(self) -> None:
        self._import({
            "items": [
                {"key": "grammar:同名", "type": "grammar", "display": "同名", "meanings": ["文法"]},
                {"key": "vocab:同名", "type": "vocabulary", "display": "同名", "reading": "どうめい", "meanings": ["單字"]},
            ]
        })
        with connect() as conn:
            self.assertIsNone(find_exact_entry(conn, "同名"))
            self.assertEqual(find_exact_entry(conn, "grammar:同名")["key"], "grammar:同名")

    def test_duplicate_attempt_is_true_noop_and_does_not_add_links(self) -> None:
        self._import({
            "items": [
                {"key": "vocab:A", "type": "vocabulary", "display": "A", "reading": "えー", "meanings": ["A"]},
                {"key": "vocab:B", "type": "vocabulary", "display": "B", "reading": "びー", "meanings": ["B"]},
            ],
            "attempts": [{
                "event_key": "attempt:dup",
                "result": "wrong",
                "question_type": "other",
                "linked_entries": ["vocab:A"],
            }],
        })
        with connect() as conn:
            with self.assertRaisesRegex(ValueError, "identity 相同但內容不同"):
                apply_import(conn, prepare_import(conn, {
                    "attempts": [{
                        "event_key": "attempt:dup",
                        "result": "wrong",
                        "question_type": "other",
                        "linked_entries": ["vocab:B"],
                    }]
                }))
            self.assertEqual(get_attempt(conn, "attempt:dup")["linked_entries"], ["vocab:A"])

    def test_nested_transaction_rolls_back_inner_work_with_outer_failure(self) -> None:
        conn = connect()
        with self.assertRaises(RuntimeError):
            with conn:
                with conn:
                    conn.execute("INSERT INTO metadata(key, value) VALUES('nested-test', '1')")
                raise RuntimeError("force outer rollback")
        with connect() as check:
            row = check.execute("SELECT value FROM metadata WHERE key='nested-test'").fetchone()
            self.assertIsNone(row)

    def test_keys_and_terminal_controls_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            validate_item({"key": "grammar:", "type": "grammar", "display": "x"})
        with self.assertRaises(ValueError):
            validate_item({"key": "grammar:x\ny", "type": "grammar", "display": "x"})
        with self.assertRaises(ValueError):
            validate_attempt({"event_key": "attempt:x\ty", "result": "wrong"})
        with self.assertRaises(ValueError):
            validate_item({"key": "grammar:x", "type": "grammar", "display": "bad\x1b]52;c;AAAA\x07"})

    def test_related_grammar_requires_key_and_relation(self) -> None:
        with self.assertRaises(ValueError):
            validate_item({
                "key": "grammar:A", "type": "grammar", "display": "A",
                "related_grammar": [{"relation": "對比"}],
            })
        with self.assertRaises(ValueError):
            validate_item({
                "key": "grammar:A", "type": "grammar", "display": "A",
                "related_grammar": [{"key": "grammar:B"}],
            })

    def test_reorder_parts_cannot_be_empty(self) -> None:
        with self.assertRaises(ValueError):
            validate_attempt({
                "event_key": "attempt:empty-parts",
                "question_type": "reorder_4",
                "result": "wrong",
                "parts": [
                    {"id": 1, "text": ""}, {"id": 2, "text": "b"},
                    {"id": 3, "text": "c"}, {"id": 4, "text": "d"},
                ],
                "correct_order": [1, 2, 3, 4],
                "user_order": [],
            })

    def test_repair_preserves_malformed_alias_json_and_skips_unsupported_romaji(self) -> None:
        self._import({
            "items": [{
                "key": "vocab:ヷ", "type": "vocabulary", "display": "ヷ",
                "reading": "ヷ", "meanings": ["unsupported"],
            }]
        })
        with connect() as conn:
            conn.execute("UPDATE entries SET aliases_json = ? WHERE key = ?", ("{broken", "vocab:ヷ"))
            before = conn.execute("SELECT aliases_json FROM entries WHERE key=?", ("vocab:ヷ",)).fetchone()[0]
            issues = run_audit(conn)
            self.assertTrue(any(issue.code == "invalid_aliases_json" for issue in issues))
            missing = [issue for issue in issues if issue.code == "missing_romaji" and issue.key == "vocab:ヷ"]
            self.assertEqual(len(missing), 1)
            self.assertFalse(missing[0].fixable)
            apply_safe_repairs(conn)
            after = conn.execute("SELECT aliases_json FROM entries WHERE key=?", ("vocab:ヷ",)).fetchone()[0]
            self.assertEqual(after, before)
            self.assertEqual(get_entry(conn, "vocab:ヷ")["romaji"], "")

    def test_future_schema_is_rejected_without_downgrade(self) -> None:
        with connect() as conn:
            pass
        with sqlite3.connect(db_path()) as raw:
            raw.execute(
                "INSERT INTO metadata(key, value) VALUES('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(SCHEMA_VERSION + 100),),
            )
        with self.assertRaises(RuntimeError):
            connect()
        with sqlite3.connect(db_path()) as raw:
            value = raw.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0]
        self.assertEqual(value, str(SCHEMA_VERSION + 100))

    def test_selective_import_drops_batch_warning_if_other_item_not_selected(self) -> None:
        with connect() as conn:
            plan = prepare_import(conn, {
                "items": [
                    {"key": "vocab:A", "type": "vocabulary", "display": "同じ", "reading": "おなじ"},
                    {"key": "vocab:B", "type": "vocabulary", "display": "同じ", "reading": "おなじ"},
                ]
            })
        self.assertTrue(any(w.scope == "batch" for w in plan.warnings))
        filtered = filter_import_plan(plan, {"vocab:A"}, set())
        self.assertFalse(any(w.scope == "batch" for w in filtered.warnings))


class InstallerRegressionTests(unittest.TestCase):
    def test_installer_replaces_symlink_without_overwriting_target(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            bin_dir = home / ".local" / "bin"
            bin_dir.mkdir(parents=True)
            target = home / "external-launcher"
            target.write_text("ORIGINAL\n", encoding="utf-8")
            launcher = bin_dir / "jpnote"
            launcher.symlink_to(target)
            env = dict(os.environ)
            env["HOME"] = str(home)
            result = subprocess.run(
                ["sh", str(root / "install.sh")],
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(target.read_text(encoding="utf-8"), "ORIGINAL\n")
            self.assertTrue(launcher.is_file())
            self.assertFalse(launcher.is_symlink())
            self.assertIn(VERSION, launcher.read_text(encoding="utf-8"))
            guide = home / ".local" / "lib" / "jpnote" / VERSION / "docs" / "USER_GUIDE.md"
            self.assertTrue(guide.is_file())
            self.assertIn("安裝與升級", guide.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
