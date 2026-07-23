"""Database repository functions with no UI dependencies."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from typing import Any, Iterable

from .db import now_text
from .sorting import entry_sort_key
from .search_normalization import entry_match_score
from .attempt_identity import attempt_identity_signature
from .data_quality import clean_aliases

ENTRY_COLUMNS = (
    "key", "type", "display", "reading", "romaji", "accent", "accent_type",
    "accent_display", "accent_note", "level", "review_group", "aliases_json",
    "origin_type", "origin_language", "origin_word", "origin_note", "created_at",
    "updated_at",
)


def _loads_list(value: str) -> list[Any]:
    try:
        result = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return result if isinstance(result, list) else []


def row_to_summary(row: sqlite3.Row) -> dict[str, Any]:
    data = {column: row[column] for column in ENTRY_COLUMNS if column in row.keys()}
    data["aliases"] = _loads_list(data.pop("aliases_json", "[]"))
    return data


def get_entry_row(conn: sqlite3.Connection, key: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM entries WHERE key = ?", (key,)).fetchone()


def list_entry_rows(
    conn: sqlite3.Connection,
    entry_type: str | None = None,
    level: str | None = None,
) -> list[sqlite3.Row]:
    clauses: list[str] = []
    params: list[str] = []
    if entry_type:
        clauses.append("type = ?")
        params.append(entry_type)
    if level is not None:
        clauses.append("level = ?")
        params.append(level)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    rows = conn.execute(f"SELECT * FROM entries{where}", params).fetchall()
    return sorted(rows, key=lambda row: entry_sort_key(row_to_summary(row)))


def _summary_from_full_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Return the stable public summary shape from a fully enriched entry."""
    return {
        field: entry.get(field, "")
        for field in ENTRY_COLUMNS
        if field != "aliases_json"
    } | {"aliases": list(entry.get("aliases", []))}


def _ranked_full_entries(conn: sqlite3.Connection, query: str) -> list[dict[str, Any]]:
    """Search using the same enriched searchable document used by browse/fzf.

    Keeping the search document in Python avoids false positives from matching
    raw JSON serialization (for example ``aliases_json='[]'`` matching ``[``)
    and guarantees that CLI search and interactive browse see the same fields.
    """
    ranked: list[tuple[int, tuple[Any, ...], dict[str, Any]]] = []
    for entry in list_entries_full(conn):
        score = entry_match_score(entry, query)
        if score is not None:
            ranked.append((score, entry_sort_key(entry), entry))
    ranked.sort(key=lambda value: (value[0], value[1]))
    return [entry for _, _, entry in ranked]


def search_entry_rows(conn: sqlite3.Connection, query: str) -> list[sqlite3.Row]:
    """Compatibility row API backed by the shared enriched search document."""
    ranked_keys = [entry["key"] for entry in _ranked_full_entries(conn, query)]
    if not ranked_keys:
        return []
    row_map = {row["key"]: row for row in list_entry_rows(conn)}
    return [row_map[key] for key in ranked_keys if key in row_map]


def find_exact_entry(conn: sqlite3.Connection, query: str) -> sqlite3.Row | None:
    """Resolve an exact lookup only when it is unambiguous.

    Stable-key equality is always safe.  Human-facing display/readings may be
    shared by multiple entries, so those are auto-resolved only when exactly
    one row matches.  Ambiguous queries fall back to normal search/fzf in the
    CLI instead of silently selecting an arbitrary row.
    """
    key_row = conn.execute("SELECT * FROM entries WHERE key = ?", (query,)).fetchone()
    if key_row is not None:
        return key_row
    rows = conn.execute(
        "SELECT * FROM entries WHERE display = ? OR reading = ? ORDER BY key",
        (query, query),
    ).fetchall()
    return rows[0] if len(rows) == 1 else None


def entry_senses(conn: sqlite3.Connection, key: str) -> list[dict[str, str]]:
    return [
        dict(row)
        for row in conn.execute(
            "SELECT meaning, example_ja, example_zh FROM senses WHERE entry_key = ? ORDER BY id",
            (key,),
        ).fetchall()
    ]


def entry_sources(conn: sqlite3.Connection, key: str) -> list[str]:
    return [
        row["source"]
        for row in conn.execute(
            "SELECT source FROM sources WHERE entry_key = ? ORDER BY added_at, id", (key,)
        ).fetchall()
    ]


def entry_relations(conn: sqlite3.Connection, key: str) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in conn.execute(
            """
            SELECT gr.target_key AS key, e.display, gr.relation_type AS relation,
                   gr.note, gr.source
            FROM grammar_relations AS gr
            JOIN entries AS e ON e.key = gr.target_key
            WHERE gr.source_key = ?
            ORDER BY gr.relation_type, e.display
            """,
            (key,),
        ).fetchall()
    ]


def pending_relations(conn: sqlite3.Connection, key: str | None = None) -> list[dict[str, Any]]:
    if key:
        rows = conn.execute(
            "SELECT * FROM pending_grammar_relations WHERE source_key = ? ORDER BY id", (key,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM pending_grammar_relations ORDER BY id").fetchall()
    return [dict(row) for row in rows]


def entry_attempt_stats(conn: sqlite3.Connection, key: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT COUNT(*) AS attempt_count,
               SUM(CASE WHEN a.result = 'correct' THEN 1 ELSE 0 END) AS correct_count,
               SUM(CASE WHEN a.result = 'wrong' THEN 1 ELSE 0 END) AS mistake_count,
               SUM(CASE WHEN a.result = 'partial' THEN 1 ELSE 0 END) AS partial_count,
               MAX(COALESCE(NULLIF(a.attempt_date, ''), a.created_at)) AS last_answered_at
        FROM attempts AS a
        JOIN attempt_entries AS ae ON ae.attempt_id = a.id
        WHERE ae.entry_key = ?
        """,
        (key,),
    ).fetchone()
    attempt_count = int(row["attempt_count"] or 0)
    correct_count = int(row["correct_count"] or 0)
    mistake_count = int(row["mistake_count"] or 0)
    partial_count = int(row["partial_count"] or 0)
    gradable = correct_count + mistake_count + partial_count
    # Keep a strict rate for transparent raw reporting, and a weighted rate where
    # "partial" earns half credit. This avoids treating a low-confidence correct
    # answer exactly the same as a fully wrong answer.
    strict_accuracy = (correct_count / gradable * 100.0) if gradable else None
    weighted_accuracy = (
        (correct_count + 0.5 * partial_count) / gradable * 100.0
        if gradable else None
    )
    return {
        "attempt_count": attempt_count,
        "correct_count": correct_count,
        "mistake_count": mistake_count,
        "partial_count": partial_count,
        "accuracy": strict_accuracy,
        "strict_accuracy": strict_accuracy,
        "weighted_accuracy": weighted_accuracy,
        "last_answered_at": row["last_answered_at"] or "",
    }


def entry_attempts(conn: sqlite3.Connection, key: str, limit: int = 20) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT a.* FROM attempts AS a
        JOIN attempt_entries AS ae ON ae.attempt_id = a.id
        WHERE ae.entry_key = ?
        ORDER BY COALESCE(NULLIF(a.attempt_date, ''), a.created_at) DESC, a.id DESC
        LIMIT ?
        """,
        (key, limit),
    ).fetchall()
    return [attempt_row_to_dict(row, linked_entries=[key]) for row in rows]


def get_entry(conn: sqlite3.Connection, key: str, include_attempts: bool = True) -> dict[str, Any] | None:
    row = get_entry_row(conn, key)
    if row is None:
        return None
    result = row_to_summary(row)
    result["senses"] = entry_senses(conn, key)
    result["sources"] = entry_sources(conn, key)
    result["related_grammar"] = entry_relations(conn, key) if row["type"] == "grammar" else []
    result["pending_related_grammar"] = pending_relations(conn, key) if row["type"] == "grammar" else []
    result["attempt_stats"] = entry_attempt_stats(conn, key)
    if include_attempts:
        result["attempts"] = entry_attempts(conn, key)
    return result


def _chunks(values: list[Any], size: int = 500) -> Iterable[list[Any]]:
    for index in range(0, len(values), size):
        yield values[index:index + size]


def _empty_attempt_stats() -> dict[str, Any]:
    return {
        "attempt_count": 0,
        "correct_count": 0,
        "mistake_count": 0,
        "partial_count": 0,
        "accuracy": None,
        "strict_accuracy": None,
        "weighted_accuracy": None,
        "last_answered_at": "",
    }


def _stats_from_aggregate(row: sqlite3.Row) -> dict[str, Any]:
    attempt_count = int(row["attempt_count"] or 0)
    correct_count = int(row["correct_count"] or 0)
    mistake_count = int(row["mistake_count"] or 0)
    partial_count = int(row["partial_count"] or 0)
    gradable = correct_count + mistake_count + partial_count
    strict_accuracy = (correct_count / gradable * 100.0) if gradable else None
    weighted_accuracy = (
        (correct_count + 0.5 * partial_count) / gradable * 100.0
        if gradable else None
    )
    return {
        "attempt_count": attempt_count,
        "correct_count": correct_count,
        "mistake_count": mistake_count,
        "partial_count": partial_count,
        "accuracy": strict_accuracy,
        "strict_accuracy": strict_accuracy,
        "weighted_accuracy": weighted_accuracy,
        "last_answered_at": row["last_answered_at"] or "",
    }


def _enrich_entry_rows(
    conn: sqlite3.Connection,
    rows: list[sqlite3.Row],
) -> list[dict[str, Any]]:
    """Hydrate entry details in batches instead of issuing queries per entry."""
    if not rows:
        return []
    entries = {row["key"]: row_to_summary(row) for row in rows}
    for entry in entries.values():
        entry["senses"] = []
        entry["sources"] = []
        entry["related_grammar"] = []
        entry["pending_related_grammar"] = []
        entry["attempt_stats"] = _empty_attempt_stats()

    keys = list(entries)
    for chunk in _chunks(keys):
        placeholders = ",".join("?" for _ in chunk)
        for row in conn.execute(
            f"SELECT entry_key, meaning, example_ja, example_zh FROM senses "
            f"WHERE entry_key IN ({placeholders}) ORDER BY id",
            chunk,
        ).fetchall():
            entries[row["entry_key"]]["senses"].append({
                "meaning": row["meaning"],
                "example_ja": row["example_ja"],
                "example_zh": row["example_zh"],
            })
        for row in conn.execute(
            f"SELECT entry_key, source, added_at FROM sources "
            f"WHERE entry_key IN ({placeholders}) ORDER BY added_at, id",
            chunk,
        ).fetchall():
            entries[row["entry_key"]]["sources"].append(row["source"])
        for row in conn.execute(
            f"""
            SELECT gr.source_key, gr.target_key AS key, e.display,
                   gr.relation_type AS relation, gr.note, gr.source
            FROM grammar_relations AS gr
            JOIN entries AS e ON e.key = gr.target_key
            WHERE gr.source_key IN ({placeholders})
            ORDER BY gr.relation_type, e.display
            """,
            chunk,
        ).fetchall():
            entries[row["source_key"]]["related_grammar"].append({
                "key": row["key"], "display": row["display"],
                "relation": row["relation"], "note": row["note"],
                "source": row["source"],
            })
        for row in conn.execute(
            f"SELECT * FROM pending_grammar_relations "
            f"WHERE source_key IN ({placeholders}) ORDER BY id",
            chunk,
        ).fetchall():
            entries[row["source_key"]]["pending_related_grammar"].append(dict(row))
        for row in conn.execute(
            f"""
            SELECT ae.entry_key,
                   COUNT(*) AS attempt_count,
                   SUM(CASE WHEN a.result = 'correct' THEN 1 ELSE 0 END) AS correct_count,
                   SUM(CASE WHEN a.result = 'wrong' THEN 1 ELSE 0 END) AS mistake_count,
                   SUM(CASE WHEN a.result = 'partial' THEN 1 ELSE 0 END) AS partial_count,
                   MAX(COALESCE(NULLIF(a.attempt_date, ''), a.created_at)) AS last_answered_at
            FROM attempt_entries AS ae
            JOIN attempts AS a ON a.id = ae.attempt_id
            WHERE ae.entry_key IN ({placeholders})
            GROUP BY ae.entry_key
            """,
            chunk,
        ).fetchall():
            entries[row["entry_key"]]["attempt_stats"] = _stats_from_aggregate(row)
    return [entries[row["key"]] for row in rows]


def list_entries_full(
    conn: sqlite3.Connection,
    entry_type: str | None = None,
    level: str | None = None,
) -> list[dict[str, Any]]:
    return _enrich_entry_rows(conn, list_entry_rows(conn, entry_type, level))


def get_entries_by_keys(
    conn: sqlite3.Connection,
    keys: Iterable[str],
) -> dict[str, dict[str, Any]]:
    wanted = list(dict.fromkeys(str(key) for key in keys if str(key)))
    if not wanted:
        return {}
    rows: list[sqlite3.Row] = []
    for chunk in _chunks(wanted):
        placeholders = ",".join("?" for _ in chunk)
        rows.extend(conn.execute(
            f"SELECT * FROM entries WHERE key IN ({placeholders})",
            chunk,
        ).fetchall())
    full = _enrich_entry_rows(conn, rows)
    return {entry["key"]: entry for entry in full}


def list_entries(
    conn: sqlite3.Connection,
    entry_type: str | None = None,
    level: str | None = None,
) -> list[dict[str, Any]]:
    return [row_to_summary(row) for row in list_entry_rows(conn, entry_type, level)]


def search_entries(conn: sqlite3.Connection, query: str) -> list[dict[str, Any]]:
    return [_summary_from_full_entry(entry) for entry in _ranked_full_entries(conn, query)]


def _local_datetime(value: str) -> datetime | None:
    """Parse jpnote ISO timestamps and express them in the current local zone."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return parsed.astimezone()


def list_recent_entries(
    conn: sqlite3.Connection,
    target_date: str | None = None,
    since_date: str | None = None,
    entry_type: str | None = None,
    source_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Return entries changed in a local-calendar date range.

    Timestamps are parsed in Python rather than with SQLite ``date()`` because
    jpnote stores ISO-8601 offsets.  Sources are loaded in one batch so recent
    views do not issue one extra query per entry.  ``source_filter`` matches an
    exact stored source label associated with the entry.
    """
    if target_date and since_date:
        raise ValueError("--date 與 --since 不能同時使用。")
    wanted_day = date.fromisoformat(target_date) if target_date else None
    since_day = date.fromisoformat(since_date) if since_date else None
    if wanted_day is None and since_day is None:
        wanted_day = datetime.now().astimezone().date()

    rows = list_entry_rows(conn, entry_type)
    source_map: dict[str, list[sqlite3.Row]] = {}
    for source_row in conn.execute(
        "SELECT entry_key, source, added_at FROM sources ORDER BY added_at, id"
    ).fetchall():
        source_map.setdefault(source_row["entry_key"], []).append(source_row)

    result: list[dict[str, Any]] = []
    for row in rows:
        source_rows = source_map.get(row["key"], [])
        if source_filter and not any(source["source"] == source_filter for source in source_rows):
            continue
        updated_local = _local_datetime(row["updated_at"])
        created_local = _local_datetime(row["created_at"])
        if updated_local is None:
            continue
        if wanted_day is not None and updated_local.date() != wanted_day:
            continue
        if since_day is not None and updated_local.date() < since_day:
            continue

        item = row_to_summary(row)
        item["action"] = "added" if row["created_at"] == row["updated_at"] else "updated"
        item["created_at_local"] = created_local.isoformat(timespec="seconds") if created_local else row["created_at"]
        item["updated_at_local"] = updated_local.isoformat(timespec="seconds")
        item["sources"] = [source["source"] for source in source_rows]
        item["recent_sources"] = []
        for source in source_rows:
            added_local = _local_datetime(source["added_at"])
            if added_local is None:
                continue
            if wanted_day is not None and added_local.date() == wanted_day:
                item["recent_sources"].append(source["source"])
            elif since_day is not None and added_local.date() >= since_day:
                item["recent_sources"].append(source["source"])
        result.append(item)

    return sorted(
        result,
        key=lambda item: item.get("updated_at_local", ""),
        reverse=True,
    )


def _merge_aliases(
    existing_json: str,
    incoming: list[str],
    *,
    key: str = "",
    display: str = "",
    reading: str = "",
    clean_existing: bool = False,
) -> str:
    merged = list(dict.fromkeys([*_loads_list(existing_json), *incoming]))
    if clean_existing:
        merged = clean_aliases(key, display, reading, merged)
    return json.dumps(merged, ensure_ascii=False)


def classify_entry_upsert(conn: sqlite3.Connection, item: dict[str, Any], default_source: str) -> str:
    """Return the exact added/updated/unchanged outcome without mutating data."""
    existing = get_entry_row(conn, item["key"])
    if existing is None:
        return "added"

    effective_display_for_aliases = str(item.get("display") or existing["display"] or "")
    effective_reading_for_aliases = str(item.get("reading") or existing["reading"] or "")
    aliases_json = _merge_aliases(
        existing["aliases_json"] or "[]",
        item["aliases"],
        key=item["key"],
        display=effective_display_for_aliases,
        reading=effective_reading_for_aliases,
        clean_existing=bool(item.get("_clean_existing_aliases")),
    )
    source = item.get("source") or default_source
    always_fields = ("key", "type")
    optional_fields = (
        "display", "reading", "romaji", "accent", "accent_type",
        "accent_display", "accent_note", "level", "review_group", "origin_type",
        "origin_language", "origin_word", "origin_note",
    )
    effective: dict[str, str] = {}
    for field in always_fields:
        effective[field] = str(item.get(field, existing[field]))
    for field in optional_fields:
        incoming = str(item.get(field, "") or "")
        effective[field] = incoming if incoming else str(existing[field] or "")

    field_changed = any(
        effective[field] != str(existing[field] or "")
        for field in (*always_fields, *optional_fields)
    )
    aliases_changed = aliases_json != (existing["aliases_json"] or "[]")
    existing_senses = {
        (row["meaning"], row["example_ja"], row["example_zh"])
        for row in conn.execute(
            "SELECT meaning, example_ja, example_zh FROM senses WHERE entry_key = ?",
            (item["key"],),
        ).fetchall()
    }
    new_senses = any(
        (sense["meaning"], sense["example_ja"], sense["example_zh"]) not in existing_senses
        for sense in item["senses"]
    )
    removable_blank_sense = False
    for meaning in item.get("_remove_existing_blank_sense_meanings", []):
        if conn.execute(
            "SELECT 1 FROM senses WHERE entry_key=? AND meaning=? AND example_ja='' AND example_zh=''",
            (item["key"], meaning),
        ).fetchone() is not None:
            removable_blank_sense = True
            break
    source_exists = True
    if source:
        source_exists = conn.execute(
            "SELECT 1 FROM sources WHERE entry_key = ? AND source = ?",
            (item["key"], source),
        ).fetchone() is not None
    return "updated" if (field_changed or aliases_changed or new_senses or removable_blank_sense or (source and not source_exists)) else "unchanged"


def upsert_entry(conn: sqlite3.Connection, item: dict[str, Any], default_source: str) -> str:
    """Insert/update an entry and report added/updated/unchanged.

    Re-importing semantically identical data is a true no-op: it must not bump
    ``updated_at`` or make ``jpnote recent`` look like content changed.
    """
    status = classify_entry_upsert(conn, item, default_source)
    if status == "unchanged":
        return status

    existing = get_entry_row(conn, item["key"])
    timestamp = now_text()
    effective_display_for_aliases = str(item.get("display") or (existing["display"] if existing else "") or "")
    effective_reading_for_aliases = str(item.get("reading") or (existing["reading"] if existing else "") or "")
    aliases_json = _merge_aliases(
        existing["aliases_json"] if existing else "[]",
        item["aliases"],
        key=item["key"],
        display=effective_display_for_aliases,
        reading=effective_reading_for_aliases,
        clean_existing=bool(item.get("_clean_existing_aliases")),
    )
    source = item.get("source") or default_source
    values = {
        **{field: item.get(field, "") for field in (
            "key", "type", "display", "reading", "romaji", "accent", "accent_type",
            "accent_display", "accent_note", "level", "review_group", "origin_type",
            "origin_language", "origin_word", "origin_note",
        )},
        "aliases_json": aliases_json,
        "created_at": existing["created_at"] if existing else timestamp,
        "updated_at": timestamp,
    }
    conn.execute(
        """
        INSERT INTO entries (
            key, type, display, reading, romaji, accent, accent_type, accent_display,
            accent_note, level, review_group, aliases_json, origin_type,
            origin_language, origin_word, origin_note, created_at, updated_at
        ) VALUES (
            :key, :type, :display, :reading, :romaji, :accent, :accent_type,
            :accent_display, :accent_note, :level, :review_group, :aliases_json,
            :origin_type, :origin_language, :origin_word, :origin_note,
            :created_at, :updated_at
        )
        ON CONFLICT(key) DO UPDATE SET
            type = excluded.type,
            display = CASE WHEN excluded.display <> '' THEN excluded.display ELSE entries.display END,
            reading = CASE WHEN excluded.reading <> '' THEN excluded.reading ELSE entries.reading END,
            romaji = CASE WHEN excluded.romaji <> '' THEN excluded.romaji ELSE entries.romaji END,
            accent = CASE WHEN excluded.accent <> '' THEN excluded.accent ELSE entries.accent END,
            accent_type = CASE WHEN excluded.accent_type <> '' THEN excluded.accent_type ELSE entries.accent_type END,
            accent_display = CASE WHEN excluded.accent_display <> '' THEN excluded.accent_display ELSE entries.accent_display END,
            accent_note = CASE WHEN excluded.accent_note <> '' THEN excluded.accent_note ELSE entries.accent_note END,
            level = CASE WHEN excluded.level <> '' THEN excluded.level ELSE entries.level END,
            review_group = CASE WHEN excluded.review_group <> '' THEN excluded.review_group ELSE entries.review_group END,
            aliases_json = excluded.aliases_json,
            origin_type = CASE WHEN excluded.origin_type <> '' THEN excluded.origin_type ELSE entries.origin_type END,
            origin_language = CASE WHEN excluded.origin_language <> '' THEN excluded.origin_language ELSE entries.origin_language END,
            origin_word = CASE WHEN excluded.origin_word <> '' THEN excluded.origin_word ELSE entries.origin_word END,
            origin_note = CASE WHEN excluded.origin_note <> '' THEN excluded.origin_note ELSE entries.origin_note END,
            updated_at = excluded.updated_at
        """,
        values,
    )
    for sense in item["senses"]:
        conn.execute(
            "INSERT OR IGNORE INTO senses(entry_key, meaning, example_ja, example_zh) VALUES(?, ?, ?, ?)",
            (item["key"], sense["meaning"], sense["example_ja"], sense["example_zh"]),
        )
    for meaning in item.get("_remove_existing_blank_sense_meanings", []):
        rich_exists = conn.execute(
            "SELECT 1 FROM senses WHERE entry_key=? AND meaning=? AND (example_ja<>'' OR example_zh<>'')",
            (item["key"], meaning),
        ).fetchone()
        if rich_exists is not None:
            conn.execute(
                "DELETE FROM senses WHERE entry_key=? AND meaning=? AND example_ja='' AND example_zh=''",
                (item["key"], meaning),
            )
    if source:
        conn.execute(
            "INSERT OR IGNORE INTO sources(entry_key, source, added_at) VALUES(?, ?, ?)",
            (item["key"], source, timestamp),
        )
    return status

def replace_entry(conn: sqlite3.Connection, original_key: str, item: dict[str, Any]) -> bool:
    """Replace editable entry data and report whether anything changed.

    Exact no-op manual edits must not bump ``updated_at`` or disturb source
    history.  Relationship changes are handled by the service layer because
    they live outside the entry row itself.
    """
    if item["key"] != original_key:
        raise ValueError("edit 目前不允許直接修改 key；請使用 merge 或重新匯入。")
    existing = get_entry_row(conn, original_key)
    if existing is None:
        raise ValueError(f"找不到項目：{original_key}")

    current = {
        "type": existing["type"], "display": existing["display"],
        "reading": existing["reading"], "romaji": existing["romaji"],
        "accent": existing["accent"], "accent_type": existing["accent_type"],
        "accent_display": existing["accent_display"], "accent_note": existing["accent_note"],
        "level": existing["level"], "review_group": existing["review_group"],
        "aliases": _loads_list(existing["aliases_json"] or "[]"),
        "origin_type": existing["origin_type"], "origin_language": existing["origin_language"],
        "origin_word": existing["origin_word"], "origin_note": existing["origin_note"],
        "senses": entry_senses(conn, original_key),
        "sources": entry_sources(conn, original_key),
    }
    desired = {
        "type": item["type"], "display": item["display"],
        "reading": item["reading"], "romaji": item["romaji"],
        "accent": item["accent"], "accent_type": item["accent_type"],
        "accent_display": item["accent_display"], "accent_note": item["accent_note"],
        "level": item["level"], "review_group": item["review_group"],
        "aliases": list(item["aliases"]),
        "origin_type": item["origin_type"], "origin_language": item["origin_language"],
        "origin_word": item["origin_word"], "origin_note": item["origin_note"],
        "senses": list(item["senses"]),
        "sources": list(dict.fromkeys(item.get("sources", []))),
    }
    if current == desired:
        return False

    timestamp = now_text()
    conn.execute(
        """
        UPDATE entries SET type=?, display=?, reading=?, romaji=?, accent=?, accent_type=?,
            accent_display=?, accent_note=?, level=?, review_group=?, aliases_json=?,
            origin_type=?, origin_language=?, origin_word=?, origin_note=?, updated_at=?
        WHERE key=?
        """,
        (
            item["type"], item["display"], item["reading"], item["romaji"], item["accent"],
            item["accent_type"], item["accent_display"], item["accent_note"], item["level"],
            item["review_group"], json.dumps(item["aliases"], ensure_ascii=False),
            item["origin_type"], item["origin_language"], item["origin_word"], item["origin_note"],
            timestamp, original_key,
        ),
    )
    conn.execute("DELETE FROM senses WHERE entry_key = ?", (original_key,))
    for sense in item["senses"]:
        conn.execute(
            "INSERT INTO senses(entry_key, meaning, example_ja, example_zh) VALUES(?, ?, ?, ?)",
            (original_key, sense["meaning"], sense["example_ja"], sense["example_zh"]),
        )
    existing_sources = {
        row["source"]: row["added_at"]
        for row in conn.execute(
            "SELECT source, added_at FROM sources WHERE entry_key = ?",
            (original_key,),
        ).fetchall()
    }
    desired_sources = list(dict.fromkeys(item.get("sources", [])))
    for source in set(existing_sources) - set(desired_sources):
        conn.execute(
            "DELETE FROM sources WHERE entry_key = ? AND source = ?",
            (original_key, source),
        )
    for source in desired_sources:
        if source in existing_sources:
            continue
        conn.execute(
            "INSERT INTO sources(entry_key, source, added_at) VALUES(?, ?, ?)",
            (original_key, source, timestamp),
        )
    return True


def insert_attempt(conn: sqlite3.Connection, attempt: dict[str, Any]) -> bool:
    # Backward compatibility for attempts imported before v0.6.3: their
    # auto-generated event_key hashed the entire normalized record, so a later
    # regenerated explanation could produce a different key.  For auto-keyed
    # imports only, compare the new stable identity against existing rows before
    # inserting. Explicit event_key values always keep exact-key semantics.
    if attempt.get("_event_key_generated"):
        incoming_identity = attempt_identity_signature(attempt)
        for existing_row in conn.execute("SELECT * FROM attempts ORDER BY id").fetchall():
            existing_attempt = attempt_row_to_dict(existing_row)
            if attempt_identity_signature(existing_attempt) == incoming_identity:
                return False

    timestamp = now_text()
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO attempts(
            event_key, result, attempt_date, source, section, question, question_type,
            prompt, user_answer, correct_answer, reason, before_text, after_text,
            parts_json, user_order_json, correct_order_json, options_json, created_at
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            attempt["event_key"], attempt["result"], attempt["date"], attempt["source"],
            attempt["section"], attempt["question"], attempt["question_type"], attempt["prompt"],
            attempt["user_answer"], attempt["correct_answer"], attempt["reason"], attempt["before"],
            attempt["after"], json.dumps(attempt["parts"], ensure_ascii=False),
            json.dumps(attempt["user_order"], ensure_ascii=False),
            json.dumps(attempt["correct_order"], ensure_ascii=False),
            json.dumps(attempt.get("options", []), ensure_ascii=False), timestamp,
        ),
    )
    inserted = cursor.rowcount > 0
    if not inserted:
        # A duplicate event_key is a true no-op.  Older versions continued and
        # attached the incoming linked_entries to the existing attempt even
        # while reporting the record as skipped.
        return False
    attempt_id = cursor.lastrowid
    if attempt_id is None:
        raise RuntimeError("無法取得作答紀錄 id。")
    for key in attempt["linked_entries"]:
        conn.execute(
            "INSERT OR IGNORE INTO attempt_entries(attempt_id, entry_key, role) VALUES(?, ?, 'related')",
            (attempt_id, key),
        )
    return True


def get_attempt(conn: sqlite3.Connection, event_key: str) -> dict[str, Any] | None:
    """Return one attempt by its stable event key.

    The public CLI and future Web API both use ``event_key`` instead of the
    SQLite row id.  Row ids are storage details and may change after a restore
    or migration, while event keys are stable user-facing identifiers.
    """
    row = conn.execute(
        "SELECT * FROM attempts WHERE event_key = ?",
        (event_key,),
    ).fetchone()
    if row is None:
        return None
    links = [
        link["entry_key"]
        for link in conn.execute(
            "SELECT entry_key FROM attempt_entries WHERE attempt_id = ? ORDER BY entry_key",
            (row["id"],),
        ).fetchall()
    ]
    return attempt_row_to_dict(row, links)


def replace_attempt(conn: sqlite3.Connection, original_event_key: str, attempt: dict[str, Any]) -> None:
    """Fully replace one attempt while keeping its stable event key.

    Editing an attempt is an explicit full replacement, just like editing an
    entry.  Keeping the original key prevents links or external API clients
    from silently losing track of the record when descriptive fields change.
    """
    row = conn.execute(
        "SELECT id FROM attempts WHERE event_key = ?",
        (original_event_key,),
    ).fetchone()
    if row is None:
        raise ValueError(f"找不到作答紀錄：{original_event_key}")
    if attempt["event_key"] != original_event_key:
        raise ValueError("edit 目前不允許修改 event_key。")

    conn.execute(
        """
        UPDATE attempts SET
            result=?, attempt_date=?, source=?, section=?, question=?, question_type=?,
            prompt=?, user_answer=?, correct_answer=?, reason=?, before_text=?, after_text=?,
            parts_json=?, user_order_json=?, correct_order_json=?, options_json=?
        WHERE event_key=?
        """,
        (
            attempt["result"], attempt["date"], attempt["source"], attempt["section"],
            attempt["question"], attempt["question_type"], attempt["prompt"],
            attempt["user_answer"], attempt["correct_answer"], attempt["reason"],
            attempt["before"], attempt["after"],
            json.dumps(attempt["parts"], ensure_ascii=False),
            json.dumps(attempt["user_order"], ensure_ascii=False),
            json.dumps(attempt["correct_order"], ensure_ascii=False),
            json.dumps(attempt.get("options", []), ensure_ascii=False),
            original_event_key,
        ),
    )
    conn.execute("DELETE FROM attempt_entries WHERE attempt_id = ?", (row["id"],))
    for key in attempt["linked_entries"]:
        conn.execute(
            "INSERT INTO attempt_entries(attempt_id, entry_key, role) VALUES(?, ?, 'related')",
            (row["id"], key),
        )


def delete_attempt(conn: sqlite3.Connection, event_key: str) -> bool:
    """Delete one attempt by stable key and report whether it existed."""
    cursor = conn.execute("DELETE FROM attempts WHERE event_key = ?", (event_key,))
    return cursor.rowcount > 0



def _safe_structured_attempt_list(
    raw: str,
    field_name: str,
    *,
    kind: str,
) -> tuple[list[Any], str | None]:
    """Decode one structured attempt JSON field without crashing readers.

    Audit still inspects the raw database value. Presentation/export instead
    receive an empty safe value plus a warning so one malformed legacy record
    cannot block access to all other data or safe repairs.
    """
    try:
        value = json.loads(raw or "[]")
    except (json.JSONDecodeError, TypeError):
        return [], f"{field_name} JSON 已損壞"
    if not isinstance(value, list):
        return [], f"{field_name} 必須是陣列"
    if kind == "parts":
        valid = all(
            isinstance(item, dict)
            and isinstance(item.get("id"), int)
            and not isinstance(item.get("id"), bool)
            and isinstance(item.get("text"), str)
            for item in value
        )
    elif kind == "options":
        valid = all(
            isinstance(item, dict)
            and isinstance(item.get("id"), int)
            and not isinstance(item.get("id"), bool)
            and isinstance(item.get("text"), str)
            for item in value
        )
    elif kind == "order":
        valid = all(isinstance(item, int) and not isinstance(item, bool) for item in value)
    else:
        valid = True
    if not valid:
        return [], f"{field_name} 結構無效"
    return value, None

def attempt_row_to_dict(row: sqlite3.Row, linked_entries: list[str] | None = None) -> dict[str, Any]:
    parts, parts_warning = _safe_structured_attempt_list(
        row["parts_json"], "parts_json", kind="parts"
    )
    user_order, user_warning = _safe_structured_attempt_list(
        row["user_order_json"], "user_order_json", kind="order"
    )
    correct_order, correct_warning = _safe_structured_attempt_list(
        row["correct_order_json"], "correct_order_json", kind="order"
    )
    if "options_json" in row.keys():
        options, options_warning = _safe_structured_attempt_list(
            row["options_json"], "options_json", kind="options"
        )
    else:
        options, options_warning = [], None
    warnings = [
        warning for warning in (parts_warning, user_warning, correct_warning, options_warning)
        if warning
    ]
    return {
        "id": row["id"],
        "event_key": row["event_key"],
        "result": row["result"],
        "date": row["attempt_date"],
        "source": row["source"],
        "section": row["section"],
        "question": row["question"],
        "question_type": row["question_type"],
        "prompt": row["prompt"],
        "user_answer": row["user_answer"],
        "correct_answer": row["correct_answer"],
        "reason": row["reason"],
        "before": row["before_text"],
        "after": row["after_text"],
        "parts": parts,
        "user_order": user_order,
        "correct_order": correct_order,
        "options": options,
        "linked_entries": linked_entries or [],
        "created_at": row["created_at"],
        "_data_warnings": warnings,
    }


def list_attempts(
    conn: sqlite3.Connection,
    results: Iterable[str] | None = None,
    entry_key: str | None = None,
    level: str | None = None,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    joins = ""
    if results:
        values = list(results)
        clauses.append("a.result IN ({})".format(",".join("?" for _ in values)))
        params.extend(values)
    if entry_key or level:
        joins += " JOIN attempt_entries ae ON ae.attempt_id = a.id JOIN entries e ON e.key = ae.entry_key"
    if entry_key:
        clauses.append("ae.entry_key = ?")
        params.append(entry_key)
    if level:
        clauses.append("e.level = ?")
        params.append(level)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    rows = conn.execute(
        f"SELECT DISTINCT a.* FROM attempts a{joins}{where} "
        "ORDER BY COALESCE(NULLIF(a.attempt_date, ''), a.created_at) DESC, a.id DESC",
        params,
    ).fetchall()
    if not rows:
        return []
    link_map: dict[int, list[str]] = {int(row["id"]): [] for row in rows}
    attempt_ids = list(link_map)
    for chunk in _chunks(attempt_ids):
        placeholders = ",".join("?" for _ in chunk)
        for link in conn.execute(
            f"SELECT attempt_id, entry_key FROM attempt_entries "
            f"WHERE attempt_id IN ({placeholders}) ORDER BY attempt_id, entry_key",
            chunk,
        ).fetchall():
            link_map[int(link["attempt_id"])].append(link["entry_key"])
    return [attempt_row_to_dict(row, link_map[int(row["id"])]) for row in rows]


def stats(conn: sqlite3.Connection) -> dict[str, Any]:
    result: dict[str, Any] = {}
    result["total"] = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    result["grammar"] = conn.execute("SELECT COUNT(*) FROM entries WHERE type='grammar'").fetchone()[0]
    result["vocabulary"] = conn.execute("SELECT COUNT(*) FROM entries WHERE type='vocabulary'").fetchone()[0]
    result["with_romaji"] = conn.execute(
        "SELECT COUNT(*) FROM entries WHERE type='vocabulary' AND romaji<>''"
    ).fetchone()[0]
    result["with_accent"] = conn.execute(
        "SELECT COUNT(*) FROM entries WHERE type='vocabulary' AND (accent<>'' OR accent_display<>'' OR accent_type<>'')"
    ).fetchone()[0]
    result["loanwords"] = conn.execute(
        "SELECT COUNT(*) FROM entries WHERE type='vocabulary' AND origin_type<>''"
    ).fetchone()[0]
    result["senses"] = conn.execute("SELECT COUNT(*) FROM senses").fetchone()[0]
    result["attempts"] = conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
    result["mistakes"] = conn.execute("SELECT COUNT(*) FROM attempts WHERE result IN ('wrong','partial')").fetchone()[0]
    result["relations"] = conn.execute("SELECT COUNT(*) FROM grammar_relations").fetchone()[0]
    result["pending_relations"] = conn.execute("SELECT COUNT(*) FROM pending_grammar_relations").fetchone()[0]
    result["levels"] = [
        dict(row)
        for row in conn.execute(
            "SELECT COALESCE(NULLIF(level,''),'未分類') AS name, COUNT(*) AS count FROM entries GROUP BY name"
        ).fetchall()
    ]
    return result
