"""Shared read-only outcome classification for import preflight and apply."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any, Iterable

from .attempt_identity import attempt_content_signature, attempt_identity_signature
from .repository import (
    _merge_aliases,
    attempt_row_to_dict,
    classify_entry_upsert,
    get_attempt,
    list_attempts,
    row_to_summary,
)


@dataclass(frozen=True, slots=True)
class EntryOutcomeSnapshot:
    """Minimal existing-entry state needed to classify one import upsert."""

    row: dict[str, Any]
    data: dict[str, Any]
    sense_signatures: frozenset[tuple[str, str, str]]
    sources: frozenset[str]


def _chunks(values: list[str], size: int = 400) -> Iterable[list[str]]:
    for index in range(0, len(values), size):
        yield values[index:index + size]


def build_entry_outcome_index(
    conn: sqlite3.Connection,
    keys: Iterable[str],
) -> dict[str, EntryOutcomeSnapshot]:
    """Bulk-load the exact state used by import preflight classifiers."""

    wanted = list(dict.fromkeys(str(key) for key in keys if str(key)))
    if not wanted:
        return {}
    rows: dict[str, sqlite3.Row] = {}
    senses: dict[str, list[dict[str, str]]] = {key: [] for key in wanted}
    sources: dict[str, list[str]] = {key: [] for key in wanted}
    for chunk in _chunks(wanted):
        placeholders = ",".join("?" for _ in chunk)
        for row in conn.execute(
            f"SELECT * FROM entries WHERE key IN ({placeholders})",
            chunk,
        ).fetchall():
            rows[str(row["key"])] = row
        for row in conn.execute(
            f"SELECT entry_key, meaning, example_ja, example_zh FROM senses "
            f"WHERE entry_key IN ({placeholders}) ORDER BY id",
            chunk,
        ).fetchall():
            senses.setdefault(str(row["entry_key"]), []).append({
                "meaning": str(row["meaning"] or ""),
                "example_ja": str(row["example_ja"] or ""),
                "example_zh": str(row["example_zh"] or ""),
            })
        for row in conn.execute(
            f"SELECT entry_key, source FROM sources "
            f"WHERE entry_key IN ({placeholders}) ORDER BY added_at, id",
            chunk,
        ).fetchall():
            sources.setdefault(str(row["entry_key"]), []).append(str(row["source"] or ""))

    result: dict[str, EntryOutcomeSnapshot] = {}
    for key, row in rows.items():
        data = row_to_summary(row)
        data["senses"] = senses.get(key, [])
        data["sources"] = sources.get(key, [])
        signatures = frozenset(
            (sense["meaning"], sense["example_ja"], sense["example_zh"])
            for sense in data["senses"]
        )
        result[key] = EntryOutcomeSnapshot(
            row=dict(row),
            data=data,
            sense_signatures=signatures,
            sources=frozenset(data["sources"]),
        )
    return result


def classify_entry_outcome_snapshot(
    snapshot: EntryOutcomeSnapshot | None,
    item: dict[str, Any],
    default_source: str,
) -> str:
    """Classify one entry from a bulk snapshot with apply-equivalent rules."""

    if snapshot is None:
        return "new"
    existing = snapshot.row
    effective_display = str(item.get("display") or existing.get("display") or "")
    effective_reading = str(item.get("reading") or existing.get("reading") or "")
    aliases_json = _merge_aliases(
        str(existing.get("aliases_json") or "[]"),
        item["aliases"],
        key=item["key"],
        display=effective_display,
        reading=effective_reading,
        clean_existing=bool(item.get("_clean_existing_aliases")),
    )
    always_fields = ("key", "type")
    optional_fields = (
        "display", "reading", "romaji", "accent", "accent_type",
        "accent_display", "accent_note", "level", "review_group", "origin_type",
        "origin_language", "origin_word", "origin_note",
    )
    field_changed = False
    for field in always_fields:
        if str(item.get(field, existing.get(field, ""))) != str(existing.get(field) or ""):
            field_changed = True
            break
    if not field_changed:
        for field in optional_fields:
            incoming = str(item.get(field, "") or "")
            effective = incoming if incoming else str(existing.get(field) or "")
            if effective != str(existing.get(field) or ""):
                field_changed = True
                break

    aliases_changed = aliases_json != str(existing.get("aliases_json") or "[]")
    new_senses = any(
        (sense["meaning"], sense["example_ja"], sense["example_zh"])
        not in snapshot.sense_signatures
        for sense in item["senses"]
    )
    removable_blank_sense = any(
        (str(meaning), "", "") in snapshot.sense_signatures
        for meaning in item.get("_remove_existing_blank_sense_meanings", [])
    )
    source = str(item.get("source") or default_source or "")
    source_missing = bool(source and source not in snapshot.sources)
    return "update" if (
        field_changed
        or aliases_changed
        or new_senses
        or removable_blank_sense
        or source_missing
    ) else "unchanged"


@dataclass(slots=True)
class AttemptOutcomeIndex:
    """One immutable-ish read snapshot for repeated attempt classification.

    Import preflight and apply can classify many generated attempts in one
    batch.  Re-scanning every stored attempt for every incoming record made that
    path quadratic and also repeated link hydration.  The maps preserve the old
    first-row-by-id match semantics for historical identity collisions.
    """

    by_event_key: dict[str, dict[str, Any]] = field(default_factory=dict)
    by_identity: dict[str, dict[str, Any]] = field(default_factory=dict)

    def add(self, attempt: dict[str, Any]) -> None:
        event_key = str(attempt.get("event_key") or "")
        if event_key:
            self.by_event_key.setdefault(event_key, attempt)
        self.by_identity.setdefault(attempt_identity_signature(attempt), attempt)


def build_attempt_outcome_index(conn: sqlite3.Connection) -> AttemptOutcomeIndex:
    index = AttemptOutcomeIndex()
    for attempt in sorted(list_attempts(conn), key=lambda item: int(item.get("id") or 0)):
        index.add(attempt)
    return index


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
    *,
    index: AttemptOutcomeIndex | None = None,
) -> dict[str, Any] | None:
    """Find the existing record that import semantics treat as the same attempt."""
    exact = (
        index.by_event_key.get(attempt["event_key"])
        if index is not None else get_attempt(conn, attempt["event_key"])
    )
    if exact is not None:
        return exact
    if not attempt.get("_event_key_generated"):
        return None
    incoming_identity = attempt_identity_signature(attempt)
    if index is not None:
        return index.by_identity.get(incoming_identity)
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
    index: AttemptOutcomeIndex | None = None,
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
    existing = find_existing_attempt_match(conn, attempt, index=index)
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
