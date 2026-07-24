#!/bin/sh

set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
TMP_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/jpnote-install-smoke.XXXXXX")
trap 'rm -rf "$TMP_ROOT"' EXIT HUP INT TERM

export HOME="$TMP_ROOT/home"
export JPNOTE_DATA_DIR="$TMP_ROOT/data"
export JPNOTE_QUIZ_DB="$TMP_ROOT/quiz.db"
export XDG_CONFIG_HOME="$TMP_ROOT/config"
export XDG_DATA_HOME="$TMP_ROOT/xdg-data"
unset PYTHONPATH

mkdir -p \
  "$HOME" \
  "$JPNOTE_DATA_DIR" \
  "$XDG_CONFIG_HOME" \
  "$XDG_DATA_HOME"

VERSION=$(
  PYTHONPATH="$ROOT" python3 -c \
    'from jpnote_app.config import VERSION; print(VERSION)'
)

printf '== isolated install ==\n'
/bin/sh "$ROOT/install.sh"

LAUNCHER="$HOME/.local/bin/jpnote"
TARGET_ROOT="$HOME/.local/lib/jpnote/$VERSION"

test -x "$LAUNCHER"
test -f "$TARGET_ROOT/jpnote_app/quiz/tui.py"
test -f "$TARGET_ROOT/docs/USER_GUIDE.md"

printf '== installed CLI ==\n'
"$LAUNCHER" --version
"$LAUNCHER" --help | grep -q 'quiz'
"$LAUNCHER" quiz --help | grep -q -- '--level'
"$LAUNCHER" quiz --help | grep -q -- '--source'

printf '== optional loader ==\n'
PYTHONPATH="$TARGET_ROOT" python3 - <<'PY'
from jpnote_app.optional_features import load_quiz_tui

loaded = load_quiz_tui()
if not loaded.available:
    raise SystemExit(loaded.error)
print("quiz-tui-loader-ok")
PY

printf '== isolated core init/stats ==\n'
"$LAUNCHER" init >/dev/null
"$LAUNCHER" stats --format json >/dev/null

test -f "$JPNOTE_DATA_DIR/jpnote.db"
test ! -e "$JPNOTE_QUIZ_DB"

printf 'isolated installed smoke: PASS\n'
