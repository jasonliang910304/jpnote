"""Audit and safely normalize vocabulary romaji from authoritative kana readings."""

from __future__ import annotations

import sqlite3
from typing import Any

from .repository import list_entries
from .romaji import spaced_hepburn
from .search_normalization import compact_text, romaji_variants


def romaji_is_equivalent(stored: str, canonical: str) -> bool:
    stored_compact = compact_text(stored)
    canonical_compact = compact_text(canonical)
    if not stored_compact or not canonical_compact:
        return False
    if stored_compact == canonical_compact:
        return True
    # Canonical reading-derived romaji is the authority.  Expanding the stored
    # value in the reverse direction can hide a dropped mora: for example
    # ``tē n`` expands to ``tein`` and would otherwise be accepted as
    # equivalent to the correct ``tē i n``.
    return stored_compact in romaji_variants(canonical)


def canonical_romaji_for_reading(reading: str) -> str:
    return spaced_hepburn(reading) if reading else ""


def normalize_import_romaji(reading: str, romaji: str) -> str:
    """Normalize permissive input only when reading proves it is equivalent.

    A mismatching supplied romaji is preserved for audit rather than silently
    overwritten, because a bad reading field and a bad romaji field cannot be
    distinguished with certainty at the import boundary.
    """
    canonical = canonical_romaji_for_reading(reading)
    if not canonical:
        return romaji
    if not romaji or romaji_is_equivalent(romaji, canonical):
        return canonical
    return romaji


def romaji_audit_records(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    # Reading/romaji audit only needs columns already present in the entry
    # summary.  Hydrating senses/sources/relations per vocabulary used to turn
    # this read-only command into an N+1 query path as the dataset grew.
    for entry in list_entries(conn, "vocabulary"):
        reading = str(entry.get("reading") or "")
        stored = str(entry.get("romaji") or "")
        canonical = canonical_romaji_for_reading(reading)
        if not reading:
            status = "missing_reading"
            safe = False
        elif not canonical:
            status = "unsupported_reading"
            safe = False
        elif not stored:
            status = "missing_romaji"
            safe = True
        elif stored == canonical:
            status = "ok"
            safe = False
        elif romaji_is_equivalent(stored, canonical):
            status = "format_only"
            safe = True
        else:
            status = "mismatch"
            safe = False
        records.append({
            "key": entry.get("key", ""),
            "display": entry.get("display", ""),
            "reading": reading,
            "stored_romaji": stored,
            "canonical_romaji": canonical,
            "status": status,
            "safe_to_apply": safe,
        })
    return records


def safe_romaji_candidates(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [record for record in romaji_audit_records(conn) if record["safe_to_apply"]]


def apply_safe_romaji_normalization(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    candidates = safe_romaji_candidates(conn)
    applied: list[dict[str, Any]] = []
    with conn:
        for record in candidates:
            conn.execute(
                "UPDATE entries SET romaji = ? WHERE key = ?",
                (record["canonical_romaji"], record["key"]),
            )
            applied.append(record)
    return applied
