"""Runtime configuration and filesystem locations for jpnote.

The data path can be overridden with ``JPNOTE_DATA_DIR``.  Tests and a future
server process can therefore reuse the same core without pretending to be the
interactive desktop CLI.
"""

from __future__ import annotations

import os
from pathlib import Path

VERSION = "0.7.1"
SCHEMA_VERSION = 5
BACKUP_MAX_BYTES = 50 * 1024 * 1024
AUXILIARY_BACKUP_MAX_BYTES = 50 * 1024 * 1024


def data_dir() -> Path:
    override = os.environ.get("JPNOTE_DATA_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".local" / "share" / "jpnote"


def db_path() -> Path:
    return data_dir() / "jpnote.db"


def export_dir() -> Path:
    return data_dir() / "exports"


def backup_dir() -> Path:
    return data_dir() / "backups"


def restored_backup_dir() -> Path:
    return backup_dir() / "restored"
