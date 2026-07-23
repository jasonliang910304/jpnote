from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch
from pathlib import Path

from jpnote_app.audit import apply_safe_repairs, run_audit
from jpnote_app.cli import _run_import_text, build_parser
from jpnote_app.db import connect, connect_preflight
from jpnote_app.import_preflight import build_preflight_report
from jpnote_app.import_safe_fixes import apply_safe_import_fixes
from jpnote_app.repository import get_entry
from jpnote_app.services import apply_import, prepare_import


class V0663Tests(unittest.TestCase):
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

    def _run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        return subprocess.run(
            [sys.executable, "-m", "jpnote_app", *args],
            text=True,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            env=env,
            check=False,
        )

    def test_audit_and_repair_clean_redundant_aliases_and_senses(self) -> None:
        self._import({"items": [{
            "key": "vocab:遅刻", "type": "vocabulary", "display": "遅刻",
            "reading": "ちこく", "aliases": ["遅刻", "ちこく", "遅刻する"],
            "senses": [
                {"meaning": "遲到", "example_ja": "遅刻した。", "example_zh": "遲到了。"},
                {"meaning": "遲到", "example_ja": "", "example_zh": ""},
            ],
        }]})
        with connect() as conn:
            issues = run_audit(conn)
            self.assertTrue(any(i.code == "aliases_need_cleanup" and i.key == "vocab:遅刻" for i in issues))
            self.assertTrue(any(i.code == "redundant_sense" and i.key == "vocab:遅刻" for i in issues))
            actions = apply_safe_repairs(conn)
            self.assertTrue(actions)
            entry = get_entry(conn, "vocab:遅刻")
        self.assertEqual(entry["aliases"], ["遅刻する"])
        self.assertEqual(len(entry["senses"]), 1)
        self.assertEqual(entry["senses"][0]["example_ja"], "遅刻した。")

    def test_distinct_nonempty_examples_are_preserved_and_reviewed(self) -> None:
        self._import({"items": [{
            "key": "grammar:すぎる", "type": "grammar", "display": "すぎる",
            "senses": [
                {"meaning": "過度", "example_ja": "食べすぎた。", "example_zh": "吃太多了。"},
                {"meaning": "過度", "example_ja": "高すぎる。", "example_zh": "太貴了。"},
            ],
        }]})
        with connect() as conn:
            issues = run_audit(conn)
            self.assertTrue(any(i.code == "same_meaning_multiple_examples" for i in issues))
            apply_safe_repairs(conn)
            entry = get_entry(conn, "grammar:すぎる")
        self.assertEqual(len(entry["senses"]), 2)

    def test_safe_import_fix_removes_blank_incoming_sense_covered_by_existing(self) -> None:
        self._import({"items": [{
            "key": "vocab:会議", "type": "vocabulary", "display": "会議",
            "reading": "かいぎ", "senses": [{
                "meaning": "會議", "example_ja": "会議に出る。", "example_zh": "參加會議。"
            }],
        }]})
        payload = {"items": [{
            "key": "vocab:会議", "type": "vocabulary", "display": "会議",
            "reading": "かいぎ", "aliases": ["会議", "かいぎ", "会議する"],
            "meanings": ["會議"],
        }]}
        with connect_preflight() as conn:
            plan = prepare_import(conn, payload)
            report = build_preflight_report(conn, plan)
            self.assertGreaterEqual(report["summary"]["safe_fixes"], 1)
            fixed, actions = apply_safe_import_fixes(conn, plan)
            fixed_report = build_preflight_report(conn, fixed)
        self.assertTrue(actions)
        self.assertEqual(fixed_report["summary"]["safe_fixes"], 0)
        with connect() as conn:
            apply_import(conn, fixed)
            entry = get_entry(conn, "vocab:会議")
        self.assertEqual(entry["aliases"], ["会議する"])
        self.assertEqual(len(entry["senses"]), 1)
        self.assertEqual(entry["senses"][0]["example_ja"], "会議に出る。")

    def test_safe_import_fix_removes_existing_blank_when_richer_sense_arrives(self) -> None:
        self._import({"items": [{
            "key": "vocab:試合", "type": "vocabulary", "display": "試合",
            "reading": "しあい", "meanings": ["比賽"],
        }]})
        payload = {"items": [{
            "key": "vocab:試合", "type": "vocabulary", "display": "試合",
            "reading": "しあい", "senses": [{
                "meaning": "比賽", "example_ja": "試合を見る。", "example_zh": "看比賽。"
            }],
        }]}
        with connect_preflight() as conn:
            fixed, actions = apply_safe_import_fixes(conn, prepare_import(conn, payload))
        self.assertTrue(any(a["kind"] == "existing_blank_sense_shadowed" for a in actions))
        with connect() as conn:
            result = apply_import(conn, fixed)
            entry = get_entry(conn, "vocab:試合")
        self.assertEqual(result.updated_entries, 1)
        self.assertEqual(len(entry["senses"]), 1)
        self.assertEqual(entry["senses"][0]["example_ja"], "試合を見る。")

    def test_interactive_no_cancels_after_preflight_without_writing(self) -> None:
        text = json.dumps({"items": [{
            "key": "vocab:鳥", "type": "vocabulary", "display": "鳥", "reading": "とり",
            "meanings": ["鳥"],
        }]}, ensure_ascii=False)
        args = build_parser().parse_args(["import", "unused.json"])
        output = StringIO()
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="n"), redirect_stdout(output):
            result = _run_import_text(text, args)
        self.assertEqual(result, 0)
        self.assertIn("是否正式匯入", output.getvalue())
        self.assertIn("已取消", output.getvalue())
        with connect() as conn:
            self.assertIsNone(get_entry(conn, "vocab:鳥"))

    def test_noninteractive_import_requires_yes_after_preflight_and_does_not_write(self) -> None:
        path = self.root / "payload.json"
        path.write_text(json.dumps({"items": [{
            "key": "vocab:猫", "type": "vocabulary", "display": "猫", "reading": "ねこ",
            "meanings": ["貓"],
        }]}, ensure_ascii=False), encoding="utf-8")
        proc = self._run_cli("import", str(path))
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("非互動正式匯入需要 --yes", proc.stderr)
        self.assertIn("匯入預檢", proc.stdout)
        with connect() as conn:
            self.assertIsNone(get_entry(conn, "vocab:猫"))

    def test_yes_runs_preflight_applies_safe_fixes_and_imports_without_all(self) -> None:
        path = self.root / "payload.json"
        path.write_text(json.dumps({"items": [{
            "key": "vocab:食堂", "type": "vocabulary", "display": "食堂", "reading": "しょくどう",
            "aliases": ["食堂", "しょくどう", "食堂する"], "meanings": ["食堂"],
        }]}, ensure_ascii=False), encoding="utf-8")
        proc = self._run_cli("import", str(path), "--yes")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("匯入預檢", proc.stdout)
        with connect() as conn:
            entry = get_entry(conn, "vocab:食堂")
        self.assertEqual(entry["aliases"], ["食堂する"])

    def test_yes_cannot_bypass_attempt_conflict(self) -> None:
        self._import({"attempts": [{
            "event_key": "attempt:x", "result": "wrong", "question_type": "multiple_choice",
            "prompt": "A", "correct_answer": "1",
        }]})
        path = self.root / "conflict.json"
        path.write_text(json.dumps({"attempts": [{
            "event_key": "attempt:x", "result": "wrong", "question_type": "multiple_choice",
            "prompt": "B", "correct_answer": "2",
        }]}, ensure_ascii=False), encoding="utf-8")
        proc = self._run_cli("import", str(path), "--yes")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("不能以 yes 強行略過", proc.stderr)

    def test_json_yes_keeps_stdout_as_one_document(self) -> None:
        path = self.root / "payload.json"
        path.write_text(json.dumps({"items": [{
            "key": "vocab:犬", "type": "vocabulary", "display": "犬", "reading": "いぬ",
            "meanings": ["狗"],
        }]}, ensure_ascii=False), encoding="utf-8")
        proc = self._run_cli("import", str(path), "--yes", "--format", "json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        parsed = json.loads(proc.stdout)
        self.assertEqual(parsed["result"]["added_entries"], 1)
        self.assertIn('"database_modified": false', proc.stderr)


if __name__ == "__main__":
    unittest.main()
