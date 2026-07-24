"""Shared crash-safe mutation execution for CLI, API, and future extensions."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Generic, TypeVar

from .db import connect, mutation_backup
from .export_markdown import export_all

T = TypeVar("T")


@dataclass(slots=True)
class SafeMutationResult(Generic[T]):
    value: T
    modified: bool
    backup: Path | None
    exports: list[Path]


def execute_safe_mutation(
    label: str,
    operation: Callable[[sqlite3.Connection], T],
    *,
    refresh_exports: bool = True,
) -> SafeMutationResult[T]:
    """Run one database mutation through the shared safety boundary.

    The pre-mutation snapshot is published only after a real SQLite change.
    ``operation`` runs inside one outer transaction; nested service-level
    ``with conn`` blocks become savepoints through ``ManagedConnection``.
    If export fails after commit, the backup context still publishes the undo
    snapshot before re-raising the error.
    """
    exports: list[Path] = []
    with mutation_backup(label) as backup_handle:
        conn = connect()
        # Keep the connection alive after the transaction commits so exports
        # are generated from committed state, then close explicitly.
        conn._jpnote_auto_close = False
        try:
            before_changes = conn.total_changes
            with conn:
                value = operation(conn)
            modified = conn.total_changes > before_changes
            backup_handle.mark_changed(modified)
            if modified and refresh_exports:
                exports = export_all(conn)
        finally:
            conn.close()
    backup = backup_handle.path if backup_handle else None
    return SafeMutationResult(
        value=value,
        modified=modified,
        backup=backup,
        exports=exports,
    )
