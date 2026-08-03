"""Process-wide writer serialization for core jpnote state.

The lock file is persistent by design.  Kernel advisory locks are released
when the process exits, including abnormal termination, while keeping the inode
stable avoids unlink/recreate races between competing writers.
"""

from __future__ import annotations

import errno
import os
import stat
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .config import data_dir
from .fs_utils import ensure_private_dir

try:
    import fcntl
except ImportError as exc:  # pragma: no cover - jpnote currently targets POSIX/Linux
    raise RuntimeError("jpnote 的多程序寫入鎖目前需要 POSIX fcntl 支援。") from exc


DEFAULT_WRITER_LOCK_TIMEOUT_SECONDS = 30.0
_LOCK_FILENAME = ".writer.lock"


class WriterLockTimeout(RuntimeError):
    """Raised when another core writer does not release the lock in time."""


@dataclass(slots=True)
class _HeldLock:
    fd: int
    depth: int


_state = threading.local()
_mutex_guard = threading.Lock()
_path_mutexes: dict[str, threading.RLock] = {}


def writer_lock_path() -> Path:
    return data_dir() / _LOCK_FILENAME


def _mutex_for(key: str) -> threading.RLock:
    with _mutex_guard:
        return _path_mutexes.setdefault(key, threading.RLock())


def _held_locks() -> dict[str, _HeldLock]:
    held = getattr(_state, "held_locks", None)
    if held is None:
        held = {}
        _state.held_locks = held
    return held


def _holder_text(fd: int) -> str:
    try:
        raw = os.pread(fd, 4096, 0)
    except OSError:
        return ""
    return raw.decode("utf-8", errors="replace").strip()


@contextmanager
def writer_lock(
    label: str,
    *,
    timeout: float = DEFAULT_WRITER_LOCK_TIMEOUT_SECONDS,
    poll_interval: float = 0.05,
) -> Iterator[Path]:
    """Serialize one complete core write/backup/export boundary.

    The lock is re-entrant within one thread and also guarded by a per-path
    ``RLock`` so threads in the same process cannot bypass the advisory lock.
    The file is never removed; deleting a lock file can let late contenders
    lock different inodes and enter the critical section together.
    """
    if timeout < 0:
        raise ValueError("writer lock timeout 不可小於 0。")
    if poll_interval <= 0:
        raise ValueError("writer lock poll interval 必須大於 0。")

    path = writer_lock_path()
    ensure_private_dir(path.parent)
    key = str(path.absolute())
    mutex = _mutex_for(key)

    with mutex:
        held = _held_locks()
        current = held.get(key)
        if current is not None:
            current.depth += 1
            try:
                yield path
            finally:
                current.depth -= 1
            return

        flags = os.O_CREAT | os.O_RDWR
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        if hasattr(os, "O_NONBLOCK"):
            flags |= os.O_NONBLOCK
        try:
            fd = os.open(path, flags, 0o600)
        except OSError as exc:
            if exc.errno in {errno.ELOOP, errno.EMLINK}:
                raise RuntimeError(f"jpnote 寫入鎖不可是符號連結：{path}") from exc
            raise
        lock_stat = os.fstat(fd)
        if not stat.S_ISREG(lock_stat.st_mode):
            os.close(fd)
            raise RuntimeError(f"jpnote 寫入鎖必須是一般檔案：{path}")
        if lock_stat.st_nlink != 1:
            os.close(fd)
            raise RuntimeError(f"jpnote 寫入鎖不可是 hard link：{path}")
        if hasattr(os, "geteuid") and lock_stat.st_uid != os.geteuid():
            os.close(fd)
            raise RuntimeError(f"jpnote 寫入鎖必須由目前使用者擁有：{path}")
        try:
            os.fchmod(fd, 0o600)
        except OSError:
            pass
        deadline = time.monotonic() + timeout
        try:
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    try:
                        current_path_stat = os.stat(path, follow_symlinks=False)
                    except FileNotFoundError as exc:
                        raise RuntimeError(
                            f"jpnote 寫入鎖路徑在取得鎖時消失：{path}"
                        ) from exc
                    if (
                        current_path_stat.st_dev != lock_stat.st_dev
                        or current_path_stat.st_ino != lock_stat.st_ino
                    ):
                        raise RuntimeError(
                            f"jpnote 寫入鎖路徑在取得鎖時被替換：{path}"
                        )
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        holder = _holder_text(fd)
                        detail = f"（目前持有者：{holder}）" if holder else ""
                        raise WriterLockTimeout(
                            f"等待 jpnote 寫入鎖超過 {timeout:g} 秒：{path}{detail}"
                        )
                    time.sleep(poll_interval)

            owner = (
                f"pid={os.getpid()} label={label} "
                f"started={time.time():.6f}\n"
            ).encode("utf-8")
            os.ftruncate(fd, 0)
            os.pwrite(fd, owner, 0)
            try:
                os.fsync(fd)
            except OSError:
                pass

            held[key] = _HeldLock(fd=fd, depth=1)
            try:
                yield path
            finally:
                held.pop(key, None)
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
