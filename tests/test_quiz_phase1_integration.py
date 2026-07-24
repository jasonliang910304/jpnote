from __future__ import annotations

import dataclasses
import hashlib
import os
import tempfile
import unittest
from pathlib import Path

from jpnote_app.api import JpnoteCore
from jpnote_app.config import db_path
from jpnote_app.db import connect
from jpnote_app.study_sources import StudySourceService


class QuizPhase1CoreIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.previous_data_dir = os.environ.get("JPNOTE_DATA_DIR")
        os.environ["JPNOTE_DATA_DIR"] = str(Path(self.temp.name) / "data")
        self.core = JpnoteCore()
        self.service = StudySourceService(self.core)

    def tearDown(self) -> None:
        if self.previous_data_dir is None:
            os.environ.pop("JPNOTE_DATA_DIR", None)
        else:
            os.environ["JPNOTE_DATA_DIR"] = self.previous_data_dir
        self.temp.cleanup()

    def seed_sources(self) -> None:
        result = self.core.apply_import(
            {
                "source": "遊戲語彙",
                "items": [
                    {
                        "key": "vocab:軌跡",
                        "type": "vocabulary",
                        "display": "軌跡",
                        "reading": "きせき",
                        "romaji": "ki se ki",
                        "level": "N3",
                        "aliases": ["軌道"],
                        "senses": [
                            {
                                "meaning": "行進後留下的路徑、軌道",
                                "example_ja": "星の軌跡を見る。",
                                "example_zh": "觀看星星的軌跡。",
                            }
                        ],
                    },
                    {
                        "key": "vocab:奇跡",
                        "type": "vocabulary",
                        "display": "奇跡",
                        "reading": "きせき",
                        "romaji": "ki se ki",
                        "level": "N3",
                        "meanings": ["奇蹟"],
                    },
                    {
                        "key": "grammar:のに",
                        "type": "grammar",
                        "display": "のに",
                        "level": "N4",
                        "meanings": ["明明卻"],
                    },
                ],
                "attempts": [
                    {
                        "event_key": "attempt:quiz-phase1-mc",
                        "date": "2026-07-24",
                        "source": "TRY! N3",
                        "section": "問題1",
                        "question": "2",
                        "question_type": "multiple_choice",
                        "prompt": "「軌跡」の意味はどれですか。",
                        "user_answer": "1",
                        "correct_answer": "2",
                        "result": "wrong",
                        "options": [
                            {"id": 1, "text": "奇蹟"},
                            {"id": 2, "text": "路徑、軌道"},
                            {"id": 3, "text": "教室"},
                            {"id": 4, "text": "食堂"},
                        ],
                        "linked_entries": ["vocab:軌跡"],
                    },
                    {
                        "event_key": "attempt:quiz-phase1-reorder",
                        "date": "2026-07-24",
                        "source": "TRY! N4",
                        "section": "問題2",
                        "question": "3",
                        "question_type": "reorder_4",
                        "prompt": "正しい順番に並べてください。",
                        "result": "wrong",
                        "parts": [
                            {"id": 1, "text": "雨が"},
                            {"id": 2, "text": "降った"},
                            {"id": 3, "text": "のに"},
                            {"id": 4, "text": "出かけた"},
                        ],
                        "user_order": [1, 3, 2, 4],
                        "correct_order": [1, 2, 3, 4],
                        "linked_entries": ["grammar:のに"],
                    },
                ],
            },
            accept_warnings=True,
        )
        self.assertEqual(result["added_entries"], 3)
        self.assertEqual(result["added_attempts"], 2)

    def test_empty_real_core_catalog_is_safe_and_adds_no_quiz_schema(self) -> None:
        catalog = StudySourceService.from_default_core().source_catalog()
        self.assertEqual(catalog.entry_count, 0)
        self.assertEqual(catalog.replayable_attempt_count, 0)

        with connect() as conn:
            table_names = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        self.assertFalse(any(name.startswith("quiz_") for name in table_names))

    def test_real_entry_snapshots_preserve_public_data_and_filters(self) -> None:
        self.seed_sources()

        vocabulary = self.service.list_entry_snapshots(
            entry_types=["vocabulary"], levels=["N3"], sources=["遊戲語彙"]
        )
        self.assertEqual({entry.key for entry in vocabulary}, {"vocab:軌跡", "vocab:奇跡"})
        trajectory = next(entry for entry in vocabulary if entry.key == "vocab:軌跡")
        self.assertEqual(trajectory.senses[0].meaning, "行進後留下的路徑、軌道")
        self.assertTrue(trajectory.capabilities.has_reading)
        self.assertTrue(trajectory.capabilities.has_meaning)
        self.assertTrue(trajectory.capabilities.has_example)
        self.assertTrue(trajectory.capabilities.has_aliases)
        self.assertNotIn("id", dataclasses.asdict(trajectory))

        grammar = self.service.list_entry_snapshots(entry_types=["grammar"], levels=["N4"])
        self.assertEqual([entry.key for entry in grammar], ["grammar:のに"])
        self.assertEqual(self.service.list_entry_snapshots(levels=["N2"]), ())
        self.assertEqual(self.service.list_entry_snapshots(sources=["不存在的來源"]), ())

    def test_real_attempt_snapshots_use_stable_ids_and_consistent_levels(self) -> None:
        self.seed_sources()

        raw = self.core.get_attempt("attempt:quiz-phase1-mc")
        self.assertIsNotNone(raw)
        assert raw is not None
        self.assertIn("id", raw)

        attempts = {
            attempt.event_key: attempt
            for attempt in self.service.list_attempt_replay_sources()
        }
        multiple_choice = attempts["attempt:quiz-phase1-mc"]
        reorder = attempts["attempt:quiz-phase1-reorder"]
        self.assertEqual(multiple_choice.linked_levels, ("N3",))
        self.assertTrue(multiple_choice.capabilities.has_choices)
        self.assertTrue(multiple_choice.capabilities.has_correct_answer)
        self.assertEqual(reorder.linked_levels, ("N4",))
        self.assertTrue(reorder.capabilities.has_reorder_parts)

        direct = self.service.get_attempt_replay_source("attempt:quiz-phase1-mc")
        self.assertIsNotNone(direct)
        assert direct is not None
        self.assertEqual(direct.linked_levels, multiple_choice.linked_levels)
        self.assertNotIn("id", dataclasses.asdict(direct))
        self.assertEqual(
            self.service.list_attempt_replay_sources(levels=["N3"]),
            (multiple_choice,),
        )
        self.assertEqual(
            self.service.list_attempt_replay_sources(sources=["TRY! N4"]),
            (reorder,),
        )

    def test_catalog_uses_real_core_metadata(self) -> None:
        self.seed_sources()
        catalog = self.service.source_catalog()
        self.assertEqual(catalog.entry_count, 3)
        self.assertEqual(catalog.replayable_attempt_count, 2)
        self.assertEqual(catalog.levels, ("N3", "N4"))
        self.assertEqual(
            catalog.sources,
            ("TRY! N3", "TRY! N4", "遊戲語彙"),
        )

    def test_question_source_reads_do_not_modify_core_database(self) -> None:
        self.seed_sources()
        before = hashlib.sha256(db_path().read_bytes()).digest()

        self.service.list_entry_snapshots()
        self.service.get_entry_snapshot("vocab:軌跡")
        self.service.list_attempt_replay_sources()
        self.service.get_attempt_replay_source("attempt:quiz-phase1-mc")
        self.service.source_catalog()

        after = hashlib.sha256(db_path().read_bytes()).digest()
        self.assertEqual(after, before)

    def test_malformed_real_attempt_degrades_without_breaking_core(self) -> None:
        self.seed_sources()
        with connect() as conn:
            conn.execute(
                "UPDATE attempts SET options_json=? WHERE event_key=?",
                ('{"not": "an array"}', "attempt:quiz-phase1-mc"),
            )

        snapshot = self.service.get_attempt_replay_source("attempt:quiz-phase1-mc")
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertFalse(snapshot.capabilities.structure_valid)
        self.assertFalse(snapshot.capabilities.has_choices)
        self.assertIn("options_json", snapshot.data_warnings[0])

        self.assertEqual(self.core.stats()["attempts"], 2)
        self.assertEqual(len(self.service.list_entry_snapshots()), 3)

    def test_snapshot_does_not_change_after_source_entry_update(self) -> None:
        self.seed_sources()
        original = self.service.get_entry_snapshot("vocab:軌跡")
        self.assertIsNotNone(original)
        assert original is not None

        result = self.core.apply_import(
            {
                "source": "補充資料",
                "items": [
                    {
                        "key": "vocab:軌跡",
                        "type": "vocabulary",
                        "display": "軌跡",
                        "reading": "きせき",
                        "romaji": "ki se ki",
                        "level": "N3",
                        "meanings": ["事物發展經過留下的痕跡"],
                    }
                ],
            }
        )
        self.assertTrue(result["modified"])

        current = self.service.get_entry_snapshot("vocab:軌跡")
        self.assertIsNotNone(current)
        assert current is not None
        self.assertEqual(original.senses[0].meaning, "行進後留下的路徑、軌道")
        self.assertIn(
            "事物發展經過留下的痕跡",
            {sense.meaning for sense in current.senses},
        )

    def test_missing_stable_keys_return_none(self) -> None:
        self.seed_sources()
        self.assertIsNone(self.service.get_entry_snapshot("vocab:不存在"))
        self.assertIsNone(self.service.get_attempt_replay_source("attempt:不存在"))


if __name__ == "__main__":
    unittest.main()
