from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from jpnote_app.fzf_filter_helper import read_state, render_panel, summary, toggle, write_state
from jpnote_app.preferences import (
    browse_default_filters,
    ensure_preferences,
    load_preferences,
    write_preferences,
)


class PreferenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "config.json"
        os.environ["JPNOTE_CONFIG_FILE"] = str(self.path)

    def tearDown(self) -> None:
        os.environ.pop("JPNOTE_CONFIG_FILE", None)
        self.temp.cleanup()

    def test_default_config_is_grammar_vocab_and_all_results(self) -> None:
        ensure_preferences()
        raw = load_preferences()
        self.assertEqual(raw["browse"]["types"], ["grammar", "vocab"])
        self.assertEqual(raw["browse"]["levels"], [])
        self.assertEqual(raw["browse"]["results"], [])
        filters = browse_default_filters()
        self.assertEqual(filters["types"], {"grammar", "vocab"})
        self.assertEqual(filters["results"], set())

    def test_user_can_change_browse_defaults(self) -> None:
        write_preferences({
            "browse": {
                "types": ["vocab", "mistake"],
                "levels": ["N4"],
                "results": ["wrong"],
            }
        })
        filters = browse_default_filters()
        self.assertEqual(filters["types"], {"vocab", "mistake"})
        self.assertEqual(filters["levels"], {"N4"})
        self.assertEqual(filters["results"], {"wrong"})

    def test_filter_helper_toggles_and_renders_in_place(self) -> None:
        state_path = Path(self.temp.name) / "state.json"
        panel_path = Path(self.temp.name) / "panel.tsv"
        state = {"types": {"grammar", "vocab"}, "levels": set(), "results": set()}
        write_state(state_path, state)
        toggle(state, "types:mistake")
        write_state(state_path, state)
        render_panel(panel_path, state)
        self.assertIn("[✓] 3. 類型  錯題", panel_path.read_text(encoding="utf-8"))
        self.assertIn("錯題＝全部", panel_path.read_text(encoding="utf-8"))
        self.assertIn("mistake", read_state(state_path)["types"])

    def test_empty_filter_groups_mean_all_and_results_are_contextual(self) -> None:
        state_path = Path(self.temp.name) / "state.json"
        panel_path = Path(self.temp.name) / "panel.tsv"
        state = {"types": set(), "levels": {"N4"}, "results": {"wrong"}}
        write_state(state_path, state)
        normalized = read_state(state_path)
        self.assertEqual(normalized["types"], set())
        self.assertEqual(normalized["results"], set())
        self.assertIn("類型＝全部", summary(normalized))

        render_panel(panel_path, normalized)
        panel = panel_path.read_text(encoding="utf-8")
        self.assertNotIn("錯題結果", panel)

        toggle(normalized, "types:mistake")
        render_panel(panel_path, normalized)
        panel = panel_path.read_text(encoding="utf-8")
        self.assertIn("錯題結果  wrong", panel)
        toggle(normalized, "results:wrong")
        self.assertEqual(normalized["results"], {"wrong"})
        toggle(normalized, "types:mistake")
        self.assertEqual(normalized["results"], set())

    def test_preferences_allow_empty_types_as_all(self) -> None:
        write_preferences({
            "browse": {
                "types": [],
                "levels": ["N5"],
                "results": ["wrong"],
            }
        })
        filters = browse_default_filters()
        self.assertEqual(filters["types"], set())
        self.assertEqual(filters["levels"], {"N5"})
        self.assertEqual(filters["results"], set())


if __name__ == "__main__":
    unittest.main()
