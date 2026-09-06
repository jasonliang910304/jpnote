from __future__ import annotations

import argparse
import io
import itertools
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stdout
from unittest.mock import patch

from jpnote_app.api import JpnoteCore
import jpnote_app.cli as cli_module
from jpnote_app.cli import (
    _read_clipboard,
    _read_paste_input,
    _protocol_error_type,
    command_undo,
)
from jpnote_app.config import SCHEMA_VERSION, backup_dir, db_path
import jpnote_app.db as db_module
from jpnote_app.db import (
    auxiliary_backups,
    connect,
    restore_database_from,
    validate_restore_candidate,
)
from jpnote_app.import_resolution import resolve_import_plan
from jpnote_app.import_transport import MAX_IMPORT_BYTES
from jpnote_app.mutations import PostCommitExportError, execute_safe_mutation
from jpnote_app.relation_integrity import (
    apply_safe_relation_repairs,
    relation_integrity_issues,
)
from jpnote_app.services import prepare_import
from jpnote_app.study_sources import StudySourceService
from jpnote_app.validation import normalize_payload


class RestoreCompatibilityTests(unittest.TestCase):
    def _formal_db(self, root: Path) -> Path:
        with patch.dict(os.environ, {"JPNOTE_DATA_DIR": str(root / "data")}):
            with connect() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO metadata(key, value) VALUES('test_marker', 'live')"
                )
            return db_path()

    def test_future_schema_is_rejected_before_formal_db_or_sidecars_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.dict(os.environ, {"JPNOTE_DATA_DIR": str(root / "data")}):
                formal = self._formal_db(root)
                candidate = root / "future.db"
                shutil.copy2(formal, candidate)
                with sqlite3.connect(candidate) as conn:
                    conn.execute(
                        "UPDATE metadata SET value=? WHERE key='schema_version'",
                        (str(SCHEMA_VERSION + 1),),
                    )
                before = formal.read_bytes()
                sidecars = []
                for suffix in ("-wal", "-shm", "-journal"):
                    path = Path(str(formal) + suffix)
                    path.write_bytes(("sentinel" + suffix).encode())
                    sidecars.append((path, path.read_bytes()))

                with self.assertRaisesRegex(ValueError, "schema v"):
                    restore_database_from(candidate)

                self.assertEqual(formal.read_bytes(), before)
                for path, content in sidecars:
                    self.assertTrue(path.exists())
                    self.assertEqual(path.read_bytes(), content)

    def test_non_jpnote_sqlite_is_rejected_without_replacing_formal_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.dict(os.environ, {"JPNOTE_DATA_DIR": str(root / "data")}):
                formal = self._formal_db(root)
                before = formal.read_bytes()
                candidate = root / "other.db"
                with sqlite3.connect(candidate) as conn:
                    conn.execute("CREATE TABLE notes(value TEXT)")
                with self.assertRaisesRegex(ValueError, "核心資料表"):
                    restore_database_from(candidate)
                self.assertEqual(formal.read_bytes(), before)


    def test_invalid_schema_version_is_rejected_without_replacing_formal_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.dict(os.environ, {"JPNOTE_DATA_DIR": str(root / "data")}):
                formal = self._formal_db(root)
                before = formal.read_bytes()
                candidate = root / "invalid-version.db"
                shutil.copy2(formal, candidate)
                with sqlite3.connect(candidate) as conn:
                    conn.execute(
                        "UPDATE metadata SET value='not-a-version' WHERE key='schema_version'"
                    )
                with self.assertRaisesRegex(ValueError, "schema_version"):
                    restore_database_from(candidate)
                self.assertEqual(formal.read_bytes(), before)

    def test_jpnote_like_but_structurally_incompatible_db_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.dict(os.environ, {"JPNOTE_DATA_DIR": str(root / "data")}):
                formal = self._formal_db(root)
                before = formal.read_bytes()
                candidate = root / "broken.db"
                with sqlite3.connect(candidate) as conn:
                    conn.executescript(
                        """
                        CREATE TABLE entries(key TEXT PRIMARY KEY, type TEXT, display TEXT);
                        CREATE TABLE senses(entry_key TEXT, meaning TEXT);
                        CREATE TABLE sources(entry_key TEXT, source TEXT);
                        """
                    )
                with self.assertRaises(ValueError):
                    restore_database_from(candidate)
                self.assertEqual(formal.read_bytes(), before)

    def test_candidate_with_foreign_key_violation_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.dict(os.environ, {"JPNOTE_DATA_DIR": str(root / "data")}):
                formal = self._formal_db(root)
                before = formal.read_bytes()
                candidate = root / "broken-fk.db"
                shutil.copy2(formal, candidate)
                with sqlite3.connect(candidate) as conn:
                    conn.execute("PRAGMA foreign_keys = OFF")
                    conn.execute(
                        "INSERT INTO senses(entry_key,meaning,example_ja,example_zh) "
                        "VALUES('vocab:missing','orphan','','')"
                    )
                with self.assertRaisesRegex(ValueError, "foreign-key"):
                    restore_database_from(candidate)
                self.assertEqual(formal.read_bytes(), before)

    def test_current_schema_missing_non_migrated_column_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.dict(os.environ, {"JPNOTE_DATA_DIR": str(root / "data")}):
                formal = self._formal_db(root)
                before = formal.read_bytes()
                candidate = root / "missing-column.db"
                with sqlite3.connect(candidate) as conn:
                    conn.executescript(db_module.SCHEMA)
                    conn.execute(
                        "INSERT INTO metadata(key,value) VALUES('schema_version', ?)",
                        (str(SCHEMA_VERSION),),
                    )
                    conn.executescript(
                        """
                        ALTER TABLE senses RENAME TO senses_original;
                        CREATE TABLE senses (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            entry_key TEXT NOT NULL REFERENCES entries(key) ON DELETE CASCADE,
                            meaning TEXT NOT NULL,
                            example_ja TEXT NOT NULL DEFAULT ''
                        );
                        DROP TABLE senses_original;
                        """
                    )
                with self.assertRaisesRegex(ValueError, "example_zh|no such column"):
                    restore_database_from(candidate)
                self.assertEqual(formal.read_bytes(), before)

    def test_supported_older_schema_is_validated_in_memory_then_can_migrate_after_restore(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.dict(os.environ, {"JPNOTE_DATA_DIR": str(root / "data")}):
                formal = self._formal_db(root)
                candidate = root / "old.db"
                shutil.copy2(formal, candidate)
                with sqlite3.connect(candidate) as conn:
                    conn.execute("DROP TABLE pending_grammar_relations")
                    conn.execute(
                        "UPDATE metadata SET value=? WHERE key='schema_version'",
                        (str(SCHEMA_VERSION - 1),),
                    )
                restore_database_from(candidate)
                with sqlite3.connect(formal) as raw:
                    version = raw.execute(
                        "SELECT value FROM metadata WHERE key='schema_version'"
                    ).fetchone()[0]
                    self.assertEqual(version, str(SCHEMA_VERSION - 1))
                with connect() as migrated:
                    version = migrated.execute(
                        "SELECT value FROM metadata WHERE key='schema_version'"
                    ).fetchone()[0]
                    tables = {
                        row[0]
                        for row in migrated.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'"
                        )
                    }
                self.assertEqual(version, str(SCHEMA_VERSION))
                self.assertIn("pending_grammar_relations", tables)


    def test_preflight_undo_rejects_incompatible_backup_before_recovery_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.dict(os.environ, {"JPNOTE_DATA_DIR": str(root / "data")}):
                formal = self._formal_db(root)
                candidate = backup_dir() / "undo-20260906T000000-000000-future.db"
                candidate.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(formal, candidate)
                with sqlite3.connect(candidate) as conn:
                    conn.execute(
                        "UPDATE metadata SET value=? WHERE key='schema_version'",
                        (str(SCHEMA_VERSION + 1),),
                    )
                before_aux = list(auxiliary_backups())
                before_formal = formal.read_bytes()

                with self.assertRaisesRegex(ValueError, "不相容"):
                    command_undo(argparse.Namespace(list=False, backup=candidate.name))

                self.assertEqual(list(auxiliary_backups()), before_aux)
                self.assertEqual(formal.read_bytes(), before_formal)
                self.assertTrue(candidate.exists())

    def test_restore_revalidates_exact_copy_if_backup_changes_after_cli_precheck(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.dict(os.environ, {"JPNOTE_DATA_DIR": str(root / "data")}):
                formal = self._formal_db(root)
                before = formal.read_bytes()
                candidate = backup_dir() / "undo-20260906T000100-000000-race.db"
                candidate.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(formal, candidate)
                replacement = root / "future-replacement.db"
                shutil.copy2(formal, replacement)
                with sqlite3.connect(replacement) as conn:
                    conn.execute(
                        "UPDATE metadata SET value=? WHERE key='schema_version'",
                        (str(SCHEMA_VERSION + 1),),
                    )

                real_recovery = cli_module.create_recovery_snapshot

                def swap_after_precheck(label: str) -> Path | None:
                    recovery = real_recovery(label)
                    shutil.copy2(replacement, candidate)
                    return recovery

                with patch(
                    "jpnote_app.cli.create_recovery_snapshot",
                    side_effect=swap_after_precheck,
                ):
                    with self.assertRaisesRegex(ValueError, "schema v"):
                        command_undo(
                            argparse.Namespace(list=False, backup=candidate.name)
                        )

                self.assertEqual(formal.read_bytes(), before)
                self.assertTrue(candidate.exists())
                with sqlite3.connect(candidate) as conn:
                    self.assertEqual(
                        conn.execute(
                            "SELECT value FROM metadata WHERE key='schema_version'"
                        ).fetchone()[0],
                        str(SCHEMA_VERSION + 1),
                    )

    def test_legacy_core_schema_without_metadata_is_still_supported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.dict(os.environ, {"JPNOTE_DATA_DIR": str(root / "data")}):
                formal = self._formal_db(root)
                candidate = root / "legacy-core.db"
                with sqlite3.connect(candidate) as conn:
                    conn.executescript(
                        """
                        PRAGMA foreign_keys = ON;
                        CREATE TABLE entries (
                            key TEXT PRIMARY KEY,
                            type TEXT NOT NULL,
                            display TEXT NOT NULL,
                            reading TEXT NOT NULL DEFAULT '',
                            level TEXT NOT NULL DEFAULT '',
                            review_group TEXT NOT NULL DEFAULT '',
                            aliases_json TEXT NOT NULL DEFAULT '[]',
                            created_at TEXT NOT NULL,
                            updated_at TEXT NOT NULL
                        );
                        CREATE TABLE senses (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            entry_key TEXT NOT NULL REFERENCES entries(key) ON DELETE CASCADE,
                            meaning TEXT NOT NULL,
                            example_ja TEXT NOT NULL DEFAULT '',
                            example_zh TEXT NOT NULL DEFAULT ''
                        );
                        CREATE TABLE sources (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            entry_key TEXT NOT NULL REFERENCES entries(key) ON DELETE CASCADE,
                            source TEXT NOT NULL,
                            added_at TEXT NOT NULL
                        );
                        """
                    )
                    stamp = "2026-01-01T00:00:00+00:00"
                    conn.execute(
                        "INSERT INTO entries(key,type,display,reading,created_at,updated_at) "
                        "VALUES('vocab:猫','vocabulary','猫','ねこ',?,?)",
                        (stamp, stamp),
                    )
                    conn.execute(
                        "INSERT INTO senses(entry_key,meaning) VALUES('vocab:猫','貓')"
                    )
                validate_restore_candidate(candidate)
                restore_database_from(candidate)
                with connect() as migrated:
                    self.assertEqual(
                        migrated.execute(
                            "SELECT value FROM metadata WHERE key='schema_version'"
                        ).fetchone()[0],
                        str(SCHEMA_VERSION),
                    )
                    self.assertEqual(
                        migrated.execute(
                            "SELECT display FROM entries WHERE key='vocab:猫'"
                        ).fetchone()[0],
                        "猫",
                    )
                # Compatibility means the restored database is usable by the
                # current public read and write paths, not merely SQLite-valid.
                core = JpnoteCore()
                self.assertEqual(core.search("猫")[0]["key"], "vocab:猫")
                self.assertTrue(
                    any(record["data"]["key"] == "vocab:猫" for record in core.browse())
                )
                applied = core.apply_import(
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
                    }
                )
                self.assertEqual(applied["added_entries"], 1)
                self.assertEqual(core.get("vocab:犬")["display"], "犬")
                self.assertTrue(formal.exists())


class PublicApiReadonlyTests(unittest.TestCase):
    def test_all_public_read_methods_leave_missing_data_dir_absent(self) -> None:
        calls = {
            "list_entries": lambda core: core.list_entries(),
            "search": lambda core: core.search("ない"),
            "browse": lambda core: core.browse(),
            "recent": lambda core: core.recent(),
            "get": lambda core: core.get("grammar:ない"),
            "romaji_audit": lambda core: core.romaji_audit(),
            "mistakes": lambda core: core.mistakes(),
            "attempts": lambda core: core.attempts(),
            "get_attempt": lambda core: core.get_attempt("attempt:missing"),
            "audit": lambda core: core.audit(),
            "duplicates": lambda core: core.duplicates(),
            "stats": lambda core: core.stats(),
        }
        for name, invoke in calls.items():
            with self.subTest(method=name), tempfile.TemporaryDirectory() as tmp:
                data = Path(tmp) / "jpnote-data"
                with patch.dict(os.environ, {"JPNOTE_DATA_DIR": str(data)}):
                    invoke(JpnoteCore())
                    self.assertFalse(data.exists())


    def test_old_schema_public_read_does_not_migrate_formal_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "jpnote-data"
            with patch.dict(os.environ, {"JPNOTE_DATA_DIR": str(data)}):
                with connect():
                    pass
                formal = db_path()
                with sqlite3.connect(formal) as conn:
                    conn.execute("DROP TABLE pending_grammar_relations")
                    conn.execute(
                        "UPDATE metadata SET value=? WHERE key='schema_version'",
                        (str(SCHEMA_VERSION - 1),),
                    )
                before = formal.read_bytes()
                before_mtime = formal.stat().st_mtime_ns
                stats = JpnoteCore().stats()
                self.assertEqual(stats["total"], 0)
                self.assertEqual(formal.read_bytes(), before)
                self.assertEqual(formal.stat().st_mtime_ns, before_mtime)

    def test_quiz_default_source_catalog_is_also_side_effect_free(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "jpnote-data"
            with patch.dict(os.environ, {"JPNOTE_DATA_DIR": str(data)}):
                catalog = StudySourceService.from_default_core().source_catalog()
                self.assertEqual(catalog.entry_count, 0)
                self.assertEqual(catalog.replayable_attempt_count, 0)
                self.assertFalse(data.exists())


class AttemptBatchCanonicalizationTests(unittest.TestCase):
    def _attempt(self, links: list[str]) -> dict[str, object]:
        return {
            "event_key": "attempt:explicit-same",
            "result": "wrong",
            "date": "2026-09-06",
            "question_type": "other",
            "prompt": "Q",
            "linked_entries": links,
        }

    def test_same_event_key_with_reordered_links_is_deduplicated(self) -> None:
        payload = {
            "attempts": [
                self._attempt(["vocab:A", "vocab:B"]),
                self._attempt(["vocab:B", "vocab:A"]),
            ]
        }
        _source, _items, attempts, notes = normalize_payload(payload)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]["linked_entries"], ["vocab:A", "vocab:B"])
        self.assertTrue(any("去重" in note for note in notes))

    def test_all_link_permutations_share_one_content_identity(self) -> None:
        links = ["vocab:A", "vocab:B", "vocab:C"]
        payload = {
            "attempts": [self._attempt(list(order)) for order in itertools.permutations(links)]
        }
        _source, _items, attempts, notes = normalize_payload(payload)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]["linked_entries"], sorted(links))
        self.assertEqual(len([note for note in notes if "去重" in note]), 5)

    def test_same_event_key_with_different_link_set_still_conflicts(self) -> None:
        payload = {
            "attempts": [
                self._attempt(["vocab:A", "vocab:B"]),
                self._attempt(["vocab:A", "vocab:C"]),
            ]
        }
        with self.assertRaisesRegex(ValueError, "相同 event_key"):
            normalize_payload(payload)


class RelationAuditDirectionTests(unittest.TestCase):
    def test_inverse_pairs_are_tracked_by_directed_identity(self) -> None:
        relation_rows = [
            ("grammar:A", "grammar:B", "前置文法"),
            ("grammar:B", "grammar:A", "延伸"),
            ("grammar:B", "grammar:A", "前置文法"),
        ]
        for order in itertools.permutations(relation_rows):
            with self.subTest(order=order), tempfile.TemporaryDirectory() as tmp:
                with patch.dict(os.environ, {"JPNOTE_DATA_DIR": str(Path(tmp) / "data")}):
                    with connect() as conn:
                        stamp = "2026-09-06T00:00:00+00:00"
                        for key in ("grammar:A", "grammar:B"):
                            conn.execute(
                                """INSERT INTO entries(
                                    key,type,display,created_at,updated_at
                                ) VALUES(?, 'grammar', ?, ?, ?)""",
                                (key, key, stamp, stamp),
                            )
                        for source, target, relation in order:
                            conn.execute(
                                """INSERT INTO grammar_relations(
                                    source_key,target_key,relation_type,note,source,created_at
                                ) VALUES(?, ?, ?, '', 'test', ?)""",
                                (source, target, relation, stamp),
                            )
                        issues = relation_integrity_issues(conn)
                        missing = [
                            issue
                            for issue in issues
                            if issue["code"] == "missing_reciprocal_relation"
                        ]
                        self.assertEqual(len(missing), 1)
                        self.assertEqual(missing[0]["key"], "grammar:B")
                        self.assertEqual(
                            missing[0]["details"]["expected_reciprocal"], "延伸"
                        )

                        actions = apply_safe_relation_repairs(conn)
                        self.assertTrue(
                            any(
                                "added_reciprocal_relation" in action
                                for action in actions
                            )
                        )
                        after = relation_integrity_issues(conn)
                        self.assertFalse(
                            any(
                                issue["code"] == "missing_reciprocal_relation"
                                for issue in after
                            )
                        )



class DuplicateResolutionDeterminismTests(unittest.TestCase):
    def _item(self, key: str, display: str, level: str = "N3") -> dict[str, object]:
        return {
            "key": key,
            "type": "vocabulary",
            "display": display,
            "level": level,
            "senses": [{"meaning": display}],
        }

    def _resolved(self, order: list[dict[str, object]]) -> dict[str, object]:
        payload = {"source": "test", "items": order}
        with connect() as conn:
            plan = prepare_import(conn, payload)
            resolved = resolve_import_plan(
                conn,
                plan,
                {"vocab:A": "vocab:TARGET", "vocab:B": "vocab:TARGET"},
            )
        return resolved.to_dict()

    def test_mapping_result_does_not_depend_on_payload_item_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"JPNOTE_DATA_DIR": str(Path(tmp) / "data")}):
                target = self._item("vocab:TARGET", "TARGET", "N3")
                a = self._item("vocab:A", "A", "N3")
                b = self._item("vocab:B", "B", "N3")
                results = [
                    self._resolved(list(order))
                    for order in itertools.permutations([target, a, b])
                ]
                for result in results[1:]:
                    self.assertEqual(result, results[0])
                self.assertEqual(results[0]["items"][0]["display"], "TARGET")
                self.assertEqual(results[0]["items"][0]["aliases"], ["A", "B"])

    def test_single_source_remap_can_still_update_existing_target_display(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"JPNOTE_DATA_DIR": str(Path(tmp) / "data")}):
                from jpnote_app.services import apply_import
                with connect() as conn:
                    apply_import(
                        conn,
                        prepare_import(
                            conn,
                            {"items": [self._item("vocab:TARGET", "かな", "N3")]},
                        ),
                    )
                    plan = prepare_import(
                        conn,
                        {"items": [self._item("vocab:A", "漢字", "N3")]},
                    )
                    resolved = resolve_import_plan(
                        conn, plan, {"vocab:A": "vocab:TARGET"}
                    )
                item = resolved.to_dict()["items"][0]
                self.assertEqual(item["display"], "漢字")
                self.assertIn("かな", item["aliases"])

    def test_existing_target_resolution_is_deterministic_across_source_permutations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"JPNOTE_DATA_DIR": str(Path(tmp) / "data")}):
                from jpnote_app.services import apply_import
                with connect() as conn:
                    apply_import(
                        conn,
                        prepare_import(
                            conn,
                            {"items": [self._item("vocab:TARGET", "TARGET", "N3")]},
                        ),
                    )
                    a = self._item("vocab:A", "A", "N4")
                    b = self._item("vocab:B", "B", "N2")
                    results = []
                    for order in itertools.permutations([a, b]):
                        plan = prepare_import(conn, {"source": "test", "items": list(order)})
                        resolved = resolve_import_plan(
                            conn,
                            plan,
                            {
                                "vocab:A": "vocab:TARGET",
                                "vocab:B": "vocab:TARGET",
                            },
                        )
                        results.append(resolved.to_dict())
                self.assertEqual(results[0], results[1])
                item = results[0]["items"][0]
                self.assertEqual(item["display"], "TARGET")
                self.assertEqual(item["level"], "N3")
                self.assertEqual(item["aliases"], ["A", "B"])

    def test_conflicting_fill_value_fails_closed_when_target_has_no_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"JPNOTE_DATA_DIR": str(Path(tmp) / "data")}):
                target = self._item("vocab:TARGET", "TARGET", "")
                with connect() as conn:
                    from jpnote_app.services import apply_import
                    apply_import(conn, prepare_import(conn, {"items": [target]}))
                    plan = prepare_import(
                        conn,
                        {
                            "items": [
                                self._item("vocab:A", "A", "N3"),
                                self._item("vocab:B", "B", "N2"),
                            ]
                        },
                    )
                    with self.assertRaisesRegex(ValueError, "欄位內容衝突"):
                        resolve_import_plan(
                            conn,
                            plan,
                            {
                                "vocab:A": "vocab:TARGET",
                                "vocab:B": "vocab:TARGET",
                            },
                        )


class BoundedPasteTransportTests(unittest.TestCase):
    def test_legacy_paste_stdin_uses_shared_size_limit(self) -> None:
        args = argparse.Namespace(stdin=True)
        with patch("sys.stdin", io.StringIO("x" * (MAX_IMPORT_BYTES + 1))):
            with self.assertRaisesRegex(ValueError, "大小上限"):
                _read_paste_input(args)

    def test_clipboard_normal_utf8_payload_uses_same_decoder(self) -> None:
        class FakeProcess:
            def __init__(self) -> None:
                self.stdout = io.BytesIO("猫".encode("utf-8"))
                self.returncode = None
            def kill(self) -> None:
                self.returncode = -9
            def wait(self) -> int:
                if self.returncode is None:
                    self.returncode = 0
                return self.returncode
            def poll(self) -> int | None:
                return self.returncode

        with patch("jpnote_app.cli.shutil.which", return_value="/usr/bin/wl-paste"), patch(
            "jpnote_app.cli.subprocess.Popen", return_value=FakeProcess()
        ):
            self.assertEqual(_read_clipboard(), "猫")

    def test_clipboard_invalid_utf8_fails_closed(self) -> None:
        class FakeProcess:
            def __init__(self) -> None:
                self.stdout = io.BytesIO(b"\xff")
                self.returncode = None
            def kill(self) -> None:
                self.returncode = -9
            def wait(self) -> int:
                if self.returncode is None:
                    self.returncode = 0
                return self.returncode
            def poll(self) -> int | None:
                return self.returncode

        with patch("jpnote_app.cli.shutil.which", return_value="/usr/bin/wl-paste"), patch(
            "jpnote_app.cli.subprocess.Popen", return_value=FakeProcess()
        ):
            with self.assertRaisesRegex(ValueError, "有效 UTF-8"):
                _read_clipboard()

    def test_clipboard_is_killed_after_limit_plus_one_byte(self) -> None:
        class FakeProcess:
            def __init__(self) -> None:
                self.stdout = io.BytesIO(b"x" * (MAX_IMPORT_BYTES + 1))
                self.returncode = None
                self.killed = False
            def kill(self) -> None:
                self.killed = True
                self.returncode = -9
            def wait(self) -> int:
                if self.returncode is None:
                    self.returncode = 0
                return self.returncode
            def poll(self) -> int | None:
                return self.returncode

        fake = FakeProcess()
        with patch("jpnote_app.cli.shutil.which", return_value="/usr/bin/wl-paste"), patch(
            "jpnote_app.cli.subprocess.Popen", return_value=fake
        ):
            with self.assertRaisesRegex(ValueError, "大小上限"):
                _read_clipboard()
        self.assertTrue(fake.killed)


class PostCommitExportSemanticsTests(unittest.TestCase):
    def test_error_type_distinguishes_committed_db_from_precommit_failure(self) -> None:
        error = PostCommitExportError("import", OSError("disk full"), Path("undo.db"))
        self.assertTrue(error.database_committed)
        self.assertEqual(_protocol_error_type(error), "post_commit_export_error")
        self.assertIn("已完成", str(error))
        self.assertIn("jpnote export", str(error))

    def test_protocol_reports_committed_database_on_export_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            with patch.dict(os.environ, {"JPNOTE_DATA_DIR": str(data)}):
                # Ensure a pre-mutation database exists so the failure also has
                # a concrete published undo snapshot.
                with connect():
                    pass
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
                output = io.StringIO()
                with (
                    patch(
                        "jpnote_app.mutations.export_all",
                        side_effect=OSError("disk full"),
                    ),
                    patch(
                        "sys.argv",
                        [
                            "jpnote",
                            "import",
                            "--stdin",
                            "--yes",
                            "--protocol",
                            "1",
                        ],
                    ),
                    patch("sys.stdin", io.StringIO(payload)),
                    redirect_stdout(output),
                ):
                    rc = cli_module.main()

                self.assertEqual(rc, 1)
                response = json.loads(output.getvalue())
                self.assertFalse(response["ok"])
                self.assertEqual(
                    response["error"]["type"], "post_commit_export_error"
                )
                self.assertTrue(response["database_committed"])
                self.assertTrue(response["modified"])
                self.assertEqual(response["export_status"], "failed")
                self.assertTrue(response["backup"])
                self.assertTrue(Path(response["backup"]).is_file())
                with sqlite3.connect(db_path()) as conn:
                    self.assertEqual(
                        conn.execute(
                            "SELECT display FROM entries WHERE key='vocab:猫'"
                        ).fetchone()[0],
                        "猫",
                    )

    def test_real_export_failure_commits_db_and_publishes_undo_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            with patch.dict(os.environ, {"JPNOTE_DATA_DIR": str(data)}):
                with connect():
                    pass
                with patch(
                    "jpnote_app.mutations.export_all",
                    side_effect=OSError("disk full"),
                ):
                    with self.assertRaises(PostCommitExportError) as caught:
                        execute_safe_mutation(
                            "test-post-commit",
                            lambda conn: conn.execute(
                                "INSERT OR REPLACE INTO metadata(key,value) VALUES('committed','yes')"
                            ),
                        )
                with sqlite3.connect(db_path()) as conn:
                    value = conn.execute(
                        "SELECT value FROM metadata WHERE key='committed'"
                    ).fetchone()[0]
                self.assertEqual(value, "yes")
                self.assertIsNotNone(caught.exception.backup)
                self.assertTrue(Path(caught.exception.backup).is_file())


    def test_keyboard_interrupt_during_export_is_reported_as_post_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            with patch.dict(os.environ, {"JPNOTE_DATA_DIR": str(data)}):
                with connect():
                    pass
                with patch(
                    "jpnote_app.mutations.export_all",
                    side_effect=KeyboardInterrupt(),
                ):
                    with self.assertRaises(PostCommitExportError) as caught:
                        execute_safe_mutation(
                            "interrupt-after-commit",
                            lambda conn: conn.execute(
                                "INSERT OR REPLACE INTO metadata(key,value) VALUES('interrupt','yes')"
                            ),
                        )
                with sqlite3.connect(db_path()) as conn:
                    self.assertEqual(
                        conn.execute(
                            "SELECT value FROM metadata WHERE key='interrupt'"
                        ).fetchone()[0],
                        "yes",
                    )
                self.assertTrue(Path(caught.exception.backup).is_file())

    def test_undo_export_failure_reports_restore_already_completed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            with patch.dict(os.environ, {"JPNOTE_DATA_DIR": str(data)}):
                with connect() as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO metadata(key,value) VALUES('state','old')"
                    )
                candidate = backup_dir() / "undo-20260906T010000-000000-old.db"
                candidate.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(db_path(), candidate)
                with sqlite3.connect(db_path()) as conn:
                    conn.execute(
                        "UPDATE metadata SET value='new' WHERE key='state'"
                    )

                with patch(
                    "jpnote_app.cli.export_all",
                    side_effect=OSError("export disk full"),
                ):
                    with self.assertRaises(PostCommitExportError) as caught:
                        command_undo(
                            argparse.Namespace(list=False, backup=candidate.name)
                        )

                with sqlite3.connect(db_path()) as conn:
                    self.assertEqual(
                        conn.execute(
                            "SELECT value FROM metadata WHERE key='state'"
                        ).fetchone()[0],
                        "old",
                    )
                self.assertEqual(caught.exception.label, "undo")
                self.assertIsNotNone(caught.exception.backup)
                self.assertTrue(Path(caught.exception.backup).is_file())
                self.assertIn("資料庫變更已完成", str(caught.exception))



if __name__ == "__main__":
    unittest.main()
