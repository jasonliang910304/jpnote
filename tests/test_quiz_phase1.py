from __future__ import annotations

import ast
import dataclasses
from pathlib import Path
import unittest
from unittest.mock import patch

from jpnote_app.optional_features import load_quiz_runtime
from jpnote_app.quiz import QuizRuntime
from jpnote_app.study_sources import (
    QuestionSourceUnavailableError,
    SourceCatalog,
    StudySourceService,
)


ENTRY = {
    "id": 99,
    "key": "vocab:軌跡",
    "type": "vocabulary",
    "display": "軌跡",
    "reading": "きせき",
    "romaji": "kiseki",
    "level": "N3",
    "review_group": "travel",
    "aliases": ["軌道"],
    "accent": "",
    "accent_type": "",
    "accent_display": "",
    "origin_language": "",
    "origin_word": "",
    "senses": [
        {
            "meaning": "行進後留下的路徑、軌道",
            "example_ja": "星の軌跡を見る。",
            "example_zh": "觀看星星的軌跡。",
        }
    ],
    "sources": ["遊戲語彙"],
}

ATTEMPT = {
    "id": 1234,
    "event_key": "attempt:stable-event",
    "result": "wrong",
    "date": "2026-07-18",
    "source": "TRY! N3",
    "section": "問題1",
    "question": "2",
    "question_type": "multiple_choice",
    "prompt": "正しい読み方はどれですか。",
    "user_answer": "きせつ",
    "correct_answer": "きせき",
    "reason": "読み方を確認する。",
    "before": "",
    "after": "",
    "parts": [],
    "user_order": [],
    "correct_order": [],
    "options": [
        {"id": 1, "text": "きせき"},
        {"id": 2, "text": "きせつ"},
    ],
    "linked_entries": ["vocab:軌跡"],
    "created_at": "2026-07-18T12:00:00.000000+08:00",
    "_data_warnings": [],
}


class FakeCore:
    def __init__(self, *, fail: bool = False):
        self.fail = fail

    def browse(self, types=None, levels=None, results=None, query=None):
        if self.fail:
            raise RuntimeError("synthetic source failure")
        if types == ["mistake"]:
            if levels and "N3" not in levels:
                return []
            if results and "wrong" not in results:
                return []
            return [{"kind": "mistake", "token": "attempt:stable-event", "levels": ["N3"], "data": dict(ATTEMPT)}]
        if levels and "N3" not in levels:
            return []
        kind = "vocab"
        return [{"kind": kind, "token": "entry:vocab:軌跡", "data": dict(ENTRY)}]

    def get(self, key):
        if self.fail:
            raise RuntimeError("synthetic source failure")
        return dict(ENTRY) if key == ENTRY["key"] else None

    def get_attempt(self, event_key):
        if self.fail:
            raise RuntimeError("synthetic source failure")
        return dict(ATTEMPT) if event_key == ATTEMPT["event_key"] else None


class EmptyReader:
    def list_entry_snapshots(self, **kwargs):
        return ()

    def get_entry_snapshot(self, key):
        return None

    def list_attempt_replay_sources(self, **kwargs):
        return ()

    def get_attempt_replay_source(self, event_key):
        return None

    def source_catalog(self):
        return SourceCatalog(0, 0, (), ())


class BrokenReader(EmptyReader):
    def source_catalog(self):
        raise RuntimeError("synthetic runtime failure")


class QuizPhase1ContractTests(unittest.TestCase):
    def test_entry_snapshot_is_immutable_and_excludes_sqlite_id(self):
        snapshot = StudySourceService(FakeCore()).get_entry_snapshot("vocab:軌跡")
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot.key, "vocab:軌跡")
        self.assertTrue(snapshot.capabilities.has_meaning)
        self.assertTrue(snapshot.capabilities.has_reading)
        self.assertTrue(snapshot.capabilities.has_example)
        self.assertNotIn("id", {field.name for field in dataclasses.fields(snapshot)})
        with self.assertRaises(dataclasses.FrozenInstanceError):
            snapshot.display = "changed"  # type: ignore[misc]

    def test_attempt_snapshot_uses_event_key_and_public_fields_only(self):
        snapshot = StudySourceService(FakeCore()).get_attempt_replay_source(
            "attempt:stable-event"
        )
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot.event_key, "attempt:stable-event")
        self.assertEqual(snapshot.options[0].text, "きせき")
        self.assertTrue(snapshot.capabilities.has_choices)
        self.assertTrue(snapshot.capabilities.structure_valid)
        self.assertNotIn("id", {field.name for field in dataclasses.fields(snapshot)})

    def test_list_filters_use_public_level_and_source_metadata(self):
        service = StudySourceService(FakeCore())
        self.assertEqual(len(service.list_entry_snapshots(levels=["N3"])), 1)
        self.assertEqual(len(service.list_entry_snapshots(levels=["N2"])), 0)
        self.assertEqual(len(service.list_entry_snapshots(sources=["遊戲語彙"])), 1)
        self.assertEqual(len(service.list_entry_snapshots(sources=["其他"])), 0)
        self.assertEqual(len(service.list_attempt_replay_sources(sources=["TRY! N3"])), 1)
        self.assertEqual(len(service.list_attempt_replay_sources(sources=["其他"])), 0)

    def test_malformed_attempt_is_fail_soft_and_not_capable(self):
        core = FakeCore()
        broken = dict(ATTEMPT)
        broken["_data_warnings"] = ["options_json 格式損壞"]
        broken["options"] = ["only-one"]
        core.get_attempt = lambda event_key: broken  # type: ignore[method-assign]
        snapshot = StudySourceService(core).get_attempt_replay_source("attempt:stable-event")
        assert snapshot is not None
        self.assertFalse(snapshot.capabilities.structure_valid)
        self.assertFalse(snapshot.capabilities.has_choices)

    def test_public_source_failure_is_wrapped(self):
        with self.assertRaises(QuestionSourceUnavailableError):
            StudySourceService(FakeCore(fail=True)).list_entry_snapshots()

    def test_runtime_probe_contains_runtime_failure(self):
        status = QuizRuntime(BrokenReader()).probe()
        self.assertFalse(status.ready)
        self.assertIn("synthetic runtime failure", status.error)

    def test_runtime_probe_reports_catalog_counts(self):
        status = QuizRuntime(EmptyReader()).probe()
        self.assertTrue(status.ready)
        self.assertEqual(status.entry_sources, 0)
        self.assertEqual(status.replayable_attempt_sources, 0)

    def test_optional_loader_contains_quiz_import_failure(self):
        with patch(
            "jpnote_app.optional_features.import_module",
            side_effect=ImportError("synthetic import failure"),
        ):
            result = load_quiz_runtime()
        self.assertFalse(result.available)
        self.assertIn("synthetic import failure", result.error)

    def test_optional_loader_contains_runtime_construction_failure(self):
        class BrokenQuizModule:
            @staticmethod
            def create_runtime(source_reader=None):
                raise RuntimeError("synthetic construction failure")

        with patch(
            "jpnote_app.optional_features.import_module",
            return_value=BrokenQuizModule,
        ):
            result = load_quiz_runtime(EmptyReader())
        self.assertFalse(result.available)
        self.assertIn("synthetic construction failure", result.error)

    def test_optional_loader_loads_runtime_only_when_requested(self):
        result = load_quiz_runtime(EmptyReader())
        self.assertTrue(result.available)
        self.assertIsInstance(result.value, QuizRuntime)

    def test_quiz_package_has_no_forbidden_core_internal_imports(self):
        forbidden_absolute = {
            "jpnote_app.db",
            "jpnote_app.repository",
            "jpnote_app.cli",
        }
        quiz_dir = Path(__file__).parents[1] / "jpnote_app" / "quiz"
        violations: list[str] = []
        for path in quiz_dir.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in forbidden_absolute:
                            violations.append(f"{path.name}: import {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if module in forbidden_absolute:
                        violations.append(f"{path.name}: from {module}")
                    if node.level and module in {"db", "repository", "cli"}:
                        violations.append(f"{path.name}: relative import {module}")
        self.assertEqual(violations, [])

    def test_quiz_sqlite_usage_is_limited_to_storage_boundary(self):
        sqlite_allowed_files = {"session_store.py"}
        quiz_dir = Path(__file__).parents[1] / "jpnote_app" / "quiz"
        violations: list[str] = []
        for path in quiz_dir.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                imports_sqlite = False
                if isinstance(node, ast.Import):
                    imports_sqlite = any(
                        alias.name == "sqlite3" for alias in node.names
                    )
                elif isinstance(node, ast.ImportFrom):
                    imports_sqlite = (node.module or "") == "sqlite3"
                if imports_sqlite and path.name not in sqlite_allowed_files:
                    violations.append(path.name)
        self.assertEqual(violations, [])

    def test_core_modules_do_not_statically_import_quiz(self):
        app_dir = Path(__file__).parents[1] / "jpnote_app"
        violations: list[str] = []
        for path in app_dir.glob("*.py"):
            if path.name == "optional_features.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    if any(alias.name.startswith("jpnote_app.quiz") for alias in node.names):
                        violations.append(path.name)
                elif isinstance(node, ast.ImportFrom):
                    if (node.module or "").startswith("jpnote_app.quiz"):
                        violations.append(path.name)
                    if node.level and (node.module or "") == "quiz":
                        violations.append(path.name)
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
