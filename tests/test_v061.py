from __future__ import annotations

import unittest
from unittest.mock import patch

from jpnote_app import ui_fzf
from jpnote_app.cli import build_parser


class V061Tests(unittest.TestCase):
    @patch("jpnote_app.ui_fzf.shutil.which", return_value="/usr/bin/fzf")
    @patch("jpnote_app.ui_fzf.subprocess.run")
    def test_browse_fzf_searches_visible_and_hidden_columns(self, run, _which) -> None:
        run.return_value.returncode = 1
        run.return_value.stdout = ""
        run.return_value.stderr = ""

        records = [{
            "record_type": "entry",
            "kind": "vocab",
            "token": "entry:vocab:教室",
            "key": "vocab:教室",
            "level": "N4",
            "search_metadata": "vocab:教室 教室 きょうしつ kyō shi tsu kyoshitsu kyoushitsu",
            "data": {
                "key": "vocab:教室",
                "type": "vocabulary",
                "display": "教室",
                "reading": "きょうしつ",
                "romaji": "kyō shi tsu",
                "level": "N4",
                "aliases": [],
                "senses": [{"meaning": "教室"}],
                "sources": [],
                "attempt_stats": {},
            },
        }]
        filters = {"types": {"vocab"}, "levels": set(), "results": set()}
        ui_fzf.select_browse(records, filters)

        command = run.call_args.args[0]
        self.assertIn("--with-nth=3", command)
        self.assertIn("--disabled", command)
        self.assertTrue(any(arg.startswith("--bind=change:reload(") for arg in command))
        self.assertFalse(any(arg.startswith("--nth=") for arg in command))
        self.assertTrue(any("直接輸入搜尋" in arg for arg in command))

        fzf_input = run.call_args.kwargs["input"]
        fields = fzf_input.split("\t", 3)
        self.assertEqual(fields[0], "entry:vocab:教室")
        self.assertIn("教室", fields[2])
        self.assertIn("kyoushitsu", fields[3])
        self.assertIn("vocab:教室", fields[3])

    def test_top_level_show_command_is_removed_but_nested_show_commands_remain(self) -> None:
        parser = build_parser()
        subparsers_action = next(
            action for action in parser._actions if hasattr(action, "choices") and isinstance(action.choices, dict)
        )
        self.assertNotIn("show", subparsers_action.choices)
        self.assertIn("config", subparsers_action.choices)
        self.assertIn("attempts", subparsers_action.choices)

        config_parser = subparsers_action.choices["config"]
        config_sub = next(
            action for action in config_parser._actions if hasattr(action, "choices") and isinstance(action.choices, dict)
        )
        self.assertIn("show", config_sub.choices)

        attempts_parser = subparsers_action.choices["attempts"]
        attempts_sub = next(
            action for action in attempts_parser._actions if hasattr(action, "choices") and isinstance(action.choices, dict)
        )
        self.assertIn("show", attempts_sub.choices)


if __name__ == "__main__":
    unittest.main()
