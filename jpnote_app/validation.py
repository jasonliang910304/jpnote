"""Payload parsing and validation independent from any terminal UI."""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date
from typing import Any

from .sorting import normalize_level
from .attempt_options import normalized_options
from .romaji_maintenance import normalize_import_romaji
from .attempt_identity import generated_attempt_event_key
from .relation_integrity import reciprocal_type

VALID_ENTRY_TYPES = {"grammar", "vocabulary"}
VALID_RESULTS = {"correct", "wrong", "partial", "unknown"}
VALID_ORIGIN_TYPES = {"", "loanword", "wasei_gairaigo", "abbreviation", "hybrid", "unknown"}
VALID_RELATION_TYPES = {
    "意思相近",
    "對比",
    "容易混淆",
    "前置文法",
    "延伸",
    "替代表達",
    "語氣比較",
}

# v0.4/v0.5.0 briefly stored older labels.  Keep them as import aliases,
# but normalize all newly validated data to the canonical user-facing enum.
RELATION_TYPE_ALIASES = {
    "相似用法": "意思相近",
    "相反／對比": "對比",
    "替代表現": "替代表達",
    "前置基礎": "前置文法",
    "延伸文法": "延伸",
}

TOP_LEVEL_FIELDS = {"source", "items", "attempts"}
ITEM_FIELDS = {
    "key", "type", "display", "reading", "romaji", "accent", "accent_type",
    "accent_display", "accent_note", "level", "review_group", "aliases",
    "origin_type", "origin_language", "origin_word", "origin_note", "suggested",
    "senses", "meanings", "related_grammar", "source",
}
SENSE_FIELDS = {"meaning", "example_ja", "example_zh"}
RELATION_FIELDS = {"key", "relation", "note"}
ATTEMPT_FIELDS = {
    "event_key", "result", "date", "source", "section", "question",
    "question_type", "prompt", "user_answer", "correct_answer", "options",
    "reason", "before", "after", "parts", "user_order", "correct_order",
    "linked_entries", "attempt_date",
}
PART_FIELDS = {"id", "text"}
ENTRY_EDIT_FIELDS = ITEM_FIELDS | {"sources"}
ATTEMPT_EDIT_FIELDS = ATTEMPT_FIELDS


def reject_unknown_fields(obj: dict[str, Any], allowed: set[str], context: str) -> None:
    unknown = sorted(set(obj) - allowed)
    if unknown:
        raise ValueError(f"{context} 包含不支援的欄位：{'、'.join(unknown)}")


def canonical_relation_type(value: Any) -> str:
    text = normalize_text(value)
    return RELATION_TYPE_ALIASES.get(text, text)


def parse_payload(text: str) -> dict[str, Any]:
    """Extract exactly one jpnote JSON payload from raw text or code fences.

    Older behavior returned the first matching object, which could silently pick
    the wrong payload when a clipboard contained two complete jpnote JSON
    blocks.  Multiple distinct valid payloads are now rejected as ambiguous.
    """
    candidates: list[str] = [text.strip()]
    candidates.extend(
        match.group(1).strip()
        for match in re.finditer(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    )
    decoder = json.JSONDecoder()
    found: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
            if _looks_like_payload(data):
                found[json.dumps(data, ensure_ascii=False, sort_keys=True)] = data
        except json.JSONDecodeError:
            pass
        for position, char in enumerate(candidate):
            if char != "{":
                continue
            try:
                data, _ = decoder.raw_decode(candidate[position:])
            except json.JSONDecodeError:
                continue
            if _looks_like_payload(data):
                found[json.dumps(data, ensure_ascii=False, sort_keys=True)] = data
    if not found:
        raise ValueError("找不到有效的 jpnote JSON。最外層需要 items 或 attempts 陣列。")
    if len(found) > 1:
        raise ValueError("偵測到多份不同的 jpnote JSON；請一次只匯入一份，避免誤選第一份資料。")
    return next(iter(found.values()))
def _looks_like_payload(data: Any) -> bool:
    # Presence is enough here; strict array type validation belongs to
    # normalize_payload() so malformed payloads receive a precise error.
    return isinstance(data, dict) and ("items" in data or "attempts" in data)


def _has_dangerous_terminal_control(text: str) -> bool:
    for char in text:
        code = ord(char)
        # Newlines/tabs remain valid learner text, but ESC/BEL, NUL, other C0
        # controls, DEL, and C1 controls can alter terminal state or fzf fields.
        if char in {"\n", "\r", "\t"}:
            continue
        if code < 0x20 or code == 0x7F or 0x80 <= code <= 0x9F:
            return True
    return False


def _validate_identifier(value: str, field_name: str) -> str:
    if not value:
        raise ValueError(f"{field_name} 不能是空字串。")
    for char in value:
        code = ord(char)
        if code < 0x20 or code == 0x7F or 0x80 <= code <= 0x9F:
            raise ValueError(f"{field_name} 不能包含 Tab、換行或控制字元。")
        # Unicode format controls include zero-width spaces and bidi overrides.
        # They are especially dangerous in stable identifiers because two keys
        # can look identical while remaining different database values.
        if unicodedata.category(char) == "Cf":
            raise ValueError(f"{field_name} 不能包含不可見的 Unicode 格式控制字元。")
    return value


def normalize_text(value: Any) -> str:
    # Preserve learner-facing Japanese/Traditional Chinese punctuation and
    # ordinary line breaks, but reject terminal control sequences at the data
    # boundary so they can never be executed by CLI/fzf previews.
    text = str(value or "").strip()
    if _has_dangerous_terminal_control(text):
        raise ValueError("文字內容包含不允許的終端控制字元。")
    return text




def normalize_text_field(value: Any, field_name: str, *, allow_none: bool = True) -> str:
    """Strict string validation for public JSON fields.

    The previous permissive ``str(value)`` behavior could permanently turn
    arrays, numbers, booleans, or objects into surprising strings.  Import JSON
    is now type-checked instead of silently coercing malformed AI-generated data.
    """
    if value is None and allow_none:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{field_name} 必須是字串。")
    return normalize_text(value)


def normalize_bool_field(value: Any, field_name: str, *, default: bool = False) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} 必須是 true 或 false。")
    return value

def normalize_identity_text(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", normalize_text(value))
    return re.sub(r"[\s　]+", "", normalized).lstrip("〜～")


def canonical_key(key: str, entry_type: str) -> str:
    raw = unicodedata.normalize("NFKC", normalize_text(key))
    expected = "grammar:" if entry_type == "grammar" else "vocab:"
    if raw.startswith("vocabulary:"):
        raw = "vocab:" + raw[len("vocabulary:") :]
    if not raw.startswith(("grammar:", "vocab:")):
        raw = expected + raw
    prefix, value = raw.split(":", 1)
    if entry_type == "grammar":
        value = value.lstrip("〜～").strip()
        prefix = "grammar"
    else:
        value = value.strip()
        prefix = "vocab"
    _validate_identifier(value, "stable key")
    return _validate_identifier(f"{prefix}:{value}", "stable key")


def normalize_string_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field_name} 必須是陣列。")
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = normalize_text_field(item, f"{field_name} 的元素")
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def normalize_sources(value: Any) -> list[str]:
    """Normalize editable source-history values with the shared text safety rules."""
    return normalize_string_list(value, "sources")


def normalize_senses(item: dict[str, Any]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    senses = [] if item.get("senses") is None else item.get("senses")
    if not isinstance(senses, list):
        raise ValueError("senses 必須是陣列。")
    for sense in senses:
        if not isinstance(sense, dict):
            raise ValueError("senses 的每個項目都必須是物件。")
        meaning = normalize_text_field(sense.get("meaning"), "senses.meaning")
        if meaning:
            result.append(
                {
                    "meaning": meaning,
                    "example_ja": normalize_text_field(sense.get("example_ja"), "senses.example_ja"),
                    "example_zh": normalize_text_field(sense.get("example_zh"), "senses.example_zh"),
                }
            )
    meanings = [] if item.get("meanings") is None else item.get("meanings")
    if not isinstance(meanings, list):
        raise ValueError("meanings 必須是陣列。")
    for meaning in meanings:
        text = normalize_text_field(meaning, "meanings 的元素")
        if text:
            result.append({"meaning": text, "example_ja": "", "example_zh": ""})
    unique: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for sense in result:
        signature = (sense["meaning"], sense["example_ja"], sense["example_zh"])
        if signature not in seen:
            seen.add(signature)
            unique.append(sense)
    return unique


def normalize_relations(value: Any) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("related_grammar 必須是陣列。")
    by_identity: dict[tuple[str, str], dict[str, str]] = {}
    for relation in value:
        if not isinstance(relation, dict):
            raise ValueError("related_grammar 的每個項目都必須是物件。")
        raw_target = normalize_text_field(relation.get("key"), "related_grammar.key")
        raw_relation = normalize_text_field(relation.get("relation"), "related_grammar.relation")
        if not raw_target or not raw_relation:
            raise ValueError("related_grammar 的 key 與 relation 都是必填欄位。")
        target = canonical_key(raw_target, "grammar")
        relation_type = canonical_relation_type(raw_relation)
        if relation_type not in VALID_RELATION_TYPES:
            raise ValueError(f"不支援的文法關聯類型：{relation_type}")
        note = normalize_text_field(relation.get("note"), "related_grammar.note")
        identity = (target, relation_type)
        existing = by_identity.get(identity)
        if existing is None:
            by_identity[identity] = {"key": target, "relation": relation_type, "note": note}
            continue
        old_note = existing["note"]
        if old_note and note and old_note != note:
            raise ValueError(
                "同批 related_grammar 的邏輯關聯相同但 note 衝突："
                f"{target}（{relation_type}）同時出現 {old_note!r} 與 {note!r}。"
            )
        if not old_note and note:
            existing["note"] = note
    return list(by_identity.values())


def validate_item(item: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("每個 items 項目都必須是 JSON 物件。")
    entry_type = normalize_text_field(item.get("type"), "type")
    display = normalize_text_field(item.get("display"), "display")
    raw_key = normalize_text_field(item.get("key"), "key")
    if entry_type not in VALID_ENTRY_TYPES or not display or not raw_key:
        raise ValueError(f"項目缺少必要欄位 key/type/display：{item!r}")
    origin_type = normalize_text_field(item.get("origin_type"), "origin_type")
    if origin_type not in VALID_ORIGIN_TYPES:
        raise ValueError(f"不支援的 origin_type：{origin_type}")
    reading = normalize_text_field(item.get("reading"), "reading")
    romaji = normalize_text_field(item.get("romaji"), "romaji")
    if entry_type == "vocabulary":
        romaji = normalize_import_romaji(reading, romaji)
    normalized = {
        "key": canonical_key(raw_key, entry_type),
        "type": entry_type,
        "display": display,
        "reading": reading,
        "romaji": romaji,
        "accent": normalize_text_field(item.get("accent"), "accent"),
        "accent_type": normalize_text_field(item.get("accent_type"), "accent_type"),
        "accent_display": normalize_text_field(item.get("accent_display"), "accent_display"),
        "accent_note": normalize_text_field(item.get("accent_note"), "accent_note"),
        "level": normalize_level(normalize_text_field(item.get("level"), "level")),
        "review_group": normalize_text_field(item.get("review_group"), "review_group"),
        "aliases": normalize_string_list(item.get("aliases"), "aliases"),
        "origin_type": origin_type,
        "origin_language": normalize_text_field(item.get("origin_language"), "origin_language"),
        "origin_word": normalize_text_field(item.get("origin_word"), "origin_word"),
        "origin_note": normalize_text_field(item.get("origin_note"), "origin_note"),
        "suggested": normalize_bool_field(item.get("suggested"), "suggested"),
        "senses": normalize_senses(item),
        "related_grammar": normalize_relations(item.get("related_grammar")),
        "source": normalize_text_field(item.get("source"), "source"),
    }
    if entry_type != "grammar" and normalized["related_grammar"]:
        raise ValueError(f"單字項目不能包含 related_grammar：{normalized['key']}")
    for relation in normalized["related_grammar"]:
        if relation["key"] == normalized["key"]:
            raise ValueError(
                f"文法不能建立指向自己的 relation：{normalized['key']}（{relation['relation']}）。"
            )
    return normalized


def _normalize_parts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("reorder_4 的 parts 必須是陣列。")
    result: list[dict[str, Any]] = []
    for part in value:
        if not isinstance(part, dict):
            raise ValueError("parts 的每個項目都必須是物件。")
        raw_part_id = part.get("id")
        if not isinstance(raw_part_id, int) or isinstance(raw_part_id, bool):
            raise ValueError("parts.id 必須是 1 到 4 的整數。")
        part_id = raw_part_id
        text = normalize_text_field(part.get("text"), "parts.text")
        if not text:
            raise ValueError("reorder_4 的四個 parts.text 都必須有內容。")
        result.append({"id": part_id, "text": text})
    if len(result) != 4 or {part["id"] for part in result} != {1, 2, 3, 4}:
        raise ValueError("reorder_4 必須剛好提供 id 1、2、3、4 四個格子。")
    return sorted(result, key=lambda part: part["id"])


def _normalize_order(value: Any, field_name: str) -> list[int]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} 必須是四個數字的陣列。")
    if not all(isinstance(item, int) and not isinstance(item, bool) for item in value):
        raise ValueError(f"{field_name} 必須只包含整數。")
    order = list(value)
    if len(order) != 4 or set(order) != {1, 2, 3, 4}:
        raise ValueError(f"{field_name} 必須是 1、2、3、4 各一次的完整順序。")
    return order




def normalize_attempt_date(value: Any) -> str:
    """Return YYYY-MM-DD or an empty string for historical attempts without a date."""
    text = normalize_text_field(value, "date")
    if not text:
        return ""
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("作答日期必須是 YYYY-MM-DD。") from exc
    if parsed.isoformat() != text:
        raise ValueError("作答日期必須是 YYYY-MM-DD。")
    return text


def validate_attempt(attempt: dict[str, Any], default_source: str = "") -> dict[str, Any]:
    if not isinstance(attempt, dict):
        raise ValueError("每個 attempts 項目都必須是 JSON 物件。")
    question_type = normalize_text_field(attempt.get("question_type"), "question_type") or "other"
    linked_entries = normalize_string_list(attempt.get("linked_entries"), "linked_entries")
    normalized_links: list[str] = []
    for key in linked_entries:
        if key.startswith("grammar:"):
            normalized_links.append(canonical_key(key, "grammar"))
        elif key.startswith(("vocab:", "vocabulary:")):
            normalized_links.append(canonical_key(key, "vocabulary"))
        else:
            raise ValueError(f"linked_entries 必須使用 grammar: 或 vocab: key：{key}")

    parts: list[dict[str, Any]] = []
    user_order: list[int] = []
    correct_order: list[int] = []
    result = normalize_text_field(attempt.get("result"), "result") or "unknown"
    if question_type == "reorder_4":
        parts = _normalize_parts(attempt.get("parts"))
        correct_order = _normalize_order(attempt.get("correct_order"), "correct_order")

        # Historical mistake entry is a different use case from a live quiz.
        # When the learner only remembers that the question was wrong, an
        # empty user_order is valid as long as result is not claimed correct.
        raw_user_order = attempt.get("user_order")
        if raw_user_order in (None, []):
            user_order = []
            if result == "correct":
                raise ValueError("reorder_4 沒有 user_order 時不能標記為 correct。")
            if result not in {"wrong", "partial", "unknown"}:
                raise ValueError("reorder_4 未記錄 user_order 時，result 只能是 wrong、partial 或 unknown。")
        else:
            user_order = _normalize_order(raw_user_order, "user_order")
            computed = "correct" if user_order == correct_order else "wrong"
            if result not in {"", "unknown", computed}:
                raise ValueError("reorder_4 的 result 與四格順序不一致。")
            result = computed
    elif result not in VALID_RESULTS:
        raise ValueError(f"不支援的作答結果：{result}")

    raw_event_key = normalize_text_field(attempt.get("event_key"), "event_key")
    if raw_event_key:
        raw_event_key = unicodedata.normalize("NFKC", raw_event_key)
        _validate_identifier(raw_event_key, "event_key")

    has_date = "date" in attempt and attempt.get("date") is not None
    has_legacy_date = "attempt_date" in attempt and attempt.get("attempt_date") is not None
    normalized_date = normalize_attempt_date(attempt.get("date")) if has_date else ""
    normalized_legacy_date = (
        normalize_attempt_date(attempt.get("attempt_date")) if has_legacy_date else ""
    )
    if has_date and has_legacy_date and normalized_date != normalized_legacy_date:
        raise ValueError(
            "attempts 的 date 與相容欄位 attempt_date 同時存在但內容不同；"
            "請只保留一個，或讓兩者使用相同日期。"
        )
    effective_date = normalized_date if has_date else normalized_legacy_date

    normalized = {
        "event_key": raw_event_key,
        "result": result,
        "date": effective_date,
        "source": normalize_text_field(attempt.get("source"), "source") or default_source,
        "section": normalize_text_field(attempt.get("section"), "section"),
        "question": normalize_text_field(attempt.get("question"), "question"),
        "question_type": question_type,
        "prompt": normalize_text_field(attempt.get("prompt"), "prompt"),
        "user_answer": normalize_text_field(attempt.get("user_answer"), "user_answer"),
        "correct_answer": normalize_text_field(attempt.get("correct_answer"), "correct_answer"),
        "options": normalized_options(attempt.get("options")),
        "reason": normalize_text_field(attempt.get("reason"), "reason"),
        "before": normalize_text_field(attempt.get("before"), "before"),
        "after": normalize_text_field(attempt.get("after"), "after"),
        "parts": parts,
        "user_order": user_order,
        "correct_order": correct_order,
        "linked_entries": list(dict.fromkeys(normalized_links)),
    }
    if not normalized["event_key"]:
        normalized["event_key"] = generated_attempt_event_key(normalized)
        normalized["_event_key_generated"] = True
    else:
        normalized["_event_key_generated"] = False
    return normalized


def merge_normalized_items(
    base: dict[str, Any],
    incoming: dict[str, Any],
    *,
    allow_identity_override: bool = False,
) -> dict[str, Any]:
    """Merge two already validated items that share one stable key.

    Import resolution also uses this helper when a possible duplicate is
    explicitly mapped onto an existing key.  Keeping one merge definition
    avoids subtle differences between same-batch coalescing and user-approved
    duplicate resolution.
    """
    if base["type"] != incoming["type"]:
        raise ValueError(f"同一 key 出現不同 type：{base['key']}")
    if not allow_identity_override:
        for field in ("display", "reading"):
            left = str(base.get(field) or "")
            right = str(incoming.get(field) or "")
            if left and right and left != right:
                raise ValueError(
                    f"同批相同 stable key 的核心欄位衝突：{base['key']} 的 {field} "
                    f"同時出現 {left!r} 與 {right!r}。"
                )
    merged = dict(base)
    for field in (
        "display", "reading", "romaji", "accent", "accent_type", "accent_display",
        "accent_note", "level", "review_group", "origin_type", "origin_language",
        "origin_word", "origin_note", "source",
    ):
        if incoming.get(field):
            merged[field] = incoming[field]
    merged["suggested"] = bool(base.get("suggested") or incoming.get("suggested"))
    merged["aliases"] = list(dict.fromkeys([*base["aliases"], *incoming["aliases"]]))
    sense_seen = {(s["meaning"], s["example_ja"], s["example_zh"]) for s in base["senses"]}
    merged["senses"] = list(base["senses"])
    for sense in incoming["senses"]:
        signature = (sense["meaning"], sense["example_ja"], sense["example_zh"])
        if signature not in sense_seen:
            sense_seen.add(signature)
            merged["senses"].append(sense)
    relation_index = {
        (r["key"], r["relation"]): dict(r) for r in base["related_grammar"]
    }
    for relation in incoming["related_grammar"]:
        identity = (relation["key"], relation["relation"])
        existing = relation_index.get(identity)
        if existing is None:
            relation_index[identity] = dict(relation)
            continue
        old_note = str(existing.get("note") or "")
        new_note = str(relation.get("note") or "")
        if old_note and new_note and old_note != new_note:
            raise ValueError(
                "同批相同 stable key 的 related_grammar note 衝突："
                f"{base['key']} → {relation['key']}（{relation['relation']}）"
                f"同時出現 {old_note!r} 與 {new_note!r}。"
            )
        if not old_note and new_note:
            existing["note"] = new_note
    merged["related_grammar"] = list(relation_index.values())
    return merged





def _validate_batch_relation_consistency(items: list[dict[str, Any]]) -> None:
    """Reject contradictory same-batch reciprocal/inverse relation metadata."""
    logical: dict[tuple[str, str, str], str] = {}
    for item in items:
        if item.get("type") != "grammar":
            continue
        source_key = item["key"]
        for relation in item.get("related_grammar", []):
            identity = (source_key, relation["key"], relation["relation"])
            note = str(relation.get("note") or "")
            old_note = logical.get(identity, "")
            if old_note and note and old_note != note:
                raise ValueError(
                    "同批文法關聯 note 衝突："
                    f"{source_key} → {relation['key']}（{relation['relation']}）"
                    f"同時出現 {old_note!r} 與 {note!r}。"
                )
            if note or identity not in logical:
                logical[identity] = note or old_note

    checked: set[tuple[tuple[str, str, str], tuple[str, str, str]]] = set()
    for identity, note in logical.items():
        source_key, target_key, relation_type = identity
        reciprocal = reciprocal_type(relation_type)
        if reciprocal is None:
            continue
        opposite = (target_key, source_key, reciprocal)
        if opposite not in logical:
            continue
        marker = tuple(sorted((identity, opposite)))
        if marker in checked:
            continue
        checked.add(marker)
        other_note = logical[opposite]
        if note and other_note and note != other_note:
            raise ValueError(
                "同批 reciprocal／inverse 文法關聯 note 衝突："
                f"{source_key} → {target_key}（{relation_type}）為 {note!r}，"
                f"但 {target_key} → {source_key}（{reciprocal}）為 {other_note!r}。"
            )


def _validate_nested_public_fields(value: Any, allowed: set[str], context: str) -> None:
    """Check nested object fields only after confirming the container is a list.

    Type validation remains the responsibility of the normalizers so malformed
    scalar values receive a precise ValueError instead of an uncaught TypeError.
    """
    if not isinstance(value, list):
        return
    for item in value:
        if isinstance(item, dict):
            reject_unknown_fields(item, allowed, context)


def validate_entry_edit_fields(raw: Any) -> None:
    if not isinstance(raw, dict):
        raise ValueError("編輯內容必須是 JSON 物件。")
    reject_unknown_fields(raw, ENTRY_EDIT_FIELDS, "edit 項目")
    _validate_nested_public_fields(raw.get("senses", []), SENSE_FIELDS, "senses 項目")
    _validate_nested_public_fields(
        raw.get("related_grammar", []), RELATION_FIELDS, "related_grammar 項目"
    )


def validate_attempt_edit_fields(raw: Any) -> None:
    if not isinstance(raw, dict):
        raise ValueError("作答編輯內容必須是 JSON 物件。")
    reject_unknown_fields(raw, ATTEMPT_EDIT_FIELDS, "attempt edit 項目")
    _validate_nested_public_fields(raw.get("parts", []), PART_FIELDS, "parts 項目")
    _validate_nested_public_fields(raw.get("options", []), {"id", "text"}, "options 項目")


def _validate_public_payload_fields(payload: dict[str, Any]) -> None:
    """Reject misspelled/unsupported fields at the public import boundary."""
    reject_unknown_fields(payload, TOP_LEVEL_FIELDS, "jpnote payload")
    raw_items = payload.get("items", []) or []
    if isinstance(raw_items, list):
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            reject_unknown_fields(item, ITEM_FIELDS, "items 項目")
            _validate_nested_public_fields(item.get("senses", []), SENSE_FIELDS, "senses 項目")
            _validate_nested_public_fields(
                item.get("related_grammar", []), RELATION_FIELDS, "related_grammar 項目"
            )
    raw_attempts = payload.get("attempts", []) or []
    if isinstance(raw_attempts, list):
        for attempt in raw_attempts:
            if not isinstance(attempt, dict):
                continue
            reject_unknown_fields(attempt, ATTEMPT_FIELDS, "attempts 項目")
            _validate_nested_public_fields(attempt.get("parts", []), PART_FIELDS, "parts 項目")
            _validate_nested_public_fields(
                attempt.get("options", []), {"id", "text"}, "options 項目"
            )

def normalize_payload(payload: dict[str, Any]) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    if not isinstance(payload, dict):
        raise ValueError("jpnote payload 最外層必須是 JSON 物件。")
    _validate_public_payload_fields(payload)
    source = normalize_text_field(payload.get("source"), "source")
    raw_items = payload["items"] if "items" in payload else []
    raw_attempts = payload["attempts"] if "attempts" in payload else []
    if not isinstance(raw_items, list) or not isinstance(raw_attempts, list):
        raise ValueError("items 與 attempts 都必須是陣列。")
    by_key: dict[str, dict[str, Any]] = {}
    notes: list[str] = []
    for raw in raw_items:
        item = validate_item(raw)
        if item["key"] in by_key:
            by_key[item["key"]] = merge_normalized_items(by_key[item["key"]], item)
            notes.append(f"同批重複 key 已合併：{item['key']}")
        else:
            by_key[item["key"]] = item
    normalized_items = list(by_key.values())
    _validate_batch_relation_consistency(normalized_items)
    attempts = [validate_attempt(raw, source) for raw in raw_attempts]
    unique_attempts: dict[str, dict[str, Any]] = {}
    for attempt in attempts:
        event_key = attempt["event_key"]
        existing = unique_attempts.get(event_key)
        if existing is not None:
            if existing != attempt:
                raise ValueError(
                    f"同批 attempts 使用相同 event_key 但內容不同：{event_key}"
                )
            notes.append(f"同批重複作答紀錄已去重：{event_key}")
            continue
        unique_attempts[event_key] = attempt
    return source, normalized_items, list(unique_attempts.values()), notes
