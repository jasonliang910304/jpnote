"""SQLite lifecycle, schema migrations, backups, and low-level helpers."""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
import tempfile
import time
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator

from .config import (
    AUXILIARY_BACKUP_MAX_BYTES,
    BACKUP_MAX_BYTES,
    SCHEMA_VERSION,
    backup_dir,
    data_dir,
    db_path,
    export_dir,
    restored_backup_dir,
)
from .fs_utils import ensure_private_dir, ensure_private_file

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS entries (
    key TEXT PRIMARY KEY,
    type TEXT NOT NULL CHECK (type IN ('grammar', 'vocabulary')),
    display TEXT NOT NULL,
    reading TEXT NOT NULL DEFAULT '',
    romaji TEXT NOT NULL DEFAULT '',
    accent TEXT NOT NULL DEFAULT '',
    accent_type TEXT NOT NULL DEFAULT '',
    accent_display TEXT NOT NULL DEFAULT '',
    accent_note TEXT NOT NULL DEFAULT '',
    level TEXT NOT NULL DEFAULT '',
    review_group TEXT NOT NULL DEFAULT '',
    aliases_json TEXT NOT NULL DEFAULT '[]',
    origin_type TEXT NOT NULL DEFAULT '',
    origin_language TEXT NOT NULL DEFAULT '',
    origin_word TEXT NOT NULL DEFAULT '',
    origin_note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS senses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_key TEXT NOT NULL REFERENCES entries(key) ON DELETE CASCADE,
    meaning TEXT NOT NULL,
    example_ja TEXT NOT NULL DEFAULT '',
    example_zh TEXT NOT NULL DEFAULT '',
    UNIQUE(entry_key, meaning, example_ja, example_zh)
);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_key TEXT NOT NULL REFERENCES entries(key) ON DELETE CASCADE,
    source TEXT NOT NULL,
    added_at TEXT NOT NULL,
    UNIQUE(entry_key, source)
);

CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_key TEXT NOT NULL UNIQUE,
    result TEXT NOT NULL CHECK (result IN ('correct', 'wrong', 'partial', 'unknown')),
    attempt_date TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    section TEXT NOT NULL DEFAULT '',
    question TEXT NOT NULL DEFAULT '',
    question_type TEXT NOT NULL DEFAULT 'other',
    prompt TEXT NOT NULL DEFAULT '',
    user_answer TEXT NOT NULL DEFAULT '',
    correct_answer TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    before_text TEXT NOT NULL DEFAULT '',
    after_text TEXT NOT NULL DEFAULT '',
    parts_json TEXT NOT NULL DEFAULT '[]',
    user_order_json TEXT NOT NULL DEFAULT '[]',
    correct_order_json TEXT NOT NULL DEFAULT '[]',
    options_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attempt_entries (
    attempt_id INTEGER NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
    entry_key TEXT NOT NULL REFERENCES entries(key) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'related',
    PRIMARY KEY (attempt_id, entry_key)
);

CREATE TABLE IF NOT EXISTS grammar_relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_key TEXT NOT NULL REFERENCES entries(key) ON DELETE CASCADE,
    target_key TEXT NOT NULL REFERENCES entries(key) ON DELETE CASCADE,
    relation_type TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(source_key, target_key, relation_type, note)
);

CREATE TABLE IF NOT EXISTS pending_grammar_relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_key TEXT NOT NULL REFERENCES entries(key) ON DELETE CASCADE,
    target_key TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(source_key, target_key, relation_type, note)
);

CREATE INDEX IF NOT EXISTS idx_entries_type ON entries(type);
CREATE INDEX IF NOT EXISTS idx_entries_level ON entries(level);
CREATE INDEX IF NOT EXISTS idx_entries_group ON entries(review_group);
CREATE INDEX IF NOT EXISTS idx_entries_reading ON entries(reading);
CREATE INDEX IF NOT EXISTS idx_senses_entry ON senses(entry_key);
CREATE INDEX IF NOT EXISTS idx_attempts_result ON attempts(result);
CREATE INDEX IF NOT EXISTS idx_attempts_date ON attempts(attempt_date);
CREATE INDEX IF NOT EXISTS idx_attempt_entries_entry ON attempt_entries(entry_key);
CREATE INDEX IF NOT EXISTS idx_relations_source ON grammar_relations(source_key);
CREATE INDEX IF NOT EXISTS idx_relations_target ON grammar_relations(target_key);
"""


ATTEMPT_MIGRATION_COLUMNS = {
    "options_json": "TEXT NOT NULL DEFAULT '[]'",
}

ENTRY_MIGRATION_COLUMNS = {
    "romaji": "TEXT NOT NULL DEFAULT ''",
    "accent": "TEXT NOT NULL DEFAULT ''",
    "accent_type": "TEXT NOT NULL DEFAULT ''",
    "accent_display": "TEXT NOT NULL DEFAULT ''",
    "accent_note": "TEXT NOT NULL DEFAULT ''",
    "origin_type": "TEXT NOT NULL DEFAULT ''",
    "origin_language": "TEXT NOT NULL DEFAULT ''",
    "origin_word": "TEXT NOT NULL DEFAULT ''",
    "origin_note": "TEXT NOT NULL DEFAULT ''",
}


class ManagedConnection(sqlite3.Connection):
    """SQLite connection with real nested transaction semantics.

    The outermost context owns the transaction and closes the connection when
    requested.  Nested ``with conn`` blocks use SAVEPOINTs, so leaving an inner
    block never commits the outer transaction early.
    """

    _jpnote_context_depth: int
    _jpnote_auto_close: bool
    _jpnote_savepoints: list[str | None]
    _jpnote_savepoint_counter: int

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._jpnote_context_depth = 0
        self._jpnote_auto_close = False
        self._jpnote_savepoints = []
        self._jpnote_savepoint_counter = 0

    def __enter__(self) -> "ManagedConnection":
        if self._jpnote_context_depth == 0:
            # Start explicitly so the first nested SAVEPOINT can never become
            # SQLite's outermost transaction and commit on RELEASE.
            if not self.in_transaction:
                self.execute("BEGIN")
            marker: str | None = None
        else:
            self._jpnote_savepoint_counter += 1
            marker = f"jpnote_sp_{self._jpnote_savepoint_counter}"
            self.execute(f"SAVEPOINT {marker}")
        self._jpnote_savepoints.append(marker)
        self._jpnote_context_depth += 1
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        marker = self._jpnote_savepoints.pop()
        self._jpnote_context_depth -= 1
        try:
            if marker is not None:
                if exc_type is None:
                    self.execute(f"RELEASE SAVEPOINT {marker}")
                else:
                    self.execute(f"ROLLBACK TO SAVEPOINT {marker}")
                    self.execute(f"RELEASE SAVEPOINT {marker}")
                return False

            if exc_type is None:
                self.commit()
            else:
                self.rollback()
            return False
        finally:
            if self._jpnote_auto_close and self._jpnote_context_depth == 0:
                self.close()


def now() -> datetime:
    return datetime.now().astimezone()


def now_text() -> str:
    return now().isoformat(timespec="microseconds")


def timestamp_for_filename() -> str:
    return now().strftime("%Y%m%dT%H%M%S-%f")


def ensure_directories() -> None:
    ensure_private_dir(data_dir())
    ensure_private_dir(export_dir())
    ensure_private_dir(backup_dir())
    ensure_private_dir(restored_backup_dir())


def sanitize_label(label: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_-]+", "-", label.strip()).strip("-")
    return cleaned or "change"


PENDING_BACKUP_LEGACY_GRACE_SECONDS = 300


def _pending_owner_pid(path: Path) -> int | None:
    match = re.search(r"-pid(\d+)-", path.name)
    return int(match.group(1)) if match else None


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def recover_orphaned_pending_backups(*, now_timestamp: float | None = None) -> list[Path]:
    """Promote valid crash-left pending snapshots into the undo pool.

    New pending filenames carry their owner PID, so a second jpnote process
    never steals an in-progress snapshot. Legacy pending files without a PID
    are promoted only after a grace period. Corrupt files are left untouched
    for manual inspection instead of being silently deleted.
    """
    ensure_directories()
    current_time = time.time() if now_timestamp is None else now_timestamp
    recovered: list[Path] = []
    for pending in sorted(backup_dir().glob(".pending-*.db")):
        try:
            stat_result = pending.stat()
        except FileNotFoundError:
            continue
        owner_pid = _pending_owner_pid(pending)
        if owner_pid is not None:
            if _pid_is_alive(owner_pid):
                continue
        elif current_time - stat_result.st_mtime < PENDING_BACKUP_LEGACY_GRACE_SECONDS:
            continue
        if not _sqlite_integrity_ok(pending):
            continue

        stem = pending.name.removeprefix(".pending-").removesuffix(".db")
        destination = backup_dir() / f"undo-{stem}-recovered.db"
        serial = 1
        while destination.exists():
            destination = backup_dir() / f"undo-{stem}-recovered-{serial}.db"
            serial += 1
        os.replace(pending, destination)
        ensure_private_file(destination)
        recovered.append(destination)
    if recovered:
        prune_backups()
    return recovered


def active_backups() -> list[Path]:
    ensure_directories()
    paths = sorted(backup_dir().glob("undo-*.db"), key=lambda path: path.stat().st_mtime)
    for path in paths:
        ensure_private_file(path)
    return paths


def _sqlite_integrity_ok(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as conn:
            row = conn.execute("PRAGMA quick_check").fetchone()
        return bool(row and str(row[0]).lower() == "ok")
    except sqlite3.Error:
        return False


def backup_integrity_ok(path: Path) -> bool:
    """Public integrity check used by backup listing and selective undo."""
    return _sqlite_integrity_ok(path)


def auxiliary_backups() -> list[Path]:
    """Return recovery snapshots and already-used backups, oldest first."""
    ensure_directories()
    paths = [*backup_dir().glob("recovery-*.db"), *restored_backup_dir().glob("*.db")]
    paths = sorted((path for path in paths if path.is_file()), key=lambda path: path.stat().st_mtime)
    for path in paths:
        ensure_private_file(path)
    return paths


def prune_auxiliary_backups() -> None:
    """Bound recovery/restored history separately from active undo snapshots."""
    paths = auxiliary_backups()
    total = sum(path.stat().st_size for path in paths)
    while total > AUXILIARY_BACKUP_MAX_BYTES and len(paths) > 1:
        oldest = paths.pop(0)
        size = oldest.stat().st_size
        oldest.unlink(missing_ok=True)
        total -= size


def active_backup_bytes() -> int:
    return sum(path.stat().st_size for path in active_backups() if path.exists())


def prune_backups() -> None:
    """Keep undo snapshots under the configured total-size budget.

    The newest snapshot is always retained even if a future database grows
    beyond the budget by itself; otherwise a successful backup operation could
    immediately leave the user with no undo point at all.
    """
    backups = active_backups()
    total = sum(path.stat().st_size for path in backups)
    while total > BACKUP_MAX_BYTES and len(backups) > 1:
        oldest = backups.pop(0)
        size = oldest.stat().st_size
        oldest.unlink(missing_ok=True)
        total -= size


def _create_sqlite_snapshot(destination: Path) -> Path:
    ensure_directories()
    source_path = db_path()
    fd, temp_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        with closing(sqlite3.connect(source_path)) as source, closing(sqlite3.connect(temp_path)) as target:
            source.backup(target)
        ensure_private_file(temp_path)
        try:
            fd = os.open(temp_path, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            pass
        if not _sqlite_integrity_ok(temp_path):
            raise RuntimeError("SQLite 備份完整性檢查失敗，未保留該備份。")
        os.replace(temp_path, destination)
        ensure_private_file(destination)
        return destination
    finally:
        temp_path.unlink(missing_ok=True)


def create_backup(label: str, *, prune_after: bool = True) -> Path | None:
    """Create an atomic, integrity-checked SQLite snapshot for undo."""
    ensure_directories()
    path = db_path()
    if not path.exists():
        return None
    destination = backup_dir() / f"undo-{timestamp_for_filename()}-{sanitize_label(label)}.db"
    _create_sqlite_snapshot(destination)
    if prune_after:
        prune_backups()
    return destination


@dataclass(slots=True)
class MutationBackupHandle:
    """Deferred undo-backup publication state.

    A pre-mutation snapshot is still taken before any write, but it is only
    published into the active undo pool after the caller explicitly marks that
    the guarded operation changed the database.  This prevents true no-op
    imports/repairs from evicting an older useful undo point.
    """

    path: Path | None
    changed: bool = False
    published: bool = False

    def mark_changed(self, changed: bool = True) -> None:
        self.changed = self.changed or bool(changed)

    def __bool__(self) -> bool:
        return bool(self.path is not None and self.published)

    def __str__(self) -> str:
        return str(self.path) if self else ""

    def __fspath__(self) -> str:
        if self.path is None:
            raise TypeError("此 mutation 沒有可用的備份路徑。")
        return str(self.path)


@contextmanager
def mutation_backup(label: str) -> Iterator[MutationBackupHandle]:
    """Publish an undo snapshot only after a successful real mutation.

    The snapshot is first written under a hidden ``.pending-*`` name that is
    excluded from ``active_backups()``.  Callers must invoke
    :meth:`MutationBackupHandle.mark_changed` when SQLite data actually changed.
    Failed and no-op operations remove the pending snapshot without pruning the
    active backup pool.
    """
    ensure_directories()
    if not db_path().exists():
        handle = MutationBackupHandle(None)
        yield handle
        return
    stamp = timestamp_for_filename()
    suffix = sanitize_label(label)
    final_path = backup_dir() / f"undo-{stamp}-{suffix}.db"
    pending_path = backup_dir() / f".pending-{stamp}-pid{os.getpid()}-{suffix}.db"
    _create_sqlite_snapshot(pending_path)
    handle = MutationBackupHandle(final_path)
    try:
        yield handle
    except Exception:
        # If the database mutation already committed but a later side effect
        # (for example Markdown export) failed, retain the pre-mutation undo
        # point instead of silently discarding it.
        if handle.changed and pending_path.exists():
            os.replace(pending_path, final_path)
            ensure_private_file(final_path)
            handle.published = True
            prune_backups()
        raise
    else:
        if handle.changed:
            os.replace(pending_path, final_path)
            ensure_private_file(final_path)
            handle.published = True
            prune_backups()
    finally:
        pending_path.unlink(missing_ok=True)


def create_recovery_snapshot(label: str) -> Path | None:
    ensure_directories()
    path = db_path()
    if not path.exists():
        return None
    destination = backup_dir() / f"recovery-{timestamp_for_filename()}-{sanitize_label(label)}.db"
    result = _create_sqlite_snapshot(destination)
    prune_auxiliary_backups()
    return result


def restore_database_from(backup_path: Path) -> None:
    ensure_directories()
    if not backup_path.is_file():
        raise ValueError(f"找不到備份：{backup_path}")
    if not _sqlite_integrity_ok(backup_path):
        raise ValueError(f"備份完整性檢查失敗，拒絕復原：{backup_path}")
    fd, temp_name = tempfile.mkstemp(prefix="jpnote-restore-", suffix=".db", dir=data_dir())
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        with closing(sqlite3.connect(backup_path)) as source, closing(sqlite3.connect(temp_path)) as target:
            source.backup(target)
        for suffix in ("-wal", "-shm", "-journal"):
            Path(str(db_path()) + suffix).unlink(missing_ok=True)
        os.replace(temp_path, db_path())
        ensure_private_file(db_path())
    finally:
        temp_path.unlink(missing_ok=True)


def _needs_migration_backup(conn: sqlite3.Connection) -> bool:
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "entries" not in tables:
        return False
    columns = {row[1] for row in conn.execute("PRAGMA table_info(entries)")}
    if any(name not in columns for name in ENTRY_MIGRATION_COLUMNS):
        return True
    if "attempts" in tables:
        attempt_columns = {row[1] for row in conn.execute("PRAGMA table_info(attempts)")}
        if any(name not in attempt_columns for name in ATTEMPT_MIGRATION_COLUMNS):
            return True
    return any(table not in tables for table in {"metadata", "attempts", "grammar_relations"})


def _stored_schema_version(conn: sqlite3.Connection) -> int:
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "metadata" not in tables:
        return 0
    row = conn.execute("SELECT value FROM metadata WHERE key = 'schema_version'").fetchone()
    if row is None:
        return 0
    try:
        return int(row[0])
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"資料庫 schema_version 無效：{row[0]!r}") from exc


RELATION_LABEL_MIGRATIONS = {
    "相似用法": "意思相近",
    "相反／對比": "對比",
    "替代表現": "替代表達",
    "前置基礎": "前置文法",
    "延伸文法": "延伸",
}


def normalize_stored_relation_labels(conn: sqlite3.Connection) -> None:
    """Normalize historical relation labels to the v0.5 canonical enum.

    This is a data-value migration only; no schema change is required.  It is
    intentionally idempotent so opening an existing database remains safe.
    """
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    with conn:
        for table in ("grammar_relations", "pending_grammar_relations"):
            if table not in tables:
                continue
            for old, new in RELATION_LABEL_MIGRATIONS.items():
                # Reinsert with the canonical label first, then remove the old
                # row. INSERT OR IGNORE safely coalesces a historical row when
                # an equivalent canonical relation already exists.
                conn.execute(
                    f"""
                    INSERT OR IGNORE INTO {table}(
                        source_key, target_key, relation_type, note, source, created_at
                    )
                    SELECT source_key, target_key, ?, note, source, created_at
                    FROM {table}
                    WHERE relation_type = ?
                    """,
                    (new, old),
                )
                conn.execute(
                    f"DELETE FROM {table} WHERE relation_type = ?",
                    (old,),
                )


def migrate_schema(
    conn: sqlite3.Connection,
    *,
    create_migration_backup: bool = True,
    prune_after: bool = True,
    normalize_relation_values: bool = False,
) -> None:
    """Upgrade a connection to the current schema.

    Normal writable connections protect on-disk migrations with a backup and
    prune the undo pool afterwards.  Read-only preflight uses an in-memory copy
    with both filesystem side effects disabled.
    """
    stored_version = _stored_schema_version(conn)
    if stored_version > SCHEMA_VERSION:
        raise RuntimeError(
            f"資料庫 schema v{stored_version} 比目前 jpnote 支援的 v{SCHEMA_VERSION} 新；"
            "請使用較新的 jpnote，避免舊版降級或破壞資料。"
        )
    if _needs_migration_backup(conn) and create_migration_backup:
        create_backup("schema-v05")

    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "entries" in tables:
        existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(entries)")}
        with conn:
            for name, definition in ENTRY_MIGRATION_COLUMNS.items():
                if name not in existing_columns:
                    conn.execute(f"ALTER TABLE entries ADD COLUMN {name} {definition}")
    if "attempts" in tables:
        existing_attempt_columns = {row[1] for row in conn.execute("PRAGMA table_info(attempts)")}
        with conn:
            for name, definition in ATTEMPT_MIGRATION_COLUMNS.items():
                if name not in existing_attempt_columns:
                    conn.execute(f"ALTER TABLE attempts ADD COLUMN {name} {definition}")

    conn.executescript(SCHEMA)
    with conn:
        conn.execute(
            "INSERT INTO metadata(key, value) VALUES('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(SCHEMA_VERSION),),
        )
    if normalize_relation_values:
        normalize_stored_relation_labels(conn)
    if prune_after:
        prune_backups()


def connect_preflight() -> ManagedConnection:
    """Return an isolated current-schema snapshot for non-destructive checks.

    The real database is never created, migrated, repaired, chmodded, or pruned.
    If it exists, SQLite's backup API copies its committed state into memory and
    migrations run only against that private snapshot.
    """
    conn = sqlite3.connect(":memory:", factory=ManagedConnection)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    path = db_path()
    try:
        if path.exists():
            with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as source:
                source.backup(conn)
        migrate_schema(
            conn, create_migration_backup=False, prune_after=False, normalize_relation_values=False
        )
    except Exception:
        conn.close()
        raise
    conn._jpnote_auto_close = True
    return conn


def connect() -> ManagedConnection:
    ensure_directories()
    recover_orphaned_pending_backups()
    conn = sqlite3.connect(db_path(), factory=ManagedConnection)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        migrate_schema(conn)
        ensure_private_file(db_path())
    except Exception:
        conn.close()
        raise
    # Migration uses transaction context blocks internally.  Enable automatic
    # close only after initialization so those blocks do not close the
    # connection before it is returned to the caller.
    conn._jpnote_auto_close = True
    return conn


def move_used_backup(path: Path) -> Path:
    ensure_private_dir(restored_backup_dir())
    destination = restored_backup_dir() / path.name
    shutil.move(str(path), str(destination))
    ensure_private_file(destination)
    prune_auxiliary_backups()
    return destination
