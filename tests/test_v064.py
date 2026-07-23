from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jpnote_app.attempt_options import normalized_options
from jpnote_app.audit import run_audit
from jpnote_app.config import db_path
from jpnote_app.db import connect, connect_preflight
from jpnote_app.import_preflight import build_preflight_report
from jpnote_app.romaji import spaced_hepburn
from jpnote_app.services import apply_import, prepare_import
from jpnote_app.validation import normalize_payload, parse_payload, validate_attempt, validate_item


class V064Tests(unittest.TestCase):
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

    def test_preflight_snapshot_does_not_create_real_database(self) -> None:
        self.assertFalse(db_path().exists())
        with connect_preflight() as conn:
            report = build_preflight_report(conn, prepare_import(conn, {
                "items": [{"key": "vocab:猫", "type": "vocabulary", "display": "猫", "reading": "ねこ"}]
            }))
        self.assertFalse(db_path().exists())
        self.assertFalse(report["database_modified"])
        self.assertEqual(report["items"][0]["status"], "new")

    def test_cli_check_does_not_create_database(self) -> None:
        payload = self.root / "payload.json"
        payload.write_text(json.dumps({
            "items": [{"key": "vocab:猫", "type": "vocabulary", "display": "猫", "reading": "ねこ"}]
        }, ensure_ascii=False), encoding="utf-8")
        env = dict(os.environ)
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        result = subprocess.run(
            [sys.executable, "-m", "jpnote_app", "import", str(payload), "--check", "--all", "--format", "json"],
            cwd=Path(__file__).resolve().parents[1], env=env, text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(db_path().exists())
        self.assertFalse(json.loads(result.stdout)["database_modified"])

    def test_preflight_migrates_only_memory_snapshot(self) -> None:
        self._import({
            "items": [
                {"key": "grammar:A", "type": "grammar", "display": "A"},
                {"key": "grammar:B", "type": "grammar", "display": "B"},
            ]
        })
        with sqlite3.connect(db_path()) as raw:
            raw.execute(
                "INSERT INTO grammar_relations(source_key,target_key,relation_type,note,source,created_at) VALUES(?,?,?,?,?,?)",
                ("grammar:A", "grammar:B", "相反／對比", "", "test", "2026-01-01T00:00:00+08:00"),
            )
        with connect_preflight() as snapshot:
            relation = snapshot.execute("SELECT relation_type FROM grammar_relations").fetchone()[0]
            # v0.6.6.2 keeps legacy data values visible in preflight so the
            # classifier matches real apply instead of reporting unchanged.
            self.assertEqual(relation, "相反／對比")
        with sqlite3.connect(db_path()) as raw:
            relation = raw.execute("SELECT relation_type FROM grammar_relations").fetchone()[0]
            self.assertEqual(relation, "相反／對比")

    def test_preflight_and_apply_share_unchanged_entry_outcome(self) -> None:
        payload = {
            "source": "book",
            "items": [{"key": "vocab:猫", "type": "vocabulary", "display": "猫", "reading": "ねこ"}],
        }
        self._import(payload)
        with connect_preflight() as conn:
            plan = prepare_import(conn, payload)
            report = build_preflight_report(conn, plan)
        self.assertEqual(report["items"][0]["status"], "unchanged")
        with connect() as conn:
            result = apply_import(conn, prepare_import(conn, payload))
        self.assertEqual(result.unchanged_entries, 1)

    def test_attempt_same_identity_different_content_is_conflict_in_preflight_and_apply(self) -> None:
        base = {
            "date": "2026-07-19", "source": "TRY! N4", "section": "第1課",
            "question": "問題1", "question_type": "multiple_choice",
            "user_answer": "2", "result": "wrong", "reason": "old",
        }
        self._import({"attempts": [{**base, "event_key": "attempt:legacy"}]})
        incoming = {"attempts": [{**base, "result": "partial", "reason": "corrected"}]}
        with connect_preflight() as conn:
            plan = prepare_import(conn, incoming)
            report = build_preflight_report(conn, plan)
        self.assertEqual(report["attempts"][0]["status"], "conflict")
        with connect() as conn:
            with self.assertRaisesRegex(ValueError, "identity 相同但內容不同"):
                apply_import(conn, prepare_import(conn, incoming))

    def test_attempt_locator_normalizes_width_and_spacing(self) -> None:
        a = validate_attempt({
            "date": "2026-07-19", "source": "TRY! N4", "section": "第 1 課",
            "question": "問題 3", "question_type": "multiple_choice", "user_answer": "2",
        })
        b = validate_attempt({
            "date": "2026-07-19", "source": "TRY! N4", "section": "第１課",
            "question": "問題３", "question_type": "multiple_choice", "user_answer": "2",
        })
        self.assertEqual(a["event_key"], b["event_key"])

    def test_strict_json_types_reject_silent_coercion(self) -> None:
        with self.assertRaisesRegex(ValueError, "display 必須是字串"):
            validate_item({"key": "vocab:猫", "type": "vocabulary", "display": ["猫"]})
        with self.assertRaisesRegex(ValueError, "aliases 的元素.*必須是字串"):
            validate_item({"key": "vocab:猫", "type": "vocabulary", "display": "猫", "aliases": [123]})
        with self.assertRaisesRegex(ValueError, "suggested 必須是 true 或 false"):
            validate_item({"key": "vocab:猫", "type": "vocabulary", "display": "猫", "suggested": "false"})
        with self.assertRaisesRegex(ValueError, "options.id 必須是正整數"):
            normalized_options([{"id": 1.9, "text": "x"}])
        with self.assertRaisesRegex(ValueError, "options.id 必須是正整數"):
            normalized_options([{"id": True, "text": "x"}])
        with self.assertRaisesRegex(ValueError, "correct_order 必須只包含整數"):
            validate_attempt({
                "question_type": "reorder_4", "parts": [
                    {"id": 1, "text": "a"}, {"id": 2, "text": "b"},
                    {"id": 3, "text": "c"}, {"id": 4, "text": "d"},
                ], "correct_order": [1.0, 2, 3, 4], "user_order": [], "result": "wrong",
            })

    def test_invisible_unicode_is_rejected_in_identifiers(self) -> None:
        with self.assertRaisesRegex(ValueError, "不可見的 Unicode"):
            validate_item({"key": "vocab:猫\u200b", "type": "vocabulary", "display": "猫"})
        with self.assertRaisesRegex(ValueError, "不可見的 Unicode"):
            validate_attempt({"event_key": "attempt:x\u202e", "result": "wrong"})

    def test_same_batch_same_key_core_conflict_is_rejected(self) -> None:
        with connect_preflight() as conn:
            with self.assertRaisesRegex(ValueError, "核心欄位衝突"):
                prepare_import(conn, {"items": [
                    {"key": "vocab:X", "type": "vocabulary", "display": "猫", "reading": "ねこ"},
                    {"key": "vocab:X", "type": "vocabulary", "display": "犬", "reading": "いぬ"},
                ]})

    def test_romaji_converter_fails_closed_on_incomplete_sokuon_or_long_mark(self) -> None:
        self.assertEqual(spaced_hepburn("あっ"), "")
        self.assertEqual(spaced_hepburn("っん"), "")
        self.assertEqual(spaced_hepburn("ーア"), "")
        self.assertEqual(spaced_hepburn("コンピューター"), "ko n pyū tā")

    def test_audit_reports_reorder_order_corruption_and_timestamp_issues(self) -> None:
        self._import({
            "source": "book",
            "items": [{"key": "vocab:A", "type": "vocabulary", "display": "A", "reading": "えー"}],
            "attempts": [{
                "event_key": "attempt:bad-audit", "date": "2026-07-19", "result": "wrong",
                "question_type": "reorder_4",
                "parts": [{"id": 1, "text": "a"}, {"id": 2, "text": "b"}, {"id": 3, "text": "c"}, {"id": 4, "text": "d"}],
                "correct_order": [1, 2, 3, 4], "user_order": [], "linked_entries": ["vocab:A"],
            }],
        })
        with connect() as conn:
            conn.execute("UPDATE attempts SET correct_order_json='[1,2,3]', user_order_json='[1,1,1,1]', attempt_date='2099-12-31', created_at='bad' WHERE event_key='attempt:bad-audit'")
            conn.execute("UPDATE entries SET created_at='bad', updated_at='bad' WHERE key='vocab:A'")
            conn.execute("UPDATE sources SET added_at='bad' WHERE entry_key='vocab:A'")
            codes = {issue.code for issue in run_audit(conn)}
        self.assertIn("invalid_reorder_correct_order", codes)
        self.assertIn("invalid_reorder_user_order", codes)
        self.assertIn("future_attempt_date", codes)
        self.assertIn("invalid_attempt_timestamp", codes)
        self.assertIn("invalid_entry_timestamp", codes)
        self.assertIn("invalid_source_timestamp", codes)

    def test_legacy_auto_identity_same_content_is_duplicate_in_preflight_and_apply(self) -> None:
        base = {
            "date": "2026-07-19", "source": "TRY! N4", "section": "第1課",
            "question": "問題1", "question_type": "multiple_choice",
            "user_answer": "2", "result": "wrong", "reason": "same",
        }
        self._import({"attempts": [{**base, "event_key": "attempt:legacy-old-hash"}]})
        incoming = {"attempts": [base]}
        with connect_preflight() as conn:
            report = build_preflight_report(conn, prepare_import(conn, incoming))
        self.assertEqual(report["attempts"][0]["status"], "duplicate")
        with connect() as conn:
            result = apply_import(conn, prepare_import(conn, incoming))
            count = conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
        self.assertEqual(result.skipped_attempts, 1)
        self.assertEqual(count, 1)

    def test_payload_container_types_are_strict(self) -> None:
        parsed = parse_payload('{"items": {}, "attempts": []}')
        with self.assertRaisesRegex(ValueError, "items 與 attempts 都必須是陣列"):
            normalize_payload(parsed)
        with self.assertRaisesRegex(ValueError, "date 必須是字串"):
            validate_attempt({"date": 20260719})

    def test_manual_command_reads_bundled_user_guide(self) -> None:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        result = subprocess.run(
            [sys.executable, "-m", "jpnote_app", "manual"],
            cwd=Path(__file__).resolve().parents[1], env=env, text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Part 1：安裝與升級", result.stdout)
        self.assertIn("jpnote paste --check --all", result.stdout)
        self.assertIn("jpnote attempts migrate-options", result.stdout)



if __name__ == "__main__":
    unittest.main()
