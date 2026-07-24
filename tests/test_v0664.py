from __future__ import annotations

import gc
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jpnote_app.api import JpnoteCore
from jpnote_app.cli import _run_import_text, build_parser
from jpnote_app.config import backup_dir, db_path, export_dir
from jpnote_app.db import active_backups, connect, connect_preflight, now_text, recover_orphaned_pending_backups
from jpnote_app.repository import get_entry
from jpnote_app.services import apply_import, prepare_import, replace_entry_data
from jpnote_app.validation import normalize_sources, validate_item


class V0664Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        os.environ["JPNOTE_DATA_DIR"] = str(self.root / "data")

    def tearDown(self) -> None:
        os.environ.pop("JPNOTE_DATA_DIR", None)
        self.temp.cleanup()

    def _import(self, payload: dict) -> None:
        with connect() as conn:
            apply_import(conn, prepare_import(conn, payload))

    @staticmethod
    def _editable(entry: dict) -> dict:
        raw = {
            field: entry.get(field, "")
            for field in (
                "key", "type", "display", "reading", "romaji", "accent", "accent_type",
                "accent_display", "accent_note", "level", "review_group", "aliases",
                "origin_type", "origin_language", "origin_word", "origin_note", "senses",
            )
        }
        raw["related_grammar"] = [
            {"key": relation["key"], "relation": relation["relation"], "note": relation["note"]}
            for relation in entry.get("related_grammar", [])
        ]
        normalized = validate_item(raw)
        normalized["sources"] = normalize_sources(entry.get("sources"))
        return normalized

    def test_relation_edit_preserves_pending_rows_and_provenance(self) -> None:
        self._import({
            "source": "TRY N3",
            "items": [
                {
                    "key": "grammar:A", "type": "grammar", "display": "A",
                    "related_grammar": [
                        {"key": "grammar:B", "relation": "意思相近", "note": "old"},
                        {"key": "grammar:Missing", "relation": "容易混淆", "note": "pending"},
                    ],
                },
                {"key": "grammar:B", "type": "grammar", "display": "B"},
            ],
        })
        with connect() as conn:
            before_pending = dict(conn.execute(
                "SELECT * FROM pending_grammar_relations WHERE source_key='grammar:A'"
            ).fetchone())
            before_rows = {
                (row["source_key"], row["target_key"], row["relation_type"]):
                (row["source"], row["created_at"])
                for row in conn.execute(
                    "SELECT * FROM grammar_relations WHERE source_key IN ('grammar:A','grammar:B')"
                ).fetchall()
            }
            item = self._editable(get_entry(conn, "grammar:A", include_attempts=False))
            item["related_grammar"][0]["note"] = "new"
            replace_entry_data(conn, "grammar:A", item)

            after_pending = dict(conn.execute(
                "SELECT * FROM pending_grammar_relations WHERE source_key='grammar:A'"
            ).fetchone())
            after_rows = conn.execute(
                "SELECT * FROM grammar_relations WHERE source_key IN ('grammar:A','grammar:B')"
            ).fetchall()

        self.assertEqual(after_pending, before_pending)
        self.assertEqual(len(after_rows), 2)
        for row in after_rows:
            identity = (row["source_key"], row["target_key"], row["relation_type"])
            self.assertEqual((row["source"], row["created_at"]), before_rows[identity])
            self.assertEqual(row["note"], "new")

    def test_relation_edit_removes_only_selected_logical_pair(self) -> None:
        self._import({
            "source": "book",
            "items": [
                {
                    "key": "grammar:A", "type": "grammar", "display": "A",
                    "related_grammar": [
                        {"key": "grammar:B", "relation": "意思相近", "note": "AB"},
                        {"key": "grammar:C", "relation": "對比", "note": "AC"},
                        {"key": "grammar:Missing", "relation": "容易混淆", "note": "AM"},
                    ],
                },
                {"key": "grammar:B", "type": "grammar", "display": "B"},
                {"key": "grammar:C", "type": "grammar", "display": "C"},
            ],
        })
        with connect() as conn:
            item = self._editable(get_entry(conn, "grammar:A", include_attempts=False))
            item["related_grammar"] = [
                relation for relation in item["related_grammar"] if relation["key"] != "grammar:B"
            ]
            replace_entry_data(conn, "grammar:A", item)
            resolved = {
                (row["source_key"], row["target_key"], row["relation_type"], row["note"])
                for row in conn.execute("SELECT * FROM grammar_relations").fetchall()
            }
            pending = [dict(row) for row in conn.execute(
                "SELECT * FROM pending_grammar_relations ORDER BY id"
            ).fetchall()]

        self.assertNotIn(("grammar:A", "grammar:B", "意思相近", "AB"), resolved)
        self.assertNotIn(("grammar:B", "grammar:A", "意思相近", "AB"), resolved)
        self.assertIn(("grammar:A", "grammar:C", "對比", "AC"), resolved)
        self.assertIn(("grammar:C", "grammar:A", "對比", "AC"), resolved)
        self.assertEqual([(row["source_key"], row["target_key"]) for row in pending], [
            ("grammar:A", "grammar:Missing")
        ])

    def test_timestamps_include_microseconds(self) -> None:
        value = now_text()
        self.assertRegex(value, r"T\d{2}:\d{2}:\d{2}\.\d{6}[+-]\d{2}:\d{2}$")

    def test_explicit_import_selector_typo_is_an_error(self) -> None:
        text = '{"items":[{"key":"vocab:猫","type":"vocabulary","display":"猫"}]}'
        args = build_parser().parse_args(["import", "unused.json", "--item-key", "vocab:犬", "--yes"])
        with self.assertRaisesRegex(ValueError, "找不到 item key"):
            _run_import_text(text, args)

    def test_explicit_attempt_index_out_of_range_is_an_error(self) -> None:
        text = '{"attempts":[{"event_key":"attempt:x","result":"wrong"}]}'
        args = build_parser().parse_args(["import", "unused.json", "--attempt-index", "3", "--yes"])
        with self.assertRaisesRegex(ValueError, "attempt index 超出範圍"):
            _run_import_text(text, args)

    def test_public_api_import_uses_preflight_backup_and_export(self) -> None:
        core = JpnoteCore()
        first = core.apply_import({"items": [{
            "key": "vocab:猫", "type": "vocabulary", "display": "猫",
            "reading": "ねこ", "meanings": ["貓"],
        }]})
        self.assertTrue(first["modified"])
        self.assertEqual(first["backup"], "")

        second = core.apply_import({"items": [{
            "key": "vocab:猫", "type": "vocabulary", "display": "猫",
            "reading": "ねこ", "meanings": ["貓科動物"],
        }]})
        self.assertTrue(second["modified"])
        self.assertTrue(second["backup"])
        self.assertEqual(len(active_backups()), 1)
        self.assertTrue(any(export_dir().glob("*.md")))

    def test_safe_mutation_keeps_undo_backup_if_export_fails_after_commit(self) -> None:
        core = JpnoteCore()
        core.apply_import({"items": [{
            "key": "vocab:猫", "type": "vocabulary", "display": "猫",
            "reading": "ねこ", "meanings": ["貓"],
        }]})

        with patch("jpnote_app.mutations.export_all", side_effect=RuntimeError("export failed")):
            with self.assertRaisesRegex(RuntimeError, "export failed"):
                core.apply_import({"items": [{
                    "key": "vocab:猫", "type": "vocabulary", "display": "猫",
                    "reading": "ねこ", "meanings": ["貓科動物"],
                }]})

        with connect() as conn:
            entry = get_entry(conn, "vocab:猫", include_attempts=False)
        self.assertIn("貓科動物", {sense["meaning"] for sense in entry["senses"]})
        self.assertEqual(len(active_backups()), 1)

    def test_public_api_cannot_bypass_blocking_import_conflict(self) -> None:
        core = JpnoteCore()
        core.apply_import({"attempts": [{
            "event_key": "attempt:x", "result": "wrong",
            "question_type": "multiple_choice", "prompt": "A", "correct_answer": "1",
        }]})
        before = len(active_backups())
        with self.assertRaisesRegex(ValueError, "不可略過"):
            core.apply_import({"attempts": [{
                "event_key": "attempt:x", "result": "wrong",
                "question_type": "multiple_choice", "prompt": "B", "correct_answer": "2",
            }]})
        self.assertEqual(len(active_backups()), before)

    def test_public_api_duplicate_warning_requires_explicit_acceptance(self) -> None:
        core = JpnoteCore()
        core.apply_import({"items": [{
            "key": "vocab:猫", "type": "vocabulary", "display": "猫", "reading": "ねこ",
        }]})
        with self.assertRaisesRegex(ValueError, "accept_warnings"):
            core.apply_import({"items": [{
                "key": "vocab:ねこ", "type": "vocabulary", "display": "猫", "reading": "ねこ",
            }]})
        with connect() as conn:
            self.assertIsNone(get_entry(conn, "vocab:ねこ"))

    def test_dead_process_pending_snapshot_is_promoted_on_next_connect(self) -> None:
        self._import({"items": [
            {"key": "vocab:猫", "type": "vocabulary", "display": "猫", "reading": "ねこ"}
        ]})
        pending = backup_dir() / ".pending-20260724T120000-000000-pid999999-crash.db"
        shutil.copy2(db_path(), pending)

        with connect() as conn:
            conn.execute("SELECT 1").fetchone()

        self.assertFalse(pending.exists())
        recovered = [path for path in active_backups() if "recovered" in path.name]
        self.assertEqual(len(recovered), 1)

    def test_live_process_pending_snapshot_is_not_promoted(self) -> None:
        self._import({"items": [
            {"key": "vocab:犬", "type": "vocabulary", "display": "犬", "reading": "いぬ"}
        ]})
        pending = backup_dir() / f".pending-20260724T120000-000000-pid{os.getpid()}-active.db"
        shutil.copy2(db_path(), pending)

        recovered = recover_orphaned_pending_backups()

        self.assertEqual(recovered, [])
        self.assertTrue(pending.exists())

    def test_repeated_preflight_does_not_leak_file_descriptors(self) -> None:
        proc_fd = Path("/proc/self/fd")
        if not proc_fd.is_dir():
            self.skipTest("requires Linux /proc/self/fd")
        self._import({"items": [
            {"key": "vocab:猫", "type": "vocabulary", "display": "猫", "reading": "ねこ"}
        ]})
        was_enabled = gc.isenabled()
        gc.disable()
        try:
            before = len(list(proc_fd.iterdir()))
            for _ in range(100):
                with connect_preflight() as conn:
                    conn.execute("SELECT COUNT(*) FROM entries").fetchone()
            after = len(list(proc_fd.iterdir()))
        finally:
            if was_enabled:
                gc.enable()
        self.assertLessEqual(after - before, 2)


if __name__ == "__main__":
    unittest.main()
