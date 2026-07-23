from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jpnote_app.browsing import browse_records
from jpnote_app.db import connect
from jpnote_app.repository import (
    get_entry,
    list_attempts,
    list_recent_entries,
    search_entries,
)
from jpnote_app.services import (
    _identity_set,
    apply_import,
    duplicate_candidates,
    merge_entries,
    prepare_import,
    replace_entry_data,
)


class V065Tests(unittest.TestCase):
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

    def test_search_and_browse_share_relation_note_and_source_metadata(self) -> None:
        self._import({
            "source": "TRY N4 特殊來源",
            "items": [
                {
                    "key": "grammar:のに", "type": "grammar", "display": "のに",
                    "related_grammar": [
                        {"key": "grammar:ので", "relation": "對比", "note": "理由表現比較測試"}
                    ],
                },
                {"key": "grammar:ので", "type": "grammar", "display": "ので"},
            ],
        })
        with connect() as conn:
            core_keys = [entry["key"] for entry in search_entries(conn, "理由表現比較測試")]
            browse_keys = [
                record["key"] for record in browse_records(conn, query="理由表現比較測試")
                if record["record_type"] == "entry"
            ]
            source_keys = [entry["key"] for entry in search_entries(conn, "TRY N4 特殊來源")]
            source_browse = [
                record["key"] for record in browse_records(conn, query="TRY N4 特殊來源")
                if record["record_type"] == "entry"
            ]
        self.assertIn("grammar:のに", core_keys)
        self.assertIn("grammar:のに", browse_keys)
        self.assertEqual(set(source_keys), set(source_browse))
        self.assertIn("grammar:のに", source_keys)

    def test_search_does_not_match_raw_aliases_json_punctuation(self) -> None:
        self._import({"items": [{
            "key": "vocab:猫", "type": "vocabulary", "display": "猫", "aliases": []
        }]})
        with connect() as conn:
            self.assertEqual(search_entries(conn, "["), [])
            self.assertEqual(search_entries(conn, "]"), [])

    def test_browse_entry_query_count_is_batched(self) -> None:
        self._import({"items": [
            {"key": f"vocab:語{i}", "type": "vocabulary", "display": f"語{i}"}
            for i in range(120)
        ]})
        with connect() as conn:
            selects: list[str] = []
            conn.set_trace_callback(lambda sql: selects.append(sql) if sql.lstrip().upper().startswith("SELECT") else None)
            records = browse_records(conn)
            conn.set_trace_callback(None)
        self.assertEqual(len(records), 120)
        self.assertLessEqual(len(selects), 8)

    def test_list_attempts_batches_link_lookup(self) -> None:
        payload = {
            "items": [{"key": "vocab:猫", "type": "vocabulary", "display": "猫"}],
            "attempts": [
                {
                    "event_key": f"attempt:{i}", "date": "2026-07-20",
                    "result": "wrong", "linked_entries": ["vocab:猫"],
                }
                for i in range(120)
            ],
        }
        self._import(payload)
        with connect() as conn:
            selects: list[str] = []
            conn.set_trace_callback(lambda sql: selects.append(sql) if sql.lstrip().upper().startswith("SELECT") else None)
            attempts = list_attempts(conn)
            conn.set_trace_callback(None)
        self.assertEqual(len(attempts), 120)
        self.assertLessEqual(len(selects), 3)

    def test_duplicate_candidates_indexes_identities_once_per_entry(self) -> None:
        self._import({"items": [
            {"key": f"vocab:語{i}", "type": "vocabulary", "display": f"語{i}"}
            for i in range(500)
        ]})
        with connect() as conn:
            with patch("jpnote_app.services._identity_set", wraps=_identity_set) as wrapped:
                candidates = duplicate_candidates(conn)
        self.assertEqual(candidates, [])
        self.assertLessEqual(wrapped.call_count, 510)

    def test_noop_manual_edit_preserves_updated_at(self) -> None:
        self._import({"source": "book", "items": [{
            "key": "vocab:猫", "type": "vocabulary", "display": "猫",
            "reading": "ねこ", "romaji": "ne ko", "meanings": ["貓"],
        }]})
        with connect() as conn:
            conn.execute("UPDATE entries SET updated_at='2020-01-01T00:00:00+08:00' WHERE key='vocab:猫'")
            entry = get_entry(conn, "vocab:猫", include_attempts=False)
            assert entry is not None
            replace_entry_data(conn, "vocab:猫", entry)
            updated_at = conn.execute("SELECT updated_at FROM entries WHERE key='vocab:猫'").fetchone()[0]
        self.assertEqual(updated_at, "2020-01-01T00:00:00+08:00")

    def test_merge_preserves_source_added_at_history(self) -> None:
        self._import({"source": "source-old", "items": [
            {"key": "vocab:A", "type": "vocabulary", "display": "A"},
            {"key": "vocab:B", "type": "vocabulary", "display": "B"},
        ]})
        with connect() as conn:
            conn.execute(
                "UPDATE sources SET added_at='2019-01-01T00:00:00+08:00' "
                "WHERE entry_key='vocab:A' AND source='source-old'"
            )
            conn.execute(
                "UPDATE sources SET source='source-target', added_at='2020-01-01T00:00:00+08:00' "
                "WHERE entry_key='vocab:B'"
            )
            merge_entries(conn, "vocab:A", "vocab:B")
            rows = conn.execute(
                "SELECT source, added_at FROM sources WHERE entry_key='vocab:B' ORDER BY source"
            ).fetchall()
        values = {row["source"]: row["added_at"] for row in rows}
        self.assertEqual(values["source-old"], "2019-01-01T00:00:00+08:00")
        self.assertEqual(values["source-target"], "2020-01-01T00:00:00+08:00")

    def test_recent_can_filter_by_exact_source(self) -> None:
        self._import({"source": "book-A", "items": [
            {"key": "vocab:A", "type": "vocabulary", "display": "A"},
        ]})
        self._import({"source": "book-B", "items": [
            {"key": "vocab:B", "type": "vocabulary", "display": "B"},
        ]})
        with connect() as conn:
            rows = list_recent_entries(conn, source_filter="book-A")
        self.assertEqual([row["key"] for row in rows], ["vocab:A"])


if __name__ == "__main__":
    unittest.main()
