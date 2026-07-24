from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from jpnote_app.config import VERSION


REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SCRIPT = REPO_ROOT / "install.sh"


class LauncherPathIsolationTests(unittest.TestCase):
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

        self.env = os.environ.copy()
        self.env.update(
            {
                "HOME": str(self.home),
                "JPNOTE_DATA_DIR": str(self.data_dir),
                "JPNOTE_QUIZ_DB": str(self.root / "quiz.db"),
                "XDG_CONFIG_HOME": str(self.config_home),
                "XDG_DATA_HOME": str(self.xdg_data_home),
                "PATH": os.environ.get("PATH", ""),
            }
        )
        self.env.pop("PYTHONPATH", None)
        self.launcher = self.home / ".local" / "bin" / "jpnote"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _install(self) -> None:
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

    def test_launcher_ignores_cwd_and_pythonpath_shadow(self) -> None:
        self._install()

        shadow_root = self.root / "shadow"
        shadow_package = shadow_root / "jpnote_app"
        shadow_package.mkdir(parents=True)
        (shadow_package / "__init__.py").write_text("", encoding="utf-8")
        (shadow_package / "__main__.py").write_text(
            "raise SystemExit('SHADOWED-JPNOTE-PACKAGE')\n",
            encoding="utf-8",
        )

        env = self.env.copy()
        env["PYTHONPATH"] = str(shadow_root)

        result = subprocess.run(
            [str(self.launcher), "--version"],
            cwd=shadow_root,
            env=env,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertEqual(result.stdout.strip(), f"jpnote {VERSION}")
        self.assertNotIn("SHADOWED-JPNOTE-PACKAGE", result.stdout + result.stderr)

    def test_generated_launcher_uses_isolated_bootstrap(self) -> None:
        self._install()

        launcher = self.launcher.read_text(encoding="utf-8")
        self.assertIn("exec python3 -I -c", launcher)
        self.assertIn("export JPNOTE_APP_DIR", launcher)
        self.assertIn(
            'sys.path.insert(0, os.environ["JPNOTE_APP_DIR"])',
            launcher,
        )
        self.assertNotIn("export PYTHONPATH", launcher)


if __name__ == "__main__":
    unittest.main()
