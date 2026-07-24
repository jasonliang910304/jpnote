from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jpnote_app.config import VERSION


REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SCRIPT = REPO_ROOT / "install.sh"


class QuizPhase5IsolatedInstallationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.data_dir = self.root / "data"
        self.config_home = self.root / "config"
        self.xdg_data_home = self.root / "xdg-data"
        for path in (
            self.home,
            self.data_dir,
            self.config_home,
            self.xdg_data_home,
        ):
            path.mkdir(parents=True, exist_ok=True)

        self.quiz_db = self.root / "quiz.db"
        self.env = os.environ.copy()
        self.env.update(
            {
                "HOME": str(self.home),
                "JPNOTE_DATA_DIR": str(self.data_dir),
                "JPNOTE_QUIZ_DB": str(self.quiz_db),
                "XDG_CONFIG_HOME": str(self.config_home),
                "XDG_DATA_HOME": str(self.xdg_data_home),
                "PATH": os.environ.get("PATH", ""),
            }
        )
        self.env.pop("PYTHONPATH", None)
        self.launcher = self.home / ".local" / "bin" / "jpnote"
        self.target_root = self.home / ".local" / "lib" / "jpnote" / VERSION

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _install(self) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["/bin/sh", str(INSTALL_SCRIPT)],
            cwd=REPO_ROOT,
            env=self.env,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        return result

    def _run_launcher(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self.launcher), *args],
            cwd=self.root,
            env=self.env,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )

    def test_isolated_install_copies_quiz_docs_and_launcher(self) -> None:
        self._install()

        self.assertTrue(self.launcher.is_file())
        self.assertTrue(os.access(self.launcher, os.X_OK))
        self.assertTrue((self.target_root / "jpnote_app" / "quiz" / "tui.py").is_file())
        self.assertTrue((self.target_root / "docs" / "USER_GUIDE.md").is_file())

    def test_installed_version_help_quiz_help_and_lazy_loader(self) -> None:
        self._install()

        version = self._run_launcher("--version")
        self.assertEqual(version.returncode, 0, version.stderr)
        self.assertEqual(version.stdout.strip(), f"jpnote {VERSION}")

        help_result = self._run_launcher("--help")
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("quiz", help_result.stdout)

        quiz_help = self._run_launcher("quiz", "--help")
        self.assertEqual(quiz_help.returncode, 0, quiz_help.stderr)
        self.assertIn("--level", quiz_help.stdout)
        self.assertIn("--source", quiz_help.stdout)

        loader_env = self.env.copy()
        loader_env["PYTHONPATH"] = str(self.target_root)
        loader = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from jpnote_app.optional_features import load_quiz_tui; "
                    "loaded = load_quiz_tui(); "
                    "assert loaded.available, loaded.error; "
                    "print('quiz-tui-loader-ok')"
                ),
            ],
            cwd=self.root,
            env=loader_env,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(loader.returncode, 0, loader.stderr or loader.stdout)
        self.assertEqual(loader.stdout.strip(), "quiz-tui-loader-ok")

    def test_fresh_installed_init_and_stats_use_only_isolated_data(self) -> None:
        self._install()

        init_result = self._run_launcher("init")
        self.assertEqual(init_result.returncode, 0, init_result.stderr)
        self.assertTrue((self.data_dir / "jpnote.db").is_file())
        self.assertFalse(self.quiz_db.exists())

        stats_result = self._run_launcher("stats", "--format", "json")
        self.assertEqual(stats_result.returncode, 0, stats_result.stderr)
        self.assertIsInstance(json.loads(stats_result.stdout), dict)

    def test_install_does_not_modify_preexisting_data_directory(self) -> None:
        sentinel = self.data_dir / "sentinel.txt"
        database = self.data_dir / "jpnote.db"
        sentinel.write_text("keep-me\n", encoding="utf-8")
        database.write_bytes(b"not-opened-by-installer")
        before = {
            sentinel: sentinel.read_bytes(),
            database: database.read_bytes(),
        }

        self._install()

        self.assertEqual(
            {path: path.read_bytes() for path in before},
            before,
        )

    def test_reinstall_backs_up_existing_launcher(self) -> None:
        self._install()
        original = self.launcher.read_bytes()

        second = self._install()

        backups = sorted(
            self.launcher.parent.glob(f"jpnote.pre-{VERSION}.*")
        )
        self.assertTrue(backups, second.stdout)
        self.assertEqual(backups[-1].read_bytes(), original)

    def test_missing_quiz_package_fails_closed_without_breaking_core(self) -> None:
        self._install()
        shutil.rmtree(self.target_root / "jpnote_app" / "quiz")

        version = self._run_launcher("--version")
        self.assertEqual(version.returncode, 0, version.stderr)

        help_result = self._run_launcher("--help")
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("quiz", help_result.stdout)

        quiz_help = self._run_launcher("quiz", "--help")
        self.assertEqual(quiz_help.returncode, 0, quiz_help.stderr)

        quiz_run = self._run_launcher("quiz", "--count", "1")
        self.assertNotEqual(quiz_run.returncode, 0)
        combined = quiz_run.stdout + quiz_run.stderr
        self.assertIn("Quiz TUI", combined)
        self.assertNotIn("Traceback", combined)

        stats_result = self._run_launcher("stats", "--format", "json")
        self.assertEqual(stats_result.returncode, 0, stats_result.stderr)
        self.assertIsInstance(json.loads(stats_result.stdout), dict)

    def test_installed_manual_path_points_to_bundled_guide(self) -> None:
        self._install()

        result = self._run_launcher("manual", "--path")
        self.assertEqual(result.returncode, 0, result.stderr)
        guide = Path(result.stdout.strip())
        self.assertTrue(guide.is_file())
        self.assertTrue(guide.is_relative_to(self.target_root))
        self.assertEqual(guide.name, "USER_GUIDE.md")


if __name__ == "__main__":
    unittest.main()
