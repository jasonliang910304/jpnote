from __future__ import annotations

import unittest

from jpnote_app.search_normalization import entry_search_metadata


class V0611HistoricalTests(unittest.TestCase):
    def test_romaji_metadata_contains_common_keyboard_variants(self) -> None:
        entry = {
            "key": "vocab:教室",
            "type": "vocabulary",
            "display": "教室",
            "reading": "きょうしつ",
            "romaji": "kyō shi tsu",
            "level": "N4",
            "aliases": [],
            "senses": [{"meaning": "教室"}],
        }
        metadata = entry_search_metadata(entry)
        self.assertIn("kyoshitsu", metadata)
        self.assertIn("kyoushitsu", metadata)
        self.assertIn("kyooshitsu", metadata)


if __name__ == "__main__":
    unittest.main()
