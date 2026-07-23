"""Structured browsing and filtering shared by CLI, fzf, and future Web UI."""

from __future__ import annotations

import sqlite3
from typing import Any, Iterable, Sequence

from .repository import get_entry, list_attempts, list_entries_full
from .search_normalization import attempt_search_metadata, compact_text, entry_match_score, entry_search_metadata

DEFAULT_TYPES = ("grammar", "vocab")
ALL_TYPES = DEFAULT_TYPES + ("mistake",)
DEFAULT_RESULTS = ("wrong", "partial")
TYPE_LABELS = {"grammar": "文法", "vocab": "單字", "mistake": "錯題"}
LEVEL_VALUES = ("N5", "N4", "N3", "N2", "N1", "unclassified")
RESULT_VALUES = ("wrong", "partial")


def normalize_level_filter(value: str) -> str:
    text = str(value or "").strip()
    if text.casefold() in {"unclassified", "none", "unknown"} or text == "未分類":
        return ""
    return text.upper()


def _entry_kind(entry_type: str) -> str:
    return "grammar" if entry_type == "grammar" else "vocab"


def _attempt_matches_query(
    attempt: dict[str, Any], linked_entries: list[dict[str, Any]], query: str | None
) -> bool:
    if not query:
        return True
    needle = compact_text(query)
    if not needle:
        return True
    return needle in compact_text(attempt_search_metadata(attempt, linked_entries))


def browse_records(
    conn: sqlite3.Connection,
    *,
    types: Sequence[str] | None = None,
    levels: Sequence[str] | None = None,
    results: Sequence[str] | None = None,
    query: str | None = None,
) -> list[dict[str, Any]]:
    """Return heterogeneous browse records without depending on fzf.

    ``types=None`` means the configured/default entry view of grammar and
    vocabulary.  An explicit empty sequence means no type restriction, i.e.
    grammar, vocabulary, and mistakes are all eligible.  This matches the
    checkbox UI convention that an empty filter group means "all".

    Entry hydration is deliberately batched.  The same enriched entry objects
    feed both core search scoring and interactive fzf metadata, preventing the
    two search paths from drifting while avoiding per-entry N+1 queries.
    """
    explicit_types = None if types is None else set(types)
    selected_types = (
        set(DEFAULT_TYPES)
        if explicit_types is None
        else (set(ALL_TYPES) if not explicit_types else explicit_types)
    )
    selected_levels = {
        normalize_level_filter(value) for value in (levels or [])
    }
    result_filter_enabled = bool(explicit_types and "mistake" in explicit_types)
    selected_results = set(results) if result_filter_enabled and results else set(DEFAULT_RESULTS)

    # Load entries once.  Mistake records reuse this map for linked-entry
    # levels/search metadata instead of querying each linked key separately.
    full_entries = list_entries_full(conn)
    entry_map = {entry["key"]: entry for entry in full_entries}

    records: list[dict[str, Any]] = []
    if selected_types & {"grammar", "vocab"}:
        for full in full_entries:
            kind = _entry_kind(full["type"])
            if kind not in selected_types:
                continue
            if selected_levels and normalize_level_filter(full.get("level", "")) not in selected_levels:
                continue
            if query and entry_match_score(full, query) is None:
                continue
            records.append({
                "record_type": "entry",
                "kind": kind,
                "token": f"entry:{full['key']}",
                "key": full["key"],
                "level": full.get("level", ""),
                "search_metadata": entry_search_metadata(full),
                "data": full,
            })

    if "mistake" in selected_types:
        attempts = list_attempts(conn, selected_results)
        for attempt in attempts:
            linked_entries = [
                entry_map[key]
                for key in attempt.get("linked_entries", [])
                if key in entry_map
            ]
            linked_levels: list[str] = []
            for entry in linked_entries:
                level = normalize_level_filter(entry.get("level", ""))
                if level not in linked_levels:
                    linked_levels.append(level)
            effective_levels = linked_levels or [""]
            if selected_levels and not selected_levels.intersection(effective_levels):
                continue
            if not _attempt_matches_query(attempt, linked_entries, query):
                continue
            records.append({
                "record_type": "attempt",
                "kind": "mistake",
                "token": f"attempt:{attempt['event_key']}",
                "event_key": attempt["event_key"],
                "levels": linked_levels,
                "linked_entries_data": linked_entries,
                "search_metadata": attempt_search_metadata(attempt, linked_entries),
                "data": attempt,
            })
    return records


def browse_json(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a compact JSON-safe public representation of browse records."""
    result: list[dict[str, Any]] = []
    for record in records:
        item = {
            "kind": record["kind"],
            "token": record["token"],
            "data": record["data"],
        }
        if record.get("levels") is not None:
            item["levels"] = record.get("levels", [])
        result.append(item)
    return result
