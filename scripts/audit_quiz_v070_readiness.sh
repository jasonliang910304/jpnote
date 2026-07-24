#!/usr/bin/env bash

set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

TMP_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/jpnote-v070-readiness.XXXXXX")
trap 'rm -rf "$TMP_ROOT"' EXIT HUP INT TERM

export HOME="$TMP_ROOT/home"
export JPNOTE_DATA_DIR="$TMP_ROOT/data"
export JPNOTE_QUIZ_DB="$TMP_ROOT/quiz.db"
export XDG_CONFIG_HOME="$TMP_ROOT/config"
export XDG_DATA_HOME="$TMP_ROOT/xdg-data"
export TMP_ROOT

mkdir -p \
  "$HOME" \
  "$JPNOTE_DATA_DIR" \
  "$XDG_CONFIG_HOME" \
  "$XDG_DATA_HOME"

printf '== repository ==\n'
git status --short
printf 'HEAD=%s\n' "$(git rev-parse --short HEAD)"

printf '\n== source version ==\n'
python - <<'PY'
from jpnote_app.config import SCHEMA_VERSION, VERSION
from jpnote_app.quiz.session_store import QUIZ_SCHEMA_VERSION

print(f"VERSION={VERSION}")
print(f"CORE_SCHEMA={SCHEMA_VERSION}")
print(f"QUIZ_SCHEMA={QUIZ_SCHEMA_VERSION}")
PY

printf '\n== syntax ==\n'
python -m compileall -q jpnote_app tests
bash -n install.sh
bash -n scripts/smoke_isolated_install.sh

printf '\n== full regression ==\n'
pytest -q

printf '\n== app-only coverage ==\n'
if python -m coverage --version >/dev/null 2>&1; then
  python -m coverage erase
  python -m coverage run --source=jpnote_app -m pytest -q
  python -m coverage report --show-missing
  python -m coverage erase
else
  printf 'ERROR: Python coverage package is not installed.\n' >&2
  exit 1
fi

printf '\n== isolated installed smoke ==\n'
scripts/smoke_isolated_install.sh

printf '\n== source-tree CLI ==\n'
python -m jpnote_app --version
python -m jpnote_app --help | grep -q 'quiz'
python -m jpnote_app quiz --help | grep -q -- '--level'
python -m jpnote_app quiz --help | grep -q -- '--source'

printf '\n== isolated fresh core ==\n'
python -m jpnote_app init >/dev/null
python -m jpnote_app stats --format json >"$TMP_ROOT/stats.json"
python - <<'PY'
import json
import os
from pathlib import Path

data_dir = Path(os.environ["JPNOTE_DATA_DIR"])
quiz_db = Path(os.environ["JPNOTE_QUIZ_DB"])

stats = json.loads((Path(os.environ["TMP_ROOT"]) / "stats.json").read_text(encoding="utf-8"))
if not isinstance(stats, dict):
    raise SystemExit("stats JSON is not an object")
if not (data_dir / "jpnote.db").is_file():
    raise SystemExit("isolated jpnote.db was not created")
if quiz_db.exists():
    raise SystemExit("core init unexpectedly created quiz.db")

print("isolated core init/stats: PASS")
PY

printf '\n== optional Quiz loader ==\n'
python - <<'PY'
from jpnote_app.optional_features import load_quiz_tui

loaded = load_quiz_tui()
if not loaded.available:
    raise SystemExit(loaded.error)
print("quiz TUI lazy loader: PASS")
PY

printf '\n== tracked secret/database guard ==\n'
if git ls-files | grep -E '(^|/)([^/]*\.db|[^/]*\.sqlite[^/]*|\.env[^/]*|[^/]*\.pem|[^/]*\.key|credentials[^/]*|secrets[^/]*)$' >/dev/null; then
  printf 'ERROR: tracked database or secret-like file detected:\n' >&2
  git ls-files | grep -E '(^|/)([^/]*\.db|[^/]*\.sqlite[^/]*|\.env[^/]*|[^/]*\.pem|[^/]*\.key|credentials[^/]*|secrets[^/]*)$' >&2
  exit 1
fi
printf 'tracked secret/database guard: PASS\n'

printf '\n== diff hygiene ==\n'
git diff --check
git diff --cached --check

printf '\nrelease-readiness audit: PASS\n'
