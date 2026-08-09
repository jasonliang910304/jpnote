#!/bin/sh
set -eu

VERSION="0.7.3"
MIN_PYTHON="3.10"
SOURCE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
APP_ROOT="$HOME/.local/lib/jpnote"
TARGET_ROOT="$APP_ROOT/$VERSION"
REVISIONS_DIR="$TARGET_ROOT/revisions"
CURRENT_LINK="$TARGET_ROOT/current"
BIN_DIR="$HOME/.local/bin"
BIN_PATH="$BIN_DIR/jpnote"
INSTALL_LOCK="$APP_ROOT/.install-lock"
INSTALL_LOCK_PID="$INSTALL_LOCK/pid"
LOCK_ACQUIRED=0
STAMP=$(date +%Y%m%dT%H%M%S)
REVISION="$STAMP-$$"
STAGE_ROOT="$REVISIONS_DIR/.stage-$REVISION"
REVISION_ROOT="$REVISIONS_DIR/$REVISION"
TMP_CURRENT="$TARGET_ROOT/.current-$REVISION"
TMP_LAUNCHER="$BIN_DIR/.jpnote-launcher-$REVISION"
BACKUP_LAUNCHER=""
OLD_CURRENT=""
ACTIVATED=0
LAUNCHER_REPLACED=0
COMPAT_APP_REPLACED=0
COMPAT_DOCS_REPLACED=0
COMPAT_APP_OLD_STATE="absent"
COMPAT_DOCS_OLD_STATE="absent"
COMPAT_APP_OLD_TARGET=""
COMPAT_DOCS_OLD_TARGET=""
TMP_COMPAT_APP="$TARGET_ROOT/.jpnote_app-$REVISION"
TMP_COMPAT_DOCS="$TARGET_ROOT/.docs-$REVISION"

umask 077

fail() {
    printf '安裝失敗：%s\n' "$*" >&2
    exit 1
}

is_safe_revision_target() {
    case "$1" in
        revisions/*)
            revision_name=${1#revisions/}
            case "$revision_name" in
                ""|.|..|*/*) return 1 ;;
                *) return 0 ;;
            esac
            ;;
        *) return 1 ;;
    esac
}

replace_path() {
    source_path=$1
    destination_path=$2
    JPNOTE_REPLACE_SOURCE="$source_path" JPNOTE_REPLACE_DEST="$destination_path" \
        python3 -I -c 'import os; os.replace(os.environ["JPNOTE_REPLACE_SOURCE"], os.environ["JPNOTE_REPLACE_DEST"])'
}

replace_symlink() {
    link_path=$1
    target=$2
    temp_path=$3
    rm -f -- "$temp_path"
    ln -s -- "$target" "$temp_path"
    replace_path "$temp_path" "$link_path"
}

release_install_lock() {
    if [ "$LOCK_ACQUIRED" -eq 1 ]; then
        if [ -d "$INSTALL_LOCK" ] && [ ! -L "$INSTALL_LOCK" ]; then
            owner_pid=""
            if [ -f "$INSTALL_LOCK_PID" ] && [ ! -L "$INSTALL_LOCK_PID" ]; then
                owner_pid=$(cat -- "$INSTALL_LOCK_PID" 2>/dev/null || true)
            fi
            if [ "$owner_pid" = "$$" ]; then
                rm -f -- "$INSTALL_LOCK_PID"
                rmdir -- "$INSTALL_LOCK" 2>/dev/null || true
            fi
        fi
        LOCK_ACQUIRED=0
    fi
}

rollback() {
    status=$?
    [ "$status" -ne 0 ] || status=1
    trap - EXIT HUP INT TERM

    rm -f -- "$TMP_LAUNCHER" "$TMP_CURRENT" "$TMP_COMPAT_APP" "$TMP_COMPAT_DOCS"
    if [ -d "$STAGE_ROOT" ] && [ ! -L "$STAGE_ROOT" ]; then
        rm -rf -- "$STAGE_ROOT"
    fi

    if [ "$LAUNCHER_REPLACED" -eq 1 ]; then
        if [ -n "$BACKUP_LAUNCHER" ] && { [ -e "$BACKUP_LAUNCHER" ] || [ -L "$BACKUP_LAUNCHER" ]; }; then
            replace_path "$BACKUP_LAUNCHER" "$BIN_PATH" || true
        else
            rm -f -- "$BIN_PATH"
        fi
    fi

    if [ "$ACTIVATED" -eq 1 ]; then
        if [ -n "$OLD_CURRENT" ]; then
            replace_symlink "$CURRENT_LINK" "$OLD_CURRENT" "$TMP_CURRENT" || true
        else
            rm -f -- "$CURRENT_LINK"
        fi
    fi

    if [ "$COMPAT_APP_REPLACED" -eq 1 ]; then
        if [ "$COMPAT_APP_OLD_STATE" = "symlink" ]; then
            replace_symlink "$TARGET_ROOT/jpnote_app" "$COMPAT_APP_OLD_TARGET" "$TMP_COMPAT_APP" || true
        else
            rm -f -- "$TARGET_ROOT/jpnote_app"
        fi
    fi
    if [ "$COMPAT_DOCS_REPLACED" -eq 1 ]; then
        if [ "$COMPAT_DOCS_OLD_STATE" = "symlink" ]; then
            replace_symlink "$TARGET_ROOT/docs" "$COMPAT_DOCS_OLD_TARGET" "$TMP_COMPAT_DOCS" || true
        else
            rm -f -- "$TARGET_ROOT/docs"
        fi
    fi

    release_install_lock
    printf 'jpnote %s 安裝未完成；已保留／恢復先前可用版本。\n' "$VERSION" >&2
    exit "$status"
}

command -v python3 >/dev/null 2>&1 || fail "找不到 python3；需要 Python >= $MIN_PYTHON。"
python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' \
    || fail "Python 版本過舊；jpnote $VERSION 需要 Python >= $MIN_PYTHON。"

case "$HOME" in
    /*) ;;
    *) fail "HOME 必須是絕對路徑。" ;;
esac

if [ -L "$APP_ROOT" ]; then
    fail "拒絕使用 symlink app root：$APP_ROOT"
fi
if [ -e "$APP_ROOT" ] && [ ! -d "$APP_ROOT" ]; then
    fail "app root 不是目錄：$APP_ROOT"
fi
mkdir -p -- "$APP_ROOT"

if [ -L "$INSTALL_LOCK" ]; then
    fail "installer lock path 不可為 symlink：$INSTALL_LOCK"
fi
if ! mkdir -- "$INSTALL_LOCK" 2>/dev/null; then
    fail "偵測到另一個安裝程序或 stale installer lock：$INSTALL_LOCK"
fi
LOCK_ACQUIRED=1
printf '%s\n' "$$" > "$INSTALL_LOCK_PID"
trap rollback EXIT HUP INT TERM

mkdir -p -- "$BIN_DIR"

if [ -L "$TARGET_ROOT" ]; then
    fail "拒絕使用 symlink version target：$TARGET_ROOT"
fi
if [ -e "$TARGET_ROOT" ] && [ ! -d "$TARGET_ROOT" ]; then
    fail "version target 不是目錄：$TARGET_ROOT"
fi
mkdir -p -- "$TARGET_ROOT"

if [ -L "$REVISIONS_DIR" ]; then
    fail "拒絕使用 symlink revisions directory：$REVISIONS_DIR"
fi
if [ -e "$REVISIONS_DIR" ] && [ ! -d "$REVISIONS_DIR" ]; then
    fail "revisions path 不是目錄：$REVISIONS_DIR"
fi
mkdir -p -- "$REVISIONS_DIR"

if [ -e "$CURRENT_LINK" ] && [ ! -L "$CURRENT_LINK" ]; then
    fail "current 必須是由 installer 管理的 symlink：$CURRENT_LINK"
fi
if [ -L "$CURRENT_LINK" ]; then
    OLD_CURRENT=$(readlink -- "$CURRENT_LINK")
    is_safe_revision_target "$OLD_CURRENT" || fail "current 指向非受管理 revision：$OLD_CURRENT"
    old_revision_path="$TARGET_ROOT/$OLD_CURRENT"
    [ -d "$old_revision_path" ] && [ ! -L "$old_revision_path" ] \
        || fail "current 指向不存在或非實體 revision：$OLD_CURRENT"
fi

compat_app="$TARGET_ROOT/jpnote_app"
if [ -e "$compat_app" ] || [ -L "$compat_app" ]; then
    [ -L "$compat_app" ] || fail "$compat_app 必須是 installer-managed symlink"
    COMPAT_APP_OLD_STATE="symlink"
    COMPAT_APP_OLD_TARGET=$(readlink -- "$compat_app")
fi

compat_docs="$TARGET_ROOT/docs"
if [ -e "$compat_docs" ] || [ -L "$compat_docs" ]; then
    [ -L "$compat_docs" ] || fail "$compat_docs 必須是 installer-managed symlink"
    COMPAT_DOCS_OLD_STATE="symlink"
    COMPAT_DOCS_OLD_TARGET=$(readlink -- "$compat_docs")
fi

if [ -e "$REVISION_ROOT" ] || [ -L "$REVISION_ROOT" ]; then
    fail "revision path collision：$REVISION_ROOT"
fi

if [ -e "$BIN_PATH" ] && [ -d "$BIN_PATH" ] && [ ! -L "$BIN_PATH" ]; then
    fail "啟動檔位置是目錄，拒絕覆寫：$BIN_PATH"
fi

mkdir -- "$STAGE_ROOT"
cp -R -- "$SOURCE_DIR/jpnote_app" "$STAGE_ROOT/jpnote_app"
if [ -d "$SOURCE_DIR/docs" ]; then
    cp -R -- "$SOURCE_DIR/docs" "$STAGE_ROOT/docs"
else
    mkdir -- "$STAGE_ROOT/docs"
fi

stage_version=$(
    JPNOTE_APP_DIR="$STAGE_ROOT" python3 -I -c '
import os
import sys
sys.path.insert(0, os.environ["JPNOTE_APP_DIR"])
from jpnote_app.config import VERSION
print(VERSION)
'
)
[ "$stage_version" = "$VERSION" ] \
    || fail "staging 版本驗證失敗：預期 $VERSION，得到 ${stage_version:-空值}"

cat > "$TMP_LAUNCHER" <<EOF2
#!/bin/sh

JPNOTE_APP_DIR="\$HOME/.local/lib/jpnote/$VERSION/current"
export JPNOTE_APP_DIR

exec python3 -I -c '
import os
import runpy
import sys
sys.path.insert(0, os.environ["JPNOTE_APP_DIR"])
runpy.run_module("jpnote_app", run_name="__main__", alter_sys=True)
' "\$@"
EOF2
chmod 755 "$TMP_LAUNCHER"

mv -- "$STAGE_ROOT" "$REVISION_ROOT"

if [ "$COMPAT_APP_OLD_STATE" != "symlink" ] || [ "$COMPAT_APP_OLD_TARGET" != "current/jpnote_app" ]; then
    COMPAT_APP_REPLACED=1
    replace_symlink "$TARGET_ROOT/jpnote_app" "current/jpnote_app" "$TMP_COMPAT_APP"
fi
if [ "$COMPAT_DOCS_OLD_STATE" != "symlink" ] || [ "$COMPAT_DOCS_OLD_TARGET" != "current/docs" ]; then
    COMPAT_DOCS_REPLACED=1
    replace_symlink "$TARGET_ROOT/docs" "current/docs" "$TMP_COMPAT_DOCS"
fi

ACTIVATED=1
replace_symlink "$CURRENT_LINK" "revisions/$REVISION" "$TMP_CURRENT"

if [ -e "$BIN_PATH" ] || [ -L "$BIN_PATH" ]; then
    BACKUP_LAUNCHER="$BIN_PATH.pre-$VERSION.$STAMP-$$"
    cp -P -- "$BIN_PATH" "$BACKUP_LAUNCHER"
    printf '舊版啟動檔已備份：%s\n' "$BACKUP_LAUNCHER"
fi
LAUNCHER_REPLACED=1
replace_path "$TMP_LAUNCHER" "$BIN_PATH"

installed_version=$("$BIN_PATH" --version)
[ "$installed_version" = "jpnote $VERSION" ] \
    || fail "安裝後啟動驗證失敗：${installed_version:-無輸出}"

release_install_lock
trap - EXIT HUP INT TERM

printf '已安裝 jpnote %s：%s\n' "$VERSION" "$BIN_PATH"
printf 'active revision：%s\n' "$REVISION_ROOT"
printf '下一步執行：jpnote init\n'
