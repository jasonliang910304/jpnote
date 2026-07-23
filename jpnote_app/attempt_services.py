"""Core use-cases for maintaining saved attempt records.

This module deliberately has no terminal or fzf dependency.  A future mimir
API can call the same functions used by the desktop CLI.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from .attempt_identity import attempt_content_signature
from .repository import delete_attempt, get_attempt, get_entry_row, replace_attempt
from .validation import validate_attempt, validate_attempt_edit_fields


def replace_attempt_data(
    conn: sqlite3.Connection,
    original_event_key: str,
    raw_attempt: dict[str, Any],
) -> dict[str, Any]:
    """Validate and fully replace one saved attempt.

    ``event_key`` remains immutable.  This keeps the record address stable for
    future Web clients even when the learner corrects the question text,
    result, reason, or linked entries.
    """
    editable = {
        key: value for key, value in raw_attempt.items()
        if key not in {"id", "created_at", "_data_warnings"}
    }
    validate_attempt_edit_fields(editable)
    normalized = validate_attempt(editable)
    normalized["event_key"] = original_event_key
    missing = [
        key for key in normalized["linked_entries"]
        if get_entry_row(conn, key) is None
    ]
    if missing:
        raise ValueError("作答紀錄連到不存在的項目：" + "、".join(missing))

    current = get_attempt(conn, original_event_key)
    if current is None:
        raise ValueError(f"找不到作答紀錄：{original_event_key}")
    if attempt_content_signature(current) == attempt_content_signature(normalized):
        return current

    with conn:
        replace_attempt(conn, original_event_key, normalized)
    updated = get_attempt(conn, original_event_key)
    if updated is None:
        raise RuntimeError("作答紀錄更新後無法讀回。")
    return updated


def delete_attempt_data(conn: sqlite3.Connection, event_key: str) -> bool:
    """Delete one attempt in a transaction."""
    with conn:
        return delete_attempt(conn, event_key)
