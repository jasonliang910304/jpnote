"""Non-destructive import preflight reports.

The preflight reuses the normal payload parser/validator and import-plan
preparation.  It adds compact status information that is useful before a real
import, but never mutates the database and never silently changes duplicate
resolution semantics used by the importer itself.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from .models import ImportPlan
from .repository import get_entry
from .import_outcomes import classify_attempt_outcome, classify_entry_outcome
from .relation_integrity import reciprocal_type
from .import_safe_fixes import safe_import_fix_candidates


def _entry_brief(entry: dict[str, Any] | None) -> dict[str, Any]:
    if not entry:
        return {}
    return {
        "key": entry.get("key", ""),
        "type": entry.get("type", ""),
        "display": entry.get("display", ""),
        "reading": entry.get("reading", ""),
        "romaji": entry.get("romaji", ""),
        "level": entry.get("level", ""),
        "aliases": list(entry.get("aliases", [])),
        "meanings": [
            sense.get("meaning", "")
            for sense in entry.get("senses", [])[:3]
            if sense.get("meaning")
        ],
    }




def _relation_state(conn: sqlite3.Connection) -> tuple[
    dict[tuple[str, str, str], list[str]],
    dict[tuple[str, str, str], list[str]],
]:
    resolved: dict[tuple[str, str, str], list[str]] = {}
    pending: dict[tuple[str, str, str], list[str]] = {}
    for table, state in (
        ("grammar_relations", resolved),
        ("pending_grammar_relations", pending),
    ):
        for row in conn.execute(
            f"SELECT source_key, target_key, relation_type, note FROM {table} ORDER BY id"
        ).fetchall():
            identity = (row["source_key"], row["target_key"], row["relation_type"])
            state.setdefault(identity, []).append(str(row["note"] or ""))
    return resolved, pending


def _classify_and_apply_relation_state(
    resolved: dict[tuple[str, str, str], list[str]],
    pending: dict[tuple[str, str, str], list[str]],
    source_key: str,
    target_key: str,
    relation_type: str,
    note: str,
    *,
    target_available: bool,
) -> str:
    identity = (source_key, target_key, relation_type)
    main_rows = resolved.get(identity, [])
    pending_rows = pending.get(identity, [])

    if not target_available:
        if not main_rows and not pending_rows:
            status = "new"
        elif not main_rows and len(pending_rows) == 1 and pending_rows[0] == note:
            status = "unchanged"
        else:
            status = "update"
        resolved.pop(identity, None)
        pending[identity] = [note]
        return status

    reciprocal = reciprocal_type(relation_type)
    opposite = (target_key, source_key, reciprocal) if reciprocal is not None else None
    reciprocal_rows = resolved.get(opposite, []) if opposite is not None else []
    exact_main = len(main_rows) == 1 and main_rows[0] == note
    exact_reciprocal = reciprocal is None or (
        len(reciprocal_rows) == 1 and reciprocal_rows[0] == note
    )
    if exact_main and exact_reciprocal and not pending_rows:
        status = "unchanged"
    elif not main_rows and not pending_rows and not reciprocal_rows:
        status = "new"
    else:
        status = "update"

    pending.pop(identity, None)
    resolved[identity] = [note]
    if opposite is not None:
        resolved[opposite] = [note]
    return status



def _resolve_available_pending_state(
    resolved: dict[tuple[str, str, str], list[str]],
    pending: dict[tuple[str, str, str], list[str]],
    available_keys: set[str],
) -> tuple[int, list[dict[str, Any]]]:
    """Simulate pending→resolved transitions after incoming entries/relations.

    This mirrors the real strict resolver: stale non-empty pending metadata may
    not overwrite a different resolved/reciprocal note.
    """
    resolved_count = 0
    conflicts: list[dict[str, Any]] = []
    for identity in list(pending):
        source_key, target_key, relation_type = identity
        if target_key not in available_keys:
            continue
        reciprocal = reciprocal_type(relation_type)
        opposite = (target_key, source_key, reciprocal) if reciprocal is not None else None
        pending_notes = {note.strip() for note in pending.get(identity, []) if note.strip()}
        resolved_notes = {note.strip() for note in resolved.get(identity, []) if note.strip()}
        if opposite is not None:
            resolved_notes.update(note.strip() for note in resolved.get(opposite, []) if note.strip())
        all_notes = pending_notes | resolved_notes
        if len(all_notes) > 1:
            conflicts.append({
                "code": "pending_relation_note_conflict",
                "severity": "review",
                "scope": "database",
                "incoming_key": target_key,
                "other_key": source_key,
                "reason": (
                    "待補 relation 與既有／本次 relation note 衝突："
                    f"{source_key} → {target_key}（{relation_type}）；"
                    f"pending={sorted(pending_notes)}，resolved={sorted(resolved_notes)}"
                ),
                "source_key": source_key,
                "target_key": target_key,
                "relation": relation_type,
                "pending_notes": sorted(pending_notes),
                "resolved_notes": sorted(resolved_notes),
            })
            continue
        note = next(iter(resolved_notes), next(iter(pending_notes), ""))
        pending.pop(identity, None)
        resolved[identity] = [note]
        if opposite is not None:
            resolved[opposite] = [note]
        resolved_count += 1
    return resolved_count, conflicts

def build_preflight_report(conn: sqlite3.Connection, plan: ImportPlan) -> dict[str, Any]:
    """Return a JSON-serializable import report using real apply classifiers."""
    incoming_by_key = {item["key"]: item for item in plan.items}
    warning_map: dict[str, list[dict[str, Any]]] = {}
    conflicts: list[dict[str, Any]] = []

    for warning in plan.warnings:
        incoming = incoming_by_key.get(warning.incoming_key)
        other = incoming_by_key.get(warning.other_key)
        if other is None:
            other = get_entry(conn, warning.other_key, include_attempts=False)
        record = {
            **warning.to_dict(),
            "incoming": _entry_brief(incoming),
            "matched": _entry_brief(other),
        }
        conflicts.append(record)
        warning_map.setdefault(warning.incoming_key, []).append(record)
        if warning.scope == "batch" and warning.other_key in incoming_by_key:
            warning_map.setdefault(warning.other_key, []).append(record)

    available_keys = {
        row["key"] for row in conn.execute("SELECT key FROM entries").fetchall()
    } | set(incoming_by_key)

    items: list[dict[str, Any]] = []
    counts = {"new": 0, "update": 0, "unchanged": 0, "review": 0}
    relation_counts = {"new": 0, "update": 0, "unchanged": 0}
    resolved_relation_state, pending_relation_state = _relation_state(conn)
    for item in plan.items:
        existing = get_entry(conn, item["key"], include_attempts=False)
        base_status = classify_entry_outcome(conn, item, plan.source)
        relation_outcomes: list[dict[str, Any]] = []
        if item["type"] == "grammar":
            for relation in item.get("related_grammar", []):
                relation_status = _classify_and_apply_relation_state(
                    resolved_relation_state,
                    pending_relation_state,
                    item["key"],
                    relation["key"],
                    relation["relation"],
                    relation["note"],
                    target_available=relation["key"] in available_keys,
                )
                relation_counts[relation_status] += 1
                relation_outcomes.append({**relation, "status": relation_status})
        apply_status = base_status
        if base_status == "unchanged" and any(
            relation["status"] in {"new", "update"} for relation in relation_outcomes
        ):
            apply_status = "update"
        item_conflicts = warning_map.get(item["key"], [])
        status = "review" if item_conflicts else apply_status
        counts[status] += 1
        items.append({
            "status": status,
            "apply_outcome": apply_status,
            "entry_outcome": base_status,
            "relation_outcomes": relation_outcomes,
            "incoming": _entry_brief(item),
            "existing_same_key": _entry_brief(existing) if existing else None,
            "conflict_count": len(item_conflicts),
        })

    resolved_pending_relations, pending_conflicts = _resolve_available_pending_state(
        resolved_relation_state, pending_relation_state, available_keys
    )
    if pending_conflicts:
        for conflict in pending_conflicts:
            incoming = incoming_by_key.get(conflict["target_key"]) or incoming_by_key.get(conflict["source_key"])
            matched = incoming_by_key.get(conflict["source_key"])
            if matched is None:
                matched = get_entry(conn, conflict["source_key"], include_attempts=False)
            conflict["incoming"] = _entry_brief(incoming)
            conflict["matched"] = _entry_brief(matched)
        conflicts.extend(pending_conflicts)
        affected = {
            key
            for conflict in pending_conflicts
            for key in (conflict["source_key"], conflict["target_key"])
            if key in incoming_by_key
        }
        for item in items:
            if item["incoming"].get("key") in affected:
                item["status"] = "review"
                item["conflict_count"] += sum(
                    1 for conflict in pending_conflicts
                    if item["incoming"].get("key") in {conflict["source_key"], conflict["target_key"]}
                )
        counts = {"new": 0, "update": 0, "unchanged": 0, "review": 0}
        for item in items:
            counts[item["status"]] += 1

    attempts: list[dict[str, Any]] = []
    attempt_counts = {"new": 0, "duplicate": 0, "conflict": 0, "invalid_links": 0}
    for attempt in plan.attempts:
        outcome = classify_attempt_outcome(conn, attempt, available_keys=available_keys)
        status = outcome["status"]
        attempt_counts[status] += 1
        existing = outcome.get("existing") or {}
        attempts.append({
            "event_key": attempt.get("event_key", ""),
            "matched_event_key": existing.get("event_key", ""),
            "date": attempt.get("date", ""),
            "source": attempt.get("source", ""),
            "section": attempt.get("section", ""),
            "question": attempt.get("question", ""),
            "result": attempt.get("result", ""),
            "status": status,
            "missing_linked_entries": outcome["missing_linked_entries"],
            "existing_result": existing.get("result", ""),
        })

    safe_fixes = safe_import_fix_candidates(conn, plan)

    return {
        "source": plan.source,
        "summary": {
            "items": len(plan.items),
            "attempts": len(plan.attempts),
            "new_items": counts["new"],
            "update_items": counts["update"],
            "unchanged_items": counts["unchanged"],
            "review_items": counts["review"],
            "conflicts": len(conflicts),
            "new_attempts": attempt_counts["new"],
            "duplicate_attempts": attempt_counts["duplicate"],
            "conflicting_attempts": attempt_counts["conflict"],
            "attempts_with_missing_links": attempt_counts["invalid_links"],
            "new_relations": relation_counts["new"],
            "updated_relations": relation_counts["update"],
            "unchanged_relations": relation_counts["unchanged"],
            "resolved_pending_relations": resolved_pending_relations,
            "pending_relation_conflicts": len(pending_conflicts),
            "notes": len(plan.notes),
            "safe_fixes": len(safe_fixes),
        },
        "notes": list(plan.notes),
        "safe_fixes": safe_fixes,
        "items": items,
        "conflicts": conflicts,
        "attempts": attempts,
        "database_modified": False,
    }


def _brief_text(entry: dict[str, Any]) -> str:
    if not entry:
        return ""
    label = "文法" if entry.get("type") == "grammar" else "單字"
    bits = [f"[{label}] {entry.get('display') or entry.get('key')} <{entry.get('key')}>" ]
    details = []
    if entry.get("reading"):
        details.append(str(entry["reading"]))
    if entry.get("romaji"):
        details.append(str(entry["romaji"]))
    if entry.get("level"):
        details.append(str(entry["level"]))
    if details:
        bits.append(" / ".join(details))
    if entry.get("aliases"):
        bits.append("aliases: " + "、".join(entry["aliases"][:5]))
    if entry.get("meanings"):
        bits.append("意思: " + "；".join(entry["meanings"][:2]))
    return "\n    ".join(bits)


def render_preflight_text(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "匯入預檢（未修改資料庫）",
        (
            f"項目 {summary['items']}｜新項目 {summary['new_items']}｜"
            f"同 key 更新 {summary['update_items']}｜未變更 {summary.get('unchanged_items', 0)}｜需確認 {summary['review_items']}｜"
            f"作答 {summary['attempts']}"
        ),
    ]
    if report.get("notes"):
        lines.append("")
        lines.append("注意")
        lines.extend(f"  - {note}" for note in report["notes"])

    if report.get("safe_fixes"):
        lines.append("")
        lines.append(f"可安全整理的本次匯入資料（{len(report['safe_fixes'])}）")
        labels = {
            "incoming_alias_cleanup": "移除本次資料中與 display／reading／key 重複的 alias",
            "existing_alias_cleanup": "整理這次會更新項目的既有冗餘 alias",
            "incoming_sense_cleanup": "整理本次資料中完全重複或被完整例句涵蓋的空白 sense",
            "incoming_blank_sense_already_covered": "略過既有完整 sense 已涵蓋的空白 sense",
            "existing_blank_sense_shadowed": "新增完整例句時移除同 meaning 的既有空白 sense",
        }
        for action in report["safe_fixes"]:
            lines.append(f"  - {action.get('key', '')}：{labels.get(action.get('kind'), action.get('kind', 'safe fix'))}")

    if report["conflicts"]:
        lines.append("")
        lines.append(f"疑似衝突（{len(report['conflicts'])}）")
        for index, conflict in enumerate(report["conflicts"], 1):
            lines.append(f"  {index}. {conflict['reason']}")
            lines.append("    本次：" + _brief_text(conflict["incoming"]).replace("\n    ", "\n      "))
            side = "同批" if conflict["scope"] == "batch" else "既有"
            lines.append(f"    {side}：" + _brief_text(conflict["matched"]).replace("\n    ", "\n      "))
    else:
        lines.append("")
        lines.append("疑似衝突：無")

    updates = [item for item in report["items"] if item["status"] == "update"]
    if updates:
        lines.append("")
        lines.append(f"同 stable key，正式匯入時會更新／合併（{len(updates)}）")
        for item in updates:
            lines.append("  - " + _brief_text(item["incoming"]).replace("\n    ", "\n    "))

    attempt_problems = [item for item in report["attempts"] if item["status"] != "new"]
    if attempt_problems:
        lines.append("")
        lines.append("作答紀錄注意事項")
        for attempt in attempt_problems:
            identity = "｜".join(
                value for value in (
                    attempt.get("date", ""), attempt.get("source", ""),
                    attempt.get("section", ""), attempt.get("question", ""),
                ) if value
            ) or attempt["event_key"]
            if attempt["status"] == "duplicate":
                lines.append(f"  - [重複作答，正式匯入會略過] {identity}")
            elif attempt["status"] == "conflict":
                lines.append(f"  - [作答 identity 衝突，正式匯入會拒絕] {identity}")
                if attempt.get("matched_event_key"):
                    lines.append(f"    既有 event_key: {attempt['matched_event_key']}")
                lines.append(
                    f"    result: 既有 {attempt.get('existing_result', '')} / 本次 {attempt.get('result', '')}"
                )
            else:
                lines.append(f"  - [缺少 linked_entries] {identity}")
                lines.append("    " + "、".join(attempt["missing_linked_entries"]))

    lines.append("")
    lines.append("結果：僅檢查，資料庫未修改。")
    return "\n".join(lines) + "\n"


def render_preflight_json(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2) + "\n"
