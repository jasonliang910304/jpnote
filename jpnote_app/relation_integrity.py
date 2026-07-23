"""Grammar relation identity, upsert, audit, and safe legacy repair helpers.

A grammar relation is conceptually identified by ``source_key + target_key +
relation_type``.  ``note`` is metadata of that relation, not part of its
identity.  Older jpnote releases used a SQLite UNIQUE constraint that included
``note``; changing a note could therefore accumulate duplicate logical rows.
This module centralizes the logical identity so import preflight, apply, audit,
and repair agree.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from .db import now_text

SYMMETRIC_RELATIONS = {"意思相近", "對比", "容易混淆", "替代表達", "語氣比較"}
INVERSE_RELATION = {"前置文法": "延伸", "延伸": "前置文法"}


@dataclass(slots=True)
class RelationApplyResult:
    status: str  # new / update / unchanged
    added_rows: int = 0
    updated_rows: int = 0
    pending_rows: int = 0


def reciprocal_type(relation_type: str) -> str | None:
    if relation_type in SYMMETRIC_RELATIONS:
        return relation_type
    return INVERSE_RELATION.get(relation_type)


def _rows_for_identity(
    conn: sqlite3.Connection,
    table: str,
    source_key: str,
    target_key: str,
    relation_type: str,
) -> list[sqlite3.Row]:
    return conn.execute(
        f"""SELECT * FROM {table}
            WHERE source_key=? AND target_key=? AND relation_type=?
            ORDER BY created_at, id""",
        (source_key, target_key, relation_type),
    ).fetchall()


def _identity_is_exact(rows: list[sqlite3.Row], note: str) -> bool:
    return len(rows) == 1 and str(rows[0]["note"] or "") == note


def classify_relation(
    conn: sqlite3.Connection,
    source_key: str,
    target_key: str,
    relation_type: str,
    note: str,
    *,
    target_available: bool,
) -> str:
    """Return new/update/unchanged for one public outgoing relation.

    The classification describes the state after a real import, including the
    reciprocal row when the target exists (or will exist in the same batch).
    """
    main_rows = _rows_for_identity(conn, "grammar_relations", source_key, target_key, relation_type)
    pending_rows = _rows_for_identity(conn, "pending_grammar_relations", source_key, target_key, relation_type)

    if not target_available:
        if not main_rows and not pending_rows:
            return "new"
        if not main_rows and _identity_is_exact(pending_rows, note):
            return "unchanged"
        return "update"

    reciprocal = reciprocal_type(relation_type)
    reciprocal_rows: list[sqlite3.Row] = []
    if reciprocal is not None:
        reciprocal_rows = _rows_for_identity(
            conn, "grammar_relations", target_key, source_key, reciprocal
        )
    exact_main = _identity_is_exact(main_rows, note)
    exact_reciprocal = reciprocal is None or _identity_is_exact(reciprocal_rows, note)
    if exact_main and exact_reciprocal and not pending_rows:
        return "unchanged"
    if not main_rows and not pending_rows and not reciprocal_rows:
        return "new"
    return "update"


def _replace_identity_row(
    conn: sqlite3.Connection,
    table: str,
    source_key: str,
    target_key: str,
    relation_type: str,
    note: str,
    source: str,
) -> tuple[int, int]:
    """Ensure exactly one logical relation row; return (added, updated)."""
    rows = _rows_for_identity(conn, table, source_key, target_key, relation_type)
    if _identity_is_exact(rows, note):
        return 0, 0

    if rows:
        created_at = min(str(row["created_at"] or now_text()) for row in rows)
        existing_source = next((str(row["source"] or "") for row in rows if row["source"]), "")
        conn.execute(
            f"DELETE FROM {table} WHERE source_key=? AND target_key=? AND relation_type=?",
            (source_key, target_key, relation_type),
        )
        conn.execute(
            f"""INSERT INTO {table}(
                source_key, target_key, relation_type, note, source, created_at
            ) VALUES(?, ?, ?, ?, ?, ?)""",
            (source_key, target_key, relation_type, note, source or existing_source, created_at),
        )
        return 0, 1

    conn.execute(
        f"""INSERT INTO {table}(
            source_key, target_key, relation_type, note, source, created_at
        ) VALUES(?, ?, ?, ?, ?, ?)""",
        (source_key, target_key, relation_type, note, source, now_text()),
    )
    return 1, 0


def upsert_relation(
    conn: sqlite3.Connection,
    source_key: str,
    target_key: str,
    relation_type: str,
    note: str,
    source: str,
) -> RelationApplyResult:
    """Apply one relation using logical identity instead of note-as-identity."""
    if source_key == target_key:
        return RelationApplyResult("unchanged")
    target_exists = conn.execute("SELECT 1 FROM entries WHERE key=?", (target_key,)).fetchone() is not None
    before = classify_relation(
        conn, source_key, target_key, relation_type, note, target_available=target_exists
    )

    added = updated = pending = 0
    if not target_exists:
        # Any impossible stale resolved rows are removed only for this exact
        # logical identity, then one canonical pending row is retained.
        conn.execute(
            "DELETE FROM grammar_relations WHERE source_key=? AND target_key=? AND relation_type=?",
            (source_key, target_key, relation_type),
        )
        a, u = _replace_identity_row(
            conn, "pending_grammar_relations", source_key, target_key, relation_type, note, source
        )
        pending += a
        updated += u
        return RelationApplyResult(before, added, updated, pending)

    # Target now exists, so stale pending rows for this identity are superseded.
    pending_rows = _rows_for_identity(
        conn, "pending_grammar_relations", source_key, target_key, relation_type
    )
    if pending_rows:
        conn.execute(
            "DELETE FROM pending_grammar_relations WHERE source_key=? AND target_key=? AND relation_type=?",
            (source_key, target_key, relation_type),
        )
        updated += 1

    a, u = _replace_identity_row(
        conn, "grammar_relations", source_key, target_key, relation_type, note, source
    )
    added += a
    updated += u
    reciprocal = reciprocal_type(relation_type)
    if reciprocal is not None:
        a, u = _replace_identity_row(
            conn, "grammar_relations", target_key, source_key, reciprocal, note, source
        )
        added += a
        updated += u
    return RelationApplyResult(before, added, updated, pending)


def _safe_note(rows: list[sqlite3.Row]) -> str | None:
    nonempty = {str(row["note"] or "").strip() for row in rows if str(row["note"] or "").strip()}
    if len(nonempty) > 1:
        return None
    return next(iter(nonempty), "")


def relation_integrity_issues(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Return relation legacy/integrity issues without modifying data."""
    issues: list[dict[str, Any]] = []
    for table in ("grammar_relations", "pending_grammar_relations"):
        groups = conn.execute(
            f"""SELECT source_key, target_key, relation_type, COUNT(*) AS n
                FROM {table}
                GROUP BY source_key, target_key, relation_type
                HAVING COUNT(*) > 1"""
        ).fetchall()
        for group in groups:
            rows = _rows_for_identity(
                conn, table, group["source_key"], group["target_key"], group["relation_type"]
            )
            note = _safe_note(rows)
            issues.append({
                "code": "conflicting_relation_notes" if note is None else "duplicate_relation_rows",
                "severity": "review" if note is None else "fixable",
                "fixable": note is not None,
                "key": group["source_key"],
                "message": (
                    f"{group['source_key']} → {group['target_key']}（{group['relation_type']}）"
                    + ("有多筆不同 note，無法安全判斷應保留哪一筆。" if note is None else "有重複邏輯關聯，可安全合併。")
                ),
                "details": {
                    "table": table,
                    "target_key": group["target_key"],
                    "relation": group["relation_type"],
                    "notes": sorted({str(row["note"] or "") for row in rows}),
                },
            })

    # Reciprocal integrity applies only to resolved relations.
    rows = conn.execute("SELECT * FROM grammar_relations ORDER BY id").fetchall()
    seen_pairs: set[tuple[str, str, str, str]] = set()
    for row in rows:
        reciprocal = reciprocal_type(str(row["relation_type"] or ""))
        if reciprocal is None:
            continue
        marker = tuple(sorted((str(row["source_key"]), str(row["target_key"])))) + tuple(sorted((str(row["relation_type"]), reciprocal)))
        if marker in seen_pairs:
            continue
        seen_pairs.add(marker)
        opposite = _rows_for_identity(
            conn, "grammar_relations", row["target_key"], row["source_key"], reciprocal
        )
        if not opposite:
            issues.append({
                "code": "missing_reciprocal_relation",
                "severity": "fixable",
                "fixable": True,
                "key": row["source_key"],
                "message": f"缺少 reciprocal relation：{row['target_key']} → {row['source_key']}（{reciprocal}）。",
                "details": {"target_key": row["target_key"], "relation": row["relation_type"], "expected_reciprocal": reciprocal},
            })
            continue
        left_note = str(row["note"] or "").strip()
        right_note = _safe_note(opposite)
        if right_note is None:
            continue
        if left_note != right_note:
            if not left_note or not right_note:
                issues.append({
                    "code": "reciprocal_relation_note_mismatch",
                    "severity": "fixable",
                    "fixable": True,
                    "key": row["source_key"],
                    "message": "雙向／反向 relation 的 note 一側為空，可安全同步非空 note。",
                    "details": {"target_key": row["target_key"], "relation": row["relation_type"], "left_note": left_note, "right_note": right_note},
                })
            else:
                issues.append({
                    "code": "reciprocal_relation_note_conflict",
                    "severity": "review",
                    "fixable": False,
                    "key": row["source_key"],
                    "message": "雙向／反向 relation 的 note 內容不同，需人工確認。",
                    "details": {"target_key": row["target_key"], "relation": row["relation_type"], "left_note": left_note, "right_note": right_note},
                })
    return issues


def apply_safe_relation_repairs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Repair deterministic legacy relation issues; leave conflicts untouched."""
    actions: list[dict[str, Any]] = []
    # Collapse duplicate logical identities only when at most one non-empty note exists.
    for table in ("grammar_relations", "pending_grammar_relations"):
        groups = conn.execute(
            f"""SELECT source_key, target_key, relation_type, COUNT(*) AS n
                FROM {table}
                GROUP BY source_key, target_key, relation_type
                HAVING COUNT(*) > 1"""
        ).fetchall()
        for group in groups:
            rows = _rows_for_identity(
                conn, table, group["source_key"], group["target_key"], group["relation_type"]
            )
            note = _safe_note(rows)
            if note is None:
                continue
            source = next((str(row["source"] or "") for row in rows if row["source"]), "")
            created_at = min(str(row["created_at"] or now_text()) for row in rows)
            conn.execute(
                f"DELETE FROM {table} WHERE source_key=? AND target_key=? AND relation_type=?",
                (group["source_key"], group["target_key"], group["relation_type"]),
            )
            conn.execute(
                f"""INSERT INTO {table}(source_key,target_key,relation_type,note,source,created_at)
                    VALUES(?,?,?,?,?,?)""",
                (group["source_key"], group["target_key"], group["relation_type"], note, source, created_at),
            )
            actions.append({"collapsed_relation_rows": {"table": table, "source_key": group["source_key"], "target_key": group["target_key"], "relation": group["relation_type"]}})

    # Ensure reciprocal rows and safely synchronize note when only one side has text.
    rows = conn.execute("SELECT * FROM grammar_relations ORDER BY id").fetchall()
    processed: set[tuple[str, str, str]] = set()
    for row in rows:
        relation_type = str(row["relation_type"] or "")
        reciprocal = reciprocal_type(relation_type)
        if reciprocal is None:
            continue
        token = (str(row["source_key"]), str(row["target_key"]), relation_type)
        if token in processed:
            continue
        processed.add(token)
        opposite = _rows_for_identity(conn, "grammar_relations", row["target_key"], row["source_key"], reciprocal)
        left_note = str(row["note"] or "").strip()
        if not opposite:
            _replace_identity_row(conn, "grammar_relations", row["target_key"], row["source_key"], reciprocal, left_note, str(row["source"] or ""))
            actions.append({"added_reciprocal_relation": {"source_key": row["target_key"], "target_key": row["source_key"], "relation": reciprocal}})
            continue
        right_note = _safe_note(opposite)
        if right_note is None or left_note == right_note:
            continue
        if left_note and not right_note:
            _replace_identity_row(conn, "grammar_relations", row["target_key"], row["source_key"], reciprocal, left_note, str(row["source"] or ""))
            actions.append({"synced_reciprocal_note": {"source_key": row["source_key"], "target_key": row["target_key"], "note": left_note}})
        elif right_note and not left_note:
            _replace_identity_row(conn, "grammar_relations", row["source_key"], row["target_key"], relation_type, right_note, str(row["source"] or ""))
            actions.append({"synced_reciprocal_note": {"source_key": row["source_key"], "target_key": row["target_key"], "note": right_note}})
    return actions
