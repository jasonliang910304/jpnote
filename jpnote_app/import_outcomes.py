"""Shared read-only outcome classification for import preflight and apply."""

from __future__ import annotations

import sqlite3
from typing import Any

from .attempt_identity import attempt_content_signature, attempt_identity_signature
from .repository import attempt_row_to_dict, classify_entry_upsert, get_attempt


def classify_entry_outcome(
    conn: sqlite3.Connection,
    item: dict[str, Any],
    default_source: str,
) -> str:
    """Return ``new``, ``update``, or ``unchanged`` exactly as apply would."""
    status = classify_entry_upsert(conn, item, default_source)
    return {"added": "new", "updated": "update", "unchanged": "unchanged"}[status]


def _attempt_with_links(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    links = [
        link["entry_key"]
        for link in conn.execute(
            "SELECT entry_key FROM attempt_entries WHERE attempt_id = ? ORDER BY entry_key",
            (row["id"],),
        ).fetchall()
    ]
    return attempt_row_to_dict(row, links)


def find_existing_attempt_match(
    conn: sqlite3.Connection,
    attempt: dict[str, Any],
) -> dict[str, Any] | None:
    """Find the existing record that import semantics treat as the same attempt."""
    exact = get_attempt(conn, attempt["event_key"])
    if exact is not None:
        return exact
    if not attempt.get("_event_key_generated"):
        return None
    incoming_identity = attempt_identity_signature(attempt)
    for row in conn.execute("SELECT * FROM attempts ORDER BY id").fetchall():
        existing = _attempt_with_links(conn, row)
        if attempt_identity_signature(existing) == incoming_identity:
            return existing
    return None


def classify_attempt_outcome(
    conn: sqlite3.Connection,
    attempt: dict[str, Any],
    *,
    available_keys: set[str] | None = None,
) -> dict[str, Any]:
    """Classify one attempt using the same rules used by the real importer.

    Same identity + same content is an idempotent duplicate. Same identity +
    different content is a conflict and must never be silently skipped or
    overwritten. Missing linked entries are reported separately.
    """
    if available_keys is None:
        available_keys = {
            row["key"] for row in conn.execute("SELECT key FROM entries").fetchall()
        }
    missing = [key for key in attempt.get("linked_entries", []) if key not in available_keys]
    existing = find_existing_attempt_match(conn, attempt)
    if missing:
        status = "invalid_links"
    elif existing is None:
        status = "new"
    elif attempt_content_signature(existing) == attempt_content_signature(attempt):
        status = "duplicate"
    else:
        status = "conflict"
    return {
        "status": status,
        "existing": existing,
        "missing_linked_entries": missing,
    }
