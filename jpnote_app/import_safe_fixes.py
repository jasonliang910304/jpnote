"""Safe, opt-in normalization of the selected incoming import plan."""

from __future__ import annotations

from copy import deepcopy
import sqlite3
from typing import Any

from .data_quality import clean_aliases, safe_clean_senses, sense_is_blank
from .models import ImportPlan
from .repository import get_entry
from .services import detect_duplicate_warnings


def _analyze_item(conn: sqlite3.Connection, item: dict[str, Any]) -> dict[str, Any]:
    existing = get_entry(conn, item["key"], include_attempts=False)
    actions: list[dict[str, Any]] = []

    cleaned_incoming_aliases = clean_aliases(
        item["key"], item.get("display", ""), item.get("reading", ""), item.get("aliases", [])
    )
    if cleaned_incoming_aliases != list(item.get("aliases", [])):
        actions.append({
            "kind": "incoming_alias_cleanup",
            "key": item["key"],
            "before": list(item.get("aliases", [])),
            "after": cleaned_incoming_aliases,
        })

    clean_existing_aliases = False
    if existing is not None:
        effective_display = str(item.get("display") or existing.get("display") or "")
        effective_reading = str(item.get("reading") or existing.get("reading") or "")
        existing_aliases = list(existing.get("aliases", []))
        cleaned_existing_aliases = clean_aliases(
            item["key"], effective_display, effective_reading, existing_aliases
        )
        clean_existing_aliases = cleaned_existing_aliases != existing_aliases
        if clean_existing_aliases and not item.get("_clean_existing_aliases"):
            actions.append({
                "kind": "existing_alias_cleanup",
                "key": item["key"],
                "before": existing_aliases,
                "after": cleaned_existing_aliases,
            })

    cleaned_senses, sense_actions = safe_clean_senses(item.get("senses", []))
    if sense_actions:
        actions.append({
            "kind": "incoming_sense_cleanup",
            "key": item["key"],
            "changes": sense_actions,
        })

    existing_senses = list(existing.get("senses", [])) if existing is not None else []
    existing_rich = {
        sense["meaning"] for sense in existing_senses if not sense_is_blank(sense)
    }
    incoming_rich = {
        sense["meaning"] for sense in cleaned_senses if not sense_is_blank(sense)
    }
    existing_blank = {
        sense["meaning"] for sense in existing_senses if sense_is_blank(sense)
    }

    filtered_senses: list[dict[str, str]] = []
    removed_against_existing: list[str] = []
    for sense in cleaned_senses:
        if sense_is_blank(sense) and sense["meaning"] in existing_rich:
            removed_against_existing.append(sense["meaning"])
            continue
        filtered_senses.append(sense)
    if removed_against_existing:
        actions.append({
            "kind": "incoming_blank_sense_already_covered",
            "key": item["key"],
            "meanings": sorted(set(removed_against_existing)),
        })

    remove_existing_blank = sorted(
        (incoming_rich & existing_blank)
        - set(item.get("_remove_existing_blank_sense_meanings", []))
    )
    if remove_existing_blank:
        actions.append({
            "kind": "existing_blank_sense_shadowed",
            "key": item["key"],
            "meanings": remove_existing_blank,
        })

    return {
        "actions": actions,
        "aliases": cleaned_incoming_aliases,
        "clean_existing_aliases": clean_existing_aliases,
        "senses": filtered_senses,
        "remove_existing_blank": sorted(
            set(item.get("_remove_existing_blank_sense_meanings", [])) | set(remove_existing_blank)
        ),
    }


def safe_import_fix_candidates(conn: sqlite3.Connection, plan: ImportPlan) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for item in plan.items:
        actions.extend(_analyze_item(conn, item)["actions"])
    return actions


def apply_safe_import_fixes(
    conn: sqlite3.Connection,
    plan: ImportPlan,
) -> tuple[ImportPlan, list[dict[str, Any]]]:
    items: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    for original in plan.items:
        item = deepcopy(original)
        analysis = _analyze_item(conn, item)
        actions.extend(analysis["actions"])
        item["aliases"] = analysis["aliases"]
        item["senses"] = analysis["senses"]
        if analysis["clean_existing_aliases"]:
            item["_clean_existing_aliases"] = True
        if analysis["remove_existing_blank"]:
            item["_remove_existing_blank_sense_meanings"] = analysis["remove_existing_blank"]
        items.append(item)
    warnings = detect_duplicate_warnings(conn, items)
    return ImportPlan(plan.source, items, deepcopy(plan.attempts), warnings, list(plan.notes)), actions
