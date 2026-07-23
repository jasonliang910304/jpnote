"""Conservative data-quality checks and safe repairs."""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any
from datetime import date, datetime
import unicodedata

from .models import AuditIssue
from .repository import list_entries, attempt_row_to_dict
from .services import duplicate_candidates
from .romaji import spaced_hepburn
from .romaji_maintenance import romaji_audit_records
from .services import pending_resolution_analysis, resolve_pending_relations
from .relation_integrity import relation_integrity_issues, apply_safe_relation_repairs
from .attempt_identity import attempt_identity_signature, attempt_content_signature, legacy_attempt_identity_signature_v063
from .sorting import normalize_level
from .attempt_options import cleaned_prompt_and_options, _suspicious_legacy_option_reason, normalized_options
from .validation import VALID_RELATION_TYPES, canonical_relation_type, normalize_attempt_date
from .data_quality import clean_aliases

_KATAKANA_RE = re.compile(r"^[\u30A0-\u30FFー・]+$")


def _has_control(value: Any, *, allow_layout: bool = True) -> bool:
    text = str(value or "")
    for char in text:
        code = ord(char)
        if allow_layout and char in {"\n", "\r", "\t"}:
            continue
        if code < 0x20 or code == 0x7F or 0x80 <= code <= 0x9F:
            return True
    return False


def _has_identifier_format_control(value: Any) -> bool:
    return any(unicodedata.category(char) == "Cf" for char in str(value or ""))


def _valid_iso_datetime(value: str) -> bool:
    if not value:
        return False
    try:
        datetime.fromisoformat(value)
        return True
    except ValueError:
        return False


def _valid_complete_order(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 4
        and all(isinstance(item, int) and not isinstance(item, bool) for item in value)
        and set(value) == {1, 2, 3, 4}
    )


def _valid_entry_key(key: str) -> bool:
    if _has_control(key, allow_layout=False) or _has_identifier_format_control(key):
        return False
    if key.startswith("grammar:"):
        return bool(key[len("grammar:"):].strip())
    if key.startswith("vocab:"):
        return bool(key[len("vocab:"):].strip())
    return False


def run_audit(conn: sqlite3.Connection) -> list[AuditIssue]:
    issues: list[AuditIssue] = []

    # Integrity checks must be fail-soft: audit should report database damage,
    # not crash while trying to diagnose it.
    try:
        quick_rows = conn.execute("PRAGMA quick_check").fetchall()
        quick_messages = [str(row[0]) for row in quick_rows]
        if quick_messages != ["ok"]:
            issues.append(AuditIssue(
                "database_quick_check_failed", "critical", False, "database",
                "SQLite quick_check 未通過。",
                {"messages": quick_messages},
            ))
    except sqlite3.Error as exc:
        issues.append(AuditIssue(
            "database_quick_check_error", "critical", False, "database",
            "執行 SQLite quick_check 時發生錯誤。", {"error": str(exc)},
        ))

    try:
        for row in conn.execute("PRAGMA foreign_key_check").fetchall():
            issues.append(AuditIssue(
                "foreign_key_violation", "critical", False, "database",
                "SQLite foreign_key_check 發現孤立或不一致的關聯。",
                {"table": row[0], "rowid": row[1], "parent": row[2], "fk_index": row[3]},
            ))
    except sqlite3.Error as exc:
        issues.append(AuditIssue(
            "foreign_key_check_error", "critical", False, "database",
            "執行 SQLite foreign_key_check 時發生錯誤。", {"error": str(exc)},
        ))
    malformed_alias_keys: set[str] = set()
    for row in conn.execute("SELECT key, aliases_json FROM entries ORDER BY key").fetchall():
        try:
            aliases = json.loads(row["aliases_json"] or "[]")
            if not isinstance(aliases, list):
                raise ValueError("aliases_json 不是陣列")
            if not all(isinstance(alias, str) for alias in aliases):
                raise ValueError("aliases_json 含非字串元素")
        except (json.JSONDecodeError, ValueError):
            malformed_alias_keys.add(row["key"])
            issues.append(AuditIssue(
                "invalid_aliases_json", "needs_input", False, row["key"],
                "aliases_json 已損壞或含非字串元素；repair 不會自動改寫，請先人工確認原始資料。",
            ))

    for row in conn.execute("SELECT * FROM entries ORDER BY key").fetchall():
        if row["key"] not in malformed_alias_keys:
            try:
                aliases_for_controls = json.loads(row["aliases_json"] or "[]")
            except json.JSONDecodeError:
                aliases_for_controls = []
            for alias in aliases_for_controls:
                if isinstance(alias, str) and _has_control(alias):
                    issues.append(AuditIssue(
                        "unsafe_terminal_control", "needs_input", False, row["key"],
                        "alias 含不安全的終端控制字元。", {"field": "aliases"},
                    ))
        if not _valid_entry_key(row["key"]):
            issues.append(AuditIssue(
                "invalid_stable_key", "needs_input", False, row["key"],
                "stable key 為空、前綴不合法，或含控制字元；請人工修正後再進行 merge/edit。",
            ))
        for timestamp_field in ("created_at", "updated_at"):
            if not _valid_iso_datetime(str(row[timestamp_field] or "")):
                issues.append(AuditIssue(
                    "invalid_entry_timestamp", "needs_input", False, row["key"],
                    f"{timestamp_field} 不是有效 ISO datetime：{row[timestamp_field]}",
                    {"field": timestamp_field},
                ))
        for field in (
            "display", "reading", "romaji", "accent", "accent_type",
            "accent_display", "accent_note", "review_group", "origin_language",
            "origin_word", "origin_note",
        ):
            if _has_control(row[field]):
                issues.append(AuditIssue(
                    "unsafe_terminal_control", "needs_input", False, row["key"],
                    f"欄位 {field} 含不安全的終端控制字元。",
                    {"field": field},
                ))

    for row in conn.execute("SELECT * FROM senses ORDER BY id").fetchall():
        for field in ("meaning", "example_ja", "example_zh"):
            if _has_control(row[field]):
                issues.append(AuditIssue(
                    "unsafe_terminal_control", "needs_input", False, row["entry_key"],
                    f"意思／例句欄位 {field} 含不安全的終端控制字元。",
                    {"field": field, "sense_id": row["id"]},
                ))

    sense_rows = conn.execute(
        "SELECT id, entry_key, meaning, example_ja, example_zh FROM senses ORDER BY entry_key, meaning, id"
    ).fetchall()
    sense_groups: dict[tuple[str, str], list[sqlite3.Row]] = {}
    for row in sense_rows:
        sense_groups.setdefault((row["entry_key"], row["meaning"]), []).append(row)
    for (entry_key, meaning), rows in sense_groups.items():
        signatures: dict[tuple[str, str, str], list[int]] = {}
        for row in rows:
            signature = (row["meaning"], row["example_ja"], row["example_zh"])
            signatures.setdefault(signature, []).append(row["id"])
        exact_duplicate_ids = [
            sense_id
            for ids in signatures.values() if len(ids) > 1
            for sense_id in ids[1:]
        ]
        blank_ids = [
            row["id"] for row in rows
            if not str(row["example_ja"] or "").strip() and not str(row["example_zh"] or "").strip()
        ]
        rich_signatures = {
            (row["example_ja"], row["example_zh"])
            for row in rows
            if str(row["example_ja"] or "").strip() or str(row["example_zh"] or "").strip()
        }
        if exact_duplicate_ids or (blank_ids and rich_signatures):
            issues.append(AuditIssue(
                "redundant_sense", "fixable", True, entry_key,
                f"意思「{meaning}」含完全重複或已被完整例句版本涵蓋的空白 sense，可安全整理。",
                {
                    "meaning": meaning,
                    "exact_duplicate_ids": exact_duplicate_ids,
                    "blank_ids": blank_ids if rich_signatures else [],
                },
            ))
        if len(rich_signatures) > 1:
            issues.append(AuditIssue(
                "same_meaning_multiple_examples", "review", False, entry_key,
                f"意思「{meaning}」有多組不同的非空例句；程式會保留，建議確認是否為刻意保存。",
                {"meaning": meaning, "example_variants": len(rich_signatures)},
            ))

    for row in conn.execute("SELECT * FROM sources ORDER BY id").fetchall():
        if not _valid_iso_datetime(str(row["added_at"] or "")):
            issues.append(AuditIssue(
                "invalid_source_timestamp", "needs_input", False, row["entry_key"],
                f"來源 added_at 不是有效 ISO datetime：{row['added_at']}",
                {"source_id": row["id"]},
            ))
        if _has_control(row["source"]):
            issues.append(AuditIssue(
                "unsafe_terminal_control", "needs_input", False, row["entry_key"],
                "來源文字含不安全的終端控制字元。",
                {"field": "source", "source_id": row["id"]},
            ))

    for table in ("grammar_relations", "pending_grammar_relations"):
        for row in conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall():
            raw_relation = str(row["relation_type"] or "")
            canonical = canonical_relation_type(raw_relation)
            if canonical not in VALID_RELATION_TYPES:
                issues.append(AuditIssue(
                    "invalid_relation_type", "needs_input", False, row["source_key"],
                    f"不支援的文法關聯類型：{raw_relation}",
                    {"table": table, "target_key": row["target_key"]},
                ))
            elif canonical != raw_relation:
                issues.append(AuditIssue(
                    "noncanonical_relation_type", "fixable", True, row["source_key"],
                    f"舊關聯標籤可正規化：{raw_relation} → {canonical}",
                    {"table": table, "target_key": row["target_key"]},
                ))
            for field in ("note", "source"):
                if _has_control(row[field]):
                    issues.append(AuditIssue(
                        "unsafe_terminal_control", "needs_input", False, row["source_key"],
                        f"文法關聯欄位 {field} 含不安全的終端控制字元。",
                        {"table": table, "target_key": row["target_key"], "field": field},
                    ))

    for relation_issue in relation_integrity_issues(conn):
        issues.append(AuditIssue(
            relation_issue["code"], relation_issue["severity"], relation_issue["fixable"],
            relation_issue["key"], relation_issue["message"], relation_issue.get("details", {}),
        ))

    identity_groups: dict[str, list[dict[str, Any]]] = {}
    legacy_identity_groups: dict[str, list[dict[str, Any]]] = {}
    attempt_rows = conn.execute("SELECT * FROM attempts ORDER BY id").fetchall()
    for raw_row in attempt_rows:
        links = [
            link["entry_key"] for link in conn.execute(
                "SELECT entry_key FROM attempt_entries WHERE attempt_id=? ORDER BY entry_key",
                (raw_row["id"],),
            ).fetchall()
        ]
        attempt_dict = attempt_row_to_dict(raw_row, links)
        identity_groups.setdefault(attempt_identity_signature(attempt_dict), []).append(attempt_dict)
        legacy_identity_groups.setdefault(legacy_attempt_identity_signature_v063(attempt_dict), []).append(attempt_dict)

    for group in identity_groups.values():
        if len(group) <= 1:
            continue
        content_signatures = {attempt_content_signature(item) for item in group}
        issues.append(AuditIssue(
            "duplicate_attempt_identity" if len(content_signatures) == 1 else "conflicting_attempt_identity",
            "review", False, group[0].get("event_key", "attempt"),
            (
                "多筆作答具有相同 identity 與相同內容；可能是重複資料，也可能是同日重做，請人工確認。"
                if len(content_signatures) == 1
                else "多筆作答具有相同 identity 但內容不同；review 前需人工確認是否為歷史衝突。"
            ),
            {"event_keys": [item.get("event_key", "") for item in group]},
        ))

    for group in legacy_identity_groups.values():
        if len(group) <= 1:
            continue
        new_signatures = {attempt_identity_signature(item) for item in group}
        if len(new_signatures) > 1:
            issues.append(AuditIssue(
                "legacy_attempt_identity_collision_risk", "review", False,
                group[0].get("event_key", "attempt"),
                "這些作答在 v0.6.3-v0.6.5 舊 identity 規則下會互相碰撞，但新版可區分；請確認歷史資料是否曾遺漏。",
                {"event_keys": [item.get("event_key", "") for item in group]},
            ))

    for row in attempt_rows:
        event_key = row["event_key"]
        if not _valid_iso_datetime(str(row["created_at"] or "")):
            issues.append(AuditIssue(
                "invalid_attempt_timestamp", "needs_input", False, event_key or f"attempt-id:{row['id']}",
                f"作答 created_at 不是有效 ISO datetime：{row['created_at']}",
            ))
        if row["attempt_date"]:
            try:
                normalized_attempt_date = normalize_attempt_date(row["attempt_date"])
                if date.fromisoformat(normalized_attempt_date) > date.today():
                    issues.append(AuditIssue(
                        "future_attempt_date", "review", False, event_key or f"attempt-id:{row['id']}",
                        f"作答日期位於未來：{row['attempt_date']}",
                    ))
            except ValueError:
                issues.append(AuditIssue(
                    "invalid_attempt_date", "needs_input", False, event_key or f"attempt-id:{row['id']}",
                    f"作答日期不是有效的 YYYY-MM-DD：{row['attempt_date']}",
                ))
        try:
            options = json.loads(row["options_json"] or "[]") if "options_json" in row.keys() else []
            if not isinstance(options, list):
                raise ValueError("options_json 不是陣列")
            normalized_options(options)
        except (json.JSONDecodeError, ValueError):
            options = []
            issues.append(AuditIssue(
                "invalid_attempt_options_json", "needs_input", False, event_key or f"attempt-id:{row['id']}",
                "options_json 已損壞；請人工確認，不會自動覆寫。",
            ))
        try:
            parts = json.loads(row["parts_json"] or "[]")
            if not isinstance(parts, list):
                raise ValueError("parts_json 不是陣列")
        except (json.JSONDecodeError, ValueError):
            parts = []
            issues.append(AuditIssue(
                "invalid_attempt_parts_json", "needs_input", False, event_key or f"attempt-id:{row['id']}",
                "parts_json 已損壞或不是陣列。",
            ))
        parsed_orders: dict[str, list[Any]] = {}
        for json_field in ("user_order_json", "correct_order_json"):
            try:
                order = json.loads(row[json_field] or "[]")
                if (
                    not isinstance(order, list)
                    or not all(isinstance(value, int) and not isinstance(value, bool) for value in order)
                ):
                    raise ValueError(f"{json_field} 格式錯誤")
                parsed_orders[json_field] = order
            except (json.JSONDecodeError, ValueError):
                parsed_orders[json_field] = []
                issues.append(AuditIssue(
                    "invalid_attempt_order_json", "needs_input", False, event_key or f"attempt-id:{row['id']}",
                    f"{json_field} 已損壞或含非整數元素。",
                    {"field": json_field},
                ))
        cleaned_prompt, cleaned_options, cleanup_action = cleaned_prompt_and_options(
            row["prompt"],
            options,
            parts=parts,
            question_type=row["question_type"],
        )
        if cleanup_action is not None:
            issue_type = "legacy_embedded_options" if cleanup_action == "split_options" else "legacy_prompt_residue"
            message = (
                "舊錯題把選項內嵌在題目文字中，可用 attempts migrate-options --apply 安全拆分。"
                if cleanup_action == "split_options"
                else "題目仍殘留已結構化的選項／四格文字，可用 attempts migrate-options --apply 安全清理。"
            )
            issues.append(AuditIssue(issue_type, "fixable", True, event_key, message))
        else:
            suspicious_reason = _suspicious_legacy_option_reason(
                row["prompt"], options, parts=parts, question_type=row["question_type"]
            )
            if suspicious_reason is not None:
                issues.append(AuditIssue(
                    "legacy_options_need_review", "review", False, event_key,
                    "題目疑似內嵌或殘留選項，但格式不足以安全自動拆分；請人工確認。",
                    {"reason": suspicious_reason},
                ))
        if not event_key or _has_control(event_key, allow_layout=False) or _has_identifier_format_control(event_key):
            issues.append(AuditIssue(
                "invalid_event_key", "needs_input", False, event_key or f"attempt-id:{row['id']}",
                "event_key 為空或含控制字元。",
            ))
        normalized_event_key = unicodedata.normalize("NFKC", str(event_key or ""))
        if event_key and normalized_event_key != event_key:
            conflict = conn.execute(
                "SELECT id FROM attempts WHERE event_key=? AND id<>?",
                (normalized_event_key, row["id"]),
            ).fetchone()
            issues.append(AuditIssue(
                "event_key_normalization_conflict" if conflict else "noncanonical_event_key",
                "review" if conflict else "fixable",
                not bool(conflict),
                event_key,
                (
                    f"event_key NFKC 正規化後會和既有 key 衝突：{normalized_event_key}"
                    if conflict else f"event_key 可安全 NFKC 正規化：{event_key} → {normalized_event_key}"
                ),
                {"normalized_event_key": normalized_event_key},
            ))
        for field in (
            "source", "section", "question", "prompt", "user_answer",
            "correct_answer", "reason", "before_text", "after_text",
        ):
            if _has_control(row[field]):
                issues.append(AuditIssue(
                    "unsafe_terminal_control", "needs_input", False, event_key,
                    f"作答欄位 {field} 含不安全的終端控制字元。",
                    {"field": field},
                ))
        if row["question_type"] == "reorder_4":
            try:
                parts = json.loads(row["parts_json"] or "[]")
            except json.JSONDecodeError:
                parts = []
            valid_parts = (
                isinstance(parts, list)
                and len(parts) == 4
                and {part.get("id") for part in parts if isinstance(part, dict)} == {1, 2, 3, 4}
                and all(str(part.get("text", "")).strip() for part in parts if isinstance(part, dict))
            )
            if not valid_parts:
                issues.append(AuditIssue(
                    "invalid_reorder_parts", "needs_input", False, event_key,
                    "reorder_4 的四格資料不完整或含空白格。",
                ))
            correct_order = parsed_orders.get("correct_order_json", [])
            user_order = parsed_orders.get("user_order_json", [])
            if not _valid_complete_order(correct_order):
                issues.append(AuditIssue(
                    "invalid_reorder_correct_order", "needs_input", False, event_key,
                    "reorder_4 的 correct_order 必須是 1、2、3、4 各一次。",
                ))
            if user_order and not _valid_complete_order(user_order):
                issues.append(AuditIssue(
                    "invalid_reorder_user_order", "needs_input", False, event_key,
                    "reorder_4 的 user_order 必須為空，或是 1、2、3、4 各一次。",
                ))

    romaji_status = {record["key"]: record for record in romaji_audit_records(conn)}

    for entry in list_entries(conn):
        key = entry["key"]
        if entry["type"] == "vocabulary":
            if not entry["reading"]:
                issues.append(AuditIssue(
                    "missing_reading", "needs_input", False, key,
                    "單字缺少假名讀音，程式無法從漢字安全推測。",
                ))
            romaji_record = romaji_status.get(key, {})
            status = romaji_record.get("status")
            if status == "missing_romaji":
                issues.append(AuditIssue(
                    "missing_romaji", "fixable", True, key,
                    f"缺少羅馬拼音，可安全補為：{romaji_record.get('canonical_romaji', '')}",
                ))
            elif status == "unsupported_reading":
                issues.append(AuditIssue(
                    "missing_romaji", "needs_input", False, key,
                    "缺少／無法正規化羅馬拼音，目前轉換器無法安全完整解析這個讀音。",
                ))
            elif status == "format_only":
                issues.append(AuditIssue(
                    "romaji_needs_normalization", "fixable", True, key,
                    f"羅馬拼音格式可安全正規化：{entry['romaji']} → {romaji_record.get('canonical_romaji', '')}",
                ))
            elif status == "mismatch":
                issues.append(AuditIssue(
                    "romaji_mismatch", "review", False, key,
                    f"羅馬拼音與假名讀音推導結果不一致：{entry['romaji']} ↔ {romaji_record.get('canonical_romaji', '')}",
                ))
            if not (entry["accent"] or entry["accent_type"] or entry["accent_display"]):
                issues.append(AuditIssue(
                    "missing_accent", "info", False, key,
                    "尚未提供可靠的東京式重音資料；程式不會猜測。",
                ))
            if _KATAKANA_RE.fullmatch(entry["display"]) and not entry["origin_type"]:
                issues.append(AuditIssue(
                    "possible_origin_missing", "review", False, key,
                    "片假名項目可能需要外來語語源；也可能是擬聲詞、專名或強調寫法。",
                ))
        normalized_level = normalize_level(entry["level"])
        if entry["level"] and normalized_level != entry["level"]:
            issues.append(AuditIssue(
                "noncanonical_level", "fixable", True, key,
                f"JLPT 等級可正規化：{entry['level']} → {normalized_level}",
            ))
        elif entry["level"] and entry["level"] not in {"N1", "N2", "N3", "N4", "N5"}:
            issues.append(AuditIssue(
                "invalid_level", "needs_input", False, key,
                f"無法辨識的 JLPT 等級：{entry['level']}",
            ))
        aliases = entry.get("aliases", [])
        if key in malformed_alias_keys:
            cleaned = aliases
        else:
            cleaned = clean_aliases(
                entry["key"], entry["display"], entry.get("reading", ""), aliases
            )
        if key not in malformed_alias_keys and cleaned != aliases:
            issues.append(AuditIssue(
                "aliases_need_cleanup", "fixable", True, key,
                "aliases 含有重複、多餘空白，或和 display／reading／stable-key 主體完全相同。",
            ))

    for candidate in duplicate_candidates(conn):
        issues.append(AuditIssue(
            "possible_duplicate", "review", False, candidate["left_key"],
            f"可能和 {candidate['right_key']} 重複：{candidate['reason']}",
            {"other_key": candidate["right_key"]},
        ))

    seen_pending: set[tuple[str, str, str]] = set()
    for row in conn.execute("SELECT * FROM pending_grammar_relations ORDER BY id").fetchall():
        identity = (str(row["source_key"]), str(row["target_key"]), str(row["relation_type"]))
        if identity in seen_pending:
            continue
        seen_pending.add(identity)
        target_exists = conn.execute("SELECT 1 FROM entries WHERE key = ?", (row["target_key"],)).fetchone()
        if target_exists:
            analysis = pending_resolution_analysis(conn, *identity)
            if not analysis["safe"]:
                issues.append(AuditIssue(
                    "pending_relation_note_conflict", "review", False, row["source_key"],
                    f"待補 relation 與既有 note 衝突，不能自動連結：{row['target_key']}",
                    {
                        "target_key": row["target_key"],
                        "relation": row["relation_type"],
                        "pending_notes": analysis["pending_notes"],
                        "resolved_notes": analysis["resolved_notes"],
                    },
                ))
                continue
        issues.append(AuditIssue(
            "pending_relation",
            "fixable" if target_exists else "needs_input",
            bool(target_exists),
            row["source_key"],
            f"相關文法尚未連結：{row['target_key']}",
            {"target_key": row["target_key"], "relation": row["relation_type"]},
        ))
    return issues


def apply_safe_repairs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Apply only deterministic transformations; never invent language data."""
    actions: list[dict[str, Any]] = []
    with conn:
        rows = conn.execute("SELECT * FROM entries ORDER BY key").fetchall()
        for row in rows:
            updates: dict[str, str] = {}
            normalized_level = normalize_level(row["level"])
            if normalized_level != row["level"]:
                updates["level"] = normalized_level
            if row["type"] == "vocabulary" and row["reading"] and not row["romaji"]:
                generated = spaced_hepburn(row["reading"])
                if generated:
                    updates["romaji"] = generated
            try:
                aliases = json.loads(row["aliases_json"] or "[]")
                aliases_valid = isinstance(aliases, list) and all(isinstance(alias, str) for alias in aliases)
            except json.JSONDecodeError:
                aliases = []
                aliases_valid = False
            if aliases_valid:
                cleaned_aliases = clean_aliases(
                    row["key"], row["display"], row["reading"], aliases
                )
                cleaned_json = json.dumps(cleaned_aliases, ensure_ascii=False)
                if cleaned_json != row["aliases_json"]:
                    updates["aliases_json"] = cleaned_json
            if updates:
                assignments = ", ".join(f"{field} = ?" for field in updates)
                conn.execute(
                    f"UPDATE entries SET {assignments} WHERE key = ?",
                    [*updates.values(), row["key"]],
                )
                actions.append({"key": row["key"], "updated": updates})
        sense_actions_by_entry: dict[str, dict[str, Any]] = {}
        sense_rows = conn.execute(
            "SELECT id, entry_key, meaning, example_ja, example_zh FROM senses ORDER BY entry_key, meaning, id"
        ).fetchall()
        sense_groups: dict[tuple[str, str], list[sqlite3.Row]] = {}
        for sense_row in sense_rows:
            sense_groups.setdefault((sense_row["entry_key"], sense_row["meaning"]), []).append(sense_row)
        for (entry_key, meaning), grouped_rows in sense_groups.items():
            delete_ids: set[int] = set()
            first_by_signature: dict[tuple[str, str, str], int] = {}
            rich_exists = any(
                str(sense_row["example_ja"] or "").strip()
                or str(sense_row["example_zh"] or "").strip()
                for sense_row in grouped_rows
            )
            for sense_row in grouped_rows:
                signature = (
                    sense_row["meaning"], sense_row["example_ja"], sense_row["example_zh"]
                )
                if signature in first_by_signature:
                    delete_ids.add(sense_row["id"])
                else:
                    first_by_signature[signature] = sense_row["id"]
                if rich_exists and not str(sense_row["example_ja"] or "").strip() and not str(sense_row["example_zh"] or "").strip():
                    delete_ids.add(sense_row["id"])
            if delete_ids:
                placeholders = ",".join("?" for _ in delete_ids)
                conn.execute(f"DELETE FROM senses WHERE id IN ({placeholders})", tuple(sorted(delete_ids)))
                record = sense_actions_by_entry.setdefault(entry_key, {"key": entry_key, "removed_redundant_senses": 0, "meanings": []})
                record["removed_redundant_senses"] += len(delete_ids)
                if meaning not in record["meanings"]:
                    record["meanings"].append(meaning)
        actions.extend(sense_actions_by_entry.values())

        relation_updates = 0
        for table in ("grammar_relations", "pending_grammar_relations"):
            for row in conn.execute(f"SELECT * FROM {table}").fetchall():
                canonical = canonical_relation_type(row["relation_type"])
                if canonical in VALID_RELATION_TYPES and canonical != row["relation_type"]:
                    conn.execute(
                        f"""INSERT OR IGNORE INTO {table}(
                            source_key, target_key, relation_type, note, source, created_at
                        ) VALUES(?, ?, ?, ?, ?, ?)""",
                        (row["source_key"], row["target_key"], canonical, row["note"], row["source"], row["created_at"]),
                    )
                    conn.execute(f"DELETE FROM {table} WHERE id = ?", (row["id"],))
                    relation_updates += 1
        if relation_updates:
            actions.append({"normalized_relation_types": relation_updates})

        actions.extend(apply_safe_relation_repairs(conn))

        # Normalize legacy explicit event keys only when the target key is free.
        for row in conn.execute("SELECT id, event_key FROM attempts ORDER BY id").fetchall():
            event_key = str(row["event_key"] or "")
            normalized = unicodedata.normalize("NFKC", event_key)
            if not event_key or normalized == event_key:
                continue
            conflict = conn.execute(
                "SELECT 1 FROM attempts WHERE event_key=? AND id<>?", (normalized, row["id"])
            ).fetchone()
            if conflict is not None:
                continue
            conn.execute("UPDATE attempts SET event_key=? WHERE id=?", (normalized, row["id"]))
            actions.append({"normalized_event_key": {"from": event_key, "to": normalized}})

        resolved = resolve_pending_relations(conn, strict=False)
        if resolved:
            actions.append({"resolved_pending_relations": resolved})
    return actions
