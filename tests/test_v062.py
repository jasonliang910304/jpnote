from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jpnote_app import ui_fzf
from jpnote_app.audit import run_audit
from jpnote_app.db import active_backups, connect, create_backup, mutation_backup
from jpnote_app.fs_utils import atomic_write_text
from jpnote_app.fzf_search_helper import matches
from jpnote_app.repository import search_entries
from jpnote_app.services import apply_import, prepare_import
from jpnote_app.validation import normalize_payload, normalize_sources


class V062Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        os.environ["JPNOTE_DATA_DIR"] = str(self.root / "data")
        os.environ["JPNOTE_CONFIG_FILE"] = str(self.root / "config" / "config.json")

    def tearDown(self) -> None:
        os.environ.pop("JPNOTE_DATA_DIR", None)
        os.environ.pop("JPNOTE_CONFIG_FILE", None)
        self.temp.cleanup()

    def test_fzf_reload_helper_matches_hidden_romaji_metadata(self) -> None:
        line = "entry:vocab:奇跡\t/tmp/preview\t[單字] 奇跡 きせき／N1\tki se ki kiseki\n"
        self.assertTrue(matches(line, "kiseki"))
        self.assertTrue(matches(line, "ki se ki"))
        self.assertTrue(matches(line, "奇跡"))
        self.assertFalse(matches(line, "kyoshitsu"))

    @patch("jpnote_app.ui_fzf.shutil.which", return_value="/usr/bin/fzf")
    @patch("jpnote_app.ui_fzf.subprocess.run")
    def test_fzf_uses_core_reload_search_instead_of_nth_matching(self, run, _which) -> None:
        run.return_value.returncode = 130
        run.return_value.stdout = ""
        run.return_value.stderr = ""
        ui_fzf._run(["entry:vocab:奇跡\t奇跡\tki se ki kiseki"], "測試", multi=False)
        command = run.call_args.args[0]
        self.assertIn("--disabled", command)
        self.assertTrue(any(arg.startswith("--bind=change:reload(") for arg in command))
        self.assertFalse(any(arg.startswith("--nth=") for arg in command))

    @patch("jpnote_app.ui_fzf.shutil.which", return_value="/usr/bin/fzf")
    @patch("jpnote_app.ui_fzf.subprocess.run")
    def test_fzf_real_error_is_not_treated_as_cancel(self, run, _which) -> None:
        run.return_value.returncode = 2
        run.return_value.stdout = ""
        run.return_value.stderr = "bad option"
        with self.assertRaisesRegex(RuntimeError, "bad option"):
            ui_fzf._run(["token\tvisible\tmetadata"], "測試", multi=False)

    def test_atomic_output_does_not_chmod_arbitrary_parent(self) -> None:
        directory = self.root / "public-output"
        directory.mkdir(mode=0o755)
        if os.name == "posix":
            directory.chmod(0o755)
        atomic_write_text(directory / "report.json", "{}\n")
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o755)

    def test_manual_sources_use_shared_validation(self) -> None:
        with self.assertRaisesRegex(ValueError, "sources 必須是陣列"):
            normalize_sources("abc")
        with self.assertRaisesRegex(ValueError, "終端控制字元"):
            normalize_sources(["safe\x1b[31mRED"])

    def test_conflicting_same_batch_event_key_is_rejected(self) -> None:
        payload = {
            "attempts": [
                {"event_key": "attempt:same", "result": "wrong", "prompt": "A"},
                {"event_key": "attempt:same", "result": "wrong", "prompt": "B"},
            ]
        }
        with self.assertRaisesRegex(ValueError, "相同 event_key 但內容不同"):
            normalize_payload(payload)

    def test_identical_same_batch_event_key_is_deduplicated(self) -> None:
        attempt = {"event_key": "attempt:same", "result": "wrong", "prompt": "A"}
        _source, _items, attempts, notes = normalize_payload({"attempts": [attempt, dict(attempt)]})
        self.assertEqual(len(attempts), 1)
        self.assertTrue(any("已去重" in note for note in notes))

    def test_audit_fails_soft_on_non_string_alias_element(self) -> None:
        with connect() as conn:
            apply_import(conn, prepare_import(conn, {
                "items": [{
                    "key": "vocab:猫", "type": "vocabulary", "display": "猫",
                    "reading": "ねこ", "romaji": "ne ko", "meanings": ["貓"],
                }]
            }))
            conn.execute("UPDATE entries SET aliases_json='[1]' WHERE key='vocab:猫'")
            issues = run_audit(conn)
        self.assertTrue(any(issue.code == "invalid_aliases_json" for issue in issues))

    def test_like_wildcards_are_literal_search_text(self) -> None:
        with connect() as conn:
            apply_import(conn, prepare_import(conn, {
                "items": [{
                    "key": "vocab:猫", "type": "vocabulary", "display": "猫",
                    "reading": "ねこ", "romaji": "ne ko", "meanings": ["貓"],
                }]
            }))
            self.assertEqual(search_entries(conn, "%"), [])
            self.assertEqual(search_entries(conn, "_"), [])

    def test_failed_mutation_backup_is_removed_without_pruning_old_backup(self) -> None:
        with connect():
            pass
        old = create_backup("old")
        self.assertIsNotNone(old)
        before = set(active_backups())
        with self.assertRaisesRegex(RuntimeError, "boom"):
            with mutation_backup("failing"):
                raise RuntimeError("boom")
        self.assertEqual(set(active_backups()), before)

    def test_json_import_stdout_is_one_json_document(self) -> None:
        payload = {
            "items": [
                {"key": "vocab:猫", "type": "vocabulary", "display": "猫", "reading": "ねこ", "romaji": "ne ko", "meanings": ["貓"]},
                {"key": "vocab:猫", "type": "vocabulary", "display": "猫", "reading": "ねこ", "romaji": "ne ko", "meanings": ["貓科動物"]},
            ]
        }
        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        payload_path = self.root / "payload.json"
        payload_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, "-m", "jpnote_app", "import", str(payload_path), "--all", "--yes", "--format", "json"],
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        parsed = json.loads(proc.stdout)
        self.assertIn("result", parsed)
        self.assertNotIn("注意：", proc.stdout)
        self.assertIn("注意：", proc.stderr)


if __name__ == "__main__":
    unittest.main()
