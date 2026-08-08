"""Safe source-file handling for import-first workflows."""

from __future__ import annotations

import errno
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from .import_transport import MAX_IMPORT_BYTES


@dataclass(frozen=True, slots=True)
class SourceIdentity:
    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int

    @classmethod
    def from_stat(cls, value: os.stat_result) -> "SourceIdentity":
        return cls(
            device=value.st_dev,
            inode=value.st_ino,
            size=value.st_size,
            mtime_ns=value.st_mtime_ns,
            ctime_ns=value.st_ctime_ns,
        )


@dataclass(frozen=True, slots=True)
class ImportSource:
    path: Path
    text: str
    identity: SourceIdentity

    @classmethod
    def read(cls, value: str | os.PathLike[str]) -> "ImportSource":
        requested = Path(value).expanduser()
        # Resolve only the parent.  The final component must remain visible so
        # O_NOFOLLOW/lstat can reject a symlink instead of silently following it.
        try:
            parent = requested.parent.resolve(strict=True)
        except FileNotFoundError as exc:
            raise ValueError(f"匯入來源檔的父目錄不存在：{requested.parent}") from exc
        path = parent / requested.name

        flags = os.O_RDONLY
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(path, flags)
        except OSError as exc:
            if exc.errno in {errno.ELOOP, errno.EMLINK}:
                raise ValueError(f"匯入來源不可是符號連結：{path}") from exc
            raise

        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode):
                raise ValueError(f"匯入來源必須是一般檔案：{path}")
            if before.st_size > MAX_IMPORT_BYTES:
                raise ValueError(
                    f"匯入來源超過大小上限 {MAX_IMPORT_BYTES} bytes：{path}"
                )
            with os.fdopen(fd, "r", encoding="utf-8-sig", closefd=False) as handle:
                text = handle.read()
                after = os.fstat(handle.fileno())
            before_identity = SourceIdentity.from_stat(before)
            after_identity = SourceIdentity.from_stat(after)
            if before_identity != after_identity:
                raise RuntimeError(f"匯入來源在讀取期間被修改，請重新執行：{path}")
            return cls(path=path, text=text, identity=after_identity)
        finally:
            os.close(fd)

    def delete_if_unchanged(self) -> None:
        """Delete only when the path still names the exact file that was read.

        The parent directory is opened once and all operations use ``dir_fd``;
        this avoids path re-resolution and rejects symlink replacement.  A
        same-user attacker could still race the final stat/unlink pair because
        POSIX has no conditional unlink-by-inode primitive, but ordinary stale
        path, symlink, replacement, and in-place modification cases fail closed.
        """
        flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            flags |= os.O_DIRECTORY
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        parent_fd = os.open(self.path.parent, flags)
        try:
            try:
                current = os.stat(
                    self.path.name,
                    dir_fd=parent_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError as exc:
                raise RuntimeError(f"來源檔已不存在，未執行刪除：{self.path}") from exc
            if not stat.S_ISREG(current.st_mode):
                raise RuntimeError(f"來源路徑已不再是一般檔案，拒絕刪除：{self.path}")
            if SourceIdentity.from_stat(current) != self.identity:
                raise RuntimeError(f"來源檔在匯入後已被修改或替換，拒絕刪除：{self.path}")
            os.unlink(self.path.name, dir_fd=parent_fd)
            try:
                os.fsync(parent_fd)
            except OSError:
                pass
        finally:
            os.close(parent_fd)
