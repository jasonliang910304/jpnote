#!/bin/sh
set -eu

VERSION="0.7.0"
SOURCE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
TARGET_ROOT="$HOME/.local/lib/jpnote/$VERSION"
BIN_DIR="$HOME/.local/bin"
BIN_PATH="$BIN_DIR/jpnote"

mkdir -p "$TARGET_ROOT" "$BIN_DIR"
rm -rf "$TARGET_ROOT/jpnote_app" "$TARGET_ROOT/docs"
cp -R "$SOURCE_DIR/jpnote_app" "$TARGET_ROOT/jpnote_app"
if [ -d "$SOURCE_DIR/docs" ]; then
    cp -R "$SOURCE_DIR/docs" "$TARGET_ROOT/docs"
fi

if [ -e "$BIN_PATH" ] || [ -L "$BIN_PATH" ]; then
    backup="$BIN_PATH.pre-$VERSION.$(date +%Y%m%dT%H%M%S)"
    cp -P "$BIN_PATH" "$backup"
    printf '舊版啟動檔已備份：%s\n' "$backup"
fi

tmp_launcher="$BIN_DIR/.jpnote-launcher.$$"
trap 'rm -f "$tmp_launcher"' EXIT HUP INT TERM
cat > "$tmp_launcher" <<EOF
#!/bin/sh

JPNOTE_APP_DIR="\$HOME/.local/lib/jpnote/$VERSION"
export JPNOTE_APP_DIR

exec python3 -I -c '
import os
import runpy
import sys

sys.path.insert(0, os.environ["JPNOTE_APP_DIR"])
runpy.run_module("jpnote_app", run_name="__main__", alter_sys=True)
' "\$@"
EOF
chmod 755 "$tmp_launcher"
mv -f "$tmp_launcher" "$BIN_PATH"
trap - EXIT HUP INT TERM

printf '已安裝 jpnote %s：%s\n' "$VERSION" "$BIN_PATH"
printf '下一步執行：jpnote init\n'
