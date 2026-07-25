from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from jpnote_app.cli import build_parser, command_paste
from jpnote_app.db import connect
from jpnote_app.repository import get_entry


class PasteStdinTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        os.environ["JPNOTE_DATA_DIR"] = str(self.root / "data")

    def tearDown(self) -> None:
        os.environ.pop("JPNOTE_DATA_DIR", None)
        self.temp.cleanup()

    def _run_cli(
        self,
        *args: str,
        input_text: str,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        return subprocess.run(
            [sys.executable, "-m", "jpnote_app", *args],
            input=input_text,
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )

    def test_default_paste_still_reads_wayland_clipboard(self) -> None:
        args = build_parser().parse_args(["paste", "--check"])
        with (
            patch("jpnote_app.cli._read_clipboard", return_value="clipboard-json") as read_clipboard,
            patch("jpnote_app.cli._run_import_text", return_value=7) as run_import,
        ):
            result = command_paste(args)
        self.assertEqual(result, 7)
        read_clipboard.assert_called_once_with()
        run_import.assert_called_once_with("clipboard-json", args)

    def test_stdin_reads_complete_text_and_uses_shared_import_pipeline(self) -> None:
        args = build_parser().parse_args(["paste", "--stdin", "--check"])
        source = StringIO("line 1\nline 2\n")
        with (
            patch("sys.stdin", source),
            patch(
                "jpnote_app.cli._read_clipboard",
                side_effect=AssertionError("stdin mode must not read clipboard"),
            ),
            patch("jpnote_app.cli._run_import_text", return_value=11) as run_import,
        ):
            result = command_paste(args)
        self.assertEqual(result, 11)
        run_import.assert_called_once_with("line 1\nline 2\n", args)

    def test_stdin_check_runs_the_existing_preflight_pipeline(self) -> None:
        payload = json.dumps(
            {
                "items": [
                    {
                        "key": "vocab:猫",
                        "type": "vocabulary",
                        "display": "猫",
                        "reading": "ねこ",
                        "meanings": ["貓"],
                    }
                ]
            },
            ensure_ascii=False,
        )
        proc = self._run_cli(
            "paste",
            "--stdin",
            "--check",
            "--format",
            "json",
            input_text=payload,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        report = json.loads(proc.stdout)
        self.assertFalse(report["database_modified"])
        self.assertEqual(report["summary"]["new_items"], 1)

    def test_stdin_yes_runs_the_existing_safe_import_pipeline(self) -> None:
        payload = json.dumps(
            {
                "items": [
                    {
                        "key": "vocab:犬",
                        "type": "vocabulary",
                        "display": "犬",
                        "reading": "いぬ",
                        "meanings": ["狗"],
                    }
                ]
            },
            ensure_ascii=False,
        )
        proc = self._run_cli(
            "paste",
            "--stdin",
            "--yes",
            input_text=payload,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("正式匯入前完整預檢", proc.stdout)
        with connect() as conn:
            entry = get_entry(conn, "vocab:犬")
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry["display"], "犬")


if __name__ == "__main__":
    unittest.main()
