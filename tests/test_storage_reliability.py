from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path

import jpnote_app.db as db_module
from jpnote_app.attempt_options import suspicious_option_migration_candidates
from jpnote_app.config import backup_dir, data_dir, db_path, export_dir
from jpnote_app.db import (
    active_backups,
    connect,
    create_backup,
    prune_backups,
    restore_database_from,
)
from jpnote_app.export_markdown import export_all
from jpnote_app.fzf_filter_helper import SHORTCUT_TOKENS, render_panel
from jpnote_app.preferences import write_preferences
from jpnote_app.services import apply_import, prepare_import


class StorageReliabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        os.environ["JPNOTE_DATA_DIR"] = str(self.root / "data")
        os.environ["JPNOTE_CONFIG_FILE"] = str(self.root / "config" / "config.json")

    def tearDown(self) -> None:
        os.environ.pop("JPNOTE_DATA_DIR", None)
        os.environ.pop("JPNOTE_CONFIG_FILE", None)
        self.temp.cleanup()

    def test_private_permissions_for_data_config_backup_and_exports(self) -> None:
        external_config_parent = self.root / "config"
        external_config_parent.mkdir(mode=0o755)
        if os.name == "posix":
            external_config_parent.chmod(0o755)
        with connect() as conn:
            export_all(conn)
        write_preferences({"browse": {"types": ["grammar", "vocab"], "levels": [], "results": []}})
        backup = create_backup("permissions")
        self.assertIsNotNone(backup)
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(data_dir().stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(db_path().stat().st_mode), 0o600)
            # Explicit JPNOTE_CONFIG_FILE parents are user-owned and must not be chmodded.
            self.assertEqual(stat.S_IMODE(external_config_parent.stat().st_mode), 0o755)
            self.assertEqual(stat.S_IMODE((external_config_parent / "config.json").stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)
            for path in export_dir().glob("*.md"):
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_undo_backups_are_pruned_by_total_size(self) -> None:
        backup_dir().mkdir(parents=True, exist_ok=True)
        paths = []
        for index in range(3):
            path = backup_dir() / f"undo-20260719T00000{index}-fake.db"
            path.write_bytes(b"x" * 6)
            os.utime(path, (100 + index, 100 + index))
            paths.append(path)
        old_cap = db_module.BACKUP_MAX_BYTES
        db_module.BACKUP_MAX_BYTES = 10
        try:
            prune_backups()
        finally:
            db_module.BACKUP_MAX_BYTES = old_cap
        remaining = active_backups()
        self.assertEqual(remaining, [paths[-1]])

    def test_corrupt_backup_is_rejected_before_restore(self) -> None:
        with connect():
            pass
        corrupt = backup_dir() / "undo-20260719T000000-corrupt.db"
        corrupt.write_bytes(b"not sqlite")
        with self.assertRaises(ValueError):
            restore_database_from(corrupt)

    def test_suspicious_legacy_options_are_reported_but_not_auto_migrated(self) -> None:
        with connect() as conn:
            apply_import(conn, prepare_import(conn, {
                "attempts": [{
                    "event_key": "attempt:suspicious-options",
                    "result": "wrong",
                    "question_type": "grammar",
                    "attempt_date": "2026-07-19",
                    "source": "TRY! N4",
                    "question": "問題1",
                    "prompt": "これは何ですか。選択肢：1 です／2 でした",
                }]
            }))
            suspicious = suspicious_option_migration_candidates(conn)
        self.assertEqual(len(suspicious), 1)
        self.assertEqual(suspicious[0]["event_key"], "attempt:suspicious-options")
        self.assertEqual(suspicious[0]["reason"], "explicit_option_marker")

    def test_filter_numeric_shortcuts_cover_common_choices(self) -> None:
        self.assertEqual(SHORTCUT_TOKENS["1"], "types:grammar")
        self.assertEqual(SHORTCUT_TOKENS["5"], "levels:N4")
        self.assertEqual(SHORTCUT_TOKENS["9"], "results:wrong")
        self.assertEqual(SHORTCUT_TOKENS["0"], "results:partial")
        panel = self.root / "panel.tsv"
        render_panel(panel, {"types": {"grammar", "vocab", "mistake"}, "levels": set(), "results": set()})
        text = panel.read_text(encoding="utf-8")
        self.assertIn("1–0 快速切換", text)
        self.assertIn("[✓] 3. 類型  錯題", text)
        self.assertIn("[ ] 9. 錯題結果  wrong", text)
        self.assertIn("[ ] 0. 錯題結果  partial", text)
        self.assertIn("等級  未分類", text)


if __name__ == "__main__":
    unittest.main()
