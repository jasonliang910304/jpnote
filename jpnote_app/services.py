"""Core jpnote use-cases.

Nothing in this module knows about fzf, terminal escape sequences, or shell
pipelines.  The CLI and a future Web API both call these functions directly.
"""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from .db import now_text
from .models import DuplicateWarning, ImportPlan, ImportResult
from .repository import (
    entry_relations,
    get_entry,
    get_entry_row,
    insert_attempt,
    list_entries,
    list_entry_rows,
    pending_relations,
    row_to_summary,
    search_entries,
    upsert_entry,
)
from .import_outcomes import classify_attempt_outcome
from .relation_integrity import reciprocal_type, upsert_relation
from .validation import normalize_identity_text, normalize_payload


def _identity_set(item: dict[str, Any]) -> set[str]:
    values = [item.get("display", ""), *item.get("aliases", [])]
    return {normalize_identity_text(value) for value in values if normalize_identity_text(value)}


def _identity_index(items: list[dict[str, Any]]) -> dict[tuple[str, str], list[str]]:
    """Index normalized display/alias identities by entry type.

    This turns the common no-duplicate path from an O(n²) pair scan into a
    linear indexing pass.  Buckets with actual collisions still expand to the
    required candidate pairs.
    """
    index: dict[tuple[str, str], list[str]] = {}
    for item in items:
        for identity in _identity_set(item):
            bucket = index.setdefault((item["type"], identity), [])
            if item["key"] not in bucket:
                bucket.append(item["key"])
    return index


def detect_duplicate_warnings(
    conn: sqlite3.Connection,
    items: list[dict[str, Any]],
) -> list[DuplicateWarning]:
    """Return conservative duplicate candidates; never mutate or auto-merge."""
    by_key = {item["key"]: item for item in items}
    pair_identities: dict[tuple[str, str], set[str]] = {}

    batch_index = _identity_index(items)
    for (_entry_type, identity), keys in batch_index.items():
        if len(keys) < 2:
            continue
        for left_index, left_key in enumerate(keys):
            for right_key in keys[left_index + 1:]:
                if left_key == right_key:
                    continue
                pair = tuple(sorted((left_key, right_key)))
                pair_identities.setdefault(pair, set()).add(identity)

    warnings: list[DuplicateWarning] = []
    for (left_key, right_key), identities in sorted(pair_identities.items()):
        # Preserve an incoming-oriented warning.  The preflight layer marks both
        # sides for review when a batch conflict is present.
        incoming_key = left_key if left_key in by_key else right_key
        other_key = right_key if incoming_key == left_key else left_key
        warnings.append(DuplicateWarning(
            code="batch_identity_overlap",
            incoming_key=incoming_key,
            other_key=other_key,
            reason=f"同批項目的名稱或 aliases 重疊：{sorted(identities)[0]}",
            scope="batch",
        ))

    existing = [row_to_summary(row) for row in list_entry_rows(conn)]
    existing_index = _identity_index(existing)
    for item in items:
        overlaps_by_key: dict[str, set[str]] = {}
        for identity in _identity_set(item):
            for other_key in existing_index.get((item["type"], identity), []):
                if other_key == item["key"]:
                    continue
                overlaps_by_key.setdefault(other_key, set()).add(identity)
        for other_key, identities in sorted(overlaps_by_key.items()):
            warnings.append(DuplicateWarning(
                code="database_identity_overlap",
                incoming_key=item["key"],
                other_key=other_key,
                reason=f"與既有項目的名稱或 aliases 重疊：{sorted(identities)[0]}",
                scope="database",
            ))

    unique: dict[tuple[str, str, str], DuplicateWarning] = {}
    for warning in warnings:
        unique[(warning.code, warning.incoming_key, warning.other_key)] = warning
    return list(unique.values())


def prepare_import(conn: sqlite3.Connection, payload: dict[str, Any]) -> ImportPlan:
    source, items, attempts, notes = normalize_payload(payload)
    warnings = detect_duplicate_warnings(conn, items)
    return ImportPlan(source=source, items=items, attempts=attempts, warnings=warnings, notes=notes)


def filter_import_plan(
    plan: ImportPlan,
    item_keys: set[str] | None = None,
    attempt_indices: set[int] | None = None,
) -> ImportPlan:
    items = plan.items if item_keys is None else [item for item in plan.items if item["key"] in item_keys]
    attempts = plan.attempts if attempt_indices is None else [
        attempt for index, attempt in enumerate(plan.attempts) if index in attempt_indices
    ]
    selected_keys = {item["key"] for item in items}
    warnings = [
        warning for warning in plan.warnings
        if warning.incoming_key in selected_keys
        and (warning.scope != "batch" or warning.other_key in selected_keys)
    ]
    return ImportPlan(plan.source, items, attempts, warnings, list(plan.notes))


def add_or_queue_relation(
    conn: sqlite3.Connection,
    source_key: str,
    relation: dict[str, str],
    source: str,
) -> tuple[int, int, int]:
    """Apply one logical grammar relation.

    v0.6.6 treats note as metadata rather than relation identity, so correcting a
    note updates the existing logical relation instead of accumulating another
    row with the same source/target/type.
    """
    outcome = upsert_relation(
        conn,
        source_key,
        relation["key"],
        relation["relation"],
        relation["note"],
        source,
    )
    return outcome.added_rows, outcome.pending_rows, outcome.updated_rows

def pending_resolution_analysis(
    conn: sqlite3.Connection,
    source_key: str,
    target_key: str,
    relation_type: str,
) -> dict[str, Any]:
    """Describe whether one pending logical relation can resolve safely.

    Existing resolved data is authoritative over an empty pending note, but a
    stale non-empty pending note must never silently overwrite a different
    non-empty resolved/reciprocal note.
    """
    pending_rows = conn.execute(
        """SELECT * FROM pending_grammar_relations
           WHERE source_key=? AND target_key=? AND relation_type=?
           ORDER BY created_at, id""",
        (source_key, target_key, relation_type),
    ).fetchall()
    main_rows = conn.execute(
        """SELECT * FROM grammar_relations
           WHERE source_key=? AND target_key=? AND relation_type=?
           ORDER BY created_at, id""",
        (source_key, target_key, relation_type),
    ).fetchall()
    reciprocal = reciprocal_type(relation_type)
    opposite_rows = []
    if reciprocal is not None:
        opposite_rows = conn.execute(
            """SELECT * FROM grammar_relations
               WHERE source_key=? AND target_key=? AND relation_type=?
               ORDER BY created_at, id""",
            (target_key, source_key, reciprocal),
        ).fetchall()

    def nonempty(rows: list[sqlite3.Row]) -> list[str]:
        return [str(row["note"] or "").strip() for row in rows if str(row["note"] or "").strip()]

    pending_notes = set(nonempty(pending_rows))
    resolved_notes = set(nonempty(main_rows) + nonempty(opposite_rows))
    all_notes = pending_notes | resolved_notes
    conflict = len(all_notes) > 1
    # Prefer already-resolved metadata when present; otherwise use the single
    # safe pending note (or an empty note).
    chosen_note = next(iter(resolved_notes), next(iter(pending_notes), ""))
    return {
        "safe": not conflict,
        "note": chosen_note,
        "pending_notes": sorted(pending_notes),
        "resolved_notes": sorted(resolved_notes),
        "reciprocal_type": reciprocal or "",
        "pending_count": len(pending_rows),
    }


def resolve_pending_relations(conn: sqlite3.Connection, *, strict: bool = True) -> int:
    """Resolve pending relations without allowing stale note overwrites.

    ``strict=True`` is used by normal imports and aborts the surrounding
    transaction on a conflict. Safe repair uses ``strict=False`` so ambiguous
    rows remain pending and are reported by audit instead of blocking unrelated
    deterministic repairs.
    """
    resolved = 0
    identities = conn.execute(
        """SELECT source_key, target_key, relation_type, MIN(id) AS first_id
           FROM pending_grammar_relations
           GROUP BY source_key, target_key, relation_type
           ORDER BY first_id"""
    ).fetchall()
    for identity in identities:
        source_key = str(identity["source_key"])
        target_key = str(identity["target_key"])
        relation_type = str(identity["relation_type"])
        if get_entry_row(conn, target_key) is None:
            continue
        analysis = pending_resolution_analysis(
            conn, source_key, target_key, relation_type
        )
        if not analysis["safe"]:
            if strict:
                raise ValueError(
                    "待補文法關聯與既有 relation note 衝突，拒絕以舊資料覆寫："
                    f"{source_key} → {target_key}（{relation_type}）；"
                    f"pending={analysis['pending_notes']}，resolved={analysis['resolved_notes']}"
                )
            continue
        source_row = conn.execute(
            """SELECT source FROM pending_grammar_relations
               WHERE source_key=? AND target_key=? AND relation_type=?
               ORDER BY created_at, id LIMIT 1""",
            (source_key, target_key, relation_type),
        ).fetchone()
        relation = {
            "key": target_key,
            "relation": relation_type,
            "note": str(analysis["note"]),
        }
        added, _, updated = add_or_queue_relation(
            conn, source_key, relation, str(source_row["source"] or "") if source_row else ""
        )
        # upsert_relation removes the main pending identity. Remove any legacy
        # duplicate leftovers defensively.
        conn.execute(
            """DELETE FROM pending_grammar_relations
               WHERE source_key=? AND target_key=? AND relation_type=?""",
            (source_key, target_key, relation_type),
        )
        if added or updated:
            conn.execute("UPDATE entries SET updated_at=? WHERE key=?", (now_text(), source_key))
        resolved += 1
    return resolved


def apply_import(conn: sqlite3.Connection, plan: ImportPlan) -> ImportResult:
    result = ImportResult()
    selected_keys = {item["key"] for item in plan.items}
    entry_statuses: dict[str, str] = {}
    with conn:
        for item in plan.items:
            status = upsert_entry(conn, item, plan.source)
            entry_statuses[item["key"]] = status
            if status == "added":
                result.added_entries += 1
            elif status == "updated":
                result.updated_entries += 1
            else:
                result.unchanged_entries += 1

        # Relations are processed after all selected entries exist, so links
        # inside the same import batch resolve immediately.
        for item in plan.items:
            if item["type"] != "grammar":
                continue
            relation_source = item.get("source") or plan.source
            for relation in item["related_grammar"]:
                added, pending, updated = add_or_queue_relation(
                    conn, item["key"], relation, relation_source
                )
                result.added_relations += added
                result.updated_relations += updated
                result.pending_relations += pending
                if added or pending or updated:
                    conn.execute("UPDATE entries SET updated_at=? WHERE key=?", (now_text(), item["key"]))
                    if entry_statuses.get(item["key"]) == "unchanged":
                        entry_statuses[item["key"]] = "updated"
                        result.unchanged_entries -= 1
                        result.updated_entries += 1

        result.resolved_relations = resolve_pending_relations(conn)

        available_keys = {row["key"] for row in conn.execute("SELECT key FROM entries").fetchall()}
        for attempt in plan.attempts:
            outcome = classify_attempt_outcome(conn, attempt, available_keys=available_keys)
            if outcome["status"] == "invalid_links":
                raise ValueError(
                    "作答紀錄引用了尚未收錄的 key："
                    + "、".join(outcome["missing_linked_entries"])
                )
            if outcome["status"] == "conflict":
                existing = outcome.get("existing") or {}
                raise ValueError(
                    "作答紀錄與既有資料 identity 相同但內容不同，拒絕自動覆蓋："
                    f"{existing.get('event_key') or attempt['event_key']}"
                )
            if outcome["status"] == "duplicate":
                result.skipped_attempts += 1
                continue
            if insert_attempt(conn, attempt):
                result.added_attempts += 1
            else:
                # Defensive fallback: outcome classification should have caught
                # every duplicate before insertion.
                result.skipped_attempts += 1
    return result


def duplicate_candidates(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    entries = list_entries(conn)
    index = _identity_index(entries)
    pair_identities: dict[tuple[str, str], set[str]] = {}
    for (_entry_type, identity), keys in index.items():
        if len(keys) < 2:
            continue
        for left_index, left_key in enumerate(keys):
            for right_key in keys[left_index + 1:]:
                pair = tuple(sorted((left_key, right_key)))
                pair_identities.setdefault(pair, set()).add(identity)
    return [
        {
            "left_key": left_key,
            "right_key": right_key,
            "reason": f"名稱或 aliases 重疊：{sorted(identities)[0]}",
        }
        for (left_key, right_key), identities in sorted(pair_identities.items())
    ]


def _plan_merged_relations(
    conn: sqlite3.Connection,
    source_key: str,
    target_key: str,
) -> list[dict[str, str]]:
    """Return conflict-checked relations after remapping source_key to target_key.

    Merge can collapse two previously distinct relation identities onto one.
    Never let last-write-wins choose between different non-empty notes.  The
    plan includes both resolved and pending rows and also validates reciprocal
    / inverse pairs before any database mutation begins.
    """
    rows: list[sqlite3.Row] = []
    for table in ("grammar_relations", "pending_grammar_relations"):
        rows.extend(conn.execute(
            f"""SELECT *, ? AS relation_table FROM {table}
                WHERE source_key IN (?, ?) OR target_key IN (?, ?)
                ORDER BY created_at, id""",
            (table, source_key, target_key, source_key, target_key),
        ).fetchall())

    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        new_source = target_key if row["source_key"] == source_key else row["source_key"]
        new_target = target_key if row["target_key"] == source_key else row["target_key"]
        if new_source == new_target:
            continue
        identity = (str(new_source), str(new_target), str(row["relation_type"]))
        group = groups.setdefault(identity, {"notes": set(), "sources": []})
        note = str(row["note"] or "").strip()
        if note:
            group["notes"].add(note)
        source = str(row["source"] or "")
        if source and source not in group["sources"]:
            group["sources"].append(source)

    for identity, group in groups.items():
        if len(group["notes"]) > 1:
            left, right, relation_type = identity
            raise ValueError(
                "merge 會把多筆文法關聯合併成同一 identity，但 note 彼此衝突，拒絕自動決定："
                f"{left} → {right}（{relation_type}）：{sorted(group['notes'])}"
            )

    checked: set[tuple[tuple[str, str, str], tuple[str, str, str]]] = set()
    for identity, group in groups.items():
        left, right, relation_type = identity
        reciprocal = reciprocal_type(relation_type)
        if reciprocal is None:
            continue
        opposite = (right, left, reciprocal)
        if opposite not in groups:
            continue
        marker = tuple(sorted((identity, opposite)))
        if marker in checked:
            continue
        checked.add(marker)
        left_note = next(iter(group["notes"]), "")
        right_note = next(iter(groups[opposite]["notes"]), "")
        if left_note and right_note and left_note != right_note:
            raise ValueError(
                "merge 後 reciprocal／inverse 文法關聯的 note 會互相衝突，拒絕自動決定："
                f"{left} → {right}（{relation_type}）={left_note!r}；"
                f"{right} → {left}（{reciprocal}）={right_note!r}"
            )

    plan: list[dict[str, str]] = []
    for (left, right, relation_type), group in sorted(groups.items()):
        plan.append({
            "source_key": left,
            "target_key": right,
            "relation_type": relation_type,
            "note": next(iter(group["notes"]), ""),
            "source": group["sources"][0] if group["sources"] else "merge",
        })
    return plan


def merge_entries(conn: sqlite3.Connection, source_key: str, target_key: str) -> dict[str, Any]:
    """Merge source into target using stable keys, then delete source.

    Relation remapping is planned and conflict-checked before any mutation.  A
    merge must never silently choose between contradictory relation notes.
    """
    if source_key == target_key:
        raise ValueError("來源與目標不能相同。")
    source = get_entry(conn, source_key)
    target = get_entry(conn, target_key)
    if source is None or target is None:
        raise ValueError("來源或目標項目不存在。")
    if source["type"] != target["type"]:
        raise ValueError("不能合併不同類型的項目。")

    relation_plan = _plan_merged_relations(conn, source_key, target_key)

    merged = dict(target)
    aliases = list(dict.fromkeys([
        *target.get("aliases", []), source["display"], *source.get("aliases", [])
    ]))
    merged["aliases"] = [alias for alias in aliases if alias and alias != target["display"]]
    for field in (
        "reading", "romaji", "accent", "accent_type", "accent_display", "accent_note",
        "level", "review_group", "origin_type", "origin_language", "origin_word", "origin_note",
    ):
        if not merged.get(field) and source.get(field):
            merged[field] = source[field]
    merged["senses"] = [*target.get("senses", [])]
    seen_senses = {
        (sense["meaning"], sense["example_ja"], sense["example_zh"])
        for sense in merged["senses"]
    }
    for sense in source.get("senses", []):
        signature = (sense["meaning"], sense["example_ja"], sense["example_zh"])
        if signature not in seen_senses:
            seen_senses.add(signature)
            merged["senses"].append(sense)
    merged["sources"] = list(dict.fromkeys([*target.get("sources", []), *source.get("sources", [])]))

    source_added_at = {
        row["source"]: row["added_at"]
        for row in conn.execute(
            "SELECT source, added_at FROM sources WHERE entry_key = ?",
            (source_key,),
        ).fetchall()
    }
    target_added_at = {
        row["source"]: row["added_at"]
        for row in conn.execute(
            "SELECT source, added_at FROM sources WHERE entry_key = ?",
            (target_key,),
        ).fetchall()
    }
    merged_added_at = {
        name: min(
            value for value in (target_added_at.get(name), source_added_at.get(name)) if value
        )
        for name in merged["sources"]
        if target_added_at.get(name) or source_added_at.get(name)
    }

    from .repository import replace_entry

    with conn:
        replace_entry(conn, target_key, merged)
        for source_name, added_at in merged_added_at.items():
            conn.execute(
                "UPDATE sources SET added_at = ? WHERE entry_key = ? AND source = ?",
                (added_at, target_key, source_name),
            )
        conn.execute(
            "INSERT OR IGNORE INTO attempt_entries(attempt_id, entry_key, role) "
            "SELECT attempt_id, ?, role FROM attempt_entries WHERE entry_key = ?",
            (target_key, source_key),
        )

        # Remove all relation rows touching either side of the merge, then
        # recreate the conflict-checked remapped plan through the canonical
        # logical relation helper.  This also restores reciprocal/inverse rows.
        if source["type"] == "grammar":
            conn.execute(
                "DELETE FROM grammar_relations "
                "WHERE source_key IN (?, ?) OR target_key IN (?, ?)",
                (source_key, target_key, source_key, target_key),
            )
            conn.execute(
                "DELETE FROM pending_grammar_relations "
                "WHERE source_key IN (?, ?) OR target_key IN (?, ?)",
                (source_key, target_key, source_key, target_key),
            )

        conn.execute("DELETE FROM entries WHERE key = ?", (source_key,))

        if source["type"] == "grammar":
            for relation in relation_plan:
                upsert_relation(
                    conn,
                    relation["source_key"],
                    relation["target_key"],
                    relation["relation_type"],
                    relation["note"],
                    relation["source"],
                )

    return get_entry(conn, target_key) or {}

def replace_entry_data(conn: sqlite3.Connection, original_key: str, item: dict[str, Any]) -> dict[str, Any]:
    """Replace one entry's editable fields and outgoing grammar relationships.

    A byte-for-byte-equivalent manual edit is a true no-op.  Relationship-only
    edits still count as content changes and update the entry timestamp once.
    """
    from .repository import replace_entry

    current = get_entry(conn, original_key, include_attempts=False)
    if current is None:
        raise ValueError(f"找不到項目：{original_key}")

    def relation_signature(values: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
        return sorted(
            (
                str(value.get("key") or ""),
                str(value.get("relation") or value.get("relation_type") or ""),
                str(value.get("note") or ""),
            )
            for value in values
            if isinstance(value, dict)
        )

    relations_changed = False
    if item["type"] == "grammar":
        relations_changed = relation_signature(current.get("related_grammar", [])) != relation_signature(
            item.get("related_grammar", [])
        )

    with conn:
        entry_changed = replace_entry(conn, original_key, item)
        if item["type"] == "grammar" and relations_changed:
            conn.execute(
                "DELETE FROM grammar_relations WHERE source_key = ? OR target_key = ?",
                (original_key, original_key),
            )
            conn.execute(
                "DELETE FROM pending_grammar_relations WHERE source_key = ? OR target_key = ?",
                (original_key, original_key),
            )
            for relation in item.get("related_grammar", []):
                add_or_queue_relation(
                    conn,
                    original_key,
                    relation,
                    item.get("source", "") or "manual edit",
                )
            resolve_pending_relations(conn)
            if not entry_changed:
                conn.execute(
                    "UPDATE entries SET updated_at = ? WHERE key = ?",
                    (now_text(), original_key),
                )
    return get_entry(conn, original_key) or {}
