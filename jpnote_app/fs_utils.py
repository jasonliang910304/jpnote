"""Filesystem helpers for crash-resistant local state and exports.

jpnote owns a few private directories under the user's home directory, but it
also writes to arbitrary user-selected output paths.  The two cases must stay
separate: app-owned state can be tightened to 0700/0600, while an export helper
must never chmod an unrelated parent directory chosen by the user.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


PRIVATE_DIR_MODE = 0o700
PRIVATE_FILE_MODE = 0o600


def ensure_private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(PRIVATE_DIR_MODE)
    except OSError:
        # The caller may be operating on a filesystem that cannot represent
        # POSIX modes.  Directory creation is still useful in that case.
        pass
    return path


def ensure_directory(path: Path) -> Path:
    """Create a directory without changing permissions of an existing parent."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_private_file(path: Path) -> None:
    if not path.exists():
        return
    try:
        path.chmod(PRIVATE_FILE_MODE)
    except OSError:
        pass


def atomic_write_text(
    path: Path,
    text: str,
    *,
    encoding: str = "utf-8",
    private_parent: bool = False,
    private_file: bool = True,
) -> Path:
    """Write text to a sibling temp file, fsync it, then atomically replace path.

    ``private_parent`` is intentionally opt-in.  App-owned config/export
    directories pass True (or pre-create them with ``ensure_private_dir``), but
    arbitrary paths supplied through ``--output`` keep their existing parent
    permissions unchanged.
    """
    if private_parent:
        ensure_private_dir(path.parent)
    else:
        ensure_directory(path.parent)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        if private_file:
            try:
                os.fchmod(fd, PRIVATE_FILE_MODE)
            except OSError:
                pass
        with os.fdopen(fd, "w", encoding=encoding, newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        if private_file:
            ensure_private_file(path)
        # Persist the directory entry where supported.
        try:
            dir_fd = os.open(path.parent, os.O_RDONLY)
        except OSError:
            dir_fd = None
        if dir_fd is not None:
            try:
                os.fsync(dir_fd)
            except OSError:
                pass
            finally:
                os.close(dir_fd)
        return path
    finally:
        temp_path.unlink(missing_ok=True)
