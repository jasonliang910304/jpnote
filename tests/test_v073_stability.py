from __future__ import annotations

import hashlib
import os
import shutil
import shlex
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from jpnote_app.cli import command_backups, command_stats
from jpnote_app.config import SCHEMA_VERSION, VERSION, backup_dir, data_dir, db_path
from jpnote_app.db import connect, connect_readonly
from jpnote_app.quiz.session_store import QuizSessionStore


ROOT = Path(__file__).resolve().parents[1]


class ReadOnlyConnectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        os.environ["JPNOTE_DATA_DIR"] = str(self.root / "data")
        os.environ.pop("JPNOTE_QUIZ_DB", None)

    def tearDown(self) -> None:
        os.environ.pop("JPNOTE_DATA_DIR", None)
        os.environ.pop("JPNOTE_QUIZ_DB", None)
        self.temp.cleanup()

    def test_missing_database_readonly_view_does_not_create_filesystem_state(self) -> None:
        self.assertFalse(data_dir().exists())
        with connect_readonly() as conn:
            row = conn.execute(
                "SELECT value FROM metadata WHERE key='schema_version'"
            ).fetchone()
            self.assertEqual(row[0], str(SCHEMA_VERSION))
            self.assertEqual(conn.execute("PRAGMA query_only").fetchone()[0], 1)
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("INSERT INTO metadata(key, value) VALUES('readonly-test', '1')")
        self.assertFalse(data_dir().exists())

    @unittest.skipUnless(os.name == "posix", "POSIX mode regression")
    def test_current_database_read_does_not_chmod_database_or_parent(self) -> None:
        with connect() as conn:
            conn.execute("SELECT 1")
        data_dir().chmod(0o755)
        db_path().chmod(0o644)

        with connect_readonly() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0], 0)
            self.assertEqual(conn.execute("PRAGMA query_only").fetchone()[0], 1)

        self.assertEqual(stat.S_IMODE(data_dir().stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE(db_path().stat().st_mode), 0o644)

    def test_older_schema_is_migrated_only_in_memory(self) -> None:
        with connect() as conn:
            conn.execute("SELECT 1")
        with sqlite3.connect(db_path()) as raw:
            raw.execute(
                "UPDATE metadata SET value=? WHERE key='schema_version'",
                (str(SCHEMA_VERSION - 1),),
            )

        before_hash = hashlib.sha256(db_path().read_bytes()).hexdigest()
        before_mtime = db_path().stat().st_mtime_ns
        with connect_readonly() as conn:
            version = conn.execute(
                "SELECT value FROM metadata WHERE key='schema_version'"
            ).fetchone()[0]
            self.assertEqual(version, str(SCHEMA_VERSION))
            self.assertEqual(conn.execute("PRAGMA query_only").fetchone()[0], 1)

        self.assertEqual(hashlib.sha256(db_path().read_bytes()).hexdigest(), before_hash)
        self.assertEqual(db_path().stat().st_mtime_ns, before_mtime)

    def test_current_version_with_missing_table_is_repaired_only_in_memory(self) -> None:
        with connect() as conn:
            conn.execute("SELECT 1")
        with sqlite3.connect(db_path()) as raw:
            raw.execute("DROP TABLE pending_grammar_relations")

        before_hash = hashlib.sha256(db_path().read_bytes()).hexdigest()
        before_mtime = db_path().stat().st_mtime_ns
        with connect_readonly() as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            self.assertIn("pending_grammar_relations", tables)
            self.assertEqual(conn.execute("PRAGMA query_only").fetchone()[0], 1)

        with sqlite3.connect(db_path()) as raw:
            disk_tables = {
                row[0]
                for row in raw.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        self.assertNotIn("pending_grammar_relations", disk_tables)
        self.assertEqual(hashlib.sha256(db_path().read_bytes()).hexdigest(), before_hash)
        self.assertEqual(db_path().stat().st_mtime_ns, before_mtime)

    def test_future_schema_is_rejected_without_disk_mutation(self) -> None:
        with connect() as conn:
            conn.execute("SELECT 1")
        with sqlite3.connect(db_path()) as raw:
            raw.execute(
                "UPDATE metadata SET value=? WHERE key='schema_version'",
                (str(SCHEMA_VERSION + 1),),
            )
        before = db_path().read_bytes()
        with self.assertRaises(RuntimeError):
            connect_readonly()
        self.assertEqual(db_path().read_bytes(), before)

    def test_stats_on_missing_database_is_readonly(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            rc = command_stats(Namespace(format="json"))
        self.assertEqual(rc, 0)
        self.assertIn('"total": 0', output.getvalue())
        self.assertFalse(data_dir().exists())

    def test_backup_listing_on_missing_database_is_readonly(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            rc = command_backups(Namespace())
        self.assertEqual(rc, 0)
        self.assertIn("目前沒有可供 undo 的備份", output.getvalue())
        self.assertFalse(data_dir().exists())

    @unittest.skipUnless(os.name == "posix", "POSIX mode regression")
    def test_backup_listing_preserves_existing_directory_and_file_modes(self) -> None:
        directory = backup_dir()
        directory.mkdir(parents=True)
        snapshot = directory / "undo-readonly-test.db"
        snapshot.write_bytes(b"not opened by listing")
        data_dir().chmod(0o755)
        directory.chmod(0o755)
        snapshot.chmod(0o644)

        output = StringIO()
        with redirect_stdout(output):
            rc = command_backups(Namespace())

        self.assertEqual(rc, 0)
        self.assertIn(snapshot.name, output.getvalue())
        self.assertEqual(stat.S_IMODE(data_dir().stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE(snapshot.stat().st_mode), 0o644)


class QuizExplicitPathPermissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        os.environ.pop("JPNOTE_QUIZ_DB", None)
        os.environ.pop("JPNOTE_DATA_DIR", None)

    def tearDown(self) -> None:
        os.environ.pop("JPNOTE_QUIZ_DB", None)
        os.environ.pop("JPNOTE_DATA_DIR", None)
        self.temp.cleanup()

    @unittest.skipUnless(os.name == "posix", "POSIX mode regression")
    def test_constructor_explicit_path_preserves_existing_parent_mode(self) -> None:
        parent = self.root / "shared"
        parent.mkdir(mode=0o755)
        parent.chmod(0o755)
        path = parent / "quiz.db"

        QuizSessionStore(path)

        self.assertEqual(stat.S_IMODE(parent.stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    @unittest.skipUnless(os.name == "posix", "POSIX mode regression")
    def test_environment_explicit_path_preserves_existing_parent_mode(self) -> None:
        parent = self.root / "shared-env"
        parent.mkdir(mode=0o755)
        parent.chmod(0o755)
        path = parent / "quiz.db"
        os.environ["JPNOTE_QUIZ_DB"] = str(path)

        QuizSessionStore()

        self.assertEqual(stat.S_IMODE(parent.stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    @unittest.skipUnless(os.name == "posix", "POSIX mode regression")
    def test_app_owned_data_parent_remains_private(self) -> None:
        parent = self.root / "owned-data"
        os.environ["JPNOTE_DATA_DIR"] = str(parent)

        QuizSessionStore()

        self.assertEqual(stat.S_IMODE(parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((parent / "quiz.db").stat().st_mode), 0o600)


class InstallerStabilityTests(unittest.TestCase):
    def _run_installer(self, home: Path, *, source: Path = ROOT, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env["HOME"] = str(home)
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            ["sh", str(source / "install.sh")],
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )

    def _minimal_source(self, root: Path, *, output: str | None = None) -> Path:
        source = root / "source"
        source.mkdir()
        shutil.copy2(ROOT / "install.sh", source / "install.sh")
        package = source / "jpnote_app"
        package.mkdir()
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "config.py").write_text(
            f'VERSION = "{VERSION}"\n', encoding="utf-8"
        )
        (package / "__main__.py").write_text(
            f'print({(output or f"jpnote {VERSION}")!r})\n', encoding="utf-8"
        )
        docs = source / "docs"
        docs.mkdir()
        (docs / "USER_GUIDE.md").write_text("test guide\n", encoding="utf-8")
        return source

    def _fail_once_python_env(self, root: Path, fail_dest: Path) -> dict[str, str]:
        fake_bin = root / "fake-bin"
        fake_bin.mkdir()
        marker = root / "python-failed-once"
        fake_python = fake_bin / "python3"
        fake_python.write_text(
            "#!/bin/sh\n"
            f"if [ \"${{JPNOTE_REPLACE_DEST:-}}\" = {shlex.quote(str(fail_dest))} ] "
            f"&& [ ! -e {shlex.quote(str(marker))} ]; then\n"
            f"  : > {shlex.quote(str(marker))}\n"
            "  exit 42\n"
            "fi\n"
            f"exec {shlex.quote(sys.executable)} \"$@\"\n",
            encoding="utf-8",
        )
        fake_python.chmod(0o755)
        return {
            "PATH": str(fake_bin) + os.pathsep + os.environ.get("PATH", ""),
        }

    def test_existing_install_lock_fails_closed_before_version_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "home"
            app_root = home / ".local" / "lib" / "jpnote"
            lock = app_root / ".install-lock"
            lock.mkdir(parents=True)
            (lock / "pid").write_text("999999\n", encoding="utf-8")
            target = app_root / VERSION
            target.mkdir()
            marker = target / "marker"
            marker.write_text("KEEP\n", encoding="utf-8")

            result = self._run_installer(home)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("另一個安裝程序或 stale installer lock", result.stderr)
            self.assertEqual(marker.read_text(encoding="utf-8"), "KEEP\n")
            self.assertTrue(lock.is_dir())

    def test_version_target_symlink_is_rejected_without_touching_external_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "home"
            app_root = home / ".local" / "lib" / "jpnote"
            app_root.mkdir(parents=True)
            external = root / "external"
            external.mkdir()
            marker = external / "marker"
            marker.write_text("SAFE\n", encoding="utf-8")
            (app_root / VERSION).symlink_to(external, target_is_directory=True)

            result = self._run_installer(home)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("symlink version target", result.stderr)
            self.assertEqual(marker.read_text(encoding="utf-8"), "SAFE\n")

    def test_current_symlink_traversal_is_rejected_without_touching_external_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "home"
            target = home / ".local" / "lib" / "jpnote" / VERSION
            revisions = target / "revisions"
            revisions.mkdir(parents=True)
            external = root / "external"
            external.mkdir()
            marker = external / "marker"
            marker.write_text("SAFE\n", encoding="utf-8")
            (target / "current").symlink_to(
                "revisions/../../../../../../external",
                target_is_directory=True,
            )

            result = self._run_installer(home)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("current 指向非受管理 revision", result.stderr)
            self.assertEqual(marker.read_text(encoding="utf-8"), "SAFE\n")

    def test_current_revision_symlink_is_rejected_without_touching_external_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "home"
            target = home / ".local" / "lib" / "jpnote" / VERSION
            revisions = target / "revisions"
            revisions.mkdir(parents=True)
            external = root / "external"
            external.mkdir()
            marker = external / "marker"
            marker.write_text("SAFE\n", encoding="utf-8")
            (revisions / "old").symlink_to(external, target_is_directory=True)
            (target / "current").symlink_to("revisions/old", target_is_directory=True)

            result = self._run_installer(home)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("current 指向不存在或非實體 revision", result.stderr)
            self.assertEqual(marker.read_text(encoding="utf-8"), "SAFE\n")

    def test_unexpected_compat_symlink_is_replaced_without_touching_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "home"
            target = home / ".local" / "lib" / "jpnote" / VERSION
            target.mkdir(parents=True)
            external = root / "external"
            external.mkdir()
            marker = external / "marker"
            marker.write_text("SAFE\n", encoding="utf-8")
            (target / "docs").symlink_to(external, target_is_directory=True)

            result = self._run_installer(home)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(marker.read_text(encoding="utf-8"), "SAFE\n")
            self.assertTrue((target / "docs").is_symlink())
            self.assertEqual(os.readlink(target / "docs"), "current/docs")
            self.assertTrue((target / "docs" / "USER_GUIDE.md").is_file())

    def test_python_too_old_fails_before_install_tree_creation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "home"
            home.mkdir()
            fake_bin = root / "bin"
            fake_bin.mkdir()
            fake_python = fake_bin / "python3"
            fake_python.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            fake_python.chmod(0o755)
            path = str(fake_bin) + os.pathsep + os.environ.get("PATH", "")

            result = self._run_installer(home, env_extra={"PATH": path})

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Python 版本過舊", result.stderr)
            self.assertFalse((home / ".local" / "lib" / "jpnote").exists())

    def test_staging_validation_failure_keeps_existing_target_unmodified(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            shutil.copy2(ROOT / "install.sh", source / "install.sh")
            (source / "jpnote_app").mkdir()
            (source / "jpnote_app" / "__init__.py").write_text("", encoding="utf-8")
            (source / "jpnote_app" / "config.py").write_text(
                'VERSION = "broken"\n', encoding="utf-8"
            )
            (source / "docs").mkdir()

            home = root / "home"
            target = home / ".local" / "lib" / "jpnote" / VERSION
            target.mkdir(parents=True)
            marker = target / "existing-marker"
            marker.write_text("KEEP\n", encoding="utf-8")

            result = self._run_installer(home, source=source)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("staging 版本驗證失敗", result.stderr)
            self.assertEqual(marker.read_text(encoding="utf-8"), "KEEP\n")
            revisions = target / "revisions"
            if revisions.exists():
                self.assertFalse(any(path.name.startswith(".stage-") for path in revisions.iterdir()))

    def test_current_atomic_replace_failure_restores_previous_current(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self._minimal_source(root)
            home = root / "home"
            target = home / ".local" / "lib" / "jpnote" / VERSION
            old_revision = target / "revisions" / "old"
            (old_revision / "jpnote_app").mkdir(parents=True)
            (old_revision / "docs").mkdir()
            (target / "current").symlink_to("revisions/old", target_is_directory=True)
            (target / "jpnote_app").symlink_to("current/jpnote_app", target_is_directory=True)
            (target / "docs").symlink_to("current/docs", target_is_directory=True)

            bin_dir = home / ".local" / "bin"
            bin_dir.mkdir(parents=True)
            launcher = bin_dir / "jpnote"
            launcher.write_text(
                "#!/bin/sh\nprintf 'jpnote 0.7.2\\n'\n",
                encoding="utf-8",
            )
            launcher.chmod(0o755)
            original_launcher = launcher.read_bytes()
            env_extra = self._fail_once_python_env(root, target / "current")

            result = self._run_installer(home, source=source, env_extra=env_extra)

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(os.readlink(target / "current"), "revisions/old")
            self.assertEqual(launcher.read_bytes(), original_launcher)

    def test_launcher_atomic_replace_failure_restores_previous_current_and_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self._minimal_source(root)
            home = root / "home"
            target = home / ".local" / "lib" / "jpnote" / VERSION
            old_revision = target / "revisions" / "old"
            (old_revision / "jpnote_app").mkdir(parents=True)
            (old_revision / "docs").mkdir()
            (target / "current").symlink_to("revisions/old", target_is_directory=True)
            (target / "jpnote_app").symlink_to("current/jpnote_app", target_is_directory=True)
            external_docs = root / "external-docs"
            external_docs.mkdir()
            external_marker = external_docs / "marker"
            external_marker.write_text("SAFE\n", encoding="utf-8")
            (target / "docs").symlink_to(external_docs, target_is_directory=True)
            old_docs_target = os.readlink(target / "docs")

            bin_dir = home / ".local" / "bin"
            bin_dir.mkdir(parents=True)
            launcher = bin_dir / "jpnote"
            launcher.write_text(
                "#!/bin/sh\nprintf 'jpnote 0.7.2\\n'\n",
                encoding="utf-8",
            )
            launcher.chmod(0o755)
            original_launcher = launcher.read_bytes()
            env_extra = self._fail_once_python_env(root, launcher)

            result = self._run_installer(home, source=source, env_extra=env_extra)

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(os.readlink(target / "current"), "revisions/old")
            self.assertEqual(launcher.read_bytes(), original_launcher)
            self.assertEqual(os.readlink(target / "docs"), old_docs_target)
            self.assertEqual(external_marker.read_text(encoding="utf-8"), "SAFE\n")

    def test_post_activation_validation_failure_restores_previous_revision_and_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            shutil.copy2(ROOT / "install.sh", source / "install.sh")
            package = source / "jpnote_app"
            package.mkdir()
            (package / "__init__.py").write_text("", encoding="utf-8")
            (package / "config.py").write_text(
                f'VERSION = "{VERSION}"\n', encoding="utf-8"
            )
            (package / "__main__.py").write_text(
                'print("jpnote broken")\n', encoding="utf-8"
            )
            (source / "docs").mkdir()

            home = root / "home"
            target = home / ".local" / "lib" / "jpnote" / VERSION
            old_revision = target / "revisions" / "old"
            (old_revision / "jpnote_app").mkdir(parents=True)
            (old_revision / "docs").mkdir()
            (target / "current").symlink_to("revisions/old", target_is_directory=True)
            (target / "jpnote_app").symlink_to("current/jpnote_app", target_is_directory=True)
            (target / "docs").symlink_to("current/docs", target_is_directory=True)

            bin_dir = home / ".local" / "bin"
            bin_dir.mkdir(parents=True)
            launcher = bin_dir / "jpnote"
            launcher.write_text(
                "#!/bin/sh\nprintf 'jpnote 0.7.2\\n'\n",
                encoding="utf-8",
            )
            launcher.chmod(0o755)
            original_launcher = launcher.read_bytes()

            result = self._run_installer(home, source=source)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("安裝後啟動驗證失敗", result.stderr)
            self.assertEqual(os.readlink(target / "current"), "revisions/old")
            self.assertEqual(launcher.read_bytes(), original_launcher)

    def test_successful_reinstall_uses_revision_activation_and_keeps_compat_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            first = self._run_installer(home)
            self.assertEqual(first.returncode, 0, first.stderr)
            second = self._run_installer(home)
            self.assertEqual(second.returncode, 0, second.stderr)

            launcher = home / ".local" / "bin" / "jpnote"
            version = subprocess.run(
                [str(launcher), "--version"],
                text=True,
                capture_output=True,
                env={**os.environ, "HOME": str(home)},
                check=False,
            )
            self.assertEqual(version.returncode, 0, version.stderr)
            self.assertEqual(version.stdout.strip(), f"jpnote {VERSION}")

            app_root = home / ".local" / "lib" / "jpnote"
            target = app_root / VERSION
            self.assertFalse((app_root / ".install-lock").exists())
            self.assertTrue((target / "current").is_symlink())
            self.assertTrue((target / "jpnote_app").is_symlink())
            self.assertTrue((target / "docs").is_symlink())
            self.assertTrue((target / "docs" / "USER_GUIDE.md").is_file())
            revisions = target / "revisions"
            self.assertGreaterEqual(len([p for p in revisions.iterdir() if p.is_dir()]), 2)
            self.assertFalse(any(p.name.startswith(".stage-") for p in revisions.iterdir()))


class CoreCiContractTests(unittest.TestCase):
    def test_core_ci_covers_minimum_and_primary_python_versions(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "core.yml").read_text(encoding="utf-8")
        self.assertIn("python-version: ['3.10', '3.13']", workflow)
        self.assertIn("python -m pytest -q -p no:cacheprovider", workflow)
        self.assertIn("python -m compileall -q jpnote_app tests", workflow)
        self.assertIn("sh ./install.sh", workflow)
        self.assertIn("actions/checkout@v6", workflow)
        self.assertIn("actions/setup-python@v6", workflow)

    def test_current_release_declares_python_310_minimum(self) -> None:
        self.assertEqual(VERSION, "0.7.5")
        installer = (ROOT / "install.sh").read_text(encoding="utf-8")
        guide = (ROOT / "docs" / "USER_GUIDE.md").read_text(encoding="utf-8")
        self.assertIn('MIN_PYTHON="3.10"', installer)
        self.assertIn("Python >= 3.10", guide)


if __name__ == "__main__":
    unittest.main()
