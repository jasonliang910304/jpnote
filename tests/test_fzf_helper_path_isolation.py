from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path
from unittest.mock import patch

from jpnote_app import ui_fzf


def test_isolated_search_helper_ignores_cwd_and_pythonpath_shadow(tmp_path: Path) -> None:
    dataset = tmp_path / "records.tsv"
    dataset.write_text(
        "entry:vocab:奇跡\t[單字] 奇跡\tki se ki kiseki\n",
        encoding="utf-8",
    )
    shadow = tmp_path / "shadow"
    package = shadow / "jpnote_app"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "fzf_search_helper.py").write_text(
        "raise SystemExit('SHADOWED-FZF-HELPER')\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(shadow)
    command = (
        f"{ui_fzf._isolated_module_command('jpnote_app.fzf_search_helper')} "
        f"{shlex.quote(str(dataset))} kiseki"
    )
    result = subprocess.run(
        ["/bin/sh", "-c", command],
        cwd=shadow,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert "entry:vocab:奇跡" in result.stdout
    assert "SHADOWED-FZF-HELPER" not in result.stdout + result.stderr


@patch("jpnote_app.ui_fzf.shutil.which", return_value="/usr/bin/fzf")
@patch("jpnote_app.ui_fzf.subprocess.run")
def test_fzf_reload_command_uses_isolated_bootstrap(run, _which) -> None:
    run.return_value.returncode = 130
    run.return_value.stdout = ""
    run.return_value.stderr = ""
    ui_fzf._run(["entry:vocab:奇跡\t奇跡\tki se ki"], "測試", multi=False)
    command = run.call_args.args[0]
    reload_bind = next(arg for arg in command if arg.startswith("--bind=change:reload("))
    assert " -I -c " in reload_bind
    assert "runpy.run_module" in reload_bind
    assert "python3 -m jpnote_app" not in reload_bind
