"""Structured duplicate-resolution helpers for import plans.

The functions here transform normalized :class:`ImportPlan` objects using
stable keys.  They do not know about fzf or terminal prompts, so the same
operations can later be exposed by a mimir Web API.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from .models import ImportPlan
from .repository import get_entry, get_entry_row
from .services import detect_duplicate_warnings
from .validation import merge_normalized_items


def _resolve_mapping(key: str, mapping: dict[str, str]) -> str:
    """Resolve mapping chains while rejecting cycles."""
    current = key
    seen: set[str] = set()
    while current in mapping:
        if current in seen:
            raise ValueError(f"key 映射形成循環：{key}")
        seen.add(current)
        current = mapping[current]
    return current


def resolve_import_plan(
    conn: sqlite3.Connection,
    plan: ImportPlan,
    key_map: dict[str, str] | None = None,
    skip_item_keys: set[str] | None = None,
) -> ImportPlan:
    """Return a new plan after explicit key remaps and skips.

    A remap means "store this incoming item under that stable key".  It is the
    safe core operation behind the desktop prompt's "沿用既有 key" choice.
    References in attempts and grammar relationships are rewritten together,
    preventing orphaned links.
    """
    raw_map = dict(key_map or {})
    skipped = set(skip_item_keys or set())
    incoming = {item["key"]: item for item in plan.items}

    unknown_sources = (set(raw_map) | skipped) - set(incoming)
    if unknown_sources:
        raise ValueError("匯入計畫中找不到要處理的 key：" + "、".join(sorted(unknown_sources)))

    resolved_map = {source: _resolve_mapping(target, raw_map) for source, target in raw_map.items()}
    for source, target in resolved_map.items():
        if source == target:
            continue
        if target in skipped:
            raise ValueError(f"不能把 {source} 映射到已跳過的 {target}。")
        source_type = incoming[source]["type"]
        target_item = incoming.get(target)
        target_entry = get_entry(conn, target, include_attempts=False) if target_item is None else None
        if target_item is None and target_entry is None:
            raise ValueError(f"映射目標不存在：{source} → {target}")
        target_type = target_item["type"] if target_item is not None else target_entry["type"]
        if source_type != target_type:
            raise ValueError(f"不能將不同類型的項目映射：{source} → {target}")

    def mapped(key: str) -> str:
        return resolved_map.get(key, key)

    merged_by_key: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for original in plan.items:
        source_key = original["key"]
        if source_key in skipped:
            continue
        target_key = mapped(source_key)
        item = dict(original)
        item["key"] = target_key

        # When an incoming kanji spelling replaces an existing kana display,
        # retain the old display as an alias before upsert changes it.
        existing = get_entry(conn, target_key, include_attempts=False)
        aliases = list(item.get("aliases", []))
        if existing and existing.get("display") and existing["display"] != item.get("display"):
            aliases.append(existing["display"])
        item["aliases"] = list(dict.fromkeys(alias for alias in aliases if alias))

        relations: list[dict[str, str]] = []
        for relation in item.get("related_grammar", []):
            rewritten = dict(relation)
            rewritten["key"] = mapped(relation["key"])
            if rewritten["key"] != target_key:
                relations.append(rewritten)
        item["related_grammar"] = relations

        if target_key in merged_by_key:
            merged_by_key[target_key] = merge_normalized_items(merged_by_key[target_key], item, allow_identity_override=True)
        else:
            merged_by_key[target_key] = item
            order.append(target_key)

    items = [merged_by_key[key] for key in order]
    available = {
        row["key"] for row in conn.execute("SELECT key FROM entries").fetchall()
    } | set(merged_by_key)

    attempts: list[dict[str, Any]] = []
    for original in plan.attempts:
        attempt = dict(original)
        links = [mapped(key) for key in original.get("linked_entries", [])]
        links = list(dict.fromkeys(links))
        missing = [key for key in links if key not in available]
        if missing:
            raise ValueError(
                f"作答紀錄 {attempt['event_key']} 在跳過／映射後仍連到不存在的項目："
                + "、".join(missing)
            )
        attempt["linked_entries"] = links
        attempts.append(attempt)

    notes = list(plan.notes)
    for source, target in sorted(resolved_map.items()):
        if source != target:
            notes.append(f"匯入 key 已映射：{source} → {target}")
    for key in sorted(skipped):
        notes.append(f"已跳過匯入項目：{key}")

    warnings = detect_duplicate_warnings(conn, items)
    return ImportPlan(plan.source, items, attempts, warnings, notes)
